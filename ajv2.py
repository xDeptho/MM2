# AJ V2 - claude rokid amaz

import os
import re
import ssl
import sys
import json
import time
import struct
import base64
import shutil
import socket
import asyncio
import hashlib
import builtins
import threading
import subprocess
from urllib.parse import urlparse, parse_qs, quote

import requests
import pyfiglet
from colorama import init, Fore, Style
from prettytable import PrettyTable

try:
    from bypasstools import BypassTools as _BypassToolsSDK, BypassToolsError as _BypassToolsError
except ImportError:
    _BypassToolsSDK = None
    _BypassToolsError = None

try:
    import discord as _discord
except ImportError:
    _discord = None

init(autoreset=True)

# ---------------------------------------------------------------- config

GAME_ID = '142823291'
SERVER_LINK = 'roblox://placeID=' + GAME_ID

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ACCOUNTS_FILE = os.path.join(SCRIPT_DIR, 'account.txt')
CACHE_FILE = os.path.join(SCRIPT_DIR, 'username_cache.json')
USERNAMES_FILE = os.path.join(SCRIPT_DIR, 'usernames.json')

DELTA_KEY_FILE = os.path.join(SCRIPT_DIR, 'delta_key.txt')
KEY_REFRESH_SECONDS = 24 * 60 * 60
_last_written_key = None
# some Delta builds re-encrypt the licence file after loading it, so we can't
# always read the key back out of it - this remembers the key WE wrote instead
KEY_STATE_FILE = os.path.join(SCRIPT_DIR, 'delta_key_state.txt')

BYPASS_KEY_FILE = os.path.join(SCRIPT_DIR, 'bypass_key.txt')
HWID_FILE = os.path.join(SCRIPT_DIR, 'delta_hwid.txt')
PLATORELAY_BASE = 'https://api.platorelay.com'
BYPASS_BASE = 'https://api.bypass.tools/api/v1'
DELTA_SERVICE = 6
_KEY_PATTERN = re.compile(r'(?:KEY|FREE)_[A-Za-z0-9_\-]+')
_HWID_PATTERN = re.compile(r'^[0-9a-fA-F]{16,}$')

EXECUTOR_GRACE_SECONDS = 60
PER_PACKAGE_DELAY = 25
SWEEP_DELAY = 90

executors = {
    'Fluxus': '/storage/emulated/0/Fluxus/',
    'Codex': '/storage/emulated/0/Codex/',
    'Arceus X': '/storage/emulated/0/Arceus X/',
    'Delta': '/storage/emulated/0/Delta/',
    'Cryptic': '/storage/emulated/0/Cryptic/',
    'VegaX': '/storage/emulated/0/VegaX/',
    'Trigon': '/storage/emulated/0/Trigon/',
}

lua_script_template = (
    'loadstring(game:HttpGet('
    '"https://raw.githubusercontent.com/aaalmaz0/mm2/main/ajv2.lua"'
    '))()'
)

WS_HOST = '0.0.0.0'
WS_PORT = 8177

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'
EXECUTOR_INACTIVITY_SECONDS = 30
_WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
_ws_registry = {}
_ws_lock = threading.Lock()
_ws_seen_any = False
_ws_conns = set()
_ws_conns_lock = threading.Lock()
_ws_send_lock = threading.Lock()

HEARTBEAT_TIMEOUT = 30   # no heartbeat for this long -> reopen that clone
REOPEN_COOLDOWN = 60     # after reopening, wait this long before triggering again
_launch_locks = {}       # package -> Lock, so a package is only relaunched once at a time
_launch_guard = threading.Lock()

SETTINGS_FILE = os.path.join(SCRIPT_DIR, 'aj.txt')


def _resolve_bot_token():
    env = os.environ.get('DISCORD_BOT_TOKEN', '').strip()
    if env:
        return env
    try:
        with open(os.path.join(SCRIPT_DIR, 'bot_token.txt')) as f:
            value = f.read().strip()
        if value:
            return value
    except IOError:
        pass
    return ''


BOT_TOKEN = _resolve_bot_token()
CHANNEL_ID = ''
LOG_ID = ''
TRANSFER_USERS = set()   # empty = anyone can use /transfer and /stoptransfer
PLACE_NAMES = {
    142823291: 'MM2',
    335132309: 'Disguise',
    636649648: 'Assassin',
}
JOIN_GAMES = set(PLACE_NAMES)
DISCORD_API = 'https://discord.com/api/v10'
DISCORD_SCAN_INTERVAL = 5
_JOIN_RE1 = re.compile(r"(\d+),\s*'([^']+)'")
_JOIN_RE2 = re.compile(r'TeleportToPlaceInstance\s*\(\s*"(\d+)"\s*,\s*"([^"]+)"')
_VALUE_RE = re.compile(r'total value[^0-9]*([0-9]+(?:\.[0-9]+)?)')
_GIVER_RE = re.compile(r'username[:\s]+([A-Za-z0-9_]{3,20})', re.IGNORECASE)
# low -> high, matches mm2's rarityTable. Used to count the giver's items at/above
# the configured min rarity (from the embed) so mm2 knows how many trades to expect.
RARITY_ORDER = ['Common', 'Uncommon', 'Rare', 'Legendary', 'Vintage', 'Godly', 'Ancient', 'Unique']
MIN_RARITY = 'Godly'
_join_target = {'placeId': None, 'jobId': None, 'msgid': None, 'giver': None}
_hits = {}          # jobId -> {placeId, jobId, giver, value, ts, expected} : the waitlist
_HIT_TTL = 120      # seconds a hit stays in the waitlist before it expires
MAX_HIT_AGE = 15 * 60   # ignore a hit whose message is already this old (likely dead)
_DISCORD_EPOCH = 1420070400000
_join_lock = threading.Lock()
_seen_join_msgs = set()
_seen_msgs = set()

GATEWAY_HOST = 'gateway.discord.gg'
_discord_client = None
_discord_loop = None
_gw_sock = None
_gw_ready = False
_gw_seq = None
_gw_session_id = None
_gw_resume_url = None
_gw_should_resume = False
_gw_send_lock = threading.Lock()
_last_presence_text = None
_last_presence_at = 0

username_cache = {}


# ---------------------------------------------------------------- console

_bottom_table = None
_bottom_lines = 0


def _erase_bottom():
    global _bottom_lines
    if _bottom_lines:
        sys.stdout.write('\033[{}A\033[0J'.format(_bottom_lines))
        _bottom_lines = 0


def _draw_bottom():
    global _bottom_lines
    if _bottom_table is not None:
        builtins.print(_bottom_table)
        _bottom_lines = _bottom_table.count('\n') + 1


def _log_print(*args, **kwargs):
    """Print a log line ABOVE the pinned status table (which stays at the bottom),
    so logs scroll and the table updates in place as ONE block."""
    if not sys.stdout.isatty():
        builtins.print(*args, **kwargs)
        return
    _erase_bottom()
    builtins.print(*args, **kwargs)
    _draw_bottom()


print = _log_print


def clear_console():
    os.system('cls' if os.name == 'nt' else 'clear')


def print_header():
    print(Fore.LIGHTYELLOW_EX + pyfiglet.figlet_format('AJ V2', font='big_money-nw') + Style.RESET_ALL)


def update_status_table(package_statuses):
    global _bottom_table
    table = PrettyTable()
    table.field_names = ['Package', 'Username', 'Status']
    table.align = 'l'
    table.border = True
    for package, info in package_statuses.items():
        table.add_row([package, info.get('Username', 'Unknown'), info.get('Status', '')])
    rendered = str(table)
    if rendered == _bottom_table:
        return
    if not sys.stdout.isatty():
        _bottom_table = rendered
        builtins.print(rendered)
        return
    _erase_bottom()
    _bottom_table = rendered
    _draw_bottom()


def set_status(package_statuses, package_name, colour, text):
    package_statuses[package_name]['Status'] = colour + text + Style.RESET_ALL
    update_status_table(package_statuses)

# ---------------------------------------------------------------- packages

def get_roblox_packages():
    packages = []
    try:
        output = subprocess.check_output('pm list packages', shell=True, text=True)
    except subprocess.CalledProcessError:
        print(Fore.RED + 'An error occurred while searching for packages on your device!' + Style.RESET_ALL)
        return packages
    print(Fore.YELLOW + 'Checking Packages On Your Device .....' + Style.RESET_ALL)
    for line in output.splitlines():
        if 'com.roblox.' in line:
            package_name = line.split(':')[1]
            print(Fore.GREEN + 'Package Found : ' + package_name + Style.RESET_ALL)
            packages.append(package_name)
    if not packages:
        print(Fore.RED + 'No Roblox-related packages found on your device.' + Style.RESET_ALL)
    return packages


def is_roblox_running(package_name):
    """True if a process for this package is alive. Uses pgrep/ps via the shell
    (psutil does not build on Android/Termux)."""
    try:
        result = subprocess.run(
            ['pgrep', '-f', package_name],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if result.stdout.strip():
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        output = subprocess.check_output(['ps', '-A'], text=True, stderr=subprocess.DEVNULL)
        return package_name in output
    except (OSError, subprocess.SubprocessError):
        return False


def kill_roblox_process(package_name):
    print('Killing Roblox process for {}...'.format(package_name))
    os.system('pkill -f ' + package_name)
    time.sleep(2)


def kill_roblox_processes():
    print('Killing all Roblox processes...')
    for package_name in get_roblox_packages():
        print('Trying to kill process for package: ' + package_name)
        os.system('pkill -f ' + package_name)
    time.sleep(2)


def launch_roblox(package_name, num_packages, package_statuses):
    try:
        set_status(package_statuses, package_name, Fore.LIGHTCYAN_EX,
                   'Opening Roblox for {}...'.format(package_name))
        subprocess.run(
            ['am', 'start', '-n', package_name + '/com.roblox.client.startup.ActivitySplash',
             '-d', SERVER_LINK],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(15 if num_packages >= 6 else 8)

        set_status(package_statuses, package_name, Fore.LIGHTCYAN_EX,
                   'Joining Roblox for {}...'.format(package_name))
        subprocess.run(
            ['am', 'start', '-n', package_name + '/com.roblox.client.ActivityProtocolLaunch',
             '-d', SERVER_LINK],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # the heartbeat watchdog / executor check confirm it came up, so no long wait
        time.sleep(3)

        set_status(package_statuses, package_name, Fore.GREEN, 'Joined Roblox')
    except Exception as e:
        set_status(package_statuses, package_name, Fore.RED,
                   'Error launching Roblox for {}: {}'.format(package_name, e))
        print('Error details: {}'.format(e))


def _package_lock(package_name):
    with _launch_guard:
        return _launch_locks.setdefault(package_name, threading.Lock())


def safe_launch(package_name, num_packages, package_statuses, kill_first=False):
    """Launch in a background thread, guarded so a package is never relaunched
    twice at once (watchdog + monitor share the lock)."""
    lock = _package_lock(package_name)
    if not lock.acquire(blocking=False):
        return False

    def _run():
        try:
            if kill_first:
                kill_roblox_process(package_name)
            launch_roblox(package_name, num_packages, package_statuses)
        finally:
            lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return True


def heartbeat_watchdog(accounts, package_statuses):
    """Reopen a clone whose mm2 heartbeat stops. mm2.lua heartbeats every 1s; if
    a clone that was alive goes silent for HEARTBEAT_TIMEOUT, its Roblox is
    reopened. A per-package cooldown avoids re-triggering while it comes back."""
    num_packages = len(accounts)
    usernames = {}
    for package_name, user_id in accounts:
        try:
            usernames[package_name] = get_username(user_id)
        except Exception:
            usernames[package_name] = None
    alive = set()          # packages whose executor has heartbeated at least once
    reopened_at = {}
    while True:
        time.sleep(2)
        now = time.time()
        for package_name, _ in accounts:
            uname = usernames.get(package_name)
            if not uname:
                continue
            with _ws_lock:
                entry = _ws_registry.get(uname)
            if entry:
                alive.add(package_name)
            if package_name not in alive:
                continue   # never came up yet - leave it to the initial launch
            silent = (now - entry['last_seen']) if entry else 1e9
            if silent > HEARTBEAT_TIMEOUT and now - reopened_at.get(package_name, 0) > REOPEN_COOLDOWN:
                set_status(package_statuses, package_name, Fore.RED,
                           'No heartbeat {}s - reopening'.format(int(silent)))
                with _ws_lock:
                    _ws_registry.pop(uname, None)
                reopened_at[package_name] = now
                safe_launch(package_name, num_packages, package_statuses)


def delete_roblox_cache():
    """Best-effort: /data/data is only listable on rooted devices. On a normal
    (non-root) Termux install this silently does nothing instead of crashing."""
    base_path = '/data/data'
    try:
        folders = os.listdir(base_path)
    except (OSError, PermissionError):
        return
    for folder in folders:
        if folder.startswith('com.roblox.'):
            cache_path = os.path.join(base_path, folder, 'cache')
            if os.path.exists(cache_path):
                try:
                    shutil.rmtree(cache_path)
                except Exception:
                    pass


# ---------------------------------------------------------------- accounts

def find_userid_from_file(file_path):
    try:
        with open(file_path, 'r') as file:
            content = file.read()
        marker = '"UserId":"'
        start = content.find(marker)
        if start == -1:
            return None
        start += len(marker)
        end = content.find('"', start)
        if end == -1:
            return None
        return content[start:end]
    except IOError:
        return None


def save_accounts(accounts):
    with open(ACCOUNTS_FILE, 'w') as file:
        for package, user_id in accounts:
            file.write('{},{}\n'.format(package, user_id))


def load_accounts():
    accounts = []
    if os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, 'r') as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    package, user_id = line.split(',', 1)
                    accounts.append((package, user_id))
                except ValueError:
                    print(Fore.RED + "Invalid line format: {}. Expected 'package,user_id'.".format(line)
                          + Style.RESET_ALL)
    return accounts


def resolve_userid_from_username(username):
    """Username -> UserId via Roblox's API. Needed on non-root devices, where
    appStorage.json (which has the UserId) isn't readable."""
    last_err = None
    for base in ('https://users.roblox.com/v1/usernames/users',
                 'https://users.roproxy.com/v1/usernames/users'):
        for attempt in range(2):
            try:
                resp = requests.post(base, json={'usernames': [username], 'excludeBannedUsers': False},
                                     timeout=15)
                resp.raise_for_status()
                data = resp.json().get('data') or []
                if data:
                    return str(data[0]['id'])
                last_err = 'no such user (empty result)'
                break   # a clean empty result means the username is wrong - don't retry
            except (requests.exceptions.RequestException, ValueError, KeyError, IndexError) as e:
                last_err = e
                time.sleep(1)
    print(Fore.RED + 'Username lookup failed: {}'.format(last_err) + Style.RESET_ALL)
    return None


def setup_accounts(packages):
    """Read each package's UserId from its appStorage.json.

    Falls back to whatever is already saved in account.txt for packages whose
    appStorage has not been written yet, so a half-logged-in clone does not
    drop out of the rotation. On a non-root device appStorage.json can't be
    read at all, so as a last resort it asks for the Roblox username and
    resolves the UserId from that.
    """
    saved = dict(load_accounts())
    accounts = []
    for package_name in packages:
        path = '/data/data/{}/files/appData/LocalStorage/appStorage.json'.format(package_name)
        user_id = find_userid_from_file(path) or saved.get(package_name)
        if not user_id:
            entered = input('Could not auto-detect the account for {} - '
                            'Roblox username (Enter to skip): '.format(package_name)).strip()
            if entered:
                user_id = resolve_userid_from_username(entered)
                if not user_id:
                    print(Fore.RED + 'Could not resolve username "{}".'.format(entered) + Style.RESET_ALL)
        if user_id:
            accounts.append((package_name, user_id))
            print(Fore.GREEN + 'UserId for {}: {}'.format(package_name, user_id) + Style.RESET_ALL)
        else:
            print(Fore.RED + 'UserId not found for {}, skipping.'.format(package_name) + Style.RESET_ALL)
    if accounts:
        save_accounts(accounts)
    return accounts


# ---------------------------------------------------------------- usernames

def load_cache():
    global username_cache
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                username_cache = json.load(f)
        except (IOError, json.JSONDecodeError):
            username_cache = {}


def save_cache():
    try:
        temp_file = CACHE_FILE + '.tmp'
        with open(temp_file, 'w') as f:
            json.dump(username_cache, f)
        os.replace(temp_file, CACHE_FILE)
    except IOError as e:
        print(Fore.RED + 'Error saving cache: {}'.format(e) + Style.RESET_ALL)


def save_username(user_id, username):
    try:
        data = {}
        if os.path.exists(USERNAMES_FILE):
            try:
                with open(USERNAMES_FILE, 'r') as file:
                    data = json.load(file)
            except json.JSONDecodeError:
                data = {}
        data[user_id] = username
        with open(USERNAMES_FILE, 'w') as file:
            json.dump(data, file)
    except (IOError, json.JSONDecodeError) as e:
        print(Fore.RED + 'Error saving username: {}'.format(e) + Style.RESET_ALL)


def get_username(user_id):
    if user_id in username_cache:
        return username_cache[user_id]
    for base in ('https://users.roblox.com/v1/users/', 'https://users.roproxy.com/v1/users/'):
        for attempt in range(2):
            try:
                response = requests.get(base + str(user_id), timeout=10)
                response.raise_for_status()
                username = response.json().get('name', 'Unknown')
                if username != 'Unknown':
                    username_cache[user_id] = username
                    save_username(user_id, username)
                    return username
            except requests.exceptions.RequestException as e:
                print(Fore.RED + 'Attempt {} failed for {}: {}'.format(attempt + 1, base, e)
                      + Style.RESET_ALL)
                time.sleep(2 ** attempt)
    return 'Unknown'


def get_username_from_id(user_id):
    return get_username(user_id) or user_id


def check_user_online(user_id):
    delay = 2
    for attempt in range(3):
        try:
            with requests.Session() as session:
                response = session.post(
                    'https://presence.roblox.com/v1/presence/users',
                    headers={'Content-Type': 'application/json'},
                    data=json.dumps({'userIds': [user_id]}),
                    timeout=7)
            response.raise_for_status()
            presence = response.json()['userPresences'][0]
            presence_type = presence['userPresenceType']
            last_location = presence.get('lastLocation', None)
            if last_location == 'Website':
                print(Fore.YELLOW + '{} is currently on the Website. Rejoin recommended.'.format(user_id)
                      + Style.RESET_ALL)
                presence_type = 0
            return (presence_type, last_location)
        except requests.exceptions.RequestException as e:
            print(Fore.RED + 'Error checking online status for user {} (Attempt {}): {}'.format(
                user_id, attempt + 1, e) + Style.RESET_ALL)
            if attempt < 2:
                time.sleep(delay)
                delay *= 2
    return (None, None)


# ---------------------------------------------------------------- executor

def detect_and_write_lua_script():
    detected_executors = []
    for executor_name, base_path in executors.items():
        for path in (os.path.join(base_path, 'Autoexec'), os.path.join(base_path, 'Autoexecute')):
            if os.path.exists(path):
                try:
                    with open(os.path.join(path, 'ajv2.lua'), 'w') as file:
                        file.write(lua_script_template)
                    detected_executors.append(executor_name)
                    break
                except Exception:
                    pass
    return detected_executors


# ---- WebSocket check server (replaces the workspace-file heartbeat) ----

def _recv_exact(conn, n):
    buf = b''
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def _ws_handshake(conn):
    data = b''
    while b'\r\n\r\n' not in data:
        chunk = conn.recv(1024)
        if not chunk:
            return False
        data += chunk
        if len(data) > 65536:
            return False
    key = None
    for line in data.decode('latin1', 'ignore').split('\r\n'):
        if line.lower().startswith('sec-websocket-key:'):
            key = line.split(':', 1)[1].strip()
    if not key:
        return False
    accept = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()
    conn.sendall((
        'HTTP/1.1 101 Switching Protocols\r\n'
        'Upgrade: websocket\r\n'
        'Connection: Upgrade\r\n'
        'Sec-WebSocket-Accept: ' + accept + '\r\n\r\n').encode())
    return True


def _ws_recv_frame(conn):
    hdr = _recv_exact(conn, 2)
    if not hdr:
        return None, None
    opcode = hdr[0] & 0x0f
    masked = hdr[1] & 0x80
    length = hdr[1] & 0x7f
    if length == 126:
        ext = _recv_exact(conn, 2)
        length = struct.unpack('>H', ext)[0] if ext else 0
    elif length == 127:
        ext = _recv_exact(conn, 8)
        length = struct.unpack('>Q', ext)[0] if ext else 0
    mask = _recv_exact(conn, 4) if masked else b'\x00\x00\x00\x00'
    payload = _recv_exact(conn, length) if length else b''
    if payload is None or mask is None:
        return None, None
    if masked:
        payload = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))
    return opcode, payload


def _ws_send_frame(conn, payload=b'', opcode=0x1):
    b1 = 0x80 | opcode
    length = len(payload)
    if length < 126:
        header = bytes([b1, length])
    elif length < 65536:
        header = bytes([b1, 126]) + struct.pack('>H', length)
    else:
        header = bytes([b1, 127]) + struct.pack('>Q', length)
    with _ws_send_lock:
        conn.sendall(header + payload)


def _send_teleport(conn, place_id, job_id, giver=None, expected=0):
    """Push a teleport command to one client (server frames are unmasked).
    'expected' = giver's items at/above min rarity, so mm2 knows how many to claim."""
    payload = json.dumps({'action': 'teleport', 'placeId': place_id, 'jobId': job_id,
                          'giver': giver, 'expected': expected})
    _ws_send_frame(conn, payload.encode('utf-8'), opcode=0x1)


def broadcast_teleport(place_id, job_id, giver=None, expected=0):
    """Tell every connected executor to TeleportToPlaceInstance to this server."""
    with _ws_conns_lock:
        conns = list(_ws_conns)
    for conn in conns:
        try:
            _send_teleport(conn, place_id, job_id, giver, expected)
        except OSError:
            with _ws_conns_lock:
                _ws_conns.discard(conn)


def broadcast_command(cmd, args=None):
    """Relay a slash command (inv / invf / rejoin / transfer) to every executor."""
    payload = json.dumps({'action': 'command', 'cmd': cmd, 'args': args or {}}).encode('utf-8')
    with _ws_conns_lock:
        conns = list(_ws_conns)
    for conn in conns:
        try:
            _ws_send_frame(conn, payload, opcode=0x1)
        except OSError:
            with _ws_conns_lock:
                _ws_conns.discard(conn)


_CMD_RE = re.compile(r'^\s*/(\w+)(.*)', re.DOTALL)


def _transfer_allowed(author_id):
    """True if this Discord user may use /transfer and /stoptransfer. An empty
    TRANSFER_USERS set means anyone is allowed."""
    return not TRANSFER_USERS or str(author_id or '') in TRANSFER_USERS


def handle_command(content, author_id=None):
    """Parse a '/command' from the channel and relay it to the alts. Returns True
    if the message was a command (so it isn't also treated as a join)."""
    match = _CMD_RE.match(content or '')
    if not match:
        return False
    cmd = match.group(1).lower()
    rest = match.group(2) or ''
    if cmd == 'waitlist':
        print(Fore.LIGHTCYAN_EX + 'Waitlist:\n' + waitlist_text() + Style.RESET_ALL)
        return True
    if cmd in ('transfer', 'stoptransfer') and not _transfer_allowed(author_id):
        print(Fore.RED + '/{} denied for user {} (not authorized)'.format(cmd, author_id)
              + Style.RESET_ALL)
        return True
    if cmd in ('inv', 'invf', 'rejoin', 'stoptransfer'):
        broadcast_command(cmd)
        print(Fore.LIGHTCYAN_EX + 'Command /{} -> alts'.format(cmd) + Style.RESET_ALL)
        return True
    if cmd == 'transfer':
        rar = re.search(r'fromrarity:\s*(\S+)', rest, re.IGNORECASE)
        usr = re.search(r'user:\s*(\S+)', rest, re.IGNORECASE)
        user = usr.group(1) if usr else None
        if not user:
            print(Fore.RED + '/transfer needs a user: <name>' + Style.RESET_ALL)
            return True
        args = {'fromrarity': rar.group(1) if rar else 'Godly', 'user': user}
        broadcast_command('transfer', args)
        print(Fore.LIGHTCYAN_EX + 'Command /transfer {} -> alts'.format(args) + Style.RESET_ALL)
        return True
    return False


def _handle_ws_message(msg):
    global _ws_seen_any
    if msg.get('event') == 'next':
        jid = msg.get('jobId')
        with _join_lock:
            removed = bool(jid) and _hits.pop(jid, None) is not None
        if removed:
            print(Fore.LIGHTCYAN_EX + 'Claimed {} - moving to the next in the waitlist.'.format(jid)
                  + Style.RESET_ALL)
        _retarget()   # promote the next-highest hit (top is unchanged if claim was elsewhere)
        return
    username = str(msg.get('username') or '').strip()
    if not username:
        return
    job_id = str(msg.get('jobId') or '') or None
    with _ws_lock:
        _ws_seen_any = True
        prev = _ws_registry.get(username)
        _ws_registry[username] = {'last_seen': time.time(), 'status': str(msg.get('status') or ''),
                                  'jobId': job_id}
    if job_id and (not prev or prev.get('jobId') != job_id):
        with _join_lock:
            hit = _hits.get(job_id)
        giver = (hit or {}).get('giver') or (_join_target.get('giver')
                 if _join_target.get('jobId') == job_id else None)
        print(Fore.GREEN + '{} joined {}{}'.format(
            username, job_id, ' (giver: {})'.format(giver) if giver else '') + Style.RESET_ALL)
    set_gateway_presence(_presence_summary())


def _ws_client_thread(conn):
    try:
        if not _ws_handshake(conn):
            return
        with _ws_conns_lock:
            _ws_conns.add(conn)
        # a fresh/relaunched client heads to the current top of the waitlist
        _retarget()
        with _join_lock:
            place_id, job_id, giver = (_join_target['placeId'], _join_target['jobId'],
                                       _join_target['giver'])
            expected = (_hits.get(job_id) or {}).get('expected', 0) if job_id else 0
        if place_id and job_id:
            try:
                _send_teleport(conn, place_id, job_id, giver, expected)
            except OSError:
                pass
        while True:
            opcode, payload = _ws_recv_frame(conn)
            if opcode is None or opcode == 0x8:
                break
            if opcode == 0x9:
                _ws_send_frame(conn, payload, opcode=0xA)
                continue
            if opcode in (0x1, 0x2):
                try:
                    _handle_ws_message(json.loads(payload.decode('utf-8', 'ignore')))
                except ValueError:
                    pass
    except OSError:
        pass
    finally:
        with _ws_conns_lock:
            _ws_conns.discard(conn)
        try:
            conn.close()
        except OSError:
            pass


def start_ws_server():
    def serve():
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind((WS_HOST, WS_PORT))
            srv.listen(16)
        except OSError as e:
            print(Fore.RED + 'WS check server could not bind {}:{} - {}'.format(WS_HOST, WS_PORT, e)
                  + Style.RESET_ALL)
            return
        local_ip = get_local_ip()
        print(Fore.LIGHTCYAN_EX + 'WS server on {}:{} (mm2.lua will connect to {})'.format(
            WS_HOST, WS_PORT, local_ip) + Style.RESET_ALL)
        try:
            settings = load_settings()
            settings['wshost'] = local_ip
            save_settings(settings)
        except Exception:
            pass
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                break
            threading.Thread(target=_ws_client_thread, args=(conn,), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()


def reset_executor_file(username):
    """Drop any stale heartbeat so a relaunch waits for a fresh one."""
    with _ws_lock:
        _ws_registry.pop(username, None)


def check_executor_status(username, max_wait_time=230, check_interval=4,
                          max_inactivity_time=EXECUTOR_INACTIVITY_SECONDS):
    """True once this username has sent a recent WS heartbeat. If no client has
    ever connected (WS unsupported/blocked), don't block - treat as fine."""
    retry_timeout = time.time() + max_wait_time
    while True:
        with _ws_lock:
            if not _ws_seen_any:
                return True
            entry = _ws_registry.get(username)
        if entry and (time.time() - entry['last_seen'] < max_inactivity_time):
            if not entry['status'].startswith('error'):
                return True
        if time.time() > retry_timeout:
            return False
        time.sleep(check_interval)


def executor_check_with_wait(username, package_name, package_statuses):
    """Check the executor; on failure wait out the grace period and retry once."""
    if check_executor_status(username):
        set_status(package_statuses, package_name, Fore.GREEN,
                   'Executor loaded successfully for {}'.format(username))
        return True

    print('Executor did not load for {} (username: {}). Waiting {}s...'.format(
        package_name, username, EXECUTOR_GRACE_SECONDS))
    set_status(package_statuses, package_name, Fore.YELLOW,
               'Executor not loaded, waiting {}s...'.format(EXECUTOR_GRACE_SECONDS))
    time.sleep(EXECUTOR_GRACE_SECONDS)

    if check_executor_status(username):
        set_status(package_statuses, package_name, Fore.GREEN,
                   'Executor loaded successfully for {} (after wait)'.format(username))
        return True

    print('Executor still not loaded for {}, continuing...'.format(package_name))
    set_status(package_statuses, package_name, Fore.YELLOW, 'Executor timeout, continuing...')
    return False


# ------------------------------------------------ settings (aj.txt)

def load_settings():
    """Read aj.txt (JSON) from the script dir or any Delta workspace."""
    paths = [SETTINGS_FILE] + [os.path.join(ws, 'aj.txt') for ws in delta_workspace_paths()]
    for path in paths:
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (IOError, ValueError):
            continue
    return {}


def save_settings(settings):
    """Write aj.txt into the script dir plus every Delta workspace (for mm2.lua)."""
    blob = json.dumps(settings)
    targets = [SETTINGS_FILE] + [os.path.join(ws, 'aj.txt') for ws in delta_workspace_paths()]
    saved = 0
    for path in targets:
        try:
            with open(path, 'w') as f:
                f.write(blob)
            saved += 1
        except IOError:
            pass
    return saved


def ensure_settings():
    """Load token / hits channel / log channel from aj.txt, prompting for any
    that are missing, then save aj.txt and apply them. Runs before joining."""
    global BOT_TOKEN, CHANNEL_ID, LOG_ID, MIN_RARITY, TRANSFER_USERS
    settings = load_settings()
    token = (settings.get('token') or '').strip()
    chanelid = (settings.get('chanelid') or '').strip()
    logid = (settings.get('logid') or '').strip()
    minrarity = (settings.get('minrarity') or '').strip()
    changed = False

    if not token:
        token = BOT_TOKEN or input('Discord bot token: ').strip()
        changed = True
    if not chanelid:
        chanelid = input('Hits channel id: ').strip()
        changed = True
    if not logid:
        logid = input('Log channel id: ').strip()
        changed = True
    if not minrarity:
        entered = input('Min rarity used (Godly/Ancient/Unique/...) [Godly]: ').strip()
        minrarity = entered.title() if entered else 'Godly'
        changed = True

    # 'transferusers' can legitimately be empty (= anyone allowed), so check
    # whether it was ever set rather than whether it's truthy.
    if 'transferusers' in settings:
        transferusers = settings.get('transferusers') or ''
    else:
        transferusers = input(
            'Discord user id(s) allowed to use /transfer and /stoptransfer '
            '(comma-separated, Enter = anyone): ').strip()
        changed = True

    if changed and token:
        count = save_settings({'token': token, 'chanelid': chanelid, 'logid': logid,
                               'minrarity': minrarity, 'transferusers': transferusers})
        print(Fore.GREEN + 'Settings saved to aj.txt ({} location(s)).'.format(count) + Style.RESET_ALL)

    if token:
        BOT_TOKEN = token
    if chanelid:
        CHANNEL_ID = chanelid
    if logid:
        LOG_ID = logid
    if minrarity:
        MIN_RARITY = minrarity
    TRANSFER_USERS = {u.strip() for u in transferusers.split(',') if u.strip()}
    if TRANSFER_USERS:
        print(Fore.GREEN + '/transfer and /stoptransfer restricted to: {}'.format(
            ', '.join(TRANSFER_USERS)) + Style.RESET_ALL)


# ------------------------------------------------ discord join-channel scan

def _msg_age_seconds(mid):
    """Age of a Discord message from its snowflake id, in seconds."""
    try:
        return time.time() - (((int(mid) >> 22) + _DISCORD_EPOCH) / 1000.0)
    except (ValueError, TypeError):
        return 0.0


def _parse_join(content):
    """Same two formats main.lua's processJoinMessage matches."""
    match = _JOIN_RE1.search(content) or _JOIN_RE2.search(content)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def _value_from_text(text):
    """Pull the hit's total value out of embed text. Lowercased first so both
    'Total Value:' and 'Total value:' (and other casings) match."""
    match = _VALUE_RE.search((text or '').lower())
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _giver_from_text(text):
    """Pull the giver's Roblox username out of the embed (the 'Username:' field).
    Case-insensitive on the label, keeps the username's own casing."""
    match = _GIVER_RE.search(text or '')
    return match.group(1) if match else None


def _expected_items(text):
    """Count the giver's items at/above MIN_RARITY from the embed text. This is
    how many items mm2 must claim in total.

    Two embed styles are supported:
      1. Aggregate per-rarity lines, e.g. 'Godly : 4'.
      2. Per-item lines with the rarity tagged in parens, e.g.
         'x1 Hallow's Edge -> 8 Value (Godly)' - summed per line via the
         leading 'xN' quantity (defaulting to 1 if there isn't one)."""
    low = (text or '').lower()
    try:
        start = RARITY_ORDER.index(MIN_RARITY)
    except ValueError:
        start = RARITY_ORDER.index('Godly')
    total = 0
    for rar in RARITY_ORDER[start:]:
        m = re.search(r'\b' + rar.lower() + r'\b\s*[:=]?\s*(\d+)', low)
        if m:
            total += int(m.group(1))
    if total:
        return total

    for rar in RARITY_ORDER[start:]:
        for line in low.split('\n'):
            if re.search(r'\(\s*' + rar.lower() + r'\s*\)', line):
                qty = re.search(r'x(\d+)\b', line)
                total += int(qty.group(1)) if qty else 1
    return total


def embed_text_discord(message):
    """Flatten a discord.py Message's embeds into one text blob."""
    parts = []
    for emb in getattr(message, 'embeds', None) or []:
        parts.append(emb.title or '')
        parts.append(emb.description or '')
        for field in emb.fields:
            parts.append(field.name or '')
            parts.append(field.value or '')
        if emb.footer and emb.footer.text:
            parts.append(emb.footer.text)
    return '\n'.join(parts)


def embed_text_raw(embeds):
    """Flatten raw REST embed dicts into one text blob."""
    parts = []
    for emb in embeds or []:
        parts.append(emb.get('title') or '')
        parts.append(emb.get('description') or '')
        for field in emb.get('fields') or []:
            parts.append(field.get('name') or '')
            parts.append(field.get('value') or '')
        parts.append((emb.get('footer') or {}).get('text') or '')
    return '\n'.join(parts)


def fetch_discord_messages(after_id=None):
    url = '{}/channels/{}/messages?limit=50'.format(DISCORD_API, CHANNEL_ID)
    if after_id:
        url += '&after=' + after_id
    try:
        resp = requests.get(url, headers={'Authorization': 'Bot ' + BOT_TOKEN}, timeout=20)
        if resp.status_code == 200:
            return resp.json()
    except (requests.RequestException, ValueError):
        pass
    return []


def react_check(mid):
    """Add a :white_check_mark: reaction to a message (REST)."""
    emoji = quote('✅')
    url = '{}/channels/{}/messages/{}/reactions/{}/@me'.format(DISCORD_API, CHANNEL_ID, mid, emoji)
    try:
        requests.put(url, headers={'Authorization': 'Bot ' + BOT_TOKEN}, timeout=15)
    except requests.RequestException:
        pass


def handle_channel_message(mid, content, embeds=None, value=None, giver=None, author_id=None):
    """Single entry point for a channel message from either the gateway or the
    REST backstop. Message-id deduped so nothing runs twice, then command-or-join.
    Returns 'command', 'hit', or None."""
    mid = str(mid)
    with _join_lock:
        if mid in _seen_msgs:
            return None
        _seen_msgs.add(mid)
    if handle_command(content or '', author_id):
        return 'command'
    ok = _process_join_message({
        'id': mid,
        'author': {'username': 'x'},
        'content': content or '',
        'embeds': embeds,
        'value': value,
        'giver': giver,
    })
    return 'hit' if ok else None


def _process_join_message(message):
    if not message or not message.get('author'):
        return
    place_id, job_id = _parse_join(message.get('content') or '')
    if not (place_id and job_id):
        return
    if int(place_id) not in JOIN_GAMES:
        return
    if message['id'] in _seen_join_msgs:
        return
    _seen_join_msgs.add(message['id'])

    if _msg_age_seconds(message['id']) > MAX_HIT_AGE:
        return   # message too old - the server is almost certainly dead

    value = message.get('value')
    giver = message.get('giver')
    expected = message.get('expected')
    if message.get('embeds') is not None:
        etext = embed_text_raw(message['embeds'])
        if value is None:
            value = _value_from_text(etext)
        if giver is None:
            giver = _giver_from_text(etext)
        if expected is None:
            expected = _expected_items(etext)

    with _join_lock:
        _hits[job_id] = {'placeId': place_id, 'jobId': job_id, 'giver': giver,
                         'value': value if value is not None else 0.0,
                         'expected': expected or 0, 'ts': time.time()}
    _retarget()
    return True


def _retarget():
    """Point _join_target at the highest-value live hit and broadcast if it
    changed. Prunes expired hits. This is the whole join priority in one place."""
    now = time.time()
    with _join_lock:
        for jid in [j for j, h in _hits.items() if now - h['ts'] > _HIT_TTL]:
            del _hits[jid]
        best = None
        for h in _hits.values():
            if best is None or h['value'] > best['value']:
                best = h
        changed = (best or {}).get('jobId') != _join_target['jobId']
        if best:
            _join_target.update({'placeId': best['placeId'], 'jobId': best['jobId'],
                                 'msgid': None, 'giver': best['giver']})
            tgt = dict(best)
        else:
            _join_target.update({'placeId': None, 'jobId': None, 'msgid': None, 'giver': None})
            tgt = None
    if changed and tgt:
        mode = PLACE_NAMES.get(int(tgt['placeId']), tgt['placeId'])
        print(Fore.LIGHTCYAN_EX + 'Target [{}]: job {} value {} giver {} ({} items) -> teleporting'
              .format(mode, tgt['jobId'], tgt['value'], tgt['giver'], tgt.get('expected', 0))
              + Style.RESET_ALL)
        broadcast_teleport(tgt['placeId'], tgt['jobId'], tgt['giver'], tgt.get('expected', 0))


def waitlist():
    """Live hits, highest value first (index 0 = joining now)."""
    now = time.time()
    with _join_lock:
        hits = [dict(h) for h in _hits.values() if now - h['ts'] <= _HIT_TTL]
    hits.sort(key=lambda h: h['value'], reverse=True)
    return hits


def waitlist_text():
    hits = waitlist()
    if not hits:
        return 'Waitlist is empty.'
    labels = ['joining now', 'joining second', 'joining third']
    lines = []
    for i, h in enumerate(hits):
        pos = labels[i] if i < len(labels) else 'joining #{}'.format(i + 1)
        lines.append('{}: {:g} value ({})'.format(h['giver'] or '?', h['value'], pos))
    return '\n'.join(lines)


def retarget_loop():
    """Periodically prune expired hits and retarget, even with no new events."""
    while True:
        time.sleep(15)
        try:
            _retarget()
        except Exception:
            pass


def discord_scan_loop():
    """REST poll of the channel. Runs alongside the gateway as a backstop so a
    dropped/zombied gateway (or a flaky content intent) can't make us miss a
    message - REST always returns content, and _seen_msgs dedups vs the gateway.
    The first batch only sets the cursor (doesn't replay old messages)."""
    last_id = None
    first = True
    while True:
        try:
            messages = fetch_discord_messages(last_id)
            if messages:
                last_id = messages[0]['id']
            if not first:
                for message in reversed(messages):
                    author_id = (message.get('author') or {}).get('id')
                    if handle_channel_message(message.get('id'), message.get('content'),
                                              message.get('embeds'), author_id=author_id) == 'hit':
                        react_check(message.get('id'))
            first = False
        except Exception as e:
            print(Fore.RED + 'Discord scan error: {}'.format(e) + Style.RESET_ALL)
        time.sleep(DISCORD_SCAN_INTERVAL)


# ------------------------------------------------ discord gateway (presence)

def _wss_connect(host):
    """Open a TLS WebSocket client connection to the Discord gateway and finish
    the HTTP upgrade handshake. Returns the ssl socket or None."""
    raw = socket.create_connection((host, 443), timeout=30)
    sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((
        'GET /?v=10&encoding=json HTTP/1.1\r\n'
        'Host: ' + host + '\r\n'
        'Upgrade: websocket\r\n'
        'Connection: Upgrade\r\n'
        'Sec-WebSocket-Key: ' + key + '\r\n'
        'Sec-WebSocket-Version: 13\r\n\r\n').encode())
    data = b''
    while b'\r\n\r\n' not in data:
        chunk = sock.recv(1024)
        if not chunk:
            sock.close()
            return None
        data += chunk
    if b' 101 ' not in data.split(b'\r\n', 1)[0]:
        sock.close()
        return None
    return sock


def _gw_send_masked(sock, payload, opcode=0x1):
    """Client -> server frames must be masked (RFC6455)."""
    length = len(payload)
    header = bytearray([0x80 | opcode])
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header += struct.pack('>H', length)
    else:
        header.append(0x80 | 127)
        header += struct.pack('>Q', length)
    mask = os.urandom(4)
    header += mask
    masked = bytes(payload[i] ^ mask[i % 4] for i in range(length))
    with _gw_send_lock:
        sock.sendall(bytes(header) + masked)


def _gw_send(op, d):
    sock = _gw_sock
    if not sock:
        return
    try:
        _gw_send_masked(sock, json.dumps({'op': op, 'd': d}).encode('utf-8'))
    except OSError:
        pass


def _presence_summary():
    """Aggregate what the alts are doing into one presence string."""
    now = time.time()
    with _ws_lock:
        statuses = [e.get('status') or 'Unknown' for e in _ws_registry.values()
                    if now - e['last_seen'] < EXECUTOR_INACTIVITY_SECONDS]
    if not statuses:
        return 'MM2 idle'
    counts = {}
    for st in statuses:
        counts[st] = counts.get(st, 0) + 1
    parts = ['{} {}'.format(n, st) for st, n in sorted(counts.items(), key=lambda kv: -kv[1])]
    return 'MM2: ' + ', '.join(parts)


def set_gateway_presence(text):
    """Update the bot presence. Prefers discord.py; falls back to the stdlib
    gateway. No-ops until connected; throttled."""
    global _last_presence_text, _last_presence_at
    now = time.time()
    if text == _last_presence_text and (now - _last_presence_at) < 15:
        return

    if _discord_client is not None and _discord_loop is not None:
        _last_presence_text, _last_presence_at = text, now
        try:
            asyncio.run_coroutine_threadsafe(
                _discord_client.change_presence(activity=_discord.Game(name=text)),
                _discord_loop)
        except RuntimeError:
            pass
        return

    if not _gw_ready or not _gw_sock:
        return
    _last_presence_text, _last_presence_at = text, now
    _gw_send(3, {'since': 0, 'activities': [{'name': text, 'type': 0}],
                 'status': 'online', 'afk': False})


def start_discord_bot():
    """Run a discord.py client (presence + channel scan) in its own thread.
    Returns True if started, False if discord.py isn't installed."""
    if _discord is None:
        return False

    intents = _discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.message_content = True
    client = _discord.Client(intents=intents)
    tree = _discord.app_commands.CommandTree(client)
    app_commands = _discord.app_commands

    @tree.command(name='waitlist', description='Show the server join queue, highest value first')
    async def _cmd_waitlist(interaction):
        await interaction.response.send_message('```\n' + waitlist_text() + '\n```')

    @tree.command(name='inv', description='Each alt posts its inventory')
    async def _cmd_inv(interaction):
        broadcast_command('inv')
        await interaction.response.send_message('`/inv` sent to the alts.')

    @tree.command(name='invf', description='Each alt posts its inventory as a file')
    async def _cmd_invf(interaction):
        broadcast_command('invf')
        await interaction.response.send_message('`/invf` sent to the alts.')

    @tree.command(name='rejoin', description='Rejoin the current server')
    async def _cmd_rejoin(interaction):
        broadcast_command('rejoin')
        await interaction.response.send_message('`/rejoin` sent to the alts.')

    @tree.command(name='stoptransfer', description='Stop trading / abort any transfer')
    async def _cmd_stoptransfer(interaction):
        if not _transfer_allowed(interaction.user.id):
            await interaction.response.send_message('You are not authorized to use this command.',
                                                     ephemeral=True)
            return
        broadcast_command('stoptransfer')
        await interaction.response.send_message('`/stoptransfer` sent to the alts.')

    @tree.command(name='transfer', description='Trade items at/above a rarity to a user')
    @app_commands.describe(user='Target Roblox username', fromrarity='Minimum rarity (default Godly)')
    async def _cmd_transfer(interaction, user: str, fromrarity: str = 'Godly'):
        if not _transfer_allowed(interaction.user.id):
            await interaction.response.send_message('You are not authorized to use this command.',
                                                     ephemeral=True)
            return
        broadcast_command('transfer', {'fromrarity': fromrarity, 'user': user})
        await interaction.response.send_message(
            '`/transfer` {}+ -> {} sent to the alts.'.format(fromrarity, user))

    async def _apply_presence():
        try:
            await client.change_presence(activity=_discord.Game(name=_presence_summary()))
        except Exception:
            pass

    @client.event
    async def on_ready():
        global _discord_loop
        _discord_loop = asyncio.get_event_loop()
        print(Fore.GREEN + 'Discord bot ready as {}'.format(client.user) + Style.RESET_ALL)
        try:
            channel = client.get_channel(int(CHANNEL_ID)) or await client.fetch_channel(int(CHANNEL_ID))
            # register the slash commands in this channel's guild (instant)
            try:
                guild = channel.guild
                tree.copy_global_to(guild=guild)
                synced = await tree.sync(guild=guild)
                print(Fore.GREEN + 'Registered {} slash commands.'.format(len(synced)) + Style.RESET_ALL)
            except Exception as e:
                print(Fore.RED + 'Slash command sync failed: {}'.format(e) + Style.RESET_ALL)
            history = [m async for m in channel.history(limit=50)]
            for message in reversed(history):
                pid, jid = _parse_join(message.content or '')
                if pid and jid and int(pid) in JOIN_GAMES:
                    _seen_join_msgs.add(str(message.id))
                    if _msg_age_seconds(str(message.id)) > MAX_HIT_AGE:
                        continue   # already stale on startup - skip
                    text = embed_text_discord(message)
                    with _join_lock:
                        _hits[jid] = {'placeId': pid, 'jobId': jid, 'giver': _giver_from_text(text),
                                      'value': _value_from_text(text) or 0.0,
                                      'expected': _expected_items(text), 'ts': time.time()}
            _retarget()
        except Exception as e:
            print(Fore.RED + 'Discord history scan failed: {}'.format(e) + Style.RESET_ALL)
        await _apply_presence()

    @client.event
    async def on_message(message):
        if str(message.channel.id) != str(CHANNEL_ID):
            return
        if (message.content or '').strip().lower() == '/waitlist':
            with _join_lock:
                _seen_msgs.add(str(message.id))
            try:
                await message.channel.send('```\n' + waitlist_text() + '\n```')
            except Exception as e:
                print(Fore.RED + '/waitlist send failed: {}'.format(e) + Style.RESET_ALL)
            return
        text = embed_text_discord(message)
        result = handle_channel_message(message.id, message.content or '', None,
                                        _value_from_text(text), _giver_from_text(text),
                                        author_id=message.author.id)
        if result == 'hit':
            try:
                await message.add_reaction('✅')
            except Exception:
                pass

    def run():
        global _discord_client
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _discord_client = client
        try:
            loop.run_until_complete(client.start(BOT_TOKEN))
        except Exception as e:
            print(Fore.RED + 'Discord bot error: {}'.format(e) + Style.RESET_ALL)

    threading.Thread(target=run, daemon=True).start()
    return True


def _gw_heartbeat(sock, interval):
    while _gw_sock is sock:
        time.sleep(interval)
        if _gw_sock is not sock:
            break
        try:
            _gw_send_masked(sock, json.dumps({'op': 1, 'd': _gw_seq}).encode('utf-8'))
        except OSError:
            break


def discord_gateway_loop():
    """Maintain a single Discord gateway connection for the bot presence.
    Ported from main.lua's connectgateway; presence only, no event handling."""
    global _gw_sock, _gw_ready, _gw_seq, _gw_session_id, _gw_resume_url, _gw_should_resume
    global _last_presence_text
    while True:
        host = GATEWAY_HOST
        if _gw_should_resume and _gw_resume_url:
            host = _gw_resume_url.replace('wss://', '').replace('/', '') or GATEWAY_HOST
        try:
            sock = _wss_connect(host)
        except (OSError, ssl.SSLError):
            sock = None
        if not sock:
            time.sleep(5)
            continue

        _gw_sock = sock
        _gw_ready = False
        try:
            while True:
                opcode, payload = _ws_recv_frame(sock)
                if opcode is None or opcode == 0x8:
                    break
                if opcode == 0x9:
                    try:
                        _gw_send_masked(sock, payload, opcode=0xA)
                    except OSError:
                        break
                    continue
                if opcode not in (0x1, 0x2):
                    continue
                try:
                    data = json.loads(payload.decode('utf-8', 'ignore'))
                except ValueError:
                    continue
                if data.get('s') is not None:
                    _gw_seq = data['s']
                op = data.get('op')
                if op == 10:
                    interval = data['d']['heartbeat_interval'] / 1000.0
                    if _gw_should_resume and _gw_session_id and _gw_seq is not None:
                        _gw_send(6, {'token': BOT_TOKEN, 'session_id': _gw_session_id, 'seq': _gw_seq})
                    else:
                        _gw_send(2, {'token': BOT_TOKEN, 'intents': 0,
                                     'properties': {'os': 'linux', 'browser': 'nub', 'device': 'nub'}})
                    threading.Thread(target=_gw_heartbeat, args=(sock, interval), daemon=True).start()
                elif op == 0 and data.get('t') == 'READY':
                    _gw_session_id = data['d'].get('session_id')
                    _gw_resume_url = data['d'].get('resume_gateway_url')
                    _gw_should_resume = True
                    _gw_ready = True
                    _last_presence_text = None
                    set_gateway_presence(_presence_summary())
                elif op == 0 and data.get('t') == 'RESUMED':
                    _gw_ready = True
                    _last_presence_text = None
                    set_gateway_presence(_presence_summary())
                elif op == 7:
                    _gw_should_resume = True
                    break
                elif op == 9:
                    _gw_should_resume = bool(data.get('d'))
                    if not _gw_should_resume:
                        _gw_session_id = None
                    time.sleep(1 + (os.urandom(1)[0] % 5))
                    break
        except OSError:
            pass
        finally:
            try:
                sock.close()
            except OSError:
                pass
            if _gw_sock is sock:
                _gw_sock = None
            _gw_ready = False
        if _gw_session_id and _gw_seq is not None:
            _gw_should_resume = True
        time.sleep(5)


# ---------------------------------------------------------------- delta key

def delta_licence_paths():
    """Every Delta clone's licence file on this device.

    Covers plain /Delta/ plus numbered clones (Delta2, Delta_3, ...), since the
    key has to land in each one separately.
    """
    paths = []
    base_dir = '/storage/emulated/0'
    try:
        entries = sorted(os.listdir(base_dir))
    except OSError:
        return paths
    for entry in entries:
        if entry.lower().startswith('delta'):
            cache = os.path.join(base_dir, entry, 'Internals', 'Cache')
            if not os.path.isdir(cache):
                continue
            chosen = None
            for name in ('license', 'licence'):
                candidate = os.path.join(cache, name)
                if os.path.isfile(candidate):
                    chosen = candidate
                    break
            paths.append(chosen or os.path.join(cache, 'license'))
    return paths


def read_supplied_key():
    """The key you obtained yourself, dropped into delta_key.txt next to this
    script. Returns None if the file is missing or empty."""
    try:
        with open(DELTA_KEY_FILE, 'r') as f:
            key = f.read().strip()
        return key or None
    except IOError:
        return None


def write_delta_licence(key):
    """Copy the key into every Delta clone's licence file. Returns how many
    were written. Also remembers the key we just wrote (see current_delta_key) -
    some Delta builds re-encrypt the licence file once they load it, so reading
    it back later can't recover the plaintext key."""
    written = 0
    for path in delta_licence_paths():
        try:
            with open(path, 'w') as f:
                f.write(key)
            written += 1
        except IOError as e:
            print(Fore.RED + 'Could not write {}: {}'.format(path, e) + Style.RESET_ALL)
    if written:
        save_key_state(key)
    return written


def save_key_state(key):
    """Remember the last key we wrote (the licence file may not stay readable)."""
    try:
        with open(KEY_STATE_FILE, 'w') as f:
            json.dump({'key': key, 'ts': time.time()}, f)
    except IOError:
        pass


def load_key_state():
    try:
        with open(KEY_STATE_FILE, 'r') as f:
            data = json.load(f)
        return (data.get('key') or '').strip() or None
    except (IOError, ValueError):
        return None


def refresh_delta_key(package_statuses=None):
    """Push the supplied key out to every Delta clone.

    Returns True if a *new* key was written (callers relaunch so Delta picks it
    up), False if there was nothing to do.
    """
    global _last_written_key
    key = read_supplied_key()
    if not key:
        print(Fore.YELLOW + 'No Delta key in {} - skipping key refresh.'.format(DELTA_KEY_FILE)
              + Style.RESET_ALL)
        return False
    if key == _last_written_key:
        return False

    written = write_delta_licence(key)
    if written:
        _last_written_key = key
        print(Fore.GREEN + 'Delta key written to {} licence file(s).'.format(written) + Style.RESET_ALL)
        return True

    print(Fore.RED + 'No Delta licence directories found - is Delta installed?' + Style.RESET_ALL)
    return False


# ------------------------------------------------ automatic delta key

def sha256_hex(value):
    """platorelay identifier = sha256(hwid) as lowercase hex (see DeltaUI.lua)."""
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def read_bypass_api_key():
    """BypassTools API key from $BYPASSTOOLS_API_KEY or bypass_key.txt."""
    key = os.environ.get('BYPASSTOOLS_API_KEY')
    if key and key.strip():
        return key.strip()
    try:
        with open(BYPASS_KEY_FILE, 'r') as f:
            return f.read().strip() or None
    except IOError:
        return None


def ensure_bt_api_key():
    """Return the BypassTools API key, prompting for it once and saving it to
    bypass_key.txt if none is set yet. Returns None if nothing was entered."""
    key = read_bypass_api_key()
    if key:
        return key
    entry = input('Paste your BypassTools API key (bt_...): ').strip()
    if not entry:
        return None
    try:
        with open(BYPASS_KEY_FILE, 'w') as f:
            f.write(entry)
        print(Fore.GREEN + 'BypassTools API key saved.' + Style.RESET_ALL)
    except IOError as e:
        print(Fore.RED + 'Could not save API key: {}'.format(e) + Style.RESET_ALL)
    return entry


def delta_workspace_paths():
    """The workspace folder of every Delta clone (Delta creates it itself)."""
    paths = []
    base_dir = '/storage/emulated/0'
    try:
        entries = sorted(os.listdir(base_dir))
    except OSError:
        return paths
    for entry in entries:
        if entry.lower().startswith('delta'):
            ws = os.path.join(base_dir, entry, 'workspace')
            if os.path.isdir(ws):
                paths.append(ws)
    return paths


def _hwid_paths():
    return [HWID_FILE] + [os.path.join(ws, 'hwid.txt') for ws in delta_workspace_paths()]


def save_hwid(hwid):
    """Persist the device hwid into every Delta workspace plus a copy next to
    this script, so later daily refreshes are hands-free. Returns count saved."""
    hwid = hwid.strip()
    saved = 0
    for path in _hwid_paths():
        try:
            with open(path, 'w') as f:
                f.write(hwid)
            saved += 1
        except IOError:
            pass
    return saved


def load_hwid():
    """First saved hwid found (script dir first, then any Delta workspace)."""
    for path in _hwid_paths():
        try:
            with open(path, 'r') as f:
                value = f.read().strip()
            if value:
                return value
        except IOError:
            continue
    return None


def platorelay_start(identifier):
    """POST /public/start -> the checkpoint URL to complete for this device."""
    resp = requests.post(
        PLATORELAY_BASE + '/public/start',
        json={'service': DELTA_SERVICE, 'identifier': identifier},
        headers={'Content-Type': 'application/json'},
        timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get('success'):
        raise RuntimeError('platorelay start failed: {}'.format(data.get('message')))
    return data['data']['url']


def current_delta_key():
    """The key Delta currently has, preferring the key WE last wrote (see
    write_delta_licence) since some Delta builds re-encrypt the licence file
    once they load it, making the plaintext unrecoverable from the file itself.
    Falls back to reading the licence file directly (handles a raw key or a
    JSON licence that embeds one) for a key placed there some other way -
    binary/encrypted content is read leniently but only an actual KEY_/FREE_
    match counts; garbled decoded bytes are never mistaken for a key."""
    remembered = load_key_state()
    if remembered:
        return remembered
    for path in delta_licence_paths():
        try:
            with open(path, 'rb') as f:
                raw = f.read()
        except IOError:
            continue
        if not raw:
            continue
        content = raw.decode('utf-8', errors='ignore')
        match = _KEY_PATTERN.search(content)
        if match:
            return match.group(0)
    return None


def check_key_valid(hwid, key):
    """Ask platorelay whether this key is still valid for this device.

    GET /public/expires/{service}?identifier=sha256(hwid)&key=...
    Returns (is_valid, expiration_ms_or_None).
    """
    identifier = sha256_hex(hwid)
    url = ('{}/public/expires/{}?identifier={}&key={}'
           .format(PLATORELAY_BASE, DELTA_SERVICE, identifier, key))
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get('success'):
        return False, None
    info = data.get('data', {})
    expiration = info.get('expiration', info.get('expires'))
    return bool(info.get('valid')), expiration


def bypass_link(link, api_key):
    """Run a checkpoint link through BypassTools. Returns (result_url, process_ms).

    Prefers the official `bypasstools` SDK when installed; otherwise falls back
    to raw HTTP against the same endpoints.
    """
    if _BypassToolsSDK is not None:
        client = _BypassToolsSDK(api_key=api_key, timeout=90)
        try:
            result = client.bypass(link, refresh=False)
            return result.result_url, getattr(result, 'process_time', 0) or 0
        except _BypassToolsError as e:
            code = getattr(e, 'code', '') or ''
            if code in ('QUOTA_EXCEEDED', 'ACCOUNT_EXPIRED', 'UNAUTHORIZED'):
                raise RuntimeError('BypassTools {}: {}'.format(code or getattr(e, 'status', ''), e))
            result = client.bypass_async(link, poll_interval=1.5, timeout=120)
            return result.result_url, getattr(result, 'process_time', 0) or 0
    return _bypass_link_http(link, api_key)


def _bypass_link_http(link, api_key):
    """Raw-HTTP fallback for bypass_link when the SDK is not installed.

    Tries the synchronous /bypass/direct first and falls back to the async
    create-task + poll flow if the sync call times out.
    """
    headers = {'x-api-key': api_key, 'Content-Type': 'application/json'}
    try:
        resp = requests.post(BYPASS_BASE + '/bypass/direct',
                             json={'url': link}, headers=headers, timeout=90)
        if resp.status_code in (401, 403):
            raise RuntimeError('BypassTools auth/quota error ({}): {}'.format(
                resp.status_code, resp.json().get('message')))
        data = resp.json()
        if data.get('status') == 'success':
            return data['result'], data.get('processTime', 0)
    except requests.Timeout:
        pass

    resp = requests.post(BYPASS_BASE + '/bypass/createTask',
                        json={'url': link}, headers=headers, timeout=30)
    task_id = resp.json().get('taskId')
    if not task_id:
        raise RuntimeError('BypassTools createTask failed: {}'.format(resp.json().get('message')))
    deadline = time.time() + 120
    while time.time() < deadline:
        time.sleep(2)
        poll = requests.get(BYPASS_BASE + '/bypass/getTaskResult/' + task_id,
                           headers=headers, timeout=30).json()
        status = poll.get('status')
        if status == 'success':
            return poll['result'], poll.get('processTime', 0)
        if status == 'error':
            raise RuntimeError('BypassTools failed: {}'.format(poll.get('message')))
    raise RuntimeError('BypassTools timed out')


def extract_key(result_url):
    """Pull a Delta KEY_ out of a bypass result: the URL itself, its query
    params, then the fetched destination page as a last resort."""
    if not result_url:
        return None
    match = _KEY_PATTERN.search(result_url)
    if match:
        return match.group(0)
    try:
        params = parse_qs(urlparse(result_url).query)
        for name in ('key', 'k', 'license', 'licence'):
            if params.get(name):
                return params[name][0]
    except Exception:
        pass
    try:
        page = requests.get(result_url, timeout=30).text
        match = _KEY_PATTERN.search(page)
        if match:
            return match.group(0)
    except requests.RequestException:
        pass
    return None


def _bypass_and_write(link, api_key, started=None):
    """Bypass one checkpoint link, pull the key out and write it to every Delta
    clone's licence file. Returns True when a key was written."""
    global _last_written_key
    if started is None:
        started = time.time()
    print(Fore.LIGHTCYAN_EX + 'Bypassing checkpoint via BypassTools...' + Style.RESET_ALL)
    result_url, process_ms = bypass_link(link, api_key)
    key = extract_key(result_url)
    elapsed = time.time() - started
    if not key:
        print(Fore.RED + 'Bypass returned no key. Result: {} (spent {:.1f}s)'.format(
            result_url, elapsed) + Style.RESET_ALL)
        return False
    written = write_delta_licence(key)
    elapsed = time.time() - started
    if written:
        _last_written_key = key
        print(Fore.GREEN + 'SUCCESS - key written to {} Delta licence file(s). '
              'Bypass {:.1f}s, total {:.1f}s.'.format(
                  written, process_ms / 1000.0, elapsed) + Style.RESET_ALL)
        return True
    print(Fore.RED + 'Got a key but no Delta licence dirs found - is Delta installed? '
          '(spent {:.1f}s)'.format(elapsed) + Style.RESET_ALL)
    return False


def auto_get_delta_key(package_statuses=None):
    """Obtain a fresh Delta key automatically and write it to every clone's
    licence file. Returns True when a new key was written.

    Falls back to the manual delta_key.txt flow when no BypassTools key is set.
    """
    api_key = ensure_bt_api_key()
    if not api_key:
        return refresh_delta_key(package_statuses)

    hwid = load_hwid()
    if not hwid:
        print(Fore.RED + 'No saved hwid - run first time setup first.' + Style.RESET_ALL)
        return False

    started = time.time()
    try:
        print(Fore.LIGHTCYAN_EX + 'Requesting platorelay link for this device...' + Style.RESET_ALL)
        link = platorelay_start(sha256_hex(hwid))
        return _bypass_and_write(link, api_key, started)
    except Exception as e:
        elapsed = time.time() - started
        print(Fore.RED + 'FAILED to auto-get Delta key: {} (spent {:.1f}s)'.format(e, elapsed)
              + Style.RESET_ALL)
        if read_supplied_key():
            print(Fore.YELLOW + 'Falling back to the key in delta_key.txt.' + Style.RESET_ALL)
            return refresh_delta_key(package_statuses)
        return False


def first_time_setup():
    """Prompt once for the BypassTools API key and either the device hwid or a
    platorelay link. Returns (kind, value) with kind 'hwid' or 'link', or
    (None, None) if nothing was entered. Saves the hwid when one is given."""
    print(Fore.YELLOW + 'First time setup.' + Style.RESET_ALL)
    ensure_bt_api_key()
    print('In Delta run ' + Fore.LIGHTCYAN_EX + 'setclipboard(gethwid())' + Style.RESET_ALL
          + ' to copy your hwid, or copy your platorelay link.')
    entry = input('Paste your hwid or platorelay link: ').strip()
    if not entry:
        return None, None
    if _HWID_PATTERN.match(entry):
        save_hwid(entry)
        print(Fore.GREEN + 'hwid saved to Delta workspace.' + Style.RESET_ALL)
        return 'hwid', entry
    return 'link', entry


def ensure_valid_delta_key(package_statuses=None):
    """Startup gate: only join once Delta has a valid key.

    With a saved hwid it checks the existing key's validity FIRST (so it never
    wastes a bypass when the current key is still good) and only bypasses when
    the key is missing or expired. First run has no saved hwid, so it asks for
    the hwid or a platorelay link plus the API key; a pasted hwid still runs the
    validity check before deciding to bypass, a pasted link is bypassed directly.

    Returns True when a *new* key was written (so callers can relaunch).
    """
    hwid = load_hwid()
    if not hwid:
        kind, value = first_time_setup()
        if not kind:
            print(Fore.RED + 'Nothing entered - cannot manage the Delta key.' + Style.RESET_ALL)
            return False
        if kind == 'link':
            api_key = ensure_bt_api_key()
            if not api_key:
                return refresh_delta_key(package_statuses)
            try:
                return _bypass_and_write(value, api_key)
            except Exception as e:
                print(Fore.RED + 'FAILED to get Delta key from link: {}'.format(e) + Style.RESET_ALL)
                return False
        hwid = value

    key = current_delta_key()
    if key:
        print(Fore.LIGHTCYAN_EX + 'Checking current Delta key...' + Style.RESET_ALL)
        try:
            valid, expiration = check_key_valid(hwid, key)
        except Exception as e:
            print(Fore.RED + 'Could not check Delta key validity: {}'.format(e) + Style.RESET_ALL)
            valid, expiration = False, None
        if valid:
            if expiration:
                hours_left = max(0, (int(expiration) - int(time.time() * 1000)) / 3600000.0)
                print(Fore.GREEN + 'Delta key is valid ({:.1f}h left) - joining.'.format(hours_left)
                      + Style.RESET_ALL)
            else:
                print(Fore.GREEN + 'Delta key is valid - joining.' + Style.RESET_ALL)
            return False
        print(Fore.YELLOW + 'Delta key invalid or expired - fetching a new one.' + Style.RESET_ALL)
    else:
        print(Fore.YELLOW + 'No Delta key found - fetching one.' + Style.RESET_ALL)

    return auto_get_delta_key(package_statuses)


# ---------------------------------------------------------------- main

def initial_launch(accounts, package_statuses):
    num_packages = len(accounts)
    kill_roblox_processes()
    time.sleep(2)
    for package_name, user_id in accounts:
        try:
            set_status(package_statuses, package_name, Fore.LIGHTCYAN_EX, 'Launching')
            launch_roblox(package_name, num_packages, package_statuses)
            set_status(package_statuses, package_name, Fore.GREEN, 'Joined')
            username = get_username(user_id)
            reset_executor_file(username)
            executor_check_with_wait(username, package_name, package_statuses)
        except Exception as e:
            print(Fore.RED + 'Error launching Roblox for {}: {}'.format(package_name, e) + Style.RESET_ALL)
            set_status(package_statuses, package_name, Fore.RED, 'Launch failed')


def monitor(accounts, package_statuses):
    """Watch every package forever, relaunching only when one has actually
    dropped out: process gone, or the account sitting on the website."""
    num_packages = len(accounts)
    next_key_check = time.time() + KEY_REFRESH_SECONDS
    while True:
        try:
            if False:  # auto key disabled
                next_key_check = time.time() + KEY_REFRESH_SECONDS
                if ensure_valid_delta_key(package_statuses):
                    print(Fore.LIGHTCYAN_EX + 'New Delta key - relaunching all packages.'
                          + Style.RESET_ALL)
                    for package_name, user_id in accounts:
                        try:
                            set_status(package_statuses, package_name, Fore.LIGHTCYAN_EX,
                                       'New key, relaunching')
                            lock = _package_lock(package_name)
                            if not lock.acquire(blocking=False):
                                continue
                            try:
                                kill_roblox_process(package_name)
                                launch_roblox(package_name, num_packages, package_statuses)
                            finally:
                                lock.release()
                        except Exception as e:
                            print(Fore.RED + 'Error relaunching {} after key refresh: {}'.format(
                                package_name, e) + Style.RESET_ALL)

            for package_name, user_id in accounts:
                try:
                    username = get_username_from_id(user_id)
                    package_statuses[package_name]['Username'] = username
                    presence_type, last_location = check_user_online(user_id)

                    if presence_type == 2:
                        set_status(package_statuses, package_name, Fore.GREEN, 'In-Game')
                        if not check_executor_status(username):
                            print('Executor did not update for {} ({}). Waiting {}s...'.format(
                                package_name, username, EXECUTOR_GRACE_SECONDS))
                            set_status(package_statuses, package_name, Fore.YELLOW,
                                       'Executor not updated, waiting {}s...'.format(EXECUTOR_GRACE_SECONDS))
                            time.sleep(EXECUTOR_GRACE_SECONDS)
                            if check_executor_status(username):
                                set_status(package_statuses, package_name, Fore.GREEN, 'Executor OK after wait')
                            else:
                                set_status(package_statuses, package_name, Fore.YELLOW,
                                           'Executor timeout, continuing...')

                    elif not is_roblox_running(package_name):
                        set_status(package_statuses, package_name, Fore.RED, 'Crashed, reopening')
                        # backup to the heartbeat watchdog; shared lock prevents
                        # double-launching. on reconnect it heads to the waitlist top.
                        safe_launch(package_name, num_packages, package_statuses)

                    elif last_location == 'Website':
                        set_status(package_statuses, package_name, Fore.RED, 'On Website, Rejoining')
                        # kill (it's alive on the website) then relaunch, lock-guarded
                        safe_launch(package_name, num_packages, package_statuses, kill_first=True)

                    else:
                        set_status(package_statuses, package_name, Fore.YELLOW,
                                   'Not In-Game, Recently Active')

                    time.sleep(PER_PACKAGE_DELAY)
                except Exception as e:
                    print(Fore.RED + 'Error during rejoin process for {}: {}'.format(package_name, e)
                          + Style.RESET_ALL)
                    set_status(package_statuses, package_name, Fore.RED, 'General error')

            save_cache()
            time.sleep(SWEEP_DELAY)
        except Exception as e:
            print(Fore.RED + 'Critical error in auto rejoin loop: {}'.format(e) + Style.RESET_ALL)
            time.sleep(EXECUTOR_GRACE_SECONDS)


def main():
    clear_console()
    print_header()
    print(Fore.LIGHTCYAN_EX + 'Auto rejoin -> place {}'.format(GAME_ID) + Style.RESET_ALL)

    ensure_settings()

    start_ws_server()
    threading.Thread(target=retarget_loop, daemon=True).start()
    # REST poll always runs as a backstop so gateway drops can't lose messages
    threading.Thread(target=discord_scan_loop, daemon=True).start()
    if start_discord_bot():
        print(Fore.LIGHTCYAN_EX + 'discord.py gateway + REST backstop.' + Style.RESET_ALL)
    else:
        print(Fore.YELLOW + 'discord.py not installed - stdlib gateway + REST scan.'
              + Style.RESET_ALL)
        threading.Thread(target=discord_gateway_loop, daemon=True).start()

    packages = get_roblox_packages()
    if not packages:
        return

    accounts = setup_accounts(packages)
    if not accounts:
        print(Fore.RED + 'No user IDs could be resolved. Log in to at least one Roblox clone first.'
              + Style.RESET_ALL)
        return
    save_cache()

    package_statuses = {
        package_name: {
            'Status': Fore.LIGHTCYAN_EX + 'Initializing' + Style.RESET_ALL,
            'Username': get_username(user_id),
        }
        for package_name, user_id in accounts
    }

    # ensure_valid_delta_key(package_statuses)  # auto key disabled

    initial_launch(accounts, package_statuses)
    threading.Thread(target=heartbeat_watchdog, args=(accounts, package_statuses), daemon=True).start()
    monitor(accounts, package_statuses)


if __name__ == '__main__':
    load_cache()
    delete_roblox_cache()
    detect_and_write_lua_script()
    try:
        main()
    except KeyboardInterrupt:
        save_cache()
        print(Fore.YELLOW + '\n[ AJ V2 ] -> Shutting down gracefully...' + Style.RESET_ALL)
