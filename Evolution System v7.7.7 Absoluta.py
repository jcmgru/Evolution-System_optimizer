import base64
import ctypes
import gc
import hashlib
import hmac
import json
import os
import platform
import queue
import secrets
import socket
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
import uuid
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk


APP_TITLE = "Evolution System - Versión 7.7.7 Absoluta"
STARTUP_REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_VALUE_NAME = "EvolutionSystemV6"
LOG_FLUSH_INTERVAL_MS = 15 * 60 * 1000
INSTANCE_MUTEX_NAME = "Local\\EvolutionSystemV777Absoluta"
CREATOR_USERNAME = "jcmgru el inmortal"
CREATOR_PASSWORD_HASH_ITERATIONS = 600_000
CREATOR_TOTP_DIGITS = 6
CREATOR_TOTP_PERIOD_SECONDS = 30
LAN_DISCOVERY_PORT = 5005
LAN_DISCOVERY_INTERVAL_SECONDS = 2
LAN_PEER_TIMEOUT_SECONDS = 8
GLOBAL_BOOTSTRAP_PORT = 50001
CPU_PAUSE_THRESHOLD_PERCENT = 95.0
CREATOR_ROLE = "USUARIO MAESTRO / CREADOR"
VOLUNTEER_ROLE = "Nodo Secundario / Voluntario"
APP_ATTRIBUTION = (
    "Creado por Juan Camilo Mazo González (jcmgru) | ProyectosGeniales | "
    "jcmgru7@gmail.com"
)


def get_windows_folder(csidl):
    if platform.system().lower() != "windows":
        raise OSError("Las carpetas conocidas de Windows no están disponibles.")
    folder_path = ctypes.create_unicode_buffer(32768)
    result = ctypes.windll.shell32.SHGetFolderPathW(
        None, csidl, None, 0, folder_path
    )
    if result != 0 or not folder_path.value:
        raise OSError("Windows no pudo resolver la carpeta conocida (CSIDL {}).".format(csidl))
    return Path(folder_path.value)


def generate_totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def decode_totp_secret(secret):
    normalized_secret = "".join(secret.split()).upper()
    padding = "=" * ((8 - len(normalized_secret) % 8) % 8)
    key = base64.b32decode(normalized_secret + padding, casefold=True)
    if len(key) < 20:
        raise ValueError("La semilla TOTP debe contener al menos 160 bits.")
    return normalized_secret, key


def verify_totp(secret, code, timestamp=None):
    normalized_code = code.strip()
    if len(normalized_code) != CREATOR_TOTP_DIGITS or not normalized_code.isdigit():
        return False
    try:
        _, key = decode_totp_secret(secret)
    except (ValueError, base64.binascii.Error):
        return False

    current_time = time.time() if timestamp is None else timestamp
    counter = int(current_time // CREATOR_TOTP_PERIOD_SECONDS)
    for offset in (-1, 0, 1):
        message = struct.pack(">Q", counter + offset)
        digest = hmac.new(key, message, hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        binary_code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
        expected = str(binary_code % (10 ** CREATOR_TOTP_DIGITS)).zfill(
            CREATOR_TOTP_DIGITS
        )
        if hmac.compare_digest(normalized_code, expected):
            return True
    return False


def get_creator_auth_path():
    return get_log_path().parent / "creator_auth.json"


def derive_creator_password_hash(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        CREATOR_PASSWORD_HASH_ITERATIONS,
    )


def load_creator_auth():
    path = get_creator_auth_path()
    with path.open("r", encoding="utf-8") as auth_file:
        auth_data = json.load(auth_file)
    if auth_data.get("version") != 1:
        raise ValueError("Versión de credenciales de creador no reconocida.")
    if auth_data.get("iterations") != CREATOR_PASSWORD_HASH_ITERATIONS:
        raise ValueError("Parámetros de credenciales de creador no válidos.")
    salt = bytes.fromhex(auth_data["password_salt"])
    password_hash = bytes.fromhex(auth_data["password_hash"])
    totp_secret, _ = decode_totp_secret(auth_data["totp_secret"])
    if len(salt) != 16 or len(password_hash) != hashlib.sha256().digest_size:
        raise ValueError("Datos de credenciales de creador incompletos.")
    return {
        "password_salt": salt,
        "password_hash": password_hash,
        "totp_secret": totp_secret,
    }


def save_creator_auth(password, totp_secret):
    path = get_creator_auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    salt = secrets.token_bytes(16)
    auth_data = {
        "version": 1,
        "iterations": CREATOR_PASSWORD_HASH_ITERATIONS,
        "password_salt": salt.hex(),
        "password_hash": derive_creator_password_hash(password, salt).hex(),
        "totp_secret": totp_secret,
    }
    with path.open("x", encoding="utf-8") as auth_file:
        json.dump(auth_data, auth_file, separators=(",", ":"))
        auth_file.write("\n")
    if platform.system().lower() != "windows":
        path.chmod(0o600)


def verify_creator_password(password, auth_data):
    candidate = derive_creator_password_hash(password, auth_data["password_salt"])
    return hmac.compare_digest(candidate, auth_data["password_hash"])


def probe_global_bootstrap(host, port=GLOBAL_BOOTSTRAP_PORT, timeout=5):
    if not host or any(character.isspace() for character in host):
        raise ValueError("Escribe un dominio No-IP o nombre DNS válido.")
    address = socket.gethostbyname(host)
    with socket.create_connection((address, port), timeout=timeout):
        return address


def is_startup_enabled():
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, STARTUP_REGISTRY_PATH, 0, winreg.KEY_QUERY_VALUE
        ) as key:
            winreg.QueryValueEx(key, STARTUP_VALUE_NAME)
            return True
    except FileNotFoundError:
        return False


def set_startup_enabled(enabled):
    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        STARTUP_REGISTRY_PATH,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            executable = Path(sys.executable)
            if not getattr(sys, "frozen", False):
                gui_executable = executable.with_name("pythonw.exe")
                if gui_executable.is_file():
                    executable = gui_executable
                command_parts = [str(executable), str(Path(__file__).resolve())]
            else:
                command_parts = [str(executable)]
            command = subprocess.list2cmdline(command_parts)
            winreg.SetValueEx(key, STARTUP_VALUE_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, STARTUP_VALUE_NAME)
            except FileNotFoundError:
                pass
        winreg.FlushKey(key)


class WindowsTrayIcon:
    WM_TRAY_CALLBACK = 0x8000 + 1
    WM_RBUTTONUP = 0x0205
    WM_LBUTTONUP = 0x0202
    WM_LBUTTONDBLCLK = 0x0203
    NIM_ADD = 0
    NIM_MODIFY = 1
    NIM_DELETE = 2
    NIF_MESSAGE = 1
    NIF_ICON = 2
    NIF_TIP = 4
    MF_STRING = 0
    TPM_RIGHTBUTTON = 2
    TPM_RETURNCMD = 0x0100
    ID_SHOW = 1001
    ID_EXIT = 1002

    class _NotifyIconData(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint),
            ("hWnd", ctypes.c_void_p),
            ("uID", ctypes.c_uint),
            ("uFlags", ctypes.c_uint),
            ("uCallbackMessage", ctypes.c_uint),
            ("hIcon", ctypes.c_void_p),
            ("szTip", ctypes.c_wchar * 128),
            ("dwState", ctypes.c_uint),
            ("dwStateMask", ctypes.c_uint),
            ("szInfo", ctypes.c_wchar * 256),
            ("uTimeoutOrVersion", ctypes.c_uint),
            ("szInfoTitle", ctypes.c_wchar * 64),
            ("dwInfoFlags", ctypes.c_uint),
            ("guidItem", ctypes.c_ubyte * 16),
            ("hBalloonIcon", ctypes.c_void_p),
        ]

    class _WindowClass(ctypes.Structure):
        pass

    def __init__(self, root, on_show, on_exit, tooltip):
        import ctypes.wintypes as wintypes

        self.root = root
        self.on_show = on_show
        self.on_exit = on_exit
        self._wintypes = wintypes
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self._kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        self._instance = self._kernel32.GetModuleHandleW(None)
        self._class_name = "EvolutionTray_" + uuid.uuid4().hex
        self._window_proc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        self._WindowClass._fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", self._window_proc_type),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]
        self._window_proc_callback = self._window_proc_type(self._window_proc)
        self._class = self._WindowClass()
        self._class.lpfnWndProc = self._window_proc_callback
        self._class.hInstance = self._instance
        self._class.lpszClassName = self._class_name
        self._user32.RegisterClassW.argtypes = [ctypes.POINTER(self._WindowClass)]
        self._user32.RegisterClassW.restype = wintypes.ATOM
        if not self._user32.RegisterClassW(ctypes.byref(self._class)):
            raise ctypes.WinError(ctypes.get_last_error())

        self._user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        ]
        self._user32.CreateWindowExW.restype = wintypes.HWND
        self._user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self._user32.DefWindowProcW.restype = ctypes.c_ssize_t
        self._user32.DestroyWindow.argtypes = [wintypes.HWND]
        self._user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        self._hwnd = self._user32.CreateWindowExW(
            0,
            self._class_name,
            APP_TITLE,
            0,
            0,
            0,
            0,
            0,
            wintypes.HWND(-3),
            None,
            self._instance,
            None,
        )
        if not self._hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

        self._user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
        self._user32.LoadIconW.restype = wintypes.HICON
        self._icon = self._user32.LoadIconW(
            None, ctypes.cast(ctypes.c_void_p(32512), wintypes.LPCWSTR)
        )
        if not self._icon:
            raise ctypes.WinError(ctypes.get_last_error())

        self._data = self._NotifyIconData()
        self._data.cbSize = ctypes.sizeof(self._NotifyIconData)
        self._data.hWnd = self._hwnd
        self._data.uID = 1
        self._data.uFlags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP
        self._data.uCallbackMessage = self.WM_TRAY_CALLBACK
        self._data.hIcon = self._icon
        self.set_tooltip(tooltip)
        self._user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self._user32.GetCursorPos.restype = wintypes.BOOL
        self._user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self._user32.SetForegroundWindow.restype = wintypes.BOOL
        self._user32.TrackPopupMenu.argtypes = [
            wintypes.HMENU,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.LPVOID,
        ]
        self._user32.TrackPopupMenu.restype = wintypes.UINT
        self._user32.PostMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self._user32.PostMessageW.restype = wintypes.BOOL
        self._user32.DestroyMenu.argtypes = [wintypes.HMENU]
        self._user32.DestroyMenu.restype = wintypes.BOOL
        self._shell32.Shell_NotifyIconW.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(self._NotifyIconData),
        ]
        self._shell32.Shell_NotifyIconW.restype = wintypes.BOOL
        if not self._shell32.Shell_NotifyIconW(self.NIM_ADD, ctypes.byref(self._data)):
            raise ctypes.WinError(ctypes.get_last_error())
        self._installed = True

    def set_tooltip(self, text):
        self._data.szTip = text[:127]
        if getattr(self, "_installed", False):
            if not self._shell32.Shell_NotifyIconW(
                self.NIM_MODIFY, ctypes.byref(self._data)
            ):
                raise ctypes.WinError(ctypes.get_last_error())

    def _window_proc(self, hwnd, message, wparam, lparam):
        if message == self.WM_TRAY_CALLBACK:
            event = lparam & 0xFFFF
            if event in (self.WM_LBUTTONUP, self.WM_LBUTTONDBLCLK):
                self.root.after(0, self.on_show)
            elif event == self.WM_RBUTTONUP:
                self._show_context_menu()
            return 0
        return self._user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _show_context_menu(self):
        wintypes = self._wintypes
        self._user32.CreatePopupMenu.restype = wintypes.HMENU
        menu = self._user32.CreatePopupMenu()
        if not menu:
            return
        self._user32.AppendMenuW.argtypes = [
            wintypes.HMENU,
            wintypes.UINT,
            ctypes.c_size_t,
            wintypes.LPCWSTR,
        ]
        self._user32.AppendMenuW(menu, self.MF_STRING, self.ID_SHOW, "Mostrar")
        self._user32.AppendMenuW(menu, self.MF_STRING, self.ID_EXIT, "Salir")
        self._user32.SetForegroundWindow(self._hwnd)
        point = wintypes.POINT()
        if self._user32.GetCursorPos(ctypes.byref(point)):
            command = self._user32.TrackPopupMenu(
                menu,
                self.TPM_RIGHTBUTTON | self.TPM_RETURNCMD,
                point.x,
                point.y,
                0,
                self._hwnd,
                None,
            )
            self._user32.PostMessageW(self._hwnd, 0, 0, 0)
            if command == self.ID_SHOW:
                self.root.after(0, self.on_show)
            elif command == self.ID_EXIT:
                self.root.after(0, self.on_exit)
        self._user32.DestroyMenu(menu)

    def remove(self):
        if getattr(self, "_installed", False):
            self._shell32.Shell_NotifyIconW(self.NIM_DELETE, ctypes.byref(self._data))
            self._installed = False
        if getattr(self, "_hwnd", None):
            self._user32.DestroyWindow(self._hwnd)
            self._hwnd = None
        if getattr(self, "_class_name", None):
            self._user32.UnregisterClassW(self._class_name, self._instance)
            self._class_name = None


def get_log_path():
    if platform.system().lower() == "windows":
        base_dir = get_windows_folder(0x001C)
    else:
        base_dir = Path.home() / ".local" / "share"
    return base_dir / "Evolution_v6" / "node_activity.txt"


def get_hardware_info():
    logical_cpus = os.cpu_count() or 1
    system = platform.system().lower()

    if system == "windows":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatus)]
        kernel32.GlobalMemoryStatusEx.restype = ctypes.c_int
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise ctypes.WinError(ctypes.get_last_error())
        total_ram = status.ullTotalPhys
        available_ram = status.ullAvailPhys
    else:
        page_size = os.sysconf("SC_PAGE_SIZE")
        total_ram = page_size * os.sysconf("SC_PHYS_PAGES")
        try:
            available_ram = page_size * os.sysconf("SC_AVPHYS_PAGES")
        except (AttributeError, ValueError):
            available_ram = None

    return logical_cpus, total_ram, available_ram


def format_bytes(value):
    if value is None:
        return "No disponible"
    return "{:.1f} GiB".format(value / (1024 ** 3))


def remove_expired_temp_data(path, cutoff):
    file_attributes = getattr(path.lstat(), "st_file_attributes", 0)
    if path.is_symlink() or file_attributes & 0x400:
        return 0

    if path.is_file():
        if path.stat().st_mtime >= cutoff:
            return 0
        path.unlink()
        return 1

    if not path.is_dir():
        return 0

    removed = 0
    for child in path.iterdir():
        removed += remove_expired_temp_data(child, cutoff)

    if path.stat().st_mtime < cutoff and not any(path.iterdir()):
        path.rmdir()
        removed += 1
    return removed


def format_local_record(username, role=VOLUNTEER_ROLE):
    username = username.replace("|", "_").replace("\r", "_").replace("\n", "_")
    role = role.replace("|", "_").replace("\r", "_").replace("\n", "_")
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    return "{}|{}|{}".format(username, role, timestamp)


class LocalRecordStore:
    def __init__(self, path):
        self.path = path
        self.pending_records = []
        self.lock = threading.Lock()

    def add(self, username, role=VOLUNTEER_ROLE):
        with self.lock:
            self.pending_records.append(format_local_record(username, role))

    def add_peer(self, peer_id):
        with self.lock:
            self.pending_records.append(
                format_local_record("peer:" + peer_id, "nodo_p2p_detectado")
            )

    def read(self):
        with self.lock:
            pending = list(self.pending_records)
            if self.path.exists():
                with self.path.open("r", encoding="utf-8") as log_file:
                    stored = log_file.read().splitlines()
            else:
                stored = []
            return "\n".join(stored + pending)

    def flush(self):
        with self.lock:
            if not self.pending_records:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as log_file:
                log_file.write("".join(record + "\n" for record in self.pending_records))
            self.pending_records.clear()


class LanPeerDiscovery:
    PROTOCOL_ID = "evolution-lan-discovery"

    def __init__(self, node_id):
        self.node_id = node_id
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = None
        self.socket = None
        self.peers = {}
        self.seen_peers = set()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._run, name="EvolutionLanDiscovery", daemon=True
        )
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.socket:
            try:
                self.socket.close()
            except OSError:
                pass

    def get_events(self):
        events = []
        while True:
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                return events

    def _publish_count(self):
        self.events.put(("count", len(self.peers)))

    def _run(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as discovery_socket:
                self.socket = discovery_socket
                discovery_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                discovery_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                discovery_socket.settimeout(0.5)
                discovery_socket.bind(("", LAN_DISCOVERY_PORT))
                payload = json.dumps(
                    {
                        "protocol": self.PROTOCOL_ID,
                        "node_id": self.node_id,
                    },
                    separators=(",", ":"),
                ).encode("utf-8")
                next_broadcast = 0.0
                next_expiry = 0.0
                self._publish_count()

                while not self.stop_event.is_set():
                    now = time.monotonic()
                    if now >= next_broadcast:
                        discovery_socket.sendto(
                            payload, ("255.255.255.255", LAN_DISCOVERY_PORT)
                        )
                        next_broadcast = now + LAN_DISCOVERY_INTERVAL_SECONDS

                    try:
                        packet, address = discovery_socket.recvfrom(512)
                    except socket.timeout:
                        packet = None
                    except OSError:
                        if self.stop_event.is_set():
                            break
                        raise

                    if packet:
                        try:
                            message = json.loads(packet.decode("utf-8"))
                            peer_id = message.get("node_id")
                            if (
                                message.get("protocol") == self.PROTOCOL_ID
                                and isinstance(peer_id, str)
                                and peer_id != self.node_id
                                and str(uuid.UUID(peer_id)) == peer_id
                            ):
                                now = time.monotonic()
                                was_connected = peer_id in self.peers
                                self.peers[peer_id] = (address[0], now)
                                if peer_id not in self.seen_peers:
                                    self.seen_peers.add(peer_id)
                                    self.events.put(("peer", peer_id, address[0]))
                                if not was_connected:
                                    self._publish_count()
                        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, ValueError):
                            continue

                    if time.monotonic() >= next_expiry:
                        current_time = time.monotonic()
                        expired = [
                            peer_id
                            for peer_id, (_address, last_seen) in self.peers.items()
                            if current_time - last_seen > LAN_PEER_TIMEOUT_SECONDS
                        ]
                        for peer_id in expired:
                            del self.peers[peer_id]
                        if expired:
                            self._publish_count()
                        next_expiry = current_time + 1
        except OSError as error:
            if not self.stop_event.is_set():
                self.events.put(("error", str(error)))
        finally:
            self.socket = None
            self.events.put(("stopped",))


def build_login_view(root, on_login):
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(
        frame,
        text=APP_TITLE,
        font=("Segoe UI", 16, "bold"),
    ).pack(anchor=tk.W, pady=(0, 8))
    ttk.Label(frame, text=APP_ATTRIBUTION, wraplength=430).pack(
        anchor=tk.W, pady=(0, 10)
    )
    ttk.Label(
        frame,
        text="Elige un nombre para identificar este equipo en el registro local.",
        wraplength=400,
    ).pack(anchor=tk.W, pady=(0, 12))
    ttk.Label(frame, text="Nombre de usuario").pack(anchor=tk.W)
    username_var = tk.StringVar()
    entry = ttk.Entry(frame, textvariable=username_var, width=42)
    entry.pack(fill=tk.X, pady=(4, 12))
    status = tk.StringVar(value="")
    ttk.Label(frame, textvariable=status).pack(anchor=tk.W)

    def submit(_event=None):
        username = username_var.get().strip()
        if not username:
            status.set("Escribe un nombre para continuar.")
            return
        role = VOLUNTEER_ROLE
        if username == CREATOR_USERNAME:
            auth_path = get_creator_auth_path()
            first_run = not auth_path.exists()
            if first_run:
                entered_seed = simpledialog.askstring(
                    APP_TITLE,
                    "Primera configuración: ingresa una semilla TOTP Base32 nueva "
                    "de respaldo o déjala vacía para generar una. No reutilices "
                    "semillas compartidas anteriormente.",
                    parent=root,
                )
                if entered_seed is None:
                    return
                try:
                    if entered_seed.strip():
                        totp_secret, _ = decode_totp_secret(entered_seed)
                        seed_generated = False
                    else:
                        totp_secret = generate_totp_secret()
                        seed_generated = True
                except (OSError, UnicodeError, ValueError, base64.binascii.Error) as error:
                    messagebox.showerror(
                        APP_TITLE,
                        "No se pudo preparar la semilla TOTP:\n{}".format(error),
                        parent=root,
                    )
                    return

                generated_password = secrets.token_urlsafe(24)
                messagebox.showinfo(
                    APP_TITLE,
                    "Credenciales nuevas de creador. Guarda ambos valores ahora: "
                    "la contraseña se mostrará una sola vez. Registra la semilla "
                    "en tu app autenticadora.\n\nContraseña de creador:\n{}\n\n"
                    "Semilla TOTP Base32{}:\n{}".format(
                        generated_password,
                        " nueva" if seed_generated else " importada",
                        totp_secret,
                    ),
                    parent=root,
                )
                try:
                    save_creator_auth(generated_password, totp_secret)
                except (OSError, FileExistsError) as error:
                    messagebox.showerror(
                        APP_TITLE,
                        "No se pudieron guardar las credenciales locales:\n{}"
                        .format(error),
                        parent=root,
                    )
                    return
                password_for_verification = generated_password
            else:
                try:
                    auth_data = load_creator_auth()
                except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
                    messagebox.showerror(
                        APP_TITLE,
                        "No se pudo leer la configuración local del creador:\n{}"
                        .format(error),
                        parent=root,
                    )
                    return
                totp_secret = auth_data["totp_secret"]
                password_for_verification = None

            entered_otp = simpledialog.askstring(
                APP_TITLE,
                "Paso 1: Ingrese el código dinámico de 6 dígitos de su App "
                "Autenticadora.",
                parent=root,
            )
            if entered_otp is None:
                return
            if not verify_totp(totp_secret, entered_otp):
                messagebox.showerror(
                    APP_TITLE, "El código TOTP no es válido.", parent=root
                )
                return

            entered_secret = simpledialog.askstring(
                APP_TITLE,
                (
                    "Paso 2: Confirma la contraseña de creador que se acaba de "
                    "mostrar."
                    if first_run
                    else "Paso 2: Ingresa tu contraseña de creador."
                ),
                parent=root,
                show="*",
            )
            if entered_secret is None:
                return
            if first_run:
                password_valid = hmac.compare_digest(
                    entered_secret, password_for_verification
                )
            else:
                password_valid = verify_creator_password(entered_secret, auth_data)
            if not password_valid:
                messagebox.showerror(
                    APP_TITLE, "La clave de creador no es válida.", parent=root
                )
                return
            role = CREATOR_ROLE
        on_login(username, role, frame)

    buttons = ttk.Frame(frame)
    buttons.pack(fill=tk.X)
    ttk.Button(buttons, text="Continuar como voluntario", command=submit).pack(
        side=tk.RIGHT
    )
    ttk.Button(buttons, text="Salir", command=root.destroy).pack(
        side=tk.RIGHT, padx=(0, 8)
    )
    root.bind("<Return>", submit)
    entry.focus_set()
    return frame


def acquire_single_instance():
    if platform.system().lower() != "windows":
        return None

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_wchar_p,
    ]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, 1, INSTANCE_MUTEX_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    if ctypes.get_last_error() == 183:
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle(handle)
        return False
    return handle


def release_single_instance(handle):
    if not handle:
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    if not kernel32.ReleaseMutex(handle):
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel32.CloseHandle(handle):
        raise ctypes.WinError(ctypes.get_last_error())


class EvolutionNodeApp:
    def __init__(self, root, username, role, record_store):
        self.root = root
        self.username = username
        self.role = role
        self.record_store = record_store
        self.closing = False
        self.flush_in_progress = False
        self.discovery = None
        self.discovery_poll_id = None
        self.node_id = str(uuid.uuid4())
        self.bootstrap_events = queue.Queue()
        self.bootstrap_check_running = False
        self.cpu_monitor_stop = threading.Event()
        self.cpu_pause_event = threading.Event()
        self.cpu_pause_event.set()
        self.cpu_monitor_events = queue.Queue()
        self.cpu_monitor_poll_id = None
        self.root.title(APP_TITLE)
        self.root.geometry("820x650")
        self.root.minsize(700, 570)

        self.startup_enabled = False
        startup_error = None
        if platform.system().lower() == "windows":
            try:
                self.startup_enabled = is_startup_enabled()
            except OSError as error:
                startup_error = error
        self.startup_var = tk.BooleanVar(value=self.startup_enabled)
        self.startup_status = tk.StringVar(
            value=(
                "Se abrirá al iniciar sesión; el procesamiento requiere consentimiento manual."
                if self.startup_enabled
                else "Desactivado; no se iniciará automáticamente."
            )
        )

        self.task_running = False
        self.node_status = tk.StringVar(
            value="Nodo local; la malla de procesamiento todavía no está conectada."
        )
        self.hardware_status = tk.StringVar(value="Detectando hardware...")
        self.operation_status = tk.StringVar(value="Listo")

        self._build_interface()
        self._refresh_hardware()
        self._start_cpu_monitor()
        if startup_error:
            messagebox.showerror(
                APP_TITLE,
                "No se pudo consultar la configuración de inicio de Windows:\n{}".format(
                    startup_error
                ),
            )
        self.tray_icon = None
        if platform.system().lower() == "windows":
            try:
                self.tray_icon = WindowsTrayIcon(
                    self.root,
                    self.show_window,
                    self.close,
                    "Evolution v7.7.7 - malla desconectada",
                )
            except OSError as error:
                messagebox.showerror(
                    APP_TITLE,
                    "No se pudo crear el icono de la bandeja. "
                    "Cerrar la ventana finalizará el programa.\n\n{}".format(error),
                )
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.root.after(LOG_FLUSH_INTERVAL_MS, self._periodic_flush)

    def _build_interface(self):
        container = ttk.Frame(self.root, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text=APP_TITLE, font=("Segoe UI", 18, "bold")).pack(anchor=tk.W)
        ttk.Label(
            container,
            text=APP_ATTRIBUTION,
        ).pack(anchor=tk.W, pady=(2, 4))
        ttk.Label(container, text="Rango local: {}".format(self.role)).pack(
            anchor=tk.W
        )
        ttk.Label(
            container,
            text=(
                "Cerrar esta ventana la minimizará al icono de la bandeja. "
                "Haz clic derecho en el icono y elige «Salir» para cerrar el nodo."
            ),
            wraplength=760,
        ).pack(anchor=tk.W, pady=(4, 12))

        ttk.Label(container, textvariable=self.hardware_status).pack(anchor=tk.W)
        ttk.Label(
            container,
            text="Estado del nodo: ",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor=tk.W, pady=(10, 0))
        ttk.Label(container, textvariable=self.node_status, wraplength=760).pack(anchor=tk.W)

        options = ttk.LabelFrame(container, text="Opciones", padding=8)
        options.pack(fill=tk.X, pady=12)
        buttons = [
            ("[A] Revisar integridad", self._review_integrity),
            ("[S] Optimizar nodo", self._optimize_local_process),
            ("[C] Panel local", self._audit_node),
            ("[M] Control de participación", self._show_mesh_controls),
            ("[V] Ver registro local", self._show_local_log),
            ("[E] Salir", self.close),
        ]
        for index, (label, command) in enumerate(buttons):
            ttk.Button(options, text=label, command=command).grid(
                row=index // 3, column=index % 3, sticky="ew", padx=4, pady=4
            )
        for column in range(3):
            options.columnconfigure(column, weight=1)

        startup_options = ttk.LabelFrame(container, text="Inicio de sesión", padding=8)
        startup_options.pack(fill=tk.X, pady=(0, 10))
        self.startup_check = ttk.Checkbutton(
            startup_options,
            text="Abrir Evolution al iniciar sesión en Windows",
            variable=self.startup_var,
            command=self._toggle_startup,
        )
        self.startup_check.pack(anchor=tk.W)
        ttk.Label(
            startup_options, textvariable=self.startup_status, wraplength=740
        ).pack(anchor=tk.W, pady=(4, 0))

        self.mesh_controls = ttk.LabelFrame(
            container, text="Participación en la malla", padding=10
        )
        self.mesh_controls.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(
            self.mesh_controls,
            text=(
                "El descubrimiento UDP es solo para la LAN. El campo Bootstrap permite "
                "resolver un dominio No-IP y probar TCP al puerto {}. La prueba solo "
                "confirma que el puerto acepta conexiones: todavía no hay protocolo "
                "global de registro, autenticación de pares ni ejecución de tareas."
            ).format(GLOBAL_BOOTSTRAP_PORT),
            wraplength=740,
        ).grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 8))
        self.bootstrap_host_var = tk.StringVar()
        ttk.Label(self.mesh_controls, text="Dominio No-IP del bootstrap:").grid(
            row=1, column=0, sticky=tk.W, padx=(0, 6), pady=4
        )
        self.bootstrap_host_entry = ttk.Entry(
            self.mesh_controls, textvariable=self.bootstrap_host_var
        )
        self.bootstrap_host_entry.grid(
            row=1, column=1, columnspan=2, sticky="ew", pady=4
        )
        self.bootstrap_button = ttk.Button(
            self.mesh_controls,
            text="Probar conexión",
            command=self._probe_global_bootstrap,
        )
        self.bootstrap_button.grid(row=1, column=3, sticky=tk.E, padx=(6, 0), pady=4)
        self.bootstrap_status = tk.StringVar(value="Bootstrap global sin configurar.")
        ttk.Label(
            self.mesh_controls,
            textvariable=self.bootstrap_status,
            wraplength=740,
        ).grid(row=2, column=0, columnspan=4, sticky=tk.W, pady=(2, 4))
        self.cpu_status = tk.StringVar(value="Monitor de CPU iniciándose...")
        self.cpu_status_label = ttk.Label(
            self.mesh_controls,
            textvariable=self.cpu_status,
            wraplength=740,
        )
        self.cpu_status_label.grid(
            row=3, column=0, columnspan=4, sticky=tk.W, pady=(2, 4)
        )
        ttk.Label(
            self.mesh_controls,
            text=(
                "El descubrimiento LAN solo anuncia un identificador aleatorio de este "
                "nodo; no comparte datos personales ni ejecuta tareas remotas."
            ),
            wraplength=740,
        ).grid(row=4, column=0, columnspan=4, sticky=tk.W, pady=(4, 8))
        self.mesh_status = tk.StringVar(value="Descubrimiento LAN detenido.")
        self.mesh_status_label = ttk.Label(
            self.mesh_controls, textvariable=self.mesh_status, foreground="#555555"
        )
        self.mesh_status_label.grid(
            row=5, column=0, columnspan=4, sticky=tk.W, pady=(0, 4)
        )
        self.start_button = ttk.Button(
            self.mesh_controls,
            text="Iniciar descubrimiento LAN",
            command=self._toggle_mesh_discovery,
        )
        self.start_button.grid(row=6, column=0, sticky=tk.W, pady=(8, 0))
        self.mesh_controls.columnconfigure(1, weight=1)

        ttk.Label(container, text="Resultado de la última operación:").pack(anchor=tk.W)
        self.output = tk.Text(container, height=9, wrap=tk.WORD, state=tk.DISABLED)
        self.output.pack(fill=tk.BOTH, expand=True, pady=(4, 8))
        ttk.Label(container, textvariable=self.operation_status).pack(anchor=tk.W)
        ttk.Label(
            container,
            text=(
                "Registro local visible (volcado cada 15 minutos y al salir): {}"
                .format(get_log_path())
            ),
            wraplength=770,
        ).pack(anchor=tk.W, pady=(6, 0))

        if platform.system().lower() != "windows":
            self.startup_check.configure(state=tk.DISABLED)
            self.node_status.set(
                "El inicio automático está disponible solo en Windows; la malla no está configurada."
            )

    def _toggle_startup(self):
        enabled = bool(self.startup_var.get())
        if enabled and not messagebox.askyesno(
            APP_TITLE,
            "¿Permites que Evolution abra su ventana al iniciar sesión en Windows? "
            "El procesamiento compartido seguirá desactivado hasta que lo habilites "
            "manualmente. Puedes desactivar esta opción aquí en cualquier momento.",
        ):
            self.startup_var.set(False)
            return

        try:
            set_startup_enabled(enabled)
        except OSError as error:
            try:
                self.startup_enabled = is_startup_enabled()
            except OSError as read_error:
                self.startup_status.set(
                    "No se pudo confirmar la configuración: {}".format(read_error)
                )
            else:
                self.startup_var.set(self.startup_enabled)
                self.startup_status.set(
                    "Se abrirá al iniciar sesión."
                    if self.startup_enabled
                    else "Desactivado; no se iniciará automáticamente."
                )
            messagebox.showerror(
                APP_TITLE, "No se pudo cambiar el inicio automático:\n{}".format(error)
            )
            return

        self.startup_enabled = enabled
        self.startup_status.set(
            "Se abrirá al iniciar sesión; el procesamiento requiere consentimiento manual."
            if enabled
            else "Desactivado; no se iniciará automáticamente."
        )

    def _refresh_hardware(self):
        try:
            logical_cpus, total_ram, available_ram = get_hardware_info()
            self.hardware_status.set(
                "Hardware detectado: {} procesadores lógicos | RAM total: {} | RAM disponible: {}".format(
                    logical_cpus,
                    format_bytes(total_ram),
                    format_bytes(available_ram),
                )
            )
        except Exception as error:
            self.hardware_status.set("No se pudo detectar el hardware: {}".format(error))

    def _start_cpu_monitor(self):
        def monitor():
            try:
                import psutil
            except ImportError as error:
                self.cpu_pause_event.set()
                self.cpu_monitor_events.put(("error", str(error)))
                return

            was_paused = None
            while not self.cpu_monitor_stop.is_set():
                cpu_percent = psutil.cpu_percent(interval=0.5)
                should_pause = cpu_percent > CPU_PAUSE_THRESHOLD_PERCENT
                if should_pause:
                    self.cpu_pause_event.set()
                else:
                    self.cpu_pause_event.clear()
                if should_pause != was_paused:
                    self.cpu_monitor_events.put(
                        ("state", cpu_percent, should_pause)
                    )
                    was_paused = should_pause
                elif should_pause:
                    self.cpu_monitor_events.put(
                        ("state", cpu_percent, True)
                    )
                self.cpu_monitor_stop.wait(0.5)

        threading.Thread(
            target=monitor, name="EvolutionCpuMonitor", daemon=True
        ).start()
        self.cpu_monitor_poll_id = self.root.after(
            500, self._poll_background_status
        )

    def _poll_background_status(self):
        self.cpu_monitor_poll_id = None
        while True:
            try:
                event = self.cpu_monitor_events.get_nowait()
            except queue.Empty:
                break

            if event[0] == "state":
                _kind, cpu_percent, should_pause = event
                if should_pause:
                    self.cpu_status.set(
                        "Pausa LOCAL: CPU {:.1f}% supera {:.0f}%. Solo afecta tareas "
                        "de este equipo; los demás nodos siguen independientes. "
                        "No hay trabajos distribuidos activos.".format(
                            cpu_percent, CPU_PAUSE_THRESHOLD_PERCENT
                        )
                    )
                    self.cpu_status_label.configure(foreground="#b42318")
                else:
                    self.cpu_status.set(
                        "CPU local {:.1f}%: bajo el umbral de {:.0f}%. La señal de "
                        "pausa local está liberada; no hay trabajos distribuidos "
                        "activos.".format(
                            cpu_percent, CPU_PAUSE_THRESHOLD_PERCENT
                        )
                    )
                    self.cpu_status_label.configure(foreground="#16803c")
            elif event[0] == "error":
                self.cpu_status.set(
                    "Monitor de CPU no disponible: {}".format(event[1])
                )

        while True:
            try:
                event = self.bootstrap_events.get_nowait()
            except queue.Empty:
                break
            self.bootstrap_check_running = False
            if event[0] == "reachable":
                _kind, host, address = event
                self.bootstrap_status.set(
                    "El endpoint {} ({}) acepta TCP en el puerto {}. Esto no "
                    "confirma que exista una malla o un protocolo P2P.".format(
                        host, address, GLOBAL_BOOTSTRAP_PORT
                    )
                )
                self.bootstrap_button.configure(state=tk.NORMAL)
                self._set_output(
                    "Prueba TCP completada: {}:{} respondió aceptando la conexión. "
                    "No se intercambiaron tareas ni se registró el nodo en una red."
                    .format(address, GLOBAL_BOOTSTRAP_PORT)
                )
            elif event[0] == "error":
                _kind, host, error = event
                self.bootstrap_status.set(
                    "No se pudo conectar a {}:{}.".format(
                        host, GLOBAL_BOOTSTRAP_PORT
                    )
                )
                self.bootstrap_button.configure(state=tk.NORMAL)
                self._set_output(
                    "Falló la prueba de bootstrap para {}:{}: {}".format(
                        host, GLOBAL_BOOTSTRAP_PORT, error
                    )
                )

        if not self.closing:
            self.cpu_monitor_poll_id = self.root.after(
                500, self._poll_background_status
            )

    def _probe_global_bootstrap(self):
        if self.bootstrap_check_running:
            return
        host = self.bootstrap_host_var.get().strip()
        if not host or any(character.isspace() for character in host):
            messagebox.showwarning(
                APP_TITLE,
                "Escribe un dominio No-IP o nombre DNS válido.",
                parent=self.root,
            )
            return
        if not messagebox.askyesno(
            APP_TITLE,
            "Se resolverá {} mediante DNS y se intentará una conexión TCP al puerto "
            "{}. Se contactará el endpoint que ingresaste; no se enviarán tareas ni "
            "credenciales. ¿Continuar?".format(host, GLOBAL_BOOTSTRAP_PORT),
            parent=self.root,
        ):
            return

        self.bootstrap_check_running = True
        self.bootstrap_button.configure(state=tk.DISABLED)
        self.bootstrap_status.set(
            "Resolviendo {} y probando TCP:{}...".format(
                host, GLOBAL_BOOTSTRAP_PORT
            )
        )

        def probe():
            try:
                address = probe_global_bootstrap(host)
            except (OSError, UnicodeError) as error:
                self.bootstrap_events.put(("error", host, str(error)))
            else:
                self.bootstrap_events.put(("reachable", host, address))

        threading.Thread(
            target=probe, name="EvolutionBootstrapProbe", daemon=True
        ).start()

    def _set_output(self, text):
        self.output.configure(state=tk.NORMAL)
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, text)
        self.output.configure(state=tk.DISABLED)

    def _run_async(self, title, operation, on_success=None):
        if self.task_running:
            messagebox.showinfo(APP_TITLE, "Espera a que termine la operación actual.")
            return
        self.task_running = True
        self.operation_status.set(title)

        def run():
            try:
                result = operation()
            except Exception as error:
                self.root.after(0, lambda error=error: self._task_failed(error))
            else:
                self.root.after(
                    0,
                    lambda result=result: self._task_succeeded(result, on_success),
                )

        threading.Thread(target=run, name="EvolutionTask", daemon=True).start()

    def _task_failed(self, error):
        self.task_running = False
        self.operation_status.set("La operación terminó con error.")
        self._set_output(
            "Error: El problema no fue corregido automáticamente por el sistema\n\n"
            "Detalle: {}".format(error)
        )

    def _task_succeeded(self, result, on_success):
        self.task_running = False
        self.operation_status.set("Operación finalizada.")
        if on_success:
            on_success(result)
        else:
            self._set_output(result)

    def _review_integrity(self):
        if platform.system().lower() != "windows":
            messagebox.showinfo(
                APP_TITLE, "La verificación SFC está disponible únicamente en Windows."
            )
            return

        def verify():
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            result = subprocess.run(
                ["sfc", "/verifyonly"],
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
                creationflags=creationflags,
            )
            details = (result.stdout or "") + (result.stderr or "")
            if result.returncode != 0:
                raise RuntimeError(
                    "SFC terminó con código {}. {}".format(
                        result.returncode,
                        details.strip() or "Windows no proporcionó detalles.",
                    )
                )
            return "SFC terminó con código {}.\n\n{}".format(
                result.returncode, details.strip() or "Windows no proporcionó detalles."
            )

        self._run_async("Verificando integridad de Windows...", verify)

    def _optimize_local_process(self):
        if platform.system().lower() != "windows":
            messagebox.showinfo(APP_TITLE, "El mantenimiento del sistema está disponible solo en Windows.")
            return
        if not ctypes.windll.shell32.IsUserAnAdmin():
            messagebox.showerror(
                APP_TITLE,
                "Para reparar Windows, cierra el "
                "programa y vuelve a abrirlo con «Ejecutar como administrador».",
            )
            return
        if not messagebox.askyesno(
            APP_TITLE,
            "Se ejecutarán DISM para reparar la imagen de Windows, sfc /scannow, "
            "una limpieza de temporales antiguos de tu cuenta y un análisis rápido "
            "de Windows Defender. Puede tardar bastante. Windows gestionará sus "
            "propios errores y la aplicación solo informará si alguna operación "
            "falla. ¿Continuar?",
        ):
            return

        def maintain():
            results = []
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            program_files = get_windows_folder(0x0026)
            defender_candidates = [
                program_files / "Windows Defender" / "MpCmdRun.exe"
            ]
            program_data = get_windows_folder(0x0023)
            platform_dir = program_data / "Microsoft" / "Windows Defender" / "Platform"
            if platform_dir.is_dir():
                defender_candidates.extend(
                    sorted(
                        platform_dir.glob("*/MpCmdRun.exe"),
                        key=lambda path: path.parent.name,
                        reverse=True,
                    )
                )
            defender_path = next(
                (candidate for candidate in defender_candidates if candidate.is_file()),
                None,
            )
            if defender_path is None:
                raise FileNotFoundError(
                    "No se encontró MpCmdRun.exe de Windows Defender para iniciar el análisis."
                )

            dism_result = subprocess.run(
                [
                    "DISM",
                    "/Online",
                    "/Cleanup-Image",
                    "/RestoreHealth",
                ],
                capture_output=True,
                text=True,
                timeout=3600,
                check=False,
                creationflags=creationflags,
            )
            dism_output = (dism_result.stdout or "") + (dism_result.stderr or "")
            if dism_result.returncode not in (0, 3010):
                raise RuntimeError(
                    "DISM terminó con código {}.\n{}".format(
                        dism_result.returncode,
                        dism_output.strip() or "DISM no proporcionó detalles.",
                    )
                )
            results.append(
                "DISM terminó con código {}.\n{}".format(
                    dism_result.returncode,
                    dism_output.strip() or "Windows no proporcionó detalles.",
                )
            )

            sfc_result = subprocess.run(
                ["sfc", "/scannow"],
                capture_output=True,
                text=True,
                timeout=3600,
                check=False,
                creationflags=creationflags,
            )
            sfc_output = (sfc_result.stdout or "") + (sfc_result.stderr or "")
            if sfc_result.returncode != 0:
                raise RuntimeError(
                    "SFC terminó con código {}.\n{}".format(
                        sfc_result.returncode,
                        sfc_output.strip() or "SFC no proporcionó detalles.",
                    )
                )
            results.append(
                "SFC terminó con código {}.\n{}".format(
                    sfc_result.returncode,
                    sfc_output.strip() or "Windows no proporcionó detalles.",
                )
            )

            local_app_data = get_windows_folder(0x001C).resolve()
            if not local_app_data.is_dir():
                raise OSError("No se encontró la carpeta LocalAppData del usuario.")
            temp_path = (local_app_data / "Temp").resolve()
            if temp_path.parent != local_app_data or not temp_path.is_dir():
                raise OSError("La carpeta temporal del usuario no es válida.")
            cutoff = time.time() - 24 * 60 * 60
            removed = 0
            skipped = []

            for item in temp_path.iterdir():
                try:
                    removed += remove_expired_temp_data(item, cutoff)
                except OSError as error:
                    skipped.append("{}: {}".format(item.name, error))

            results.append(
                "Temporales de la cuenta: {} elementos eliminados; {} omitidos.".format(
                    removed, len(skipped)
                )
            )
            if skipped:
                results.append("No se pudieron eliminar:\n" + "\n".join(skipped[:10]))

            defender_result = subprocess.run(
                [str(defender_path), "-Scan", "-ScanType", "1"],
                capture_output=True,
                text=True,
                timeout=3600,
                check=False,
                creationflags=creationflags,
            )
            defender_output = (defender_result.stdout or "") + (defender_result.stderr or "")
            if defender_result.returncode != 0:
                raise RuntimeError(
                    "Windows Defender terminó con código {}.\n{}".format(
                        defender_result.returncode,
                        defender_output.strip()
                        or "Windows Defender no proporcionó detalles.",
                    )
                )
            results.append(
                "Windows Defender terminó con código {}.\n{}".format(
                    defender_result.returncode,
                    defender_output.strip() or "Windows no proporcionó detalles.",
                )
            )
            collected = gc.collect()
            results.append(
                "Limpieza de memoria del proceso local: {} objetos recuperados.".format(
                    collected
                )
            )
            return "\n\n".join(results)

        self._run_async("Ejecutando mantenimiento de Windows...", maintain)

    def _audit_node(self):
        def audit():
            logical_cpus, total_ram, available_ram = get_hardware_info()
            records = self.record_store.read()
            record_count = sum(1 for line in records.splitlines() if line.strip())
            return (
                "Auditoría local\n"
                "Procesadores lógicos: {}\nRAM total: {}\nRAM disponible: {}\n"
                "Registros locales visibles: {}\n"
                "Los peers detectados por LAN: {}; las pruebas bootstrap solo "
                "confirman conectividad TCP, no una malla autenticada."
            ).format(
                logical_cpus,
                format_bytes(total_ram),
                format_bytes(available_ram),
                record_count,
                len(self.discovery.peers) if self.discovery else 0,
            )

        self._run_async("Auditando el nodo local...", audit)

    def _show_mesh_controls(self):
        self.mesh_controls.focus_set()
        self._set_output(
            "Control de participación\n"
            "La prueba Bootstrap resuelve el nombre ingresado y verifica una conexión "
            "TCP al puerto 50001. No registra peers ni confirma una malla global, ya "
            "que falta un servicio bootstrap con protocolo autenticado. El descubrimiento "
            "UDP sigue limitado a la LAN. No se reciben ni ejecutan trabajos remotos."
        )

    def _toggle_mesh_discovery(self):
        if self.discovery:
            self.discovery.stop()
            self.discovery = None
            if self.discovery_poll_id is not None:
                self.root.after_cancel(self.discovery_poll_id)
                self.discovery_poll_id = None
            self.start_button.configure(text="Iniciar descubrimiento LAN")
            self.mesh_status.set("Descubrimiento LAN detenido.")
            self.mesh_status_label.configure(foreground="#555555")
            self._set_output("Se detuvo el descubrimiento de nodos en la red local.")
            return

        if not messagebox.askyesno(
            APP_TITLE,
            "Evolution enviará y escuchará anuncios UDP de descubrimiento en la red "
            "local por el puerto {}. Los anuncios contienen solo un identificador "
            "aleatorio del nodo; no transportan tareas ni datos personales. "
            "¿Permitir el descubrimiento LAN?".format(LAN_DISCOVERY_PORT),
            parent=self.root,
        ):
            return

        self.discovery = LanPeerDiscovery(self.node_id)
        self.discovery.start()
        self.start_button.configure(text="Detener descubrimiento LAN")
        self.mesh_status.set("Descubrimiento LAN activo; buscando otros nodos...")
        self.mesh_status_label.configure(foreground="#9a6700")
        self._set_output(
            "Buscando otros nodos Evolution en la red local. Solo se anuncia un "
            "identificador aleatorio; no se aceptan ni ejecutan trabajos remotos."
        )
        self._poll_mesh_discovery()

    def _poll_mesh_discovery(self):
        self.discovery_poll_id = None
        discovery = self.discovery
        if discovery is None or self.closing:
            return

        for event in discovery.get_events():
            event_type = event[0]
            if event_type == "count":
                peer_count = event[1]
                self.mesh_status.set(
                    "Malla P2P LAN activa: {} nodos anunciados (incluye este equipo); "
                    "sin ejecución de tareas remotas.".format(peer_count + 1)
                )
                self.mesh_status_label.configure(
                    foreground="#16803c" if peer_count else "#9a6700"
                )
            elif event_type == "peer":
                _event_type, peer_id, _address = event
                self.record_store.add_peer(peer_id)
            elif event_type == "error":
                self.discovery = None
                self.start_button.configure(text="Iniciar descubrimiento LAN")
                self.mesh_status.set("No se pudo iniciar el descubrimiento LAN.")
                self.mesh_status_label.configure(foreground="#b42318")
                self._set_output(
                    "Error de descubrimiento UDP: {}\nComprueba que el puerto {} "
                    "esté disponible y permitido en la red.".format(
                        event[1], LAN_DISCOVERY_PORT
                    )
                )
                return

        if self.discovery is discovery:
            self.discovery_poll_id = self.root.after(
                500, self._poll_mesh_discovery
            )

    def _show_local_log(self):
        def read_log():
            contents = self.record_store.read()
            if not contents:
                return "Todavía no hay registros locales."
            return contents

        self._run_async(
            "Leyendo el registro visible local...",
            read_log,
            on_success=self._display_log,
        )

    def _display_log(self, contents):
        window = tk.Toplevel(self.root)
        window.title("Registro local visible")
        window.geometry("700x420")
        text = tk.Text(window, wrap=tk.NONE)
        scrollbar = ttk.Scrollbar(window, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.insert("1.0", contents)
        text.configure(state=tk.DISABLED)

    def _periodic_flush(self):
        if self.closing:
            return
        self.root.after(LOG_FLUSH_INTERVAL_MS, self._periodic_flush)
        self._flush_records_async()

    def _flush_records_async(self, on_complete=None):
        if self.flush_in_progress:
            if on_complete:
                self.root.after(250, lambda: self._flush_records_async(on_complete))
            return
        self.flush_in_progress = True

        def finish(error):
            self.flush_in_progress = False
            if error is not None:
                self.closing = False
                self.operation_status.set("No se pudo guardar el registro local.")
                if on_complete:
                    messagebox.showerror(
                        APP_TITLE,
                        "No se pudo guardar el registro; el nodo sigue abierto para "
                        "que puedas reintentar:\n{}".format(error),
                    )
                else:
                    self.node_status.set(
                        "No se pudo guardar el registro local: {}".format(error)
                    )
                return
            if on_complete:
                on_complete()

        def flush():
            try:
                self.record_store.flush()
            except OSError as error:
                self.root.after(0, lambda error=error: finish(error))
            else:
                self.root.after(0, lambda: finish(None))

        threading.Thread(target=flush, name="EvolutionLogFlush", daemon=True).start()

    def show_window(self):
        if not self.root.winfo_exists():
            return
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_window(self):
        if self.tray_icon:
            self.root.withdraw()
        else:
            self.close()

    def close(self):
        if self.closing:
            return
        if self.task_running:
            messagebox.showinfo(
                APP_TITLE,
                "Espera a que termine la operación de mantenimiento antes de salir.",
            )
            return
        self.closing = True
        self.cpu_monitor_stop.set()
        if self.cpu_monitor_poll_id is not None:
            self.root.after_cancel(self.cpu_monitor_poll_id)
            self.cpu_monitor_poll_id = None
        if self.discovery:
            self.discovery.stop()
            self.discovery = None
        if self.discovery_poll_id is not None:
            self.root.after_cancel(self.discovery_poll_id)
            self.discovery_poll_id = None
        self.node_status.set("Guardando registro local antes de salir...")
        self._flush_records_async(on_complete=self._finish_close)

    def _finish_close(self):
        if self.tray_icon:
            self.tray_icon.remove()
            self.tray_icon = None
        self.root.destroy()


def main():
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("La interfaz Tkinter debe iniciarse en el hilo principal.")

    instance_handle = acquire_single_instance()
    if instance_handle is False:
        ctypes.windll.user32.MessageBoxW(
            None,
            "Evolution System ya está ejecutándose. Usa la ventana abierta antes de iniciar otra instancia.",
            APP_TITLE,
            0x40,
        )
        return

    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("480x280")
    root.minsize(420, 260)
    root.resizable(False, False)

    def activate_node(username, role, login_frame):
        try:
            record_store = LocalRecordStore(get_log_path())
            record_store.add(username)
        except OSError as error:
            messagebox.showerror(APP_TITLE, str(error), parent=root)
            return

        login_frame.destroy()
        try:
            EvolutionNodeApp(root, username, role, record_store)
        except Exception as error:
            messagebox.showerror(
                APP_TITLE,
                "No se pudo inicializar la ventana principal:\n{}".format(error),
                parent=root,
            )
            build_login_view(root, activate_node)
            root.deiconify()
            root.lift()
            return
        root.deiconify()
        root.lift()
        root.focus_force()

    build_login_view(root, activate_node)
    root.deiconify()
    root.lift()
    root.update_idletasks()
    root.update()
    try:
        root.mainloop()
    finally:
        release_single_instance(instance_handle)


if __name__ == "__main__":
    main()
