import ctypes
import base64
import gc
import hashlib
import hmac
import ipaddress
import json
import multiprocessing
import os
import platform
import queue
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import uuid
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import urljoin, urlsplit

from cryptography import x509
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


APP_TITLE = "Evolution System - Versión 7.7.7 Absoluta"
STARTUP_REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_VALUE_NAME = "EvolutionSystemV6"
LOG_FLUSH_INTERVAL_MS = 15 * 60 * 1000
INSTANCE_MUTEX_NAME = "Local\\EvolutionSystemV777Absoluta"
LAN_DISCOVERY_PORT = 5005
LAN_DISCOVERY_INTERVAL_SECONDS = 2
LAN_PEER_TIMEOUT_SECONDS = 8
GLOBAL_BOOTSTRAP_PORT = 50001
CPU_PAUSE_THRESHOLD_PERCENT = 95.0
VOLUNTEER_ROLE = "Rol del Nodo: NODO PRINCIPAL / COOPERANTE"
MESH_BOOTSTRAP = ""
MESH_CACHE_FILENAME = "nodos_red.txt"
MESH_KEY_FILENAME = "nodos_red.key"
TLS_CERT_FILENAME = "nodo_tls.crt"
TLS_KEY_FILENAME = "nodo_tls.key"
APP_CONFIG_DIRECTORY = "evolution-system-v777"
MAX_MATH_MATRIX_DIMENSION = 32
MATH_TASK_COOLDOWN_SECONDS = 0.05
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


def get_mesh_cache_path():
    if getattr(sys, "frozen", False):
        app_directory = Path(sys.executable).resolve().parent
    else:
        app_directory = Path(__file__).resolve().parent
    return app_directory / MESH_CACHE_FILENAME


def get_app_config_path():
    if platform.system().lower() == "windows":
        root = os.environ.get("LOCALAPPDATA")
        if not root:
            raise OSError("Windows no definió LOCALAPPDATA para guardar las claves.")
        base = Path(root)
    else:
        root = os.environ.get("XDG_CONFIG_HOME")
        base = Path(root) if root else Path.home() / ".config"
    config_path = base / APP_CONFIG_DIRECTORY
    config_path.mkdir(parents=True, exist_ok=True)
    try:
        config_path.chmod(0o700)
    except OSError:
        if platform.system().lower() != "windows":
            raise
    return config_path


def _write_private_file(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
    )
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)
    try:
        path.chmod(0o600)
    except OSError:
        if platform.system().lower() != "windows":
            raise


def _load_or_create_secret(path, create):
    path = Path(path)
    if path.exists():
        secret = path.read_bytes()
        if not secret:
            raise ValueError("El archivo de clave local está vacío: {}".format(path))
        return secret
    if not create:
        raise FileNotFoundError("No se encontró la clave local: {}".format(path))
    secret = Fernet.generate_key()
    _write_private_file(path, secret)
    return secret


def _create_tls_identity(config_path):
    config_path = Path(config_path)
    cert_path = config_path / TLS_CERT_FILENAME
    key_path = config_path / TLS_KEY_FILENAME
    if cert_path.exists() and key_path.exists():
        return cert_path, key_path
    if cert_path.exists() != key_path.exists():
        raise OSError("La identidad TLS local está incompleta; no se regeneró.")

    private_key = ec.generate_private_key(ec.SECP256R1())
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Evolution P2P node")]
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]
            ),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )
    key_bytes = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    cert_bytes = certificate.public_bytes(serialization.Encoding.PEM)
    _write_private_file(key_path, key_bytes)
    try:
        _write_private_file(cert_path, cert_bytes)
    except OSError:
        key_path.unlink(missing_ok=True)
        raise
    return cert_path, key_path


def create_tls_contexts(config_path):
    cert_path, key_path = _create_tls_identity(config_path)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.minimum_version = ssl.TLSVersion.TLSv1_2
    server_context.load_cert_chain(str(cert_path), str(key_path))
    client_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client_context.minimum_version = ssl.TLSVersion.TLSv1_2
    client_context.check_hostname = False
    client_context.verify_mode = ssl.CERT_NONE
    return server_context, client_context


def read_protected_peer_cache(path):
    path = Path(path)
    if not path.exists():
        return {"peers": [], "fingerprints": {}}
    config_path = get_app_config_path()
    key = _load_or_create_secret(config_path / MESH_KEY_FILENAME, create=False)
    return load_protected_peer_cache(path, Fernet(key))


def load_protected_peer_cache(path, fernet):
    path = Path(path)
    if not path.exists():
        return {"peers": [], "fingerprints": {}}
    with path.open("r", encoding="utf-8") as cache_file:
        envelope = json.load(cache_file)
    if (
        not isinstance(envelope, dict)
        or envelope.get("version") != 2
        or envelope.get("protection") != "fernet"
        or not isinstance(envelope.get("data"), str)
    ):
        raise ValueError(
            "Formato de libreta no reconocido. El archivo previo estaba protegido "
            "con un formato heredado que no puede migrarse automáticamente."
        )
    try:
        encrypted = base64.b64decode(envelope["data"], validate=True)
        payload = json.loads(fernet.decrypt(encrypted).decode("utf-8"))
    except (ValueError, UnicodeError, InvalidToken) as error:
        raise ValueError(
            "No se pudo autenticar la libreta. Verifica la clave local y el archivo."
        ) from error
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("peers"), list)
        or not isinstance(payload.get("fingerprints"), dict)
    ):
        raise ValueError("Contenido descifrado de libreta no válido.")
    return {
        "peers": [
            host for host in payload["peers"][:128] if isinstance(host, str)
        ],
        "fingerprints": {
            host: value
            for host, value in list(payload["fingerprints"].items())[:128]
            if isinstance(host, str)
            and isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value.lower())
        },
    }


def _upnp_soap_request(endpoint, service_type, action, arguments):
    fields = "".join(
        "<{0}>{1}</{0}>".format(name, value) for name, value in arguments.items()
    )
    body = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        "<s:Body><u:{0} xmlns:u=\"{1}\">{2}</u:{0}></s:Body></s:Envelope>"
    ).format(action, service_type, fields).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": '"{}#{}"'.format(service_type, action),
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        return response.read(64 * 1024).decode("utf-8", errors="replace")


def add_upnp_tcp_mapping(port):
    discovery = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    discovery.settimeout(1)
    search = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 1\r\n"
        'ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n'
    ).encode("ascii")
    try:
        discovery.sendto(search, ("239.255.255.250", 1900))
        response, _address = discovery.recvfrom(8192)
    finally:
        discovery.close()
    headers = {}
    for line in response.decode("iso-8859-1").splitlines():
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
    location = headers.get("location")
    if not location:
        raise OSError("El gateway UPnP no anunció una URL de dispositivo.")
    location_parts = urlsplit(location)
    if location_parts.scheme != "http" or not location_parts.hostname:
        raise OSError("La URL UPnP debe ser HTTP y apuntar a una IP del gateway.")
    try:
        gateway_address = ipaddress.ip_address(location_parts.hostname)
    except ValueError as error:
        raise OSError("La URL UPnP no contiene una IP local verificable.") from error
    if not gateway_address.is_private or gateway_address.is_loopback:
        raise OSError("Se rechazó una URL UPnP fuera de la red privada local.")
    with urllib.request.urlopen(location, timeout=3) as response:
        description = ET.fromstring(response.read(256 * 1024))
    base_url = location
    for element in description.iter():
        if element.tag.rsplit("}", 1)[-1] == "URLBase" and element.text:
            base_url = element.text.strip()
            break
    base_parts = urlsplit(base_url)
    if (
        base_parts.scheme != "http"
        or base_parts.hostname != location_parts.hostname
    ):
        raise OSError("El gateway UPnP anunció una URL de control no local.")
    service = None
    for candidate in description.iter():
        if candidate.tag.rsplit("}", 1)[-1] != "service":
            continue
        fields = {
            child.tag.rsplit("}", 1)[-1]: child.text or ""
            for child in candidate
        }
        service_type = fields.get("serviceType", "")
        known_service = any(
            service_type.startswith(prefix)
            for prefix in (
                "urn:schemas-upnp-org:service:WANIPConnection:",
                "urn:schemas-upnp-org:service:WANPPPConnection:",
            )
        )
        version = service_type.rsplit(":", 1)[-1]
        if known_service and version.isdigit() and fields.get("controlURL"):
            service = (service_type, fields.get("controlURL"))
            break
    if not service or not service[1]:
        raise OSError("El gateway no expone WANIPConnection/WANPPPConnection.")
    service_type, control_path = service
    endpoint = urljoin(base_url, control_path)
    endpoint_parts = urlsplit(endpoint)
    if (
        endpoint_parts.scheme != "http"
        or endpoint_parts.hostname != location_parts.hostname
    ):
        raise OSError("El endpoint UPnP no pertenece al gateway local descubierto.")
    route_probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        route_probe.connect(("198.51.100.1", 9))
        internal_address = route_probe.getsockname()[0]
    finally:
        route_probe.close()
    _upnp_soap_request(
        endpoint,
        service_type,
        "AddPortMapping",
        {
            "NewRemoteHost": "",
            "NewExternalPort": str(port),
            "NewProtocol": "TCP",
            "NewInternalPort": str(port),
            "NewInternalClient": internal_address,
            "NewEnabled": "1",
            "NewPortMappingDescription": "Evolution System P2P",
            "NewLeaseDuration": "1800",
        },
    )
    return endpoint, service_type, internal_address


def get_public_ip():
    request = urllib.request.Request(
        "https://api.ipify.org", headers={"User-Agent": "EvolutionSystem/7.7.7"}
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        address = response.read(64).decode("ascii").strip()
    return str(ipaddress.ip_address(address))


def calculate_math_task(task, pause_event=None, stop_event=None):
    if not isinstance(task, dict):
        raise ValueError("La micro-tarea debe ser un objeto JSON.")
    task_type = task.get("task_type")
    if task_type == "matrix_add":
        left = task.get("left")
        right = task.get("right")
        if not isinstance(left, list) or not isinstance(right, list):
            raise ValueError("matrix_add requiere las matrices left y right.")
        if not left or len(left) > MAX_MATH_MATRIX_DIMENSION:
            raise ValueError("Dimensiones de matriz fuera del límite permitido.")
        if len(left) != len(right):
            raise ValueError("Las matrices deben tener el mismo número de filas.")
        if (
            not isinstance(left[0], list)
            or not isinstance(right[0], list)
            or not left[0]
            or len(left[0]) > MAX_MATH_MATRIX_DIMENSION
        ):
            raise ValueError("Dimensiones de matriz fuera del límite permitido.")
        columns = len(left[0])
        result = []
        for left_row, right_row in zip(left, right):
            if pause_event is not None and pause_event.is_set():
                raise InterruptedError("La micro-tarea se pausó por carga local alta.")
            if stop_event is not None and stop_event.is_set():
                raise InterruptedError("La participación P2P fue desactivada.")
            if (
                not isinstance(left_row, list)
                or not isinstance(right_row, list)
                or len(left_row) != columns
                or len(left_row) != len(right_row)
            ):
                raise ValueError("Filas de matriz no válidas.")
            if any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or abs(value) > 1_000_000
                for value in left_row + right_row
            ):
                raise ValueError("Solo se admiten enteros acotados.")
            result.append([a + b for a, b in zip(left_row, right_row)])
        return {"task_type": task_type, "result": result}
    if task_type == "sum_range":
        start = task.get("start")
        end = task.get("end")
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or start < 0
            or end > 1_000_000_000
            or end < start
            or end - start > 100_000
        ):
            raise ValueError("Rango de suma fuera del límite permitido.")
        total = 0
        for value in range(start, end + 1):
            if value % 1024 == 0:
                if pause_event is not None and pause_event.is_set():
                    raise InterruptedError("La micro-tarea se pausó por carga local alta.")
                if stop_event is not None and stop_event.is_set():
                    raise InterruptedError("La participación P2P fue desactivada.")
            total += value
        return {"task_type": task_type, "result": total}
    raise ValueError("Tipo de micro-tarea no admitido.")


def is_windows_admin():
    system = platform.system().lower()
    if system == "windows":
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    if hasattr(os, "geteuid"):
        return os.geteuid() == 0
    return False


def validate_peer_address(host):
    host = host.strip()
    if not host or len(host) > 253 or any(character.isspace() for character in host):
        raise ValueError("Escribe una dirección IP o dominio válido.")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if any(character in host for character in ("/", "\\", "@", ":")):
        raise ValueError("Escribe solo una IP o dominio, sin puerto ni URL.")
    return host


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
    try:
        logical_cpus = multiprocessing.cpu_count()
    except NotImplementedError:
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


def clear_temp_directory(path):
    path = Path(path)
    if not path.is_dir() or path.is_symlink():
        raise OSError("La ruta temporal no es una carpeta accesible: {}".format(path))
    if getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
        raise OSError("Se rechazó una ruta temporal marcada como reparse point.")

    removed = 0
    skipped = []

    def remove_item(item):
        nonlocal removed
        try:
            attributes = getattr(item.lstat(), "st_file_attributes", 0)
            if item.is_symlink() or attributes & 0x400:
                skipped.append("{}: enlace o punto de reanálisis omitido".format(item))
                return
            if item.is_dir():
                for child in item.iterdir():
                    remove_item(child)
                try:
                    item.rmdir()
                    removed += 1
                except OSError as error:
                    skipped.append("{}: {}".format(item, error))
            elif item.is_file():
                item.unlink()
                removed += 1
        except OSError as error:
            skipped.append("{}: {}".format(item, error))

    for child in path.iterdir():
        remove_item(child)
    return removed, skipped


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


class P2PPeerMesh:
    PROTOCOL_ID = "evolution-peer-exchange-v2-tls"
    MAX_PEERS = 128
    MAX_MESSAGE_BYTES = 64 * 1024
    PEER_TIMEOUT_SECONDS = 30 * 60
    GOSSIP_INTERVAL_SECONDS = 5
    CACHE_INTERVAL_SECONDS = LOG_FLUSH_INTERVAL_MS / 1000

    def __init__(self, node_id, cache_path):
        self.node_id = node_id
        self.cache_path = cache_path
        self.config_path = None
        self.fernet = None
        self.server_ssl_context = None
        self.client_ssl_context = None
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.paused_event = threading.Event()
        self.lock = threading.Lock()
        self.cache_lock = threading.Lock()
        self.connection_slots = threading.BoundedSemaphore(16)
        self.task_slots = threading.BoundedSemaphore(1)
        self.peers = {}
        self.peer_fingerprints = {}
        self.sockets = []
        self.threads = []
        self.gossip_offset = 0
        self.processed_task_count = 0

    def start(self, bootstrap_host=""):
        if any(thread.is_alive() for thread in self.threads):
            return True
        self.stop_event.clear()
        try:
            self.config_path = get_app_config_path()
            key = _load_or_create_secret(
                self.config_path / MESH_KEY_FILENAME, create=True
            )
            self.fernet = Fernet(key)
            self.server_ssl_context, self.client_ssl_context = create_tls_contexts(
                self.config_path
            )
            self._load_cache()
            if bootstrap_host:
                self._remember_peer(
                    bootstrap_host, time.monotonic() - self.PEER_TIMEOUT_SECONDS - 1
                )
        except (OSError, UnicodeError, ValueError) as error:
            self.events.put(("error", "No se pudo cargar la libreta de pares: {}".format(error)))
            return False

        targets = [
            ("EvolutionPeerTcp", self._tcp_server),
            ("EvolutionPeerLan", self._lan_discovery),
            ("EvolutionPeerGossip", self._gossip_loop),
            ("EvolutionPeerUpnp", self._network_setup),
        ]
        self.threads = [
            threading.Thread(target=target, name=name, daemon=True)
            for name, target in targets
        ]
        for thread in self.threads:
            thread.start()
        self.events.put(("status", "started"))
        return True

    def stop(self):
        self.stop_event.set()
        for listener in self.sockets:
            try:
                listener.close()
            except OSError:
                pass
        if self.fernet is not None:
            self.save_cache()

    def get_events(self):
        events = []
        while True:
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                return events

    def set_paused(self, paused):
        if paused:
            self.paused_event.set()
        else:
            self.paused_event.clear()

    def peer_count(self):
        now = time.monotonic()
        with self.lock:
            return sum(
                1 for last_seen in self.peers.values()
                if now - last_seen <= self.PEER_TIMEOUT_SECONDS
            )

    def address_count(self):
        with self.lock:
            return len(self.peers)

    def _remember_peer(self, host, last_seen=None):
        try:
            host = validate_peer_address(host)
        except ValueError:
            return False
        if host.lower() in ("localhost", socket.gethostname().lower()):
            return False
        now = time.monotonic() if last_seen is None else last_seen
        with self.lock:
            is_new = host not in self.peers
            if is_new and len(self.peers) >= self.MAX_PEERS:
                oldest = min(self.peers, key=self.peers.get)
                del self.peers[oldest]
            self.peers[host] = now
        if is_new:
            self.events.put(("peer", host))
            self.events.put(("count", self.peer_count()))
        return is_new

    def _peer_snapshot(self):
        with self.lock:
            return list(self.peers.keys())[:self.MAX_PEERS]

    def _load_cache(self):
        cache = load_protected_peer_cache(self.cache_path, self.fernet)
        for host, fingerprint in cache["fingerprints"].items():
            if len(fingerprint) == 64:
                self.peer_fingerprints[host] = fingerprint
        for host in cache["peers"][:self.MAX_PEERS]:
            try:
                validate_peer_address(host)
            except ValueError:
                continue
            else:
                self._remember_peer(
                    host, time.monotonic() - self.PEER_TIMEOUT_SECONDS - 1
                )

    def save_cache(self):
        with self.cache_lock:
            peers = self._peer_snapshot()
            with self.lock:
                fingerprints = dict(self.peer_fingerprints)
            cleartext = json.dumps(
                {"peers": peers, "fingerprints": fingerprints},
                separators=(",", ":"),
            ).encode("utf-8")
            encrypted = self.fernet.encrypt(cleartext)
            envelope = {
                "version": 2,
                "protection": "fernet",
                "data": base64.b64encode(encrypted).decode("ascii"),
            }
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.cache_path.with_name(self.cache_path.name + ".tmp")
            with temp_path.open("w", encoding="utf-8", newline="\n") as cache_file:
                json.dump(envelope, cache_file, separators=(",", ":"))
                cache_file.write("\n")
            os.replace(str(temp_path), str(self.cache_path))

    def _connect_tls(self, host):
        raw_connection = socket.create_connection(
            (host, GLOBAL_BOOTSTRAP_PORT), timeout=3
        )
        try:
            connection = self.client_ssl_context.wrap_socket(
                raw_connection, server_hostname=host
            )
        except (OSError, ValueError):
            raw_connection.close()
            raise
        connection.settimeout(3)
        certificate = connection.getpeercert(binary_form=True)
        if not certificate:
            connection.close()
            raise ssl.SSLError("El par no presentó un certificado TLS.")
        fingerprint = hashlib.sha256(certificate).hexdigest()
        with self.lock:
            expected = self.peer_fingerprints.get(host)
            if expected and not hmac.compare_digest(expected, fingerprint):
                connection.close()
                raise ssl.SSLError(
                    "Cambió la identidad TLS fijada para {}. Requiere verificación manual."
                    .format(host)
                )
            is_first_use = expected is None
            if is_first_use:
                self.peer_fingerprints[host] = fingerprint
        if is_first_use:
            self.events.put(("tls_first_use", host, fingerprint))
            self.save_cache()
        return connection

    def _network_setup(self):
        try:
            endpoint, service_type, internal_address = add_upnp_tcp_mapping(
                GLOBAL_BOOTSTRAP_PORT
            )
            self.events.put(
                (
                    "network_setup",
                    "UPnP asignó TCP:{} → {}.".format(
                        GLOBAL_BOOTSTRAP_PORT, internal_address
                    ),
                )
            )
        except (OSError, urllib.error.URLError, ET.ParseError, ValueError) as error:
            self.events.put(
                (
                    "network_setup",
                    "UPnP no disponible; la conexión LAN/local sigue activa ({})"
                    .format(error),
                )
            )
            endpoint = None
            service_type = None

        try:
            public_address = get_public_ip()
            self.events.put(
                ("public_ip", "IP externa detectada: {}".format(public_address))
            )
        except (OSError, urllib.error.URLError, ValueError) as error:
            self.events.put(
                ("public_ip_error", "No se pudo consultar api.ipify.org: {}".format(error))
            )

        if endpoint and service_type:
            while not self.stop_event.wait(900):
                try:
                    add_upnp_tcp_mapping(GLOBAL_BOOTSTRAP_PORT)
                except (OSError, urllib.error.URLError, ET.ParseError, ValueError) as error:
                    self.events.put(
                        ("network_setup", "No se pudo renovar el mapeo UPnP: {}".format(error))
                    )
            try:
                _upnp_soap_request(
                    endpoint,
                    service_type,
                    "DeletePortMapping",
                    {
                        "NewRemoteHost": "",
                        "NewExternalPort": str(GLOBAL_BOOTSTRAP_PORT),
                        "NewProtocol": "TCP",
                    },
                )
            except (OSError, urllib.error.URLError, ValueError) as error:
                if self.stop_event.is_set():
                    self.events.put(
                        ("network_setup", "No se pudo retirar el mapeo UPnP: {}".format(error))
                    )

    def _tcp_server(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                self.sockets.append(server)
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.settimeout(0.5)
                server.bind(("", GLOBAL_BOOTSTRAP_PORT))
                server.listen(32)
                self.events.put(("listening", GLOBAL_BOOTSTRAP_PORT))
                while not self.stop_event.is_set():
                    try:
                        connection, address = server.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        if self.stop_event.is_set():
                            break
                        raise
                    if not self.connection_slots.acquire(blocking=False):
                        connection.close()
                        continue

                    def handle_exchange(client=connection, peer=address[0]):
                        try:
                            client.settimeout(3)
                            secure_client = self.server_ssl_context.wrap_socket(
                                client, server_side=True
                            )
                            self._handle_exchange(secure_client, peer)
                        except (OSError, ssl.SSLError) as error:
                            if not self.stop_event.is_set():
                                self.events.put(
                                    ("peer_error", peer, "TLS: {}".format(error))
                                )
                        finally:
                            self.connection_slots.release()

                    handler = threading.Thread(
                        target=handle_exchange,
                        name="EvolutionPeerExchange",
                        daemon=True,
                    )
                    handler.start()
        except OSError as error:
            if not self.stop_event.is_set():
                self.events.put(("error", "No se pudo escuchar TCP:{}: {}".format(
                    GLOBAL_BOOTSTRAP_PORT, error
                )))
        finally:
            self.events.put(("count", self.peer_count()))

    def _handle_exchange(self, connection, remote_host):
        try:
            with connection:
                connection.settimeout(3)
                data = self._receive_json_line(connection)
                if not isinstance(data, dict) or data.get("protocol") != self.PROTOCOL_ID:
                    return
                if data.get("node_id") == self.node_id:
                    return
                if data.get("type") == "math_task":
                    self._handle_math_task(connection, remote_host, data)
                    return
                if data.get("type") != "exchange":
                    raise ValueError("Tipo de mensaje P2P no reconocido.")
                self._remember_peer(remote_host)
                candidates = data.get("peers", [])
                if isinstance(candidates, list):
                    for host in candidates[:self.MAX_PEERS]:
                        if isinstance(host, str):
                            self._remember_peer(host)
                response = {
                    "protocol": self.PROTOCOL_ID,
                    "type": "exchange",
                    "node_id": self.node_id,
                    "peers": self._peer_snapshot(),
                }
                connection.sendall(
                    json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n"
                )
                self.events.put(("count", self.peer_count()))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            if not self.stop_event.is_set():
                self.events.put(("peer_error", remote_host, str(error)))

    def _handle_math_task(self, connection, remote_host, message):
        task_id = message.get("task_id")
        if not isinstance(task_id, str) or not 1 <= len(task_id) <= 80:
            raise ValueError("Identificador de micro-tarea no válido.")
        if self.stop_event.is_set() or self.paused_event.is_set():
            response = {"type": "task_error", "task_id": task_id, "error": "paused"}
        elif not self.task_slots.acquire(blocking=False):
            response = {"type": "task_error", "task_id": task_id, "error": "busy"}
        else:
            try:
                self._remember_peer(remote_host)
                thread_cpu_start = time.thread_time()
                result = calculate_math_task(
                    message.get("task"), self.paused_event, self.stop_event
                )
                if self.paused_event.is_set() or self.stop_event.is_set():
                    raise InterruptedError("El nodo pausó su participación.")
                cpu_seconds = time.thread_time() - thread_cpu_start
                remaining = max(
                    MATH_TASK_COOLDOWN_SECONDS,
                    cpu_seconds * (1.0 / 0.015 - 1.0),
                )
                while remaining > 0 and not self.stop_event.is_set():
                    if self.paused_event.is_set():
                        self.stop_event.wait(0.25)
                        continue
                    wait_started = time.monotonic()
                    time.sleep(min(remaining, 0.25))
                    remaining -= time.monotonic() - wait_started
                if self.paused_event.is_set() or self.stop_event.is_set():
                    raise InterruptedError("El nodo pausó su participación.")
                self.processed_task_count += 1
                self.events.put(("task_processed", self.processed_task_count))
                response = {
                    "type": "task_result",
                    "task_id": task_id,
                    "result": result,
                }
            except (ValueError, InterruptedError) as error:
                response = {
                    "type": "task_error",
                    "task_id": task_id,
                    "error": str(error)[:200],
                }
            finally:
                self.task_slots.release()
        payload = {
            "protocol": self.PROTOCOL_ID,
            "node_id": self.node_id,
        }
        payload.update(response)
        connection.sendall(
            json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
        )
        if response["type"] == "task_result":
            self.events.put(("task_served", remote_host, task_id))

    def submit_math_task(self, task):
        calculate_math_task(task)
        peers = self._peer_snapshot()
        if not peers:
            self.events.put(("task_error", "No hay pares conocidos para recibir la tarea."))
            return
        task_id = str(uuid.uuid4())
        for host in peers[:8]:
            threading.Thread(
                target=self._send_math_task,
                args=(host, task_id, task),
                name="EvolutionMathTask",
                daemon=True,
            ).start()

    def _send_math_task(self, host, task_id, task):
        if self.stop_event.is_set() or self.paused_event.is_set():
            return
        try:
            with self._connect_tls(host) as connection:
                request = {
                    "protocol": self.PROTOCOL_ID,
                    "type": "math_task",
                    "node_id": self.node_id,
                    "task_id": task_id,
                    "task": task,
                }
                encoded = json.dumps(
                    request, separators=(",", ":")
                ).encode("utf-8") + b"\n"
                if len(encoded) > self.MAX_MESSAGE_BYTES:
                    raise ValueError("La micro-tarea supera el tamaño permitido.")
                connection.sendall(encoded)
                response = self._receive_json_line(connection)
            if (
                not isinstance(response, dict)
                or response.get("protocol") != self.PROTOCOL_ID
                or response.get("task_id") != task_id
            ):
                raise ValueError("Respuesta de micro-tarea no válida.")
            if response.get("type") == "task_result":
                self.events.put(("task_result", host, response.get("result")))
            else:
                self.events.put(
                    ("task_error", "{}: {}".format(host, response.get("error", "rechazada")))
                )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            self.events.put(("task_error", "{}: {}".format(host, error)))

    def _receive_json_line(self, connection):
        data = bytearray()
        while len(data) < self.MAX_MESSAGE_BYTES:
            chunk = connection.recv(min(2048, self.MAX_MESSAGE_BYTES - len(data)))
            if not chunk:
                break
            newline = chunk.find(b"\n")
            if newline >= 0:
                data.extend(chunk[:newline])
                break
            data.extend(chunk)
        if not data or len(data) >= self.MAX_MESSAGE_BYTES:
            raise ValueError("Mensaje P2P vacío o demasiado grande.")
        return json.loads(data.decode("utf-8"))

    def _exchange_with_peer(self, host):
        if self.stop_event.is_set() or self.paused_event.is_set():
            return
        try:
            with self._connect_tls(host) as connection:
                request = {
                    "protocol": self.PROTOCOL_ID,
                    "type": "exchange",
                    "node_id": self.node_id,
                    "peers": self._peer_snapshot(),
                }
                connection.sendall(
                    json.dumps(request, separators=(",", ":")).encode("utf-8") + b"\n"
                )
                response = self._receive_json_line(connection)
            if (
                not isinstance(response, dict)
                or response.get("protocol") != self.PROTOCOL_ID
                or response.get("type") != "exchange"
            ):
                raise ValueError("Respuesta de intercambio de pares no válida.")
            self._remember_peer(host)
            self.events.put(("count", self.peer_count()))
            candidates = response.get("peers", [])
            if isinstance(candidates, list):
                for candidate in candidates[:self.MAX_PEERS]:
                    if isinstance(candidate, str):
                        self._remember_peer(candidate)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            self.events.put(("peer_error", host, str(error)))

    def _gossip_loop(self):
        next_save = time.monotonic() + self.CACHE_INTERVAL_SECONDS
        while not self.stop_event.wait(self.GOSSIP_INTERVAL_SECONDS):
            if not self.paused_event.is_set():
                all_peers = self._peer_snapshot()
                peers = []
                if all_peers:
                    offset = self.gossip_offset % len(all_peers)
                    peers = (all_peers[offset:] + all_peers[:offset])[:8]
                    self.gossip_offset = (offset + len(peers)) % len(all_peers)
                for host in peers:
                    if self.stop_event.is_set() or self.paused_event.is_set():
                        break
                    self._exchange_with_peer(host)
            cutoff = time.monotonic() - self.PEER_TIMEOUT_SECONDS
            with self.lock:
                active_count = sum(
                    1 for last_seen in self.peers.values() if last_seen >= cutoff
                )
            self.events.put(("count", active_count))
            if time.monotonic() >= next_save:
                try:
                    self.save_cache()
                except OSError as error:
                    self.events.put(("error", "No se pudo guardar la libreta de pares: {}".format(error)))
                next_save = time.monotonic() + self.CACHE_INTERVAL_SECONDS

    def _lan_discovery(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as discovery:
                self.sockets.append(discovery)
                discovery.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                discovery.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                discovery.settimeout(0.5)
                discovery.bind(("", LAN_DISCOVERY_PORT))
                next_broadcast = 0.0
                while not self.stop_event.is_set():
                    now = time.monotonic()
                    if not self.paused_event.is_set() and now >= next_broadcast:
                        packet = json.dumps(
                            {"protocol": self.PROTOCOL_ID, "node_id": self.node_id},
                            separators=(",", ":"),
                        ).encode("utf-8")
                        discovery.sendto(
                            packet, ("255.255.255.255", LAN_DISCOVERY_PORT)
                        )
                        next_broadcast = now + LAN_DISCOVERY_INTERVAL_SECONDS
                    try:
                        packet, address = discovery.recvfrom(512)
                    except socket.timeout:
                        continue
                    try:
                        message = json.loads(packet.decode("utf-8"))
                        if (
                            message.get("protocol") == self.PROTOCOL_ID
                            and message.get("node_id") != self.node_id
                        ):
                            self._remember_peer(address[0])
                    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                        continue
        except OSError as error:
            if not self.stop_event.is_set():
                self.events.put(("error", "No se pudo iniciar el descubrimiento LAN: {}".format(error)))


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
    def __init__(self, root, record_store):
        self.root = root
        self.record_store = record_store
        self.is_admin = is_windows_admin()
        self.closing = False
        self.flush_in_progress = False
        self.mesh = None
        self.mesh_poll_id = None
        self.node_id = str(uuid.uuid4())
        self.math_task_count = 0
        self.cpu_monitor_stop = threading.Event()
        self.cpu_pause_event = threading.Event()
        self.cpu_pause_event.set()
        self.cpu_monitor_available = False
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
                "Evolution se abrirá al iniciar sesión en Windows."
                if self.startup_enabled
                else "Desactivado; no se iniciará automáticamente."
            )
        )

        self.task_running = False
        self.node_status = tk.StringVar(
            value="Nodo local; conexión P2P desactivada hasta que la habilites."
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
        self.root.after(100, self._show_privilege_notice)

    def _show_privilege_notice(self):
        if self.closing or not self.root.winfo_exists():
            return
        if platform.system().lower() != "windows":
            message = (
                "Modo multiplataforma activo. La telemetría y la malla P2P están "
                "disponibles; SFC y Windows Defender solo existen en Windows."
            )
        elif self.is_admin:
            message = (
                "Modo Técnico Avanzado Desbloqueado. Herramientas de reparación "
                "del sistema SFC y Windows Defender listas."
            )
        else:
            message = (
                "Modo Estándar Activo. Optimización de memoria disponible. Para "
                "habilitar mantenimiento avanzado, SFC Scannow y Windows Defender, "
                "ejecute como Administrador."
            )
        messagebox.showinfo(APP_TITLE, message, parent=self.root)

    def _build_interface(self):
        container = ttk.Frame(self.root, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text=APP_TITLE, font=("Segoe UI", 18, "bold")).pack(anchor=tk.W)
        ttk.Label(
            container,
            text=APP_ATTRIBUTION,
        ).pack(anchor=tk.W, pady=(2, 4))
        ttk.Label(container, text=VOLUNTEER_ROLE).pack(anchor=tk.W)
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

        if platform.system().lower() == "windows":
            startup_options = ttk.LabelFrame(
                container, text="Inicio de Windows", padding=8
            )
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
            container, text="Red P2P voluntaria", padding=10
        )
        self.mesh_controls.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(
            self.mesh_controls,
            text=(
                "Al participar, este equipo intercambia direcciones de pares por TCP "
                "en el puerto {} y anuncia descubrimiento en la LAN. También puede "
                "recibir micro-tareas JSON matemáticas con límites fijos; "
                "nunca ejecuta código o expresiones arbitrarias. El consumo reducido "
                "busca aproximadamente el 1.5% de CPU, no es un límite duro. "
                "TLS cifra las conexiones con identidad TOFU: confirma por otro canal "
                "la huella del primer contacto; una conexión inicial no verificada "
                "puede ser interceptada. Se intentará UPnP y se consultará "
                "api.ipify.org para detectar la IP pública. Si UPnP falla, la LAN "
                "sigue disponible; para Internet se requiere router/firewall."
            ).format(GLOBAL_BOOTSTRAP_PORT),
            wraplength=740,
        ).grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 8))
        self.mesh_host_var = tk.StringVar(value=MESH_BOOTSTRAP)
        ttk.Label(self.mesh_controls, text="IP o dominio inicial (opcional):").grid(
            row=1, column=0, sticky=tk.W, padx=(0, 6), pady=4
        )
        self.mesh_host_entry = ttk.Entry(
            self.mesh_controls, textvariable=self.mesh_host_var
        )
        self.mesh_host_entry.grid(row=1, column=1, columnspan=3, sticky="ew", pady=4)
        self.mesh_enabled_var = tk.BooleanVar(value=False)
        self.mesh_switch = ttk.Checkbutton(
            self.mesh_controls,
            text="Activar Conexión en Red Solidaria",
            variable=self.mesh_enabled_var,
            command=self._toggle_mesh_connection,
        )
        self.mesh_switch.grid(row=2, column=0, columnspan=4, sticky=tk.W, pady=(4, 2))
        self.mesh_status = tk.StringVar(value="Conexión en red desactivada.")
        self.mesh_status_label = ttk.Label(
            self.mesh_controls,
            textvariable=self.mesh_status,
            wraplength=740,
            foreground="#555555",
        )
        self.mesh_status_label.grid(
            row=3, column=0, columnspan=4, sticky=tk.W, pady=(2, 4)
        )
        self.math_task_count_var = tk.StringVar(
            value="Micro-tareas matemáticas procesadas por el enjambre: 0 (contador local)"
        )
        ttk.Label(
            self.mesh_controls, textvariable=self.math_task_count_var
        ).grid(row=4, column=0, columnspan=4, sticky=tk.W, pady=(2, 4))
        self.math_task_button = ttk.Button(
            self.mesh_controls,
            text="Enviar micro-tarea educativa (suma de matrices)",
            command=self._submit_sample_math_task,
            state=tk.DISABLED,
        )
        self.math_task_button.grid(
            row=5, column=0, columnspan=4, sticky="ew", pady=(2, 6)
        )
        self.cpu_status = tk.StringVar(value="Monitor de CPU iniciándose...")
        self.cpu_status_label = ttk.Label(
            self.mesh_controls,
            textvariable=self.cpu_status,
            wraplength=740,
        )
        self.cpu_status_label.grid(
            row=6, column=0, columnspan=4, sticky=tk.W, pady=(2, 4)
        )
        ttk.Label(
            self.mesh_controls,
            text=(
                "El descubrimiento LAN solo anuncia un identificador aleatorio de este "
                "nodo; no comparte datos personales ni ejecuta tareas remotas."
            ),
            wraplength=740,
        ).grid(row=7, column=0, columnspan=4, sticky=tk.W, pady=(4, 8))
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
            self.node_status.set(
                "Mantenimiento de Windows no está disponible; malla P2P multiplataforma lista."
            )

    def _toggle_startup(self):
        enabled = bool(self.startup_var.get())
        if enabled and not messagebox.askyesno(
            APP_TITLE,
            "¿Permites que Evolution abra su ventana al iniciar sesión en Windows? "
            "La conexión P2P seguirá desactivada hasta que la habilites en la "
            "interfaz. Puedes desactivar esta opción aquí en cualquier momento.",
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
            "Evolution se abrirá al iniciar sesión en Windows."
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

            self.cpu_monitor_available = True
            was_paused = None
            while not self.cpu_monitor_stop.is_set():
                try:
                    cpu_percent = psutil.cpu_percent(interval=0.5)
                except (psutil.Error, OSError) as error:
                    self.cpu_monitor_available = False
                    self.cpu_pause_event.set()
                    mesh = self.mesh
                    if mesh is not None:
                        mesh.set_paused(True)
                    self.cpu_monitor_events.put(("error", str(error)))
                    return
                should_pause = cpu_percent >= CPU_PAUSE_THRESHOLD_PERCENT
                mesh = self.mesh
                if mesh is not None:
                    mesh.set_paused(should_pause)
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
                        "Pausa LOCAL del intercambio P2P: CPU {:.1f}% supera {:.0f}%. "
                        "Se detiene el gossip saliente de este equipo; otros nodos "
                        "siguen independientes; las tareas entrantes se rechazan o "
                        "pausan cooperativamente."
                        .format(
                            cpu_percent, CPU_PAUSE_THRESHOLD_PERCENT
                        )
                    )
                    self.cpu_status_label.configure(foreground="#b42318")
                else:
                    self.cpu_status.set(
                        "CPU local {:.1f}%: bajo el umbral de {:.0f}%. El intercambio "
                        "P2P saliente y las micro-tareas limitadas pueden continuar."
                        .format(
                            cpu_percent, CPU_PAUSE_THRESHOLD_PERCENT
                        )
                    )
                    self.cpu_status_label.configure(foreground="#16803c")
            elif event[0] == "error":
                self.cpu_status.set(
                    "Monitor de CPU no disponible: {}".format(event[1])
                )

        if not self.closing:
            self.cpu_monitor_poll_id = self.root.after(
                500, self._poll_background_status
            )

    def _set_output(self, text):
        self.output.configure(state=tk.NORMAL)
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, text)
        self.output.configure(state=tk.DISABLED)

    def _run_async(self, title, operation, on_success=None):
        if self.task_running:
            messagebox.showinfo(APP_TITLE, "Espera a que termine la operación actual.")
            return False
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
        return True

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
            self._show_local_read_only_panel()
            self.operation_status.set(
                "SFC y Windows Defender solo están disponibles en Windows."
            )
            return
        if not self.is_admin:
            self._audit_node()
            return
        if not messagebox.askyesno(
            APP_TITLE,
            "Se iniciarán en paralelo SFC /scannow y un análisis rápido de "
            "Windows Defender. Ambas tareas pueden tardar varios minutos. ¿Continuar?",
            parent=self.root,
        ):
            return
        if not self._run_async(
            "Iniciando reparación y análisis de seguridad...",
            self._run_admin_scans,
        ):
            return
        messagebox.showinfo(
            APP_TITLE,
            "Mantenimiento profundo en ejecución: Procesando SFC Scannow y análisis "
            "de Windows Defender en segundo plano...",
            parent=self.root,
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

    def _find_defender_command(self):
        program_files = get_windows_folder(0x0026)
        candidates = [program_files / "Windows Defender" / "MpCmdRun.exe"]
        program_data = get_windows_folder(0x0023)
        platform_dir = program_data / "Microsoft" / "Windows Defender" / "Platform"
        if platform_dir.is_dir():
            candidates.extend(
                sorted(
                    platform_dir.glob("*/MpCmdRun.exe"),
                    key=lambda path: path.parent.name,
                    reverse=True,
                )
            )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise FileNotFoundError("No se encontró MpCmdRun.exe de Windows Defender.")

    def _run_admin_scans(self):
        defender_path = self._find_defender_command()
        scans = [
            ("SFC /scannow", ["sfc", "/scannow"]),
            (
                "Windows Defender",
                [str(defender_path), "-Scan", "-ScanType", "1"],
            ),
        ]
        results = []
        result_lock = threading.Lock()

        def run_scan(name, command):
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=4 * 60 * 60,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                details = ((result.stdout or "") + (result.stderr or "")).strip()
                if result.returncode != 0:
                    raise RuntimeError(
                        "código {}: {}".format(
                            result.returncode,
                            details or "el comando no proporcionó detalles",
                        )
                    )
                outcome = "{} finalizó correctamente (código {}).".format(
                    name, result.returncode
                )
                if details:
                    outcome += "\n" + details[-6000:]
                success = True
            except (OSError, subprocess.SubprocessError, RuntimeError) as error:
                outcome = "{} falló: {}".format(name, error)
                success = False
            with result_lock:
                results.append((name, success, outcome))

        workers = [
            threading.Thread(
                target=run_scan,
                args=(name, command),
                name="Evolution" + name.replace(" ", "").replace("/", ""),
                daemon=True,
            )
            for name, command in scans
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        results.sort(key=lambda result: result[0])
        summary = "\n\n".join(result[2] for result in results)
        failed = [result[0] for result in results if not result[1]]
        if failed:
            raise RuntimeError(
                "Fallaron uno o más análisis ({}).\n\n{}".format(
                    ", ".join(failed), summary
                )
            )
        return summary

    def _optimize_local_process(self):
        system = platform.system().lower()
        if self.is_admin and system == "windows":
            if not messagebox.askyesno(
                APP_TITLE,
                "Se eliminarán los elementos accesibles dentro de C:\\Windows\\Temp "
                "y de la carpeta Temp de este usuario. Archivos protegidos, enlaces "
                "y elementos en uso se omitirán. ¿Continuar?",
                parent=self.root,
            ):
                return

            def optimize():
                collected = gc.collect()
                temp_paths = [
                    get_windows_folder(0x0024) / "Temp",
                    get_windows_folder(0x001C) / "Temp",
                ]
                results = [
                    "Objetos Python liberados por gc.collect(): {}.".format(collected)
                ]
                for temp_path in temp_paths:
                    try:
                        removed, skipped = clear_temp_directory(temp_path)
                    except OSError as error:
                        results.append("{}: error: {}".format(temp_path, error))
                        continue
                    results.append(
                        "{}: {} elementos eliminados; {} omitidos.".format(
                            temp_path, removed, len(skipped)
                        )
                    )
                    if skipped:
                        results.append("Omitidos:\n" + "\n".join(skipped[:20]))
                return "\n\n".join(results)

            self._run_async("Optimizando memoria y temporales...", optimize)
            return

        if self.is_admin and system in ("linux", "darwin"):
            temp_path = Path(tempfile.gettempdir())
            if not temp_path.is_dir():
                messagebox.showerror(
                    APP_TITLE,
                    "No se encontró la carpeta temporal del sistema: {}".format(
                        temp_path
                    ),
                    parent=self.root,
                )
                return
            if not messagebox.askyesno(
                APP_TITLE,
                "Se eliminarán los archivos accesibles dentro de la carpeta temporal "
                "del sistema ({}). Archivos en uso y enlaces se omitirán. "
                "¿Continuar?".format(temp_path),
                parent=self.root,
            ):
                return

            def optimize_unix():
                collected = gc.collect()
                removed, skipped = clear_temp_directory(temp_path)
                results = [
                    "Objetos Python liberados por gc.collect(): {}.".format(collected),
                    "{}: {} elementos eliminados; {} omitidos.".format(
                        temp_path, removed, len(skipped)
                    ),
                ]
                if skipped:
                    results.append("Omitidos:\n" + "\n".join(skipped[:20]))
                return "\n\n".join(results)

            self._run_async(
                "Optimizando memoria y temporales del sistema...", optimize_unix
            )
            return

        def optimize():
            collected = gc.collect()
            return (
                "Optimización de memoria del proceso completada. "
                "gc.collect() liberó {} objetos Python no referenciados."
            ).format(collected)

        self._run_async("Optimizando memoria local...", optimize)
        return
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

    def _show_local_read_only_panel(self):
        window = tk.Toplevel(self.root)
        window.title("Panel local de recursos — solo lectura")
        window.geometry("480x260")
        window.transient(self.root)
        panel = ttk.LabelFrame(window, text="Telemetría del equipo", padding=16)
        panel.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        variables = {
            "role": tk.StringVar(value=VOLUNTEER_ROLE),
            "cpus": tk.StringVar(value="Detectando..."),
            "cpu": tk.StringVar(value="Leyendo..."),
            "ram": tk.StringVar(value="Leyendo..."),
            "app_ram": tk.StringVar(value="No disponible"),
        }
        for row, (label, key) in enumerate(
            (
                ("Rol", "role"),
                ("Procesadores lógicos", "cpus"),
                ("Uso de CPU", "cpu"),
                ("Memoria física", "ram"),
                ("Memoria del proceso Evolution", "app_ram"),
            )
        ):
            ttk.Label(panel, text=label + ":").grid(
                row=row, column=0, sticky=tk.W, padx=(0, 12), pady=5
            )
            ttk.Label(panel, textvariable=variables[key]).grid(
                row=row, column=1, sticky=tk.W, pady=5
            )
        panel.columnconfigure(1, weight=1)
        after_id = [None]

        def refresh():
            if not window.winfo_exists():
                return
            try:
                logical_cpus, total_ram, available_ram = get_hardware_info()
                variables["cpus"].set(str(logical_cpus))
                variables["ram"].set(
                    "{} total / {} disponible".format(
                        format_bytes(total_ram), format_bytes(available_ram)
                    )
                )
            except (OSError, ValueError) as error:
                variables["ram"].set("Error: {}".format(error))
            try:
                import psutil

                variables["cpu"].set(
                    "{:.1f}%".format(psutil.cpu_percent(interval=None))
                )
                variables["app_ram"].set(
                    format_bytes(psutil.Process().memory_info().rss)
                )
            except ImportError as error:
                variables["cpu"].set("No disponible: {}".format(error))
                variables["app_ram"].set("No disponible")
            except (psutil.Error, OSError) as error:
                variables["cpu"].set("No disponible: {}".format(error))
                variables["app_ram"].set("No disponible")
            after_id[0] = window.after(1000, refresh)

        def close_panel():
            if after_id[0] is not None:
                window.after_cancel(after_id[0])
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", close_panel)
        refresh()

    def _show_mesh_read_only_panel(self):
        window = tk.Toplevel(self.root)
        window.title("Control de participación — solo lectura")
        window.geometry("560x300")
        window.transient(self.root)
        panel = ttk.LabelFrame(window, text="Estado de sincronización P2P", padding=16)
        panel.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        status = tk.StringVar()
        active = tk.StringVar()
        known = tk.StringVar()
        tasks = tk.StringVar(value="0")
        port = tk.StringVar(value=str(GLOBAL_BOOTSTRAP_PORT))
        cache = tk.StringVar(value=str(get_mesh_cache_path()))
        fields = (
            ("Estado", status),
            ("Pares activos", active),
            ("Direcciones en libreta", known),
            ("Micro-tareas observadas en este nodo", tasks),
            ("Puerto TCP", port),
            ("Archivo local de pares", cache),
        )
        for row, (label, variable) in enumerate(fields):
            ttk.Label(panel, text=label + ":").grid(
                row=row, column=0, sticky=tk.NW, padx=(0, 12), pady=5
            )
            ttk.Label(
                panel, textvariable=variable, wraplength=390, justify=tk.LEFT
            ).grid(row=row, column=1, sticky=tk.NW, pady=5)
        panel.columnconfigure(1, weight=1)
        after_id = [None]

        def refresh():
            if not window.winfo_exists():
                return
            mesh = self.mesh
            status.set(
                "Conexión habilitada" if mesh else "Conexión desactivada"
            )
            active.set(str(mesh.peer_count()) if mesh else "0")
            tasks.set(str(self.math_task_count))
            if mesh:
                known.set(str(mesh.address_count()))
            else:
                try:
                    known.set(
                        str(
                            len(
                                read_protected_peer_cache(
                                    get_mesh_cache_path()
                                )["peers"]
                            )
                        )
                    )
                except (OSError, UnicodeError, ValueError) as error:
                    known.set("No disponible: {}".format(error))
            after_id[0] = window.after(1500, refresh)

        def close_panel():
            if after_id[0] is not None:
                window.after_cancel(after_id[0])
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", close_panel)
        refresh()

    def _audit_node(self):
        self._show_local_read_only_panel()

    def _show_mesh_controls(self):
        self._show_mesh_read_only_panel()

    def _toggle_mesh_connection(self):
        if not self.mesh_enabled_var.get():
            mesh = self.mesh
            self.mesh = None
            self.math_task_button.configure(state=tk.DISABLED)
            if mesh:
                try:
                    mesh.stop()
                except OSError as error:
                    messagebox.showerror(
                        APP_TITLE,
                        "No se pudo guardar la libreta de pares:\n{}".format(error),
                        parent=self.root,
                    )
            if self.mesh_poll_id is not None:
                self.root.after_cancel(self.mesh_poll_id)
                self.mesh_poll_id = None
            self.mesh_status.set("Conexión en red desactivada.")
            self.mesh_status_label.configure(foreground="#555555")
            self.mesh_host_entry.configure(state=tk.NORMAL)
            self._set_output("Este nodo dejó de participar en el intercambio P2P.")
            return

        if not messagebox.askyesno(
            APP_TITLE,
            "Al activar la red, este equipo escuchará conexiones P2P entrantes en "
            "TCP:{} y anunciará un identificador aleatorio por UDP en la LAN. "
            "Compartirá direcciones IP/dominios de pares y podrá recibir tareas "
            "JSON limitadas a cálculos matemáticos; no ejecutará código arbitrario. "
            "Se intentará abrir el puerto mediante UPnP y consultar api.ipify.org. "
            "¿Activar la conexión?".format(
                GLOBAL_BOOTSTRAP_PORT
            ),
            icon=messagebox.WARNING,
            parent=self.root,
        ):
            self.mesh_enabled_var.set(False)
            return
        if not self.cpu_monitor_available:
            messagebox.showerror(
                APP_TITLE,
                "No se activará la red: el monitor psutil no está disponible. "
                "Instala psutil para habilitar el freno local de CPU.",
                parent=self.root,
            )
            self.mesh_enabled_var.set(False)
            return

        host = self.mesh_host_var.get().strip()
        if host:
            try:
                host = validate_peer_address(host)
            except ValueError as error:
                messagebox.showwarning(APP_TITLE, str(error), parent=self.root)
                self.mesh_enabled_var.set(False)
                return
        try:
            cache_path = get_mesh_cache_path()
        except OSError as error:
            messagebox.showerror(
                APP_TITLE,
                "No se pudo preparar la libreta local de pares:\n{}".format(error),
                parent=self.root,
            )
            self.mesh_enabled_var.set(False)
            return
        self.mesh = P2PPeerMesh(self.node_id, cache_path)
        self.mesh.set_paused(self.cpu_pause_event.is_set())
        if not self.mesh.start(host):
            errors = self.mesh.get_events()
            self.mesh = None
            self.mesh_enabled_var.set(False)
            self.math_task_button.configure(state=tk.DISABLED)
            self.mesh_host_entry.configure(state=tk.NORMAL)
            error_message = next(
                (event[1] for event in errors if event[0] == "error"),
                "No se pudo inicializar el cifrado local de la malla.",
            )
            messagebox.showerror(
                APP_TITLE, error_message, parent=self.root
            )
            return
        self.mesh_host_entry.configure(state=tk.DISABLED)
        self.mesh_status.set(
            "P2P activado; conectando y buscando pares conocidos. "
            "Las micro-tareas matemáticas están limitadas a operaciones permitidas."
        )
        self.mesh_status_label.configure(foreground="#9a6700")
        self.math_task_button.configure(state=tk.NORMAL)
        self._set_output(
            "P2P voluntario activo. Intentando intercambio TCP con pares guardados "
            "y descubrimiento UDP en la LAN. Solo se admiten micro-tareas matemáticas "
            "JSON permitidas."
        )
        self._poll_mesh_discovery()

    def _submit_sample_math_task(self):
        mesh = self.mesh
        if mesh is None:
            messagebox.showinfo(
                APP_TITLE,
                "Activa primero la conexión voluntaria a la red.",
                parent=self.root,
            )
            return
        if self.cpu_pause_event.is_set():
            messagebox.showinfo(
                APP_TITLE,
                "La CPU local está por encima del umbral; el trabajo está pausado.",
                parent=self.root,
            )
            return
        task = {
            "task_type": "matrix_add",
            "left": [[1, 2], [3, 4]],
            "right": [[5, 6], [7, 8]],
        }
        try:
            mesh.submit_math_task(task)
        except ValueError as error:
            messagebox.showerror(APP_TITLE, str(error), parent=self.root)
            return
        self.operation_status.set("Enviando micro-tarea matemática a pares conocidos...")

    def _poll_mesh_discovery(self):
        self.mesh_poll_id = None
        mesh = self.mesh
        if mesh is None or self.closing:
            return

        for event in mesh.get_events():
            event_type = event[0]
            if event_type == "count":
                peer_count = event[1]
                if peer_count:
                    self.mesh_status.set(
                        "Malla P2P Activa: {} Nodos Descubiertos en el Enjambre"
                        .format(peer_count)
                    )
                else:
                    self.mesh_status.set(
                        "P2P activo; buscando pares para micro-tareas matemáticas."
                    )
                self.mesh_status_label.configure(
                    foreground="#00a83b" if peer_count else "#9a6700"
                )
            elif event_type == "listening":
                self._set_output(
                    "Escuchando conexiones P2P TCP en el puerto {}.".format(event[1])
                )
            elif event_type == "error":
                self.mesh_status.set(event[1])
                self.mesh_status_label.configure(foreground="#b42318")
                messagebox.showerror(APP_TITLE, event[1], parent=self.root)
            elif event_type == "peer_error":
                self.operation_status.set(
                    "No se pudo intercambiar pares con {}: {}".format(
                        event[1], event[2]
                    )
                )
            elif event_type == "tls_first_use":
                self.operation_status.set(
                    "Nueva identidad TLS (TOFU) para {}. Verifica por otro canal "
                    "esta huella SHA-256: {}".format(event[1], event[2])
                )
            elif event_type in ("network_setup", "public_ip"):
                self.operation_status.set(event[1])
            elif event_type == "public_ip_error":
                self.operation_status.set(event[1])
            elif event_type == "task_result":
                self.math_task_count += 1
                self.math_task_count_var.set(
                    "Micro-tareas matemáticas procesadas por el enjambre: {} "
                    "(contador local)".format(
                        self.math_task_count
                    )
                )
                self.operation_status.set(
                    "Un par devolvió el resultado matemático: {}".format(event[2])
                )
            elif event_type == "task_processed":
                self.math_task_count += 1
                self.math_task_count_var.set(
                    "Micro-tareas matemáticas procesadas por el enjambre: {} "
                    "(contador local)".format(
                        self.math_task_count
                    )
                )
            elif event_type == "task_error":
                self.operation_status.set("Micro-tarea no completada: {}".format(event[1]))

        if self.mesh is mesh:
            self.mesh_poll_id = self.root.after(
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
                mesh = self.mesh
                if mesh is not None:
                    mesh.save_cache()
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
        if self.mesh:
            try:
                self.mesh.stop()
            except OSError as error:
                self.closing = False
                messagebox.showerror(
                    APP_TITLE,
                    "No se pudo guardar la libreta de pares; el nodo permanece "
                    "abierto:\n{}".format(error),
                    parent=self.root,
                )
                return
            self.mesh = None
        if self.mesh_poll_id is not None:
            self.root.after_cancel(self.mesh_poll_id)
            self.mesh_poll_id = None
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
    try:
        record_store = LocalRecordStore(get_log_path())
        record_store.add("NODO PRINCIPAL / COOPERANTE", VOLUNTEER_ROLE)
        EvolutionNodeApp(root, record_store)
    except (OSError, RuntimeError, ValueError) as error:
        messagebox.showerror(
            APP_TITLE,
            "No se pudo inicializar la aplicación:\n{}".format(error),
            parent=root,
        )
        root.destroy()
        release_single_instance(instance_handle)
        return
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
