"""
A tray icon, so the bridge stops looking like a script.

"Leave this window open while you print" is the last thing that marks a tool
as somebody's weekend project. With this, Print Bridge starts at logon with no
window at all and lives next to the clock: right-click for the address, the
folder and the log, or to stop it.

This is the one place a real Windows service would be worse. A service runs in
session 0, which cannot reach the logged-in user's printer queue or drive a
scanner through WIA - both of which are the entire point. Starting at logon is
not a compromise here, it is the correct place for this to live.

Pure ctypes against user32 and shell32: no pywin32, no build step.
"""

from __future__ import annotations

import os
import platform
import subprocess
import tempfile
import threading
import webbrowser

IS_WINDOWS = platform.system() == "Windows"

from . import __version__, icons

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
else:
    ctypes = wintypes = user32 = shell32 = kernel32 = None

WM_DESTROY, WM_COMMAND, WM_CLOSE = 0x0002, 0x0111, 0x0010
WM_LBUTTONDBLCLK, WM_RBUTTONUP, WM_LBUTTONUP = 0x0203, 0x0205, 0x0202
WM_TRAY = 0x0400 + 20                      # WM_APP + 20

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x0010, 0x0040
MF_STRING, MF_SEPARATOR, MF_GRAYED = 0x0000, 0x0800, 0x0001
TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x0002, 0x0100

ID_OPEN, ID_FOLDER, ID_LOG, ID_CLEAR, ID_QUIT = 1001, 1002, 1003, 1004, 1005


if IS_WINDOWS:
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT),
                    ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                    ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR),
                    ("lpszClassName", wintypes.LPCWSTR),
                    ("hIconSm", wintypes.HICON)]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                    ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                    ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                    ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
                    ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                    ("uTimeout", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                    ("dwInfoFlags", wintypes.DWORD),
                    ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HICON)]

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    # Same reasoning as winprint: window, menu and icon handles are pointers,
    # and an undeclared ctypes call would truncate them to 32 bits.
    for _name, _restype, _args in (
            ("RegisterClassExW", wintypes.ATOM, [ctypes.c_void_p]),
            ("CreateWindowExW", wintypes.HWND,
             [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
              ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
              wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]),
            ("DefWindowProcW", ctypes.c_long,
             [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]),
            ("PostMessageW", wintypes.BOOL,
             [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]),
            ("PostQuitMessage", None, [ctypes.c_int]),
            ("GetMessageW", wintypes.BOOL,
             [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT]),
            ("TranslateMessage", wintypes.BOOL, [ctypes.c_void_p]),
            ("DispatchMessageW", ctypes.c_long, [ctypes.c_void_p]),
            ("CreatePopupMenu", wintypes.HMENU, []),
            ("AppendMenuW", wintypes.BOOL,
             [wintypes.HMENU, wintypes.UINT, ctypes.c_void_p, wintypes.LPCWSTR]),
            ("TrackPopupMenu", wintypes.BOOL,
             [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
              ctypes.c_int, wintypes.HWND, ctypes.c_void_p]),
            ("DestroyMenu", wintypes.BOOL, [wintypes.HMENU]),
            ("SetForegroundWindow", wintypes.BOOL, [wintypes.HWND]),
            ("GetCursorPos", wintypes.BOOL, [ctypes.c_void_p]),
            ("LoadImageW", wintypes.HANDLE,
             [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
              ctypes.c_int, ctypes.c_int, wintypes.UINT]),
            ("LoadIconW", wintypes.HICON, [wintypes.HINSTANCE, wintypes.LPCWSTR]),
    ):
        _fn = getattr(user32, _name)
        _fn.restype, _fn.argtypes = _restype, _args

    shell32.Shell_NotifyIconW.restype = wintypes.BOOL
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.c_void_p]
    kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


def available():
    return bool(IS_WINDOWS)


class Tray:
    """One icon next to the clock, and the menu behind it."""

    def __init__(self, folder, url="", printer="", scanner="", log_path="",
                 on_quit=None, on_clear=None):
        self.folder = folder
        self.url = url
        self.printer = printer
        self.scanner = scanner
        self.log_path = log_path
        self.on_quit = on_quit
        self.on_clear = on_clear
        self.hwnd = None
        self._icon = None
        self._proc = None
        self._icon_file = None

    # -- helpers ---------------------------------------------------------
    def _load_icon(self):
        try:
            path = os.path.join(tempfile.gettempdir(), "printbridge-tray.ico")
            with open(path, "wb") as fh:
                fh.write(icons.ico((16, 32, 48)))
            self._icon_file = path
            handle = user32.LoadImageW(None, path, IMAGE_ICON, 0, 0,
                                       LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if handle:
                return handle
        except Exception:
            pass
        return user32.LoadIconW(None, ctypes.c_wchar_p(32512))    # IDI_APPLICATION

    def _tip(self):
        bits = ["Print Bridge %s" % __version__]
        if self.printer:
            bits.append(self.printer)
        if self.url:
            bits.append(self.url)
        return "\n".join(bits)[:127]

    def _notify(self, action, extra=0, info="", title=""):
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = self.hwnd
        data.uID = 1
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | extra
        data.uCallbackMessage = WM_TRAY
        data.hIcon = self._icon
        data.szTip = self._tip()
        if info:
            data.szInfo = info[:255]
            data.szInfoTitle = title[:63]
            data.uTimeout = 8000
            data.dwInfoFlags = 0
        return bool(shell32.Shell_NotifyIconW(action, ctypes.byref(data)))

    # -- menu ------------------------------------------------------------
    def _menu(self):
        menu = user32.CreatePopupMenu()
        header = self.printer or "no printer"
        user32.AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, header[:60])
        if self.scanner:
            user32.AppendMenuW(menu, MF_STRING | MF_GRAYED, 0,
                               ("scanner: " + self.scanner)[:60])
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_OPEN, "Open the print page")
        if self.on_clear:
            user32.AppendMenuW(menu, MF_STRING, ID_CLEAR,
                               "Clear the print queue")
        user32.AppendMenuW(menu, MF_STRING, ID_FOLDER, "Open the folder")
        if self.log_path:
            user32.AppendMenuW(menu, MF_STRING, ID_LOG, "Show the log")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_QUIT, "Stop Print Bridge")

        point = POINT()
        user32.GetCursorPos(ctypes.byref(point))
        user32.SetForegroundWindow(self.hwnd)
        choice = user32.TrackPopupMenu(
            menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, point.x, point.y,
            0, self.hwnd, None)
        user32.DestroyMenu(menu)
        if choice:
            self._command(choice)

    def _command(self, which):
        if which == ID_OPEN and self.url:
            webbrowser.open(self.url)
        elif which == ID_FOLDER:
            try:
                os.startfile(self.folder)
            except Exception:
                subprocess.Popen(["explorer", self.folder])
        elif which == ID_LOG and self.log_path:
            try:
                os.startfile(self.log_path)
            except Exception:
                subprocess.Popen(["notepad", self.log_path])
        elif which == ID_CLEAR and self.on_clear:
            ok, detail = self.on_clear()
            self._notify(NIM_MODIFY, NIF_INFO, info=detail,
                         title="Print queue" if ok else "Could not clear it")
        elif which == ID_QUIT:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    # -- window ----------------------------------------------------------
    def _wndproc(self, hwnd, message, wparam, lparam):
        if message == WM_TRAY:
            low = lparam & 0xFFFF
            if low == WM_RBUTTONUP:
                self._menu()
            elif low in (WM_LBUTTONDBLCLK, WM_LBUTTONUP):
                self._command(ID_OPEN)
            return 0
        if message == WM_COMMAND:
            self._command(wparam & 0xFFFF)
            return 0
        if message in (WM_CLOSE, WM_DESTROY):
            self._notify(NIM_DELETE)
            user32.PostQuitMessage(0)
            if self.on_quit:
                try:
                    self.on_quit()
                except Exception:
                    pass
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def run(self):
        """Show the icon and pump messages. Returns when the user quits."""
        if not IS_WINDOWS:
            return False
        self._proc = WNDPROC(self._wndproc)        # keep a reference alive

        klass = WNDCLASSEXW()
        klass.cbSize = ctypes.sizeof(WNDCLASSEXW)
        klass.lpfnWndProc = self._proc
        klass.hInstance = kernel32.GetModuleHandleW(None)
        klass.lpszClassName = "PrintBridgeTray"
        if not user32.RegisterClassExW(ctypes.byref(klass)):
            if ctypes.get_last_error() != 1410:     # already registered
                return False

        self.hwnd = user32.CreateWindowExW(
            0, "PrintBridgeTray", "Print Bridge", 0, 0, 0, 0, 0,
            None, None, klass.hInstance, None)
        if not self.hwnd:
            return False

        self._icon = self._load_icon()
        if not self._notify(NIM_ADD):
            return False
        self._notify(NIM_MODIFY, NIF_INFO,
                     info=("Printing to %s.\n%s" % (self.printer or "your printer",
                                                    self.url or "")).strip(),
                     title="Print Bridge is running")

        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        return True

    def stop(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
