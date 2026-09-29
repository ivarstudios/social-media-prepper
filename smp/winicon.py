"""SMP's own icon on its windows (Windows only): the console that keeps the server running, and the Chrome or
Edge app window. Chrome gives an app window an icon scaled up from the page's small favicon, which is blurry in
the taskbar, so the window gets the .ico (16 to 256 px) at the size this screen's DPI asks for."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ICO = Path(__file__).parent / "static" / "smp-icon.ico"
TITLE = "IVAR SMP"                        # the page's <title>, so the app window's title
WM_SETICON, WM_GETICON, ICON_SMALL, ICON_BIG = 0x80, 0x7F, 0, 1
SM_CXICON, SM_CXSMICON = 11, 49
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10


def _user32():
    import ctypes
    from ctypes import wintypes

    u = ctypes.windll.user32
    u.LoadImageW.restype = wintypes.HANDLE
    u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                             wintypes.UINT]
    u.SendMessageW.restype = ctypes.c_void_p
    u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p]
    u.FindWindowW.restype = wintypes.HWND
    u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    u.GetDpiForWindow.restype = wintypes.UINT
    u.GetDpiForWindow.argtypes = [wintypes.HWND]
    return u


def set_icon(hwnd) -> int:
    """Give the window SMP's icon at its DPI. Returns the big icon's handle (0 if it couldn't be loaded)."""
    u = _user32()
    dpi = u.GetDpiForWindow(hwnd) or 96
    big = 0
    for which, metric in ((ICON_SMALL, SM_CXSMICON), (ICON_BIG, SM_CXICON)):
        size = u.GetSystemMetricsForDpi(metric, dpi)
        h = u.LoadImageW(None, str(ICO), IMAGE_ICON, size, size, LR_LOADFROMFILE)
        if h:
            u.SendMessageW(hwnd, WM_SETICON, which, h)
            big = h if which == ICON_BIG else big
    return big or 0


def brand_console() -> None:
    """Only the classic console has a window to change; in Windows Terminal this does nothing."""
    if sys.platform != "win32" or not ICO.exists():
        return
    import ctypes

    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd:
        set_icon(hwnd)


def brand_app_window(timeout: float = 30) -> bool:
    """Wait for the app window to open and give it SMP's icon. Chrome sets its own icon again once the page's
    favicon loads, so this keeps putting ours back until it has stayed for a few seconds."""
    if sys.platform != "win32" or not ICO.exists():
        return False
    u = _user32()
    end, ours, kept_since = time.monotonic() + timeout, 0, None
    while time.monotonic() < end:
        hwnd = u.FindWindowW("Chrome_WidgetWin_1", TITLE)
        if hwnd:
            if ours and u.SendMessageW(hwnd, WM_GETICON, ICON_BIG, 0) == ours:
                kept_since = kept_since or time.monotonic()
                if time.monotonic() - kept_since > 4:
                    return True
            else:
                ours, kept_since = set_icon(hwnd), None
        time.sleep(0.25)
    return bool(ours)
