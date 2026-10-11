import ctypes
import gc
import os
import platform
import subprocess
import sys
import threading
import time
import tkinter as tk
import uuid
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk


APP_TITLE = "Evolution System - Versión 7.7.7 Absoluta"
STARTUP_REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_VALUE_NAME = "EvolutionSystemV6"
LOG_FLUSH_INTERVAL_MS = 15 * 60 * 1000


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
            wintypes.LRESULT,
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
            ("hCursor", wintypes.HCURSOR),
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
        self._user32.DefWindowProcW.restype = wintypes.LRESULT
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
        base_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
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


def format_local_record(username):
    username = username.replace("|", "_").replace("\r", "_").replace("\n", "_")
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    return "{}|nodo_secundario_voluntario|{}".format(username, timestamp)


class LocalRecordStore:
    def __init__(self, path):
        self.path = path
        self.pending_records = []
        self.lock = threading.Lock()

    def add(self, username):
        with self.lock:
            self.pending_records.append(format_local_record(username))

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


def request_node_username(root):
    result = {"username": None}
    dialog = tk.Toplevel(root)
    dialog.title("Activar nodo local")
    dialog.resizable(False, False)
    dialog.transient(root)
    dialog.grab_set()
    frame = ttk.Frame(dialog, padding=18)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(
        frame,
        text="Elige un nombre para identificar este equipo en el registro local.",
        wraplength=350,
    ).pack(anchor=tk.W, pady=(0, 10))
    ttk.Label(frame, text="Nombre de usuario").pack(anchor=tk.W)
    username_var = tk.StringVar()
    entry = ttk.Entry(frame, textvariable=username_var, width=42)
    entry.pack(fill=tk.X, pady=(4, 12))

    def accept():
        username = username_var.get().strip()
        if not username:
            messagebox.showwarning(
                "Activar nodo local", "Escribe un nombre para continuar.", parent=dialog
            )
            return
        result["username"] = username
        dialog.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill=tk.X)
    ttk.Button(buttons, text="Continuar como voluntario", command=accept).pack(
        side=tk.RIGHT
    )
    ttk.Button(buttons, text="Cancelar", command=dialog.destroy).pack(
        side=tk.RIGHT, padx=(0, 8)
    )
    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
    dialog.bind("<Return>", lambda _event: accept())
    entry.focus_set()
    root.wait_window(dialog)
    return result["username"]


class EvolutionNodeApp:
    def __init__(self, root, username, record_store):
        self.root = root
        self.username = username
        self.record_store = record_store
        self.closing = False
        self.flush_in_progress = False
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
            text="Creador: Juan Camilo Mazo González (jcmgru) | Proyectos Geniales | jcmgru7@gmail.com",
        ).pack(anchor=tk.W, pady=(2, 4))
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
                "El intercambio de tareas entre equipos no está habilitado: falta definir "
                "un protocolo de emparejamiento y autenticación de pares. Este programa "
                "no consume CPU ni acepta trabajos de red mientras no esté configurado. "
                "Al habilitarlo, los límites de recursos deberán ser explícitos y configurables."
            ),
            wraplength=740,
        ).grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 8))
        self.start_button = ttk.Button(
            self.mesh_controls,
            text="Malla no configurada",
            state=tk.DISABLED,
        )
        self.start_button.grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
        self.mesh_controls.columnconfigure(0, weight=1)

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
        messagebox.showerror(APP_TITLE, str(error))

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
                "Para ejecutar SFC y Windows Defender, cierra el programa y vuelve a "
                "abrirlo con «Ejecutar como administrador».",
            )
            return
        if not messagebox.askyesno(
            APP_TITLE,
            "Se limpiarán elementos temporales de tu cuenta y se ejecutarán "
            "sfc /scannow y un análisis rápido de Windows Defender. "
            "El análisis puede tardar varios minutos. ¿Continuar?",
        ):
            return

        def maintain():
            results = []
            program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            defender_candidates = [
                program_files / "Windows Defender" / "MpCmdRun.exe"
            ]
            program_data = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
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

            local_app_data = Path(os.environ.get("LOCALAPPDATA", "")).resolve()
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

            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            sfc_result = subprocess.run(
                ["sfc", "/scannow"],
                capture_output=True,
                text=True,
                timeout=3600,
                check=False,
                creationflags=creationflags,
            )
            sfc_output = (sfc_result.stdout or "") + (sfc_result.stderr or "")
            results.append(
                "SFC terminó con código {}.\n{}".format(
                    sfc_result.returncode,
                    sfc_output.strip() or "Windows no proporcionó detalles.",
                )
            )

            defender_result = subprocess.run(
                [str(defender_path), "-Scan", "-ScanType", "1"],
                capture_output=True,
                text=True,
                timeout=3600,
                check=False,
                creationflags=creationflags,
            )
            defender_output = (defender_result.stdout or "") + (defender_result.stderr or "")
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
                "La malla no está configurada; no hay conexión con otros nodos."
            ).format(
                logical_cpus,
                format_bytes(total_ram),
                format_bytes(available_ram),
                record_count,
            )

        self._run_async("Auditando el nodo local...", audit)

    def _show_mesh_controls(self):
        self.mesh_controls.focus_set()
        self._set_output(
            "Control de participación\n"
            "La malla todavía no está conectada. El programa no recibe ni ejecuta "
            "trabajos remotos, y no consume CPU en espera. Para habilitarla hace falta "
            "definir cómo se emparejan y autentican los equipos."
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

    def hide_window(self):
        if self.tray_icon:
            self.root.withdraw()
            return
        if messagebox.askyesno(
            APP_TITLE,
            "No está disponible el icono de bandeja. ¿Quieres salir del programa?",
        ):
            self.close()

    def show_window(self):
        if not self.root.winfo_exists():
            return
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

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
        self.node_status.set("Guardando registro local antes de salir...")
        self._flush_records_async(on_complete=self._finish_close)

    def _finish_close(self):
        if self.tray_icon:
            self.tray_icon.remove()
            self.tray_icon = None
        self.root.destroy()


def main():
    root = tk.Tk()
    root.withdraw()
    username = request_node_username(root)
    if username is None:
        root.destroy()
        return
    try:
        record_store = LocalRecordStore(get_log_path())
        record_store.add(username)
    except OSError as error:
        messagebox.showerror(APP_TITLE, str(error), parent=root)
        root.destroy()
        return
    EvolutionNodeApp(root, username, record_store)
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
