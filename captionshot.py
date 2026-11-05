"""CaptionShot v25 - tray screenshot tool with annotations and a caption bar.

Windows 11 and macOS 26 (Tahoe), Python 3.10+, PySide6 6.11+.
Keep the 'fonts' folder next to this file (Mukta, for Hindi).
Run on Windows:  pythonw captionshot.py
Run on macOS:    python3 captionshot.py
"""
import sys, os, re, json, math, ctypes, datetime, threading, subprocess, tempfile, plistlib, unicodedata
from collections import Counter

from PySide6.QtCore import (Qt, QRect, QRectF, QPointF, QSizeF, QPoint, QSize, Signal, QObject,
                            QTimer, QUrl, QUrlQuery, QLockFile, QDir, QByteArray)
from PySide6.QtGui import (QGuiApplication, QPainter, QPen, QColor, QPixmap, QImage, QIcon,
                           QFont, QFontMetrics, QPainterPath, QPolygonF, QCursor, QKeySequence,
                           QTextOption, QDesktopServices, QFontDatabase, QTextCursor, QPainterPathStroker)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (QApplication, QWidget, QSystemTrayIcon, QMenu, QToolButton,
                               QHBoxLayout, QVBoxLayout, QTextEdit, QLineEdit,
                               QFileDialog, QDialog, QLabel, QPushButton,
                               QCheckBox, QFrame, QSpinBox, QGroupBox,
                               QGraphicsDropShadowEffect, QScrollArea, QSizePolicy, QStylePainter,
                               QStyleOptionToolButton, QStyle)

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
UI_FONT = "Segoe UI" if IS_WIN else "Helvetica Neue" if IS_MAC else "Sans Serif"
MOD = "⌘" if IS_MAC else "Ctrl+"     # Qt maps Command to Ctrl on macOS
APP_NAME = "CaptionShot"
APP_VERSION = "1.1.4"
ACCENT = "#007AFF"            # Apple system blue (light); dark uses #0A84FF via theme()
SWATCHES = ["#e53935", "#fb8c00", "#fdd835", "#43a047", "#1e88e5", "#ffffff"]
MIN_W, MAX_W = 1, 20      # tool size range (Ctrl + scroll)

# ---------------------------------------------------------------- settings
TOOL_KINDS = ("pen", "line", "arrow", "rect", "oval", "marker", "text")
DEFAULTS = {"vk": 0x2C, "mods": 0, "key_name": "Print Screen",
            "color": "#e53935", "stamp": True,
            "sizes": {"pen": 3, "line": 3, "arrow": 3, "rect": 3, "oval": 3, "marker": 3, "text": 5},
            "caption_px": 20, "caption_autofit": True,
            "save_dir": os.path.join(os.path.expanduser("~"), "Pictures", "CaptionShot")}
if IS_MAC:
    # No Print Screen key on a Mac. Cmd+Shift+2 is free (system uses 3, 4, 5, 6).
    DEFAULTS.update(vk=0x13, mods=0x0100 | 0x0200, key_name="⌘⇧2")


def settings_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "settings.json")


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(settings_path(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            s.update(data)
    except (OSError, ValueError):
        pass
    sizes = dict(DEFAULTS["sizes"])
    if isinstance(s.get("sizes"), dict):
        for k, v in s["sizes"].items():
            if k in sizes:
                try:
                    sizes[k] = max(MIN_W, min(MAX_W, int(v)))
                except (TypeError, ValueError):
                    pass
    s["sizes"] = sizes
    s.pop("width", None)                    # v4 single width replaced by per-tool sizes
    s.pop("bulk_mode", None)                # v16 saved Bulk; it is now per set and always starts off
    try:
        s["caption_px"] = max(12, min(64, int(s.get("caption_px", 20))))
    except (TypeError, ValueError):
        s["caption_px"] = 20
    if not isinstance(s.get("save_dir"), str) or not s["save_dir"]:
        s["save_dir"] = DEFAULTS["save_dir"]
    if not QColor(str(s.get("color"))).isValid():
        s["color"] = DEFAULTS["color"]
    return s


def save_settings(s):
    try:
        with open(settings_path(), "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except OSError:
        pass  # settings are a convenience; never crash the capture flow


# ---------------------------------------------------------------- Windows helpers
WM_HOTKEY, WM_QUIT, MOD_NOREPEAT = 0x0312, 0x0012, 0x4000
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8
ASFW_ANY = 0xFFFFFFFF
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
PRTSC_KEY = r"Control Panel\Keyboard"

if IS_WIN:
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Explicit 64-bit-safe signatures (default ctypes int truncates handles).
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE


def foreground_title():
    if not IS_WIN:
        return ""
    h = user32.GetForegroundWindow()
    if not h:
        return ""
    n = user32.GetWindowTextLengthW(h)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(h, buf, n + 1)
    return buf.value


def force_foreground(hwnd):
    """Give our overlay keyboard focus even when another app owns the foreground."""
    if not IS_WIN:
        return
    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    me = kernel32.GetCurrentThreadId()
    attached = bool(fg_tid and fg_tid != me and user32.AttachThreadInput(fg_tid, me, True))
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    if attached:
        user32.AttachThreadInput(fg_tid, me, False)


def prtsc_owned_by_snipping():
    """True when Windows sends Print Screen to Snipping Tool (default on Win 11)."""
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PRTSC_KEY) as k:
            v, _ = winreg.QueryValueEx(k, "PrintScreenKeyForSnippingEnabled")
            return v != 0
    except OSError:
        return True  # value missing = Windows default = on


def free_prtsc():
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PRTSC_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "PrintScreenKeyForSnippingEnabled", 0, winreg.REG_DWORD, 0)


def launch_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = sys.executable
    w = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return f'"{w if os.path.exists(w) else exe}" "{os.path.abspath(__file__)}"'


MAC_AGENT = os.path.expanduser("~/Library/LaunchAgents/com.captionshot.agent.plist")


def autostart_enabled():
    if IS_MAC:
        return os.path.exists(MAC_AGENT)
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(on):
    if IS_MAC:
        if on:
            os.makedirs(os.path.dirname(MAC_AGENT), exist_ok=True)
            with open(MAC_AGENT, "wb") as f:
                # A packaged .app runs by itself; __file__ only means something when run from source.
                args = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, os.path.abspath(__file__)]
                plistlib.dump({"Label": "com.captionshot.agent", "RunAtLoad": True,
                               "ProgramArguments": args}, f)
        elif os.path.exists(MAC_AGENT):
            os.remove(MAC_AGENT)
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except OSError:
                pass


class HotkeyListener(QObject):
    """Global hotkey through Win32 RegisterHotKey on its own message-loop thread."""
    triggered = Signal()
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self._thread, self._tid = None, None

    def start(self, vk, mods, name):
        self.stop()
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(vk, mods, name, ready), daemon=True)
        self._thread.start()
        ready.wait(2)

    def _run(self, vk, mods, name, ready):
        self._tid = kernel32.GetCurrentThreadId()
        ok = user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk)
        ready.set()
        if not ok:
            self.failed.emit(f"Could not use '{name}' as hotkey. Another app may own it. "
                             "Pick another key in Settings.")
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                user32.AllowSetForegroundWindow(ASFW_ANY)  # this thread got the input
                self.triggered.emit()
        user32.UnregisterHotKey(None, 1)

    def stop(self):
        if self._thread and self._thread.is_alive() and self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(1)
        self._thread, self._tid = None, None



# ---------------------------------------------------------------- macOS helpers (Tahoe 26)
if IS_MAC:
    _objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")
    ctypes.cdll.LoadLibrary("/System/Library/Frameworks/AppKit.framework/AppKit")
    _cg = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    _carbon = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Carbon.framework/Carbon")
    _objc.objc_getClass.restype = ctypes.c_void_p
    _objc.objc_getClass.argtypes = [ctypes.c_char_p]
    _objc.sel_registerName.restype = ctypes.c_void_p
    _objc.sel_registerName.argtypes = [ctypes.c_char_p]
    _cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
    _cg.CGRequestScreenCaptureAccess.restype = ctypes.c_bool


def _msg(obj, sel, restype=ctypes.c_void_p, argtypes=(), *args):
    """Typed objc_msgSend (a typed cast is required on Apple silicon)."""
    if not obj:
        return None
    f = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)(
        ctypes.cast(_objc.objc_msgSend, ctypes.c_void_p).value)
    return f(obj, _objc.sel_registerName(sel.encode()), *args)


def _cls(name):
    return _objc.objc_getClass(name.encode())


def mac_hide_dock_icon():
    app = _msg(_cls("NSApplication"), "sharedApplication")
    _msg(app, "setActivationPolicy:", ctypes.c_bool, (ctypes.c_long,), 1)   # accessory: menu bar only


def mac_activate():
    app = _msg(_cls("NSApplication"), "sharedApplication")
    _msg(app, "activateIgnoringOtherApps:", None, (ctypes.c_bool,), True)


def mac_float_above_all(widget):
    """Put the overlay above the menu bar and Dock, on every Space and over full-screen apps."""
    view = int(widget.winId())
    win = _msg(view, "window")
    # NSStatusWindowLevel (25): above menu bar (24) and Dock (20), below pop-up menus (101)
    _msg(win, "setLevel:", None, (ctypes.c_long,), 25)
    _msg(win, "setCollectionBehavior:", None, (ctypes.c_ulong,), 1 | 256)  # all Spaces + full-screen aux


def mac_frontmost_app():
    try:
        ws = _msg(_cls("NSWorkspace"), "sharedWorkspace")
        app = _msg(ws, "frontmostApplication")
        name = _msg(app, "localizedName")
        raw = _msg(name, "UTF8String", ctypes.c_char_p)
        return raw.decode("utf-8", "replace") if raw else ""
    except Exception:
        return ""


def mac_can_capture():
    if _cg.CGPreflightScreenCaptureAccess():
        return True
    _cg.CGRequestScreenCaptureAccess()      # shows the system prompt once
    return False


def mac_grab(screen):
    """Capture one display with the built-in screencapture tool (handles Retina scaling)."""
    g = screen.geometry()
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        subprocess.run(["/usr/sbin/screencapture", "-x", "-t", "png",
                        f"-R{g.x()},{g.y()},{g.width()},{g.height()}", path],
                       check=False, timeout=15)
        pm = QPixmap(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if not pm.isNull():
        pm.setDevicePixelRatio(pm.width() / max(1, g.width()))
    return pm


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


def _fourcc(code):
    return int.from_bytes(code.encode("ascii"), "big")


class MacHotkeyListener(QObject):
    """Global hotkey through Carbon RegisterEventHotKey: no Accessibility permission needed."""
    triggered = Signal()
    failed = Signal(str)
    _HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

    def __init__(self):
        super().__init__()
        c = _carbon
        c.GetApplicationEventTarget.restype = ctypes.c_void_p
        c.InstallEventHandler.argtypes = [ctypes.c_void_p, self._HANDLER, ctypes.c_ulong,
                                          ctypes.POINTER(_EventTypeSpec), ctypes.c_void_p,
                                          ctypes.POINTER(ctypes.c_void_p)]
        c.InstallEventHandler.restype = ctypes.c_int32
        c.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID,
                                          ctypes.c_void_p, ctypes.c_uint32,
                                          ctypes.POINTER(ctypes.c_void_p)]
        c.RegisterEventHotKey.restype = ctypes.c_int32
        c.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        self._cb = self._HANDLER(self._on_hotkey)          # keep a reference: no GC
        self._spec = _EventTypeSpec(_fourcc("keyb"), 5)      # kEventHotKeyPressed
        self._handler_ref = ctypes.c_void_p()
        c.InstallEventHandler(c.GetApplicationEventTarget(), self._cb, 1,
                              ctypes.byref(self._spec), None, ctypes.byref(self._handler_ref))
        self._hk = None

    def _on_hotkey(self, _call, _event, _data):
        QTimer.singleShot(0, self.triggered.emit)
        return 0

    def start(self, vk, mods, name):
        self.stop()
        ref = ctypes.c_void_p()
        st = _carbon.RegisterEventHotKey(vk, mods, _EventHotKeyID(_fourcc("CSht"), 1),
                                         _carbon.GetApplicationEventTarget(), 0, ctypes.byref(ref))
        if st != 0:
            self.failed.emit(f"Could not use '{name}' as hotkey (error {st}). "
                             "Pick a combination with ⌘ or ⌃ in Settings.")
        else:
            self._hk = ref

    def stop(self):
        if self._hk:
            _carbon.UnregisterEventHotKey(self._hk)
            self._hk = None


# ---------------------------------------------------------------- file names
STOPWORDS = set("""a an the and or but if of to in on at by for with from as is are was were be been
being it its this that these those i me my we our you your he she they them his her their there here
then than so not no yes do does did done have has had will would can could should may might must just
also very into out up down over under again about after before while when where why how what which who
whom all any each few more most other some such only own same too don now ok okay please pls via per am
pm get got let lets see shown shows show screenshot image pic photo
है हैं था थी थे हो हुआ हुई हुए गया गई गए रहा रही रहे का की के को में से पर ने भी तो ही और या कि
यह वह ये वे इस उस एक लिए नहीं जो अब तक साथ बाद पहले कर करें किया दिया""".split())


def _words(text):
    """Split into words; vowel signs (matras) and virama count as part of a word."""
    import unicodedata
    out, cur = [], []
    for ch in text.lower():
        if ch.isalnum() or unicodedata.category(ch).startswith("M") or ch in "\u200c\u200d":
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def caption_keywords(text, n=3):
    """Pick n memorable words: most frequent, then longest, kept in reading order."""
    words = [w for w in _words(text)
             if w not in STOPWORDS and not w.isdigit() and len(w) > 1]
    if not words:
        return []
    freq, first = Counter(words), {}
    for i, w in enumerate(words):
        first.setdefault(w, i)
    top = sorted(freq, key=lambda w: (-freq[w], -len(w), first[w]))[:n]
    return [w[:20] for w in sorted(top, key=first.get)]


def next_save_path(folder, caption):
    """0007_booking-submitted-confirmation.CS.png - number = highest in folder + 1."""
    os.makedirs(folder, exist_ok=True)
    nums = []
    for f in os.listdir(folder):
        m = re.match(r"^(\d+)(?:_.*)?\.CS\.png$", f, re.IGNORECASE)
        if m:
            nums.append(int(m.group(1)))
    n = max(nums, default=0) + 1
    kw = "-".join(caption_keywords(caption))
    while True:
        name = f"{n:04d}_{kw}.CS.png" if kw else f"{n:04d}.CS.png"
        path = os.path.join(folder, name)
        if not os.path.exists(path):
            return path
        n += 1


def bulk_on(ctl):
    """Bulk = collecting several shots. Starts off; ends when the set is copied or discarded."""
    return bool(getattr(ctl, "bulk", False))


def caption_px(settings, sel_width):
    """Caption font size. Auto-fit grows it with wide shots so it stays readable on phones."""
    base = int(settings["caption_px"])
    return max(base, round(sel_width / 30)) if settings.get("caption_autofit", True) else base


# ---------------------------------------------------------------- icons (vector, no font needed)
def make_icon(name, color="#ececf1", size=48, width=3):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 24, size / 24)
    c = QColor(color)
    p.setPen(QPen(c, 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    if name == "move":
        path = QPainterPath(QPointF(6, 4))
        for x, y in ((18, 12), (12.5, 13.3), (9.8, 19)):
            path.lineTo(x, y)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "pen":
        path = QPainterPath(QPointF(4, 17))
        path.cubicTo(7, 8, 10, 20, 13, 12)
        path.cubicTo(15, 6, 18, 13, 20, 8)
        p.drawPath(path)
    elif name == "line":
        p.drawLine(QPointF(5, 19), QPointF(19, 5))
    elif name == "arrow":
        p.drawLine(QPointF(5, 19), QPointF(18, 6))
        p.drawPolyline(QPolygonF([QPointF(11, 6), QPointF(18, 6), QPointF(18, 13)]))
    elif name == "rect":
        p.drawRoundedRect(QRectF(4, 6, 16, 12), 2, 2)
    elif name == "oval":
        p.drawEllipse(QRectF(4, 6, 16, 12))
    elif name == "marker":
        m = QColor(c)
        m.setAlpha(150)
        p.setPen(QPen(m, 5, Qt.SolidLine, Qt.FlatCap))
        p.drawLine(QPointF(5, 16), QPointF(19, 8))
    elif name == "text":
        f = QFont(UI_FONT)
        f.setPixelSize(17)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 0, 24, 24), Qt.AlignCenter, "T")
    elif name == "pause":
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(7, 5.5, 3.6, 13), 1.4, 1.4)
        p.drawRoundedRect(QRectF(13.4, 5.5, 3.6, 13), 1.4, 1.4)
    elif name == "play":
        p.setPen(QPen(c, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(c)
        p.drawPolygon(QPolygonF([QPointF(8.5, 5.5), QPointF(18.5, 12), QPointF(8.5, 18.5)]))
    elif name == "hindi":
        p.setFont(_font(17, bold=True))
        p.drawText(QRectF(0, -1, 24, 24), Qt.AlignCenter, "अ")
    elif name == "undo":
        path = QPainterPath(QPointF(7, 9))
        path.lineTo(14.5, 9)
        path.cubicTo(20, 9, 20, 18.5, 14.5, 18.5)
        path.lineTo(9, 18.5)
        p.drawPath(path)
        p.drawPolyline(QPolygonF([QPointF(10.5, 5.5), QPointF(7, 9), QPointF(10.5, 12.5)]))
    elif name == "copy":
        p.drawRoundedRect(QRectF(8.5, 8.5, 11, 11.5), 2, 2)
        p.drawPolyline(QPolygonF([QPointF(5, 15.5), QPointF(5, 6), QPointF(6, 5), QPointF(15.5, 5)]))
    elif name == "save":
        p.drawLine(QPointF(12, 4), QPointF(12, 15))
        p.drawPolyline(QPolygonF([QPointF(7.5, 10.5), QPointF(12, 15), QPointF(16.5, 10.5)]))
        p.drawPolyline(QPolygonF([QPointF(5, 15), QPointF(5, 19), QPointF(19, 19), QPointF(19, 15)]))
    elif name == "close":
        p.drawLine(QPointF(7, 7), QPointF(17, 17))
        p.drawLine(QPointF(17, 7), QPointF(7, 17))
    elif name == "plus":
        p.drawLine(QPointF(12, 6), QPointF(12, 18))
        p.drawLine(QPointF(6, 12), QPointF(18, 12))
    elif name == "up":
        p.drawPolyline(QPolygonF([QPointF(7, 14.5), QPointF(12, 9.5), QPointF(17, 14.5)]))
    elif name == "down":
        p.drawPolyline(QPolygonF([QPointF(7, 9.5), QPointF(12, 14.5), QPointF(17, 9.5)]))
    elif name == "edit":
        p.drawPolygon(QPolygonF([QPointF(5, 19), QPointF(6, 15), QPointF(15.5, 5.5), QPointF(18.5, 8.5),
                                 QPointF(9, 18)]))
        p.drawLine(QPointF(13.5, 7.5), QPointF(16.5, 10.5))
    elif name == "trash":
        p.drawLine(QPointF(5, 7), QPointF(19, 7))
        p.drawPolyline(QPolygonF([QPointF(9.5, 7), QPointF(9.5, 4.8), QPointF(14.5, 4.8), QPointF(14.5, 7)]))
        p.drawPolyline(QPolygonF([QPointF(6.8, 7), QPointF(7.8, 19.2), QPointF(16.2, 19.2), QPointF(17.2, 7)]))
    elif name == "stack":
        p.drawRoundedRect(QRectF(6, 4, 12, 7), 1.5, 1.5)
        p.drawRoundedRect(QRectF(6, 13, 12, 7), 1.5, 1.5)
    elif name == "grid":
        for x, y in ((4.5, 4.5), (13, 4.5), (4.5, 13), (13, 13)):
            p.drawRoundedRect(QRectF(x, y, 6.5, 6.5), 1.5, 1.5)
    elif name == "chat":                          # speech bubble with text lines
        path = QPainterPath()
        path.addRoundedRect(QRectF(3.5, 4.5, 17, 12.5), 4, 4)
        tail = QPainterPath(QPointF(8, 16.5))
        tail.lineTo(6.5, 20.5)
        tail.lineTo(12, 16.8)
        p.drawPath(path.united(tail).simplified())
        p.drawLine(QPointF(7.5, 9.2), QPointF(16.5, 9.2))
        p.drawLine(QPointF(7.5, 12.6), QPointF(13.5, 12.6))
    elif name == "width":
        p.setPen(QPen(c, max(1.0, width * 0.9), Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(5, 12), QPointF(19, 12))
    p.end()
    return QIcon(pm)


_CHEVRON = None


def _asset(name):
    return os.path.join(QDir.tempPath(), name).replace("\\", "/")


def chevron_png(color="#ececf1", up=False):
    """Small chevron (down, or up) for dropdowns and steppers (stylesheets need an image file)."""
    path = _asset(f"captionshot_chevron_{'up_' if up else ''}{QColor(color).name()[1:]}.png")
    if os.path.exists(path):
        return path
    pm = QPixmap(20, 20)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    pts = [QPointF(4, 7.5), QPointF(10, 13.5), QPointF(16, 7.5)]
    if up:
        pts = [QPointF(x.x(), 20 - x.y()) for x in pts]
    p.drawPolyline(QPolygonF(pts))
    p.end()
    pm.save(path, "PNG")
    return path


def switch_png(on, t):
    """Apple-style switch drawn at 2x for the Settings window (QSS needs image files)."""
    path = _asset(f"captionshot_switch_{'on' if on else 'off'}_{'d' if t['dark'] else 'l'}.png")
    if os.path.exists(path):
        return path
    W, H = 76, 44
    pm = QPixmap(W, H)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#34C759") if on else (QColor(120, 120, 128, 92) if t["dark"] else QColor(120, 120, 128, 40)))
    p.drawRoundedRect(QRectF(2, 2, W - 4, H - 4), (H - 4) / 2, (H - 4) / 2)
    p.setBrush(QColor(0, 0, 0, 40))
    cx = W - H / 2 if on else H / 2
    p.drawEllipse(QPointF(cx, H / 2 + 1), H / 2 - 5, H / 2 - 5)
    p.setBrush(QColor("#ffffff"))
    p.drawEllipse(QPointF(cx, H / 2), H / 2 - 6, H / 2 - 6)
    p.end()
    pm.save(path, "PNG")
    return path


# ---------------------------------------------------------------- drawing model
def text_font(width):
    return _font(12 + width * 3, bold=True)


# ---------------------------------------------------------------- curved arrows
# The arrow follows the path of the mouse. Hand wobble is removed by fitting Bezier curves to the
# path (Schneider, "An Algorithm for Automatically Fitting Digitized Curves", Graphics Gems, 1990).
# A nearly straight drag gives a perfectly straight arrow.
def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _path_len(pts):
    return sum(_dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def _unit(x, y):
    n = math.hypot(x, y)
    return (x / n, y / n) if n > 1e-9 else (0.0, 0.0)


def _resample(pts, step):
    """Evenly spaced points along the path, keeping its exact start and end."""
    out, gap = [pts[0]], 0.0
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        seg = _dist(a, b)
        while seg > 0 and gap + seg >= step:
            f = (step - gap) / seg
            a = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
            out.append(a)
            seg = _dist(a, b)
            gap = 0.0
        gap += seg
    if _dist(out[-1], pts[-1]) < step / 2 and len(out) > 1:
        out.pop()
    out.append(pts[-1])
    return out


def _bez_at(c, t):
    s = 1 - t
    b0, b1, b2, b3 = s * s * s, 3 * s * s * t, 3 * s * t * t, t * t * t
    return (b0 * c[0][0] + b1 * c[1][0] + b2 * c[2][0] + b3 * c[3][0],
            b0 * c[0][1] + b1 * c[1][1] + b2 * c[2][1] + b3 * c[3][1])


def _bez_solve(pts, u, t1, t2):
    """Least-squares control points for fixed ends and fixed end directions."""
    p0, p3 = pts[0], pts[-1]
    c00 = c01 = c11 = x0 = x1 = 0.0
    for p, t in zip(pts, u):
        s = 1 - t
        b0, b1, b2, b3 = s * s * s, 3 * s * s * t, 3 * s * t * t, t * t * t
        a1, a2 = (t1[0] * b1, t1[1] * b1), (t2[0] * b2, t2[1] * b2)
        c00 += a1[0] * a1[0] + a1[1] * a1[1]
        c01 += a1[0] * a2[0] + a1[1] * a2[1]
        c11 += a2[0] * a2[0] + a2[1] * a2[1]
        rx = p[0] - p0[0] * (b0 + b1) - p3[0] * (b2 + b3)
        ry = p[1] - p0[1] * (b0 + b1) - p3[1] * (b2 + b3)
        x0 += a1[0] * rx + a1[1] * ry
        x1 += a2[0] * rx + a2[1] * ry
    det = c00 * c11 - c01 * c01
    al = (x0 * c11 - x1 * c01) / det if abs(det) > 1e-9 else 0.0
    ar = (c00 * x1 - c01 * x0) / det if abs(det) > 1e-9 else 0.0
    span = _path_len(pts)
    if not (1e-3 * span < al < span and 1e-3 * span < ar < span):   # would overshoot: use a safe length
        al = ar = span / 3
    return (p0, (p0[0] + t1[0] * al, p0[1] + t1[1] * al), (p3[0] + t2[0] * ar, p3[1] + t2[1] * ar), p3)


def _bez_refine(c, pts, u):
    """One Newton step: for each point, move t towards the nearest place on the curve."""
    d1 = [(3 * (c[i + 1][0] - c[i][0]), 3 * (c[i + 1][1] - c[i][1])) for i in range(3)]
    d2 = [(2 * (d1[i + 1][0] - d1[i][0]), 2 * (d1[i + 1][1] - d1[i][1])) for i in range(2)]
    out = []
    for p, t in zip(pts, u):
        s = 1 - t
        q = _bez_at(c, t)
        q1 = (s * s * d1[0][0] + 2 * s * t * d1[1][0] + t * t * d1[2][0],
              s * s * d1[0][1] + 2 * s * t * d1[1][1] + t * t * d1[2][1])
        q2 = (s * d2[0][0] + t * d2[1][0], s * d2[0][1] + t * d2[1][1])
        ex, ey = q[0] - p[0], q[1] - p[1]
        den = q1[0] * q1[0] + q1[1] * q1[1] + ex * q2[0] + ey * q2[1]
        out.append(min(1.0, max(0.0, t - (ex * q1[0] + ey * q1[1]) / den)) if abs(den) > 1e-9 else t)
    return out


def _bez_fit(pts, t1, t2, tol, depth=0):
    """Cubic Bezier segments within tol of pts. t1 and t2 point into the curve at each end."""
    if len(pts) < 3:
        span = _path_len(pts) / 3
        return [(pts[0], (pts[0][0] + t1[0] * span, pts[0][1] + t1[1] * span),
                 (pts[-1][0] + t2[0] * span, pts[-1][1] + t2[1] * span), pts[-1])]
    total = _path_len(pts) or 1.0
    u, run = [0.0], 0.0
    for i in range(len(pts) - 1):
        run += _dist(pts[i], pts[i + 1])
        u.append(run / total)
    best, split = None, len(pts) // 2
    for _ in range(5):
        c = _bez_solve(pts, u, t1, t2)
        errs = [_dist(_bez_at(c, t), p) for p, t in zip(pts, u)]
        err = max(errs)
        if best is None or err < best[0]:
            best, split = (err, c), errs.index(err)
        if err <= tol:
            return [c]
        u = _bez_refine(c, pts, u)
    if depth >= 5:
        return [best[1]]
    k = max(1, min(split, len(pts) - 1 - split, 4))
    split = max(1, min(split, len(pts) - 2))
    k = min(k, split, len(pts) - 1 - split)
    tc = _unit(pts[split - k][0] - pts[split + k][0], pts[split - k][1] - pts[split + k][1])
    return (_bez_fit(pts[:split + 1], t1, tc, tol, depth + 1)
            + _bez_fit(pts[split:], (-tc[0], -tc[1]), t2, tol, depth + 1))


def _meant_straight(even):
    """True when an evenly spaced mouse path is a straight drag with some hand wobble in it."""
    a, b = even[0], even[-1]
    chord = _dist(a, b)
    if chord < 1:
        return False
    ux, uy = _unit(b[0] - a[0], b[1] - a[1])
    slack = max(10.0, chord * 0.07)                     # how far a straight drag can drift by accident
    off = [(q[0] - a[0], q[1] - a[1]) for q in even]
    if any(not -slack <= x * ux + y * uy <= chord + slack for x, y in off):
        return False                                    # ran past an end: it goes somewhere else first
    side = [x * uy - y * ux for x, y in off]
    # Average out tremor, and skip the ends, where the hand settles and slips on release.
    w = max(1, len(side) // 24)
    calm = [sum(side[max(0, i - w):i + w + 1]) / len(side[max(0, i - w):i + w + 1]) for i in range(len(side))]
    skip = len(calm) // 20
    calm = calm[skip:len(calm) - skip] or calm
    peak = max(abs(v) for v in calm)
    if peak <= slack:
        return True
    # A larger wobble still counts when it keeps crossing the line instead of bending one way.
    big = [v for v in calm if abs(v) > 2]
    crossings = sum(1 for i in range(len(big) - 1) if big[i] * big[i + 1] < 0)
    return crossings >= 3 and peak <= slack * 1.25


def arrow_polyline(raw):
    """The drawn line for a mouse path: two points when straight, else closely spaced points on a curve."""
    pts = [raw[0]]
    for q in raw[1:]:
        if q != pts[-1]:
            pts.append(q)
    if len(pts) < 3:
        return [pts[0], pts[-1]]
    a, b = pts[0], pts[-1]
    total = _path_len(pts)
    even = _resample(pts, max(2.0, total / 80))
    if _meant_straight(even):
        return [a, b]
    k = max(1, min(len(even) - 1, round(min(total * 0.12, 40.0) / (_path_len(even) / (len(even) - 1) or 1.0))))
    t1 = _unit(even[k][0] - a[0], even[k][1] - a[1])
    t2 = _unit(even[-1 - k][0] - b[0], even[-1 - k][1] - b[1])
    out = [a]
    for c in _bez_fit(even, t1, t2, min(14.0, max(5.0, total * 0.025))):
        n = max(8, math.ceil(_path_len(c) / 1.5))
        out.extend(_bez_at(c, i / n) for i in range(1, n + 1))
    return out


def _trim_end(pts, d):
    """The polyline with length d removed from its end."""
    for i in range(len(pts) - 1, 0, -1):
        seg = _dist(pts[i], pts[i - 1])
        if seg > d:
            f = d / seg
            return pts[:i] + [(pts[i][0] + (pts[i - 1][0] - pts[i][0]) * f,
                               pts[i][1] + (pts[i - 1][1] - pts[i][1]) * f)]
        d -= seg
    return pts[:1]


class Shape:
    def __init__(self, kind, color, width, pt):
        self.kind, self.color, self.width = kind, QColor(color), width
        self.pts = [QPointF(pt)]
        self.text = ""
        self._arrow_cache = (None, None)

    def add(self, pt):
        if self.kind in ("pen", "marker") or len(self.pts) == 1:
            self.pts.append(QPointF(pt))
        elif self.kind == "arrow":                # keep the mouse's path; the tip is always the pointer
            last = self.pts[-1]
            if len(self.pts) > 2 and math.hypot(pt.x() - last.x(), pt.y() - last.y()) < 2:
                self.pts[-1] = QPointF(pt)
            else:
                self.pts.append(QPointF(pt))
        else:
            self.pts[-1] = QPointF(pt)

    def arrow_line(self):
        """Fitted line for an arrow, refitted only when its points have changed."""
        key = [(q.x(), q.y()) for q in self.pts]
        if self._arrow_cache[0] != key:
            self._arrow_cache = (key, arrow_polyline(key))
        return self._arrow_cache[1]

    def copy(self):
        c = Shape(self.kind, self.color, self.width, self.pts[0])
        c.pts = [QPointF(q) for q in self.pts]
        c.text = self.text
        return c

    def translate(self, d):
        self.pts = [q + QPointF(d) for q in self.pts]

    def outline(self):
        """Path along what is drawn (for hit-testing and the selection box)."""
        a, b = self.pts[0], self.pts[-1]
        path = QPainterPath(a)
        if self.kind == "text":
            fm = QFontMetrics(text_font(self.width))
            r = QRectF(fm.boundingRect(QRect(0, 0, 4000, 4000), Qt.AlignLeft | Qt.AlignTop, self.text))
            path = QPainterPath()
            path.addRect(r.translated(a))
        elif self.kind in ("pen", "marker"):
            for q in self.pts[1:]:
                path.lineTo(q)
        elif self.kind == "line":
            path.lineTo(b)
        elif self.kind == "arrow":
            for x, y in self.arrow_line()[1:]:
                path.lineTo(x, y)
        elif self.kind == "rect":
            path = QPainterPath()
            path.addRect(QRectF(a, b).normalized())
        elif self.kind == "oval":
            path = QPainterPath()
            path.addEllipse(QRectF(a, b).normalized())
        return path

    def hit(self, pt, slop=6):
        path = self.outline()
        if self.kind == "text":
            return path.boundingRect().adjusted(-slop, -slop, slop, slop).contains(QPointF(pt))
        st = QPainterPathStroker()
        st.setWidth((self.width * 5 if self.kind == "marker" else self.width) + 2 * slop)
        st.setCapStyle(Qt.RoundCap)
        st.setJoinStyle(Qt.RoundJoin)
        return st.createStroke(path).contains(QPointF(pt))

    def bounds(self):
        w = (self.width * 5 if self.kind == "marker" else self.width) / 2 + (12 if self.kind == "arrow" else 2)
        return self.outline().boundingRect().adjusted(-w, -w, w, w)

    def valid(self):
        if self.kind == "text":
            return bool(self.text.strip())
        if self.kind in ("pen", "marker"):
            return True
        if self.kind == "arrow":                  # a curve may end back where it started
            return _path_len(self.arrow_line()) > 3
        a, b = self.pts[0], self.pts[-1]
        return abs(a.x() - b.x()) + abs(a.y() - b.y()) > 3

    def paint(self, p):
        a, b = self.pts[0], self.pts[-1]
        if self.kind == "text":
            p.setFont(text_font(self.width))
            p.setPen(self.color)
            p.drawText(QRectF(a, QSizeF(4000, 4000)), Qt.AlignLeft | Qt.AlignTop, self.text)
            return
        color, w = QColor(self.color), self.width
        if self.kind == "marker":
            color.setAlpha(90)
            w = self.width * 5
        p.setPen(QPen(color, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        if self.kind in ("pen", "marker"):
            path = QPainterPath(a)
            for q in self.pts[1:]:
                path.lineTo(q)
            if len(self.pts) == 1:
                path.lineTo(a + QPointF(0.1, 0.1))
            p.drawPath(path)
        elif self.kind == "line":
            p.drawLine(a, b)
        elif self.kind == "arrow":
            line = self.arrow_line()
            size = 10 + self.width * 2
            # The head points along the last stretch of the curve, so a flick on release can't twist it.
            base = _trim_end(line, size)[-1]
            ang = math.atan2(b.y() - base[1], b.x() - base[0])
            shaft = _trim_end(line, size * 0.6)
            path = QPainterPath(a)
            for x, y in shaft[1:]:
                path.lineTo(x, y)
            p.drawPath(path)
            p1 =QPointF(b.x() - size * math.cos(ang - 0.45), b.y() - size * math.sin(ang - 0.45))
            p2 = QPointF(b.x() - size * math.cos(ang + 0.45), b.y() - size * math.sin(ang + 0.45))
            p.setPen(QPen(self.color, 1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(self.color)
            p.drawPolygon(QPolygonF([b, p1, p2]))
        elif self.kind == "rect":
            p.drawRect(QRectF(a, b).normalized())
        elif self.kind == "oval":
            p.drawEllipse(QRectF(a, b).normalized())


# ---------------------------------------------------------------- caption composite
CAP_BG, CAP_FG = QColor("#ffffff"), QColor("#1a1a1a")
STAMP_FG, CAP_LINE = QColor("#5f5e5a"), QColor("#d3d1c7")
CAP_PX, STAMP_PX, PAD = 16, 12, 10


def stamp_px_for(cap_px):
    return max(STAMP_PX, round(cap_px * 0.7))


def pad_for(cap_px):
    return max(PAD, round(cap_px * 0.6))


FONT_FAMILIES = [UI_FONT]          # + "Mukta" once load_fonts() finds it


def load_fonts():
    """Register the bundled Mukta font so Hindi always renders in Mukta, on any PC."""
    global UI_FONT
    fams = set(QFontDatabase.families())
    if IS_MAC:                                   # SF Pro, the system UI font
        UI_FONT = QFontDatabase.systemFont(QFontDatabase.GeneralFont).family()
    elif IS_WIN and "Segoe UI Variable Text" in fams:   # Windows 11 system UI font
        UI_FONT = "Segoe UI Variable Text"
    FONT_FAMILIES[0] = UI_FONT
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    folder = os.path.join(base, "fonts")
    found = False
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith((".ttf", ".otf")):
                fid = QFontDatabase.addApplicationFont(os.path.join(folder, name))
                found = found or (fid != -1 and "Mukta" in QFontDatabase.applicationFontFamilies(fid))
    if found and "Mukta" not in FONT_FAMILIES:
        FONT_FAMILIES.append("Mukta")
    return found


def _font(px, bold=False):
    f = QFont()
    f.setFamilies(FONT_FAMILIES)       # Latin from UI font, Devanagari from Mukta
    f.setPixelSize(max(1, round(px)))
    f.setBold(bold)
    return f


def compose(shot, caption, stamp, dpr=1.0, cap_px=CAP_PX):
    """Return shot with a caption bar of the same width appended below it (opaque RGB32)."""
    caption, stamp = caption.strip(), stamp.strip()
    if not caption and not stamp:
        return shot.convertToFormat(QImage.Format_RGB32)
    W = shot.width()
    pad = round(pad_for(cap_px) * dpr)
    tw = max(1, W - 2 * pad)
    f1, f2 = _font(cap_px * dpr), _font(stamp_px_for(cap_px) * dpr)
    opt = QTextOption()
    opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    scratch = QImage(1, 1, QImage.Format_RGB32)
    sp = QPainter(scratch)
    h1 = h2 = 0.0
    if caption:
        sp.setFont(f1)
        h1 = sp.boundingRect(QRectF(0, 0, tw, 1e7), caption, opt).height()
    if stamp:
        sp.setFont(f2)
        h2 = sp.boundingRect(QRectF(0, 0, tw, 1e7), stamp, opt).height()
    sp.end()
    gap = round(4 * dpr) if caption and stamp else 0
    bar = math.ceil(pad + h1 + gap + h2 + pad)
    out = QImage(W, shot.height() + bar, QImage.Format_RGB32)
    out.fill(CAP_BG)
    p = QPainter(out)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.drawImage(0, 0, shot)
    p.setPen(QPen(CAP_LINE, max(1, round(dpr))))
    p.drawLine(0, shot.height(), W, shot.height())
    y = shot.height() + pad
    if caption:
        p.setFont(f1)
        p.setPen(CAP_FG)
        p.drawText(QRectF(pad, y, tw, h1), caption, opt)
        y += h1 + gap
    if stamp:
        p.setFont(f2)
        p.setPen(STAMP_FG)
        p.drawText(QRectF(pad, y, tw, h2), stamp, opt)
    p.end()
    return out



# ---------------------------------------------------------------- Hindi typing (Hinglish -> हिंदी)
# Online: Google Input Tools, the service behind Google Indic typing (unofficial endpoint).
# Offline: rules + common-word list below. Words the user picks are learned and work offline.

_VOWELS = [  # latin, independent, matra   (longest first)
    ("aa", "आ", "ा"), ("ai", "ऐ", "ै"), ("au", "औ", "ौ"), ("ou", "औ", "ौ"),
    ("ee", "ई", "ी"), ("ii", "ई", "ी"), ("oo", "ऊ", "ू"), ("uu", "ऊ", "ू"),
    ("a", "अ", ""), ("i", "इ", "ि"), ("u", "उ", "ु"), ("e", "ए", "े"), ("o", "ओ", "ो"),
]
_CONS = [  # longest first
    ("ksh", "क्ष"), ("chh", "छ"), ("shr", "श्र"), ("gya", "ज्ञ"), ("gy", "ज्ञ"), ("tr", "त्र"),
    ("kh", "ख"), ("gh", "घ"), ("ch", "च"), ("jh", "झ"), ("th", "थ"), ("dh", "ध"), ("ph", "फ"),
    ("cch", "च्छ"), ("cc", "च्छ"), ("bh", "भ"), ("sh", "श"),
    ("k", "क"), ("g", "ग"), ("c", "क"), ("j", "ज"), ("t", "त"), ("d", "द"), ("n", "न"),
    ("p", "प"), ("f", "फ़"), ("b", "ब"), ("m", "म"), ("y", "य"), ("r", "र"), ("l", "ल"),
    ("v", "व"), ("w", "व"), ("s", "स"), ("h", "ह"), ("z", "ज़"), ("q", "क़"), ("x", "क्स"),
]
_VIRAMA = "्"
_TOKEN = re.compile("|".join(re.escape(t) for t, *_ in sorted(_VOWELS + [(c, v) for c, v in _CONS],
                                                             key=lambda x: -len(x[0]))))
_V = {t: (ind, mat) for t, ind, mat in _VOWELS}
_C = dict(_CONS)


COMMON = {  # frequent words the rules can't guess (nasal vowels, nukta, English loans)
    "main": "मैं", "mein": "में", "hain": "हैं", "hoon": "हूँ", "hun": "हूँ", "nahi": "नहीं",
    "nahin": "नहीं", "haan": "हाँ", "han": "हाँ", "kyun": "क्यों", "kyon": "क्यों", "yahan": "यहाँ",
    "wahan": "वहाँ", "kahan": "कहाँ", "unhe": "उन्हें", "inhe": "इन्हें", "hum": "हम", "tum": "तुम",
    "aap": "आप", "ji": "जी", "bada": "बड़ा", "badi": "बड़ी", "bade": "बड़े", "sadak": "सड़क",
    "padh": "पढ़", "padha": "पढ़ा", "ladka": "लड़का", "ladki": "लड़की", "khana": "खाना",
    "kitab": "किताब", "accha": "अच्छा", "achha": "अच्छा", "thik": "ठीक", "theek": "ठीक",
    "order": "ऑर्डर", "payment": "पेमेंट", "office": "ऑफिस", "ticket": "टिकट", "train": "ट्रेन",
    "station": "स्टेशन", "number": "नंबर", "bank": "बैंक", "online": "ऑनलाइन", "phone": "फ़ोन",
    "mobile": "मोबाइल", "email": "ईमेल", "status": "स्टेटस", "done": "डन", "ok": "ओके",
    "dhanyavaad": "धन्यवाद", "dhanyawad": "धन्यवाद", "shukriya": "शुक्रिया", "purana": "पुराना",
}


def to_hindi(word):
    """'mera' -> 'मेरा', 'hindi' -> 'हिंदी', 'namaste' -> 'नमस्ते'. Non-letters pass through."""
    w = word.lower()
    if w in COMMON:
        return COMMON[w]
    toks, i = [], 0
    while i < len(w):
        m = _TOKEN.match(w, i)
        if not m:
            toks.append(("x", w[i]))
            i += 1
            continue
        t = m.group(0)
        toks.append(("v" if t in _V else "c", t))
        i = m.end()
    out = []
    n = len(toks)
    for j, (kind, t) in enumerate(toks):
        prev = toks[j - 1] if j else None
        nxt = toks[j + 1] if j + 1 < n else None
        last = j == n - 1
        if kind == "x":
            out.append(t)
        elif kind == "v":
            ind, mat = _V[t]
            after_cons = prev is not None and prev[0] == "c"
            if not after_cons:
                out.append(ind)
            elif t == "a" and last and n > 2:
                out.append("ा")                       # Hinglish: final 'a' is long (mera, accha)
            elif t == "i" and last:
                out.append("ी")                       # final 'i' is long (hindi, nahi)
            else:
                out.append(mat)
        else:  # consonant
            # n/m before another consonant -> anusvara (hindi -> हिंदी, hum -> हम stays)
            if (t in ("n", "m") and nxt and nxt[0] == "c" and prev and prev[0] == "v"
                    and nxt[1][0] not in "hyrlvw"):
                out.append("ं")
                continue
            out.append(_C[t])
            if nxt and nxt[0] == "c":
                out.append(_VIRAMA)                   # conjunct: namaste -> नमस्ते
    return unicodedata.normalize("NFC", "".join(out))


GOOGLE_XLIT = "https://inputtools.google.com/request"


def learned_path():
    return os.path.join(os.path.dirname(settings_path()), "hindi_words.json")


def load_learned():
    try:
        with open(learned_path(), encoding="utf-8") as f:
            d = json.load(f)
        return {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


class SuggestionPopup(QFrame):
    """Google-Indic-style candidate list under the caret, on glass. Never takes keyboard focus."""

    def __init__(self, parent, on_pick):
        super().__init__(parent)
        t = parent_theme(parent)
        self.t = t
        self._glass = GlassFrame(self, 14, backdrop=lambda: getattr(parent, "_backdrop", None), shadow=False)
        fx = QGraphicsDropShadowEffect(self)
        fx.setBlurRadius(28)
        fx.setOffset(0, 6)
        fx.setColor(t["shadow"])
        self.setGraphicsEffect(fx)
        self.setObjectName("sugg")
        self.setCursor(Qt.ArrowCursor)
        self.setStyleSheet(
            f"QLabel{{color:{t['label2']};padding:2px 10px;background:transparent;}}"
            f"QPushButton{{color:{t['label']};background:transparent;border:none;border-radius:9px;"
            "padding:4px 12px;text-align:left;}"
            f"QPushButton:hover{{background:{t['hover']};}}"
            f"QPushButton[sel=\"true\"]{{background:{t['accent_fill']};color:{t['on_accent']};}}")
        self.on_pick = on_pick
        lay = QVBoxLayout(self)
        lay.setContentsMargins(5, 5, 5, 5)
        lay.setSpacing(1)
        self.head = QLabel()
        self.head.setFont(_font(12))
        lay.addWidget(self.head)
        self.rows = []
        for i in range(5):
            b = QPushButton()
            b.setFocusPolicy(Qt.NoFocus)
            b.setFont(_font(17))
            b.clicked.connect(lambda _=False, j=i: self.on_pick(j))
            lay.addWidget(b)
            self.rows.append(b)
        self.hide()

    def resizeEvent(self, e):
        self._glass.setGeometry(self.rect())
        self._glass.lower()
        super().resizeEvent(e)

    def moveEvent(self, e):
        self._glass.update()
        super().moveEvent(e)

    def show_for(self, word, cands, sel, pos):
        self.head.setText(f"{word}   ·   space = 1   ·   Esc = keep English")
        for i, b in enumerate(self.rows):
            if i < len(cands):
                b.setText(f"{i + 1}   {cands[i]}")
                b.setProperty("sel", i == sel)
                b.style().unpolish(b)
                b.style().polish(b)
                b.show()
            else:
                b.hide()
        self.adjustSize()
        R = self.parentWidget().rect()
        x = max(0, min(pos.x(), R.right() - self.width()))
        y = pos.y() + 4 if pos.y() + 4 + self.height() <= R.bottom() else pos.y() - self.height() - 30
        self.move(x, max(0, y))
        self.show()
        self.raise_()


class HindiTyper(QObject):
    """Type Hinglish in the caption; space/enter/punctuation converts the word to Hindi."""
    COMMIT_TEXT = set(" ,.?!;:)]}\"'-/")

    def __init__(self, overlay, edit):
        super().__init__(overlay)
        self.ov, self.edit = overlay, edit
        self.enabled = False
        self.nam = QNetworkAccessManager(self)
        self.cache, self.pending, self.fixups = {}, {}, []
        self.learned = load_learned()
        self.sel = 0
        self.popup = SuggestionPopup(overlay, self.commit)

    # -- data
    def current_word(self):
        c = self.edit.textCursor()
        if c.hasSelection():
            return None, None
        before = c.block().text()[:c.positionInBlock()]
        m = re.search(r"[A-Za-z]+$", before)
        if not m:
            return None, None
        return m.group(0), c.position() - len(m.group(0))

    def candidates(self, word):
        w = word.lower()
        out = []
        for cand in ([self.learned[w]] if w in self.learned else []) + self.cache.get(w, []):
            if cand not in out:
                out.append(cand)
        if not self.cache.get(w):
            off = to_hindi(w)
            if off not in out:
                out.append(off)
        return out[:5]

    def fetch(self, word):
        w = word.lower()
        if w in self.cache or w in self.pending:
            return
        url = QUrl(GOOGLE_XLIT)
        q = QUrlQuery()
        for k, v in (("text", w), ("itc", "hi-t-i0-und"), ("num", "5"), ("cp", "0"), ("cs", "1"),
                     ("ie", "utf-8"), ("oe", "utf-8")):
            q.addQueryItem(k, v)
        url.setQuery(q)
        req = QNetworkRequest(url)
        req.setTransferTimeout(3000)
        r = self.nam.get(req)
        self.pending[w] = r
        r.finished.connect(lambda r=r, w=w: self._done(w, r))

    def _done(self, w, r):
        self.pending.pop(w, None)
        try:
            if r.error() == QNetworkReply.NoError:
                data = json.loads(bytes(r.readAll()).decode("utf-8"))
                if data[0] == "SUCCESS" and data[1] and data[1][0][1]:
                    self.cache[w] = [unicodedata.normalize("NFC", x) for x in data[1][0][1]]
        except (ValueError, IndexError, TypeError, KeyError):
            pass
        r.deleteLater()
        self._apply_fixups(w)
        word, _ = self.current_word()
        if self.enabled and word and word.lower() == w:
            self.refresh()

    def learn(self, w, choice):
        if self.learned.get(w) == choice:
            return
        self.learned[w] = choice
        try:
            with open(learned_path(), "w", encoding="utf-8") as f:
                json.dump(self.learned, f, ensure_ascii=False, indent=0)
        except OSError:
            pass

    # -- UI
    def set_enabled(self, on):
        self.enabled = on
        if not on:
            self.popup.hide()
        else:
            self.refresh()

    def refresh(self):
        word, _ = self.current_word() if self.enabled else (None, None)
        if not word or not self.ov.isVisible():
            self.popup.hide()
            return
        self.fetch(word)
        cands = self.candidates(word)
        self.sel = max(0, min(self.sel, len(cands) - 1))
        r = self.edit.cursorRect()
        pt = self.edit.viewport().mapTo(self.ov, r.bottomLeft())
        self.popup.show_for(word, cands, self.sel, pt)

    def commit(self, idx=None):
        word, start = self.current_word()
        if not word:
            self.popup.hide()
            return False
        cands = self.candidates(word)
        i = self.sel if idx is None else idx
        choice = cands[min(i, len(cands) - 1)]
        c = self.edit.textCursor()
        c.setPosition(start)
        c.setPosition(start + len(word), QTextCursor.KeepAnchor)
        c.insertText(choice)
        self.edit.setTextCursor(c)
        w = word.lower()
        if i > 0:
            self.learn(w, choice)                 # remember an explicit choice
        elif w in self.pending and w not in self.learned:
            # Offline guess now; Google's answer replaces it on arrival. Track only the start:
            # a selection would stretch when the user types right after the word.
            start_c = QTextCursor(self.edit.document())
            start_c.setPosition(c.position() - len(choice))
            self.fixups.append((w, start_c, choice))
        self.sel = 0
        self.popup.hide()
        return True

    def _apply_fixups(self, w):
        keep = []
        for fw, span, text in self.fixups:
            if fw != w:
                keep.append((fw, span, text))
            elif self.cache.get(w) and self.cache[w][0] != text:
                sel = QTextCursor(span)
                sel.setPosition(span.position() + len(text), QTextCursor.KeepAnchor)
                if sel.selectedText() == text:        # untouched since: safe to replace
                    sel.insertText(self.cache[w][0])
        self.fixups = keep

    def handle_key(self, e):
        """Return True to swallow the key. Called only while Hindi typing is on."""
        if e.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        k, t, shown = e.key(), e.text(), self.popup.isVisible()
        if shown and k == Qt.Key_Escape:
            self.popup.hide()                     # keep the English word as typed
            return True
        if shown and k in (Qt.Key_Up, Qt.Key_Down):
            n = len([b for b in self.popup.rows if not b.isHidden()])
            self.sel = (self.sel + (1 if k == Qt.Key_Down else -1)) % max(1, n)
            self.refresh()
            return True
        if shown and Qt.Key_1 <= k <= Qt.Key_5:
            word, _ = self.current_word()
            if word and k - Qt.Key_1 < len(self.candidates(word)):
                self.commit(k - Qt.Key_1)
                return True
        if k in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab) or (t and t in self.COMMIT_TEXT):
            if self.current_word()[0]:
                self.commit()
            if k == Qt.Key_Tab:
                return True
            return False                          # let the space / punctuation / newline in
        if (t and t.isascii() and t.isalpha()) or k in (Qt.Key_Backspace, Qt.Key_Delete, Qt.Key_Left,
                                                          Qt.Key_Right, Qt.Key_Home, Qt.Key_End):
            if k not in (Qt.Key_Up, Qt.Key_Down):
                self.sel = 0
            QTimer.singleShot(0, self.refresh)
        return False


# ---------------------------------------------------------------- hold bar
class HoldBar(QWidget):
    """Floating bar shown while a capture is on hold. Doesn't steal focus; can be dragged."""

    def __init__(self, ctl, overlay, screen):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.ov = overlay
        self.t = t = dict(theme())
        t["glass"] = QColor(t["glass"].red(), t["glass"].green(), t["glass"].blue(), 238)
        frame = GlassFrame(self, BTN // 2 + GLASS_PAD, shadow=False)
        frame.setObjectName("bar")
        frame.setStyleSheet(bar_css(t, BTN // 2))
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(16, GLASS_PAD, GLASS_PAD, GLASS_PAD)
        lay.setSpacing(2)
        lay.setAlignment(Qt.AlignVCenter)
        dot = QLabel("●")
        dot.setStyleSheet("color:#FF3B30;")
        lay.addWidget(dot, 0, Qt.AlignVCenter)
        lay.addSpacing(8)
        msg = QLabel(f"On hold — copy what you need, then press {ctl.settings['key_name']} or Resume")
        msg.setFont(_font(13))
        msg.setContentsMargins(0, 0, 6, 0)
        lay.addWidget(msg, 0, Qt.AlignVCenter)
        lay.addWidget(divider(False))
        x = QToolButton()
        x.setIcon(tinted_icon("close", t))
        x.setIconSize(QSize(18, 18))
        x.setFixedSize(BTN, BTN)
        x.setToolTip("Discard this capture")
        x.clicked.connect(overlay.close)
        res = text_button("Resume", make_icon("play", t["on_accent"]), "Bring the capture back", t, primary=True)
        res.clicked.connect(overlay.resume)
        lay.addWidget(elevate(res, t))         # primary on the trailing side, lifted...
        lay.addWidget(divider(False))
        lay.addWidget(x)                       # ...close/discard stays last (standard X)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 18)   # room for the soft shadow painted below
        outer.addWidget(frame)
        self.adjustSize()
        g = screen.availableGeometry()
        self.move(g.center().x() - self.width() // 2, g.top() + 16)
        self._drag = None

    def paintEvent(self, _):
        paint_soft_shadow(self, QRectF(self.rect()).adjusted(14, 10, -14, -18), BTN // 2 + GLASS_PAD, self.t)

    def mousePressEvent(self, e):
        self._drag = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def showEvent(self, e):
        super().showEvent(e)
        if IS_MAC:
            QTimer.singleShot(0, lambda: mac_float_above_all(self))


# ---------------------------------------------------------------- toast
class Toast(QWidget):
    """Small self-closing confirmation pill; never takes focus."""

    def __init__(self, text, screen, ms=1600):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.text = text
        self.t = theme()
        f = _font(14)
        f.setWeight(QFont.Medium)
        self.setFont(f)
        fm = QFontMetrics(f)
        tr = fm.boundingRect(QRect(0, 0, 460, 2000), Qt.TextWordWrap, text)   # long messages wrap
        self.text_w, self.text_h = tr.width(), max(tr.height(), fm.height())
        w = self.text_w + 44 + 28
        h = self.text_h + 26 + 28
        g = screen.availableGeometry()
        self.setGeometry(g.center().x() - w // 2, g.bottom() - 90 - h, w, h)
        QTimer.singleShot(ms, self.close)

    def paintEvent(self, _):
        r = QRectF(self.rect()).adjusted(14, 8, -14, -20)
        p = paint_soft_shadow(self, r, min(r.height() / 2, 20), self.t, keep=True)
        p.setPen(QColor(self.t["label"]))
        p.drawText(r.adjusted(22, 0, -22, 0), Qt.AlignCenter | Qt.TextWordWrap, self.text)
        p.end()


def paint_soft_shadow(w, r, radius, t, keep=False):
    """Capsule with a soft shadow, glass tint, highlight and hairline, for top-level windows."""
    p = QPainter(w)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    for i in range(10, 0, -1):                       # layered soft shadow
        a = int(t["shadow"].alpha() * 0.10 * (1 - i / 11))
        p.setBrush(QColor(0, 0, 0, a))
        p.drawRoundedRect(r.adjusted(-i, -i + 5, i, i + 5), radius + i, radius + i)
    g = QColor(t["glass"])
    g.setAlpha(max(g.alpha(), 238))
    p.setBrush(g)
    p.drawRoundedRect(r, radius, radius)
    p.setPen(QPen(t["highlight"], 1))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(r.adjusted(1, 1, -1, -1), radius - 1, radius - 1)
    p.setPen(QPen(t["border"], 1))
    p.drawRoundedRect(r, radius, radius)
    if keep:
        return p
    p.end()



# ---------------------------------------------------------------- Apple-style theme (HIG, Liquid Glass)
# Controls float on a glass layer above the content (the screenshot); one prominent action;
# monochrome symbols; corners concentric with their bar; follows system light/dark and
# Reduce Transparency.
def system_dark():
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def reduce_transparency():
    try:
        if IS_WIN:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "EnableTransparency")[0] == 0
        if IS_MAC:
            ws = _msg(_cls("NSWorkspace"), "sharedWorkspace")
            return bool(_msg(ws, "accessibilityDisplayShouldReduceTransparency", ctypes.c_bool))
    except Exception:
        pass
    return False


def theme():
    dark, solid = system_dark(), reduce_transparency()
    if dark:
        t = dict(dark=True, label="#f5f5f7", label2="#a1a1a6", accent="#0A84FF", on_accent="#ffffff",
                 glass=QColor(36, 36, 40, 255 if solid else 168), border=QColor(255, 255, 255, 38),
                 highlight=QColor(255, 255, 255, 46), hover="rgba(255,255,255,0.10)",
                 selected="rgba(255,255,255,0.16)", sep="rgba(255,255,255,0.22)",
                 menu="#2c2c2e", window="#1c1c1e", card="#2c2c2e", field="#3a3a3c",
                 shadow=QColor(0, 0, 0, 120))
    else:
        t = dict(dark=False, label="#1d1d1f", label2="#6e6e73", accent="#007AFF", on_accent="#ffffff",
                 glass=QColor(250, 250, 252, 255 if solid else 178), border=QColor(0, 0, 0, 26),
                 highlight=QColor(255, 255, 255, 200), hover="rgba(0,0,0,0.06)",
                 selected="rgba(0,0,0,0.09)", sep="rgba(0,0,0,0.16)",
                 menu="#ffffff", window="#f2f2f7", card="#ffffff", field="#ffffff",
                 shadow=QColor(0, 0, 0, 70))
    t["solid"] = solid
    t["accent_fill"] = "#0071E3"      # behind white text: 4.70:1 (WCAG AA); system blue only 4.02/3.65
    return t


def bar_css(t, radius):
    """Buttons are circles/capsules whose radius = bar radius - padding (concentric)."""
    return f"""
QToolButton {{ background: transparent; border: none; border-radius: {radius}px; color: {t['label']};
              font: 13px '{UI_FONT}'; }}
QToolButton:hover {{ background: {t['hover']}; }}
QToolButton:checked {{ background: {t['selected']}; }}
QToolButton#primary {{ color: {t['on_accent']}; font: 600 13px '{UI_FONT}'; padding: 0 14px;
                      border-radius: {radius}px; border: 1px solid {QColor(t['accent_fill']).darker(115).name()};
                      border-top-color: {QColor(t['accent_fill']).lighter(135).name()};
                      background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                          stop:0 {t['accent_fill']}, stop:1 {QColor(t['accent_fill']).darker(112).name()}); }}
QToolButton#primary:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                          stop:0 {t['accent_fill']}, stop:1 {QColor(t['accent_fill']).darker(104).name()}); }}
QToolButton#primary:pressed {{ background: {QColor(t['accent_fill']).darker(110).name()};
                              border-top-color: {QColor(t['accent_fill']).darker(115).name()}; }}
QFrame#sep {{ background: {t['sep']}; border: none; }}
QLabel {{ color: {t['label']}; background: transparent; }}
"""


GLASS_PAD = 6
# Spacing system (px): button 34 high; icon 16 in text buttons, 20 in icon buttons; text buttons pad
# 12 left / 14 right (icon side optically lighter); 2 between buttons in a group; a 1 px divider with
# 6 px on each side between groups. Everything sits on the bar's centre line.
TEXT_PAD_L, TEXT_PAD_R, GROUP_GAP = 14, 14, 6
ICON_TEXT_GAP = 6


class TextButton(QToolButton):
    """Icon + text drawn as ONE centred unit: equal padding both sides and exactly ICON_TEXT_GAP
    between icon and text, on any font or platform (Qt's own layout left-aligns the pair and
    adds uneven trailing space). The style still paints the background, hover and pressed states."""

    def __init__(self, t):
        super().__init__()
        self.t = t

    _INK = {}

    def _icon_ink(self):
        """Icon pixmap trimmed to its visible pixels (optical spacing, not the transparent box)."""
        mode = QIcon.Normal if self.isEnabled() else QIcon.Disabled
        state = QIcon.On if self.isChecked() else QIcon.Off
        pm = self.icon().pixmap(self.iconSize(), self.devicePixelRatioF(), mode, state)
        key = pm.cacheKey()
        if key not in self._INK:
            img = pm.toImage()
            xs = [x for x in range(img.width()) if any(img.pixelColor(x, y).alpha() > 40
                                                        for y in range(img.height()))]
            ys = [y for y in range(img.height()) if any(img.pixelColor(x, y).alpha() > 40
                                                        for x in range(img.width()))]
            r = QRect(xs[0], ys[0], xs[-1] - xs[0] + 1, ys[-1] - ys[0] + 1) if xs and ys else img.rect()
            self._INK[key] = r
        return pm, self._INK[key]

    def sizeHint(self):
        fm = self.fontMetrics()
        icon = 0
        if not self.icon().isNull():
            pm, ink = self._icon_ink()
            icon = ink.width() / pm.devicePixelRatio() + ICON_TEXT_GAP
        return QSize(round(TEXT_PAD_L + icon + fm.horizontalAdvance(self.text()) + TEXT_PAD_R), BTN)

    minimumSizeHint = sizeHint

    def paintEvent(self, _):
        p = QStylePainter(self)
        opt = QStyleOptionToolButton()
        self.initStyleOption(opt)
        opt.text, opt.icon = "", QIcon()
        p.drawComplexControl(QStyle.CC_ToolButton, opt)          # background / hover / pressed only
        fm = self.fontMetrics()
        has_icon = not self.icon().isNull()
        tw = fm.horizontalAdvance(self.text())
        iw = 0
        if has_icon:
            pm, ink = self._icon_ink()
            d = pm.devicePixelRatio()
            iw = ink.width() / d
        x = (self.width() - (iw + (ICON_TEXT_GAP if has_icon else 0) + tw)) / 2
        if has_icon:
            ih = ink.height() / d
            p.drawPixmap(QRectF(x, (self.height() - ih) / 2, iw, ih), pm, QRectF(ink))
            x += iw + ICON_TEXT_GAP
        fg = self.t["on_accent"] if self.objectName() == "primary" else (
            self.t["accent"] if self.isChecked() else self.t["label"])
        p.setPen(QColor(fg))
        p.setFont(self.font())
        p.drawText(QRectF(x, 0, tw + 2, self.height()), Qt.AlignLeft | Qt.AlignVCenter, self.text())


def text_button(text, icon=None, tip="", t=None, primary=False):
    """Text (+ optional icon) button sized to its content, never a fixed width."""
    b = TextButton(t or theme())
    b.setText(text)
    b.setFixedHeight(BTN)
    b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    if icon is not None:
        b.setIcon(icon)
        b.setIconSize(QSize(16, 16))
    if primary:
        b.setObjectName("primary")
    b.setStyleSheet("QToolButton { padding: 0; font: 600 13px; }")
    b.setToolTip(tip)
    b.setAccessibleName(text)
    b.setFocusPolicy(Qt.NoFocus)
    return b


def divider(vertical_bar):
    """Group boundary. In a vertical bar it is a horizontal line, and vice versa."""
    line = QFrame()
    line.setObjectName("sep")
    wrap = QWidget()
    if vertical_bar:
        line.setFixedHeight(1)
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(6, GROUP_GAP, 6, GROUP_GAP)
    else:
        line.setFixedWidth(1)
        line.setFixedHeight(20)
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(GROUP_GAP, 0, GROUP_GAP, 0)
    wl.addWidget(line, 0, Qt.AlignCenter)
    if vertical_bar:
        line.setMinimumWidth(BTN - 10)
    return wrap


class GlassFrame(QFrame):
    """Liquid-Glass-like bar: blurred backdrop + tint + hairline border + top highlight + soft shadow.
    Blur comes from the overlay's own screenshot, so it is real backdrop blur without OS support."""

    def __init__(self, parent, radius, backdrop=None, shadow=True):
        super().__init__(parent)
        self.t, self.radius, self.backdrop = parent_theme(parent), radius, backdrop
        self.setAttribute(Qt.WA_StyledBackground, False)
        if shadow:
            fx = QGraphicsDropShadowEffect(self)
            fx.setBlurRadius(28)
            fx.setOffset(0, 6)
            fx.setColor(self.t["shadow"])
            self.setGraphicsEffect(fx)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self.radius, self.radius)
        p.setClipPath(path)
        bd = self.backdrop() if callable(self.backdrop) else None
        if bd is not None and not self.t["solid"]:
            img, scale = bd
            g = QRect(self.mapTo(self.window(), QPoint(0, 0)), self.size())
            p.drawImage(QRectF(self.rect()), img,
                        QRectF(g.x() * scale, g.y() * scale, g.width() * scale, g.height() * scale))
        p.fillPath(path, self.t["glass"])
        p.setClipping(False)
        # specular top highlight (inner) and hairline edge
        p.setPen(QPen(self.t["highlight"], 1))
        p.drawRoundedRect(r.adjusted(1, 1, -1, -1), self.radius - 1, self.radius - 1)
        p.setPen(QPen(self.t["border"], 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, self.radius, self.radius)


def parent_theme(w):
    while w is not None:
        if getattr(w, "t", None) is not None and isinstance(w.t, dict):
            return w.t
        w = w.parentWidget()
    return theme()


class _Elevation(QObject):
    """Subtle lift for a prominent button: soft accent-tinted shadow + top highlight.
    Rest: 2 px lift. Hover: 3 px. Pressed: settles to 1 px (feels physically pressed)."""
    STATES = {"rest": (10, 2, 70), "hover": (14, 3, 90), "press": (4, 1, 60)}

    def __init__(self, btn, t):
        super().__init__(btn)
        self.fx = QGraphicsDropShadowEffect(btn)
        self.base = QColor(t["accent_fill"]).darker(160)
        btn.setGraphicsEffect(self.fx)
        btn.installEventFilter(self)
        self.set("rest")

    def set(self, state):
        blur, dy, alpha = self.STATES[state]
        c = QColor(self.base)
        c.setAlpha(alpha)
        self.fx.setBlurRadius(blur)
        self.fx.setOffset(0, dy)
        self.fx.setColor(c)

    def eventFilter(self, obj, e):
        k = e.type()
        if k == e.Type.Enter:
            self.set("hover")
        elif k == e.Type.Leave:
            self.set("rest")
        elif k == e.Type.MouseButtonPress:
            self.set("press")
        elif k == e.Type.MouseButtonRelease:
            self.set("hover" if obj.underMouse() else "rest")
        return False


def elevate(btn, t):
    btn._elevation = _Elevation(btn, t)
    return btn


def style_menu(menu, t):
    """Rounded, system-coloured menu (no hard borders)."""
    menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WA_TranslucentBackground)
    menu.setStyleSheet(
        f"QMenu{{background:{t['menu']};color:{t['label']};border:1px solid {t['border'].name(QColor.HexArgb)};"
        f"border-radius:12px;padding:5px;font:13px '{UI_FONT}';}}"
        "QMenu::item{padding:6px 18px;border-radius:7px;}"
        f"QMenu::item:selected{{background:{t['accent_fill']};color:{t['on_accent']};}}"
        f"QMenu::item:disabled{{color:{t['label2']};}}"
        f"QMenu::separator{{height:1px;background:{t['sep']};margin:5px 8px;}}")


def tinted_icon(name, t, size=48):
    """Monochrome symbol in the label colour; accent tint when the button is on (selected)."""
    icon = QIcon()
    icon.addPixmap(make_icon(name, t["label"], size).pixmap(size, size), QIcon.Normal, QIcon.Off)
    icon.addPixmap(make_icon(name, t["accent"], size).pixmap(size, size), QIcon.Normal, QIcon.On)
    return icon


def colour_dot_icon(color, t, selected=False, size=48):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = size / 2
    if selected:                                      # Apple colour-well ring with a gap
        p.setPen(QPen(QColor(t["label"]), size * 0.07))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(c, c), size * 0.44, size * 0.44)
    p.setPen(QPen(QColor(0, 0, 0, 40) if not t["dark"] else QColor(255, 255, 255, 50), size * 0.03))
    p.setBrush(QColor(color))
    p.drawEllipse(QPointF(c, c), size * 0.32, size * 0.32)
    p.end()
    return QIcon(pm)


def blur_backdrop(pix, factor=14):
    """Cheap, strong blur of the screenshot: tiny smooth downscale, drawn back up smoothly."""
    w = max(1, pix.width() // factor)
    h = max(1, pix.height() // factor)
    small = pix.toImage().scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    small = small.scaled(max(1, w // 2), max(1, h // 2), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return small, (small.width() / max(1, pix.width() / pix.devicePixelRatio()))



BUBBLE = 44
CARD_R = 14          # caption card corner radius (same family as the bars)
CARD_IN = 4          # editors sit 4 px inside the card: a 14 px rounded corner clears a square edge at >= 4.1 px


class CaptionCard(QWidget):
    """Rounded white card behind the caption + stamp. Painted antialiased; the editors on top stay
    opaque rectangles inset by CARD_IN, so typing still repaints only the editor (no lag)."""
    SH = 8           # room for the soft shadow

    def __init__(self, ov):
        super().__init__(ov)
        self.t = ov.t
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_card(self, r):
        self.setGeometry(r.adjusted(-self.SH, -self.SH, self.SH, self.SH))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(self.SH, self.SH, -self.SH, -self.SH)
        p.setPen(Qt.NoPen)
        for i in range(self.SH, 0, -1):                        # soft shadow, slightly lower
            p.setBrush(QColor(0, 0, 0, int(36 * (1 - i / (self.SH + 1)) / 3)))
            p.drawRoundedRect(r.adjusted(-i, -i + 3, i, i + 3), CARD_R + i, CARD_R + i)
        p.setBrush(QColor("#ffffff"))
        p.setPen(QPen(QColor(0, 0, 0, 30), 1))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), CARD_R, CARD_R)
        p.end()



class CaptionBubble(QToolButton):
    """Folded caption: a round glass button with a chat icon. A dot shows a note is written.
    Tooltip previews the note. Click to open the caption again."""

    def __init__(self, ov, on_click):
        super().__init__(ov)
        self.ov, self.t = ov, ov.t
        self.setFixedSize(BUBBLE, BUBBLE)
        self.setIcon(make_icon("chat", self.t["label"]))
        self.setIconSize(QSize(22, 22))
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAccessibleName("Open caption")
        self.setStyleSheet("QToolButton{background:transparent;border:none;}")
        fx = QGraphicsDropShadowEffect(self)
        fx.setBlurRadius(18)
        fx.setOffset(0, 3)
        fx.setColor(self.t["shadow"])
        self.setGraphicsEffect(fx)
        self.setAttribute(Qt.WA_Hover)
        self.clicked.connect(on_click)

    def refresh(self):
        text = self.ov.caption.toPlainText().strip()
        self.setToolTip("Caption" + (f":  {text[:80]}{'…' if len(text) > 80 else ''}" if text
                                     else "  —  click to write a note"))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        g = QColor(self.t["glass"])
        g.setAlpha(max(g.alpha(), 235))
        p.setPen(QPen(self.t["border"], 1))
        p.setBrush(g)
        p.drawEllipse(r)
        if self.underMouse():                          # hover: accent ring
            p.setPen(QPen(QColor(self.t["accent"]), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(r)
        ic = self.icon().pixmap(self.iconSize(), self.devicePixelRatioF())
        p.drawPixmap(QPointF((self.width() - self.iconSize().width()) / 2,
                             (self.height() - self.iconSize().height()) / 2), ic)
        if self.ov.caption.toPlainText().strip():     # a note exists
            p.setPen(QPen(QColor(self.t["glass"].name()), 2))
            p.setBrush(QColor(self.t["accent"]))
            p.drawEllipse(QPointF(self.width() - 11, 11), 5, 5)
        p.end()


# ---------------------------------------------------------------- overlay
TOOLS = [("Select and move", None, "move", Qt.Key_V), ("Pen", "pen", "pen", Qt.Key_P),
         ("Line", "line", "line", Qt.Key_L), ("Arrow", "arrow", "arrow", Qt.Key_A),
         ("Rectangle", "rect", "rect", Qt.Key_R), ("Ellipse", "oval", "oval", Qt.Key_O),
         ("Highlighter", "marker", "marker", Qt.Key_H), ("Text", "text", "text", Qt.Key_T)]
HANDLES = ("tl", "t", "tr", "r", "br", "b", "bl", "l")
HANDLE_CURSORS = {"tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor,
                  "bl": Qt.SizeBDiagCursor, "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
                  "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor}
_CURSOR_CACHE = {}


# Navigation-arrow pointer from the user's reference image, flipped horizontally so the tip
# points up-left. Points traced from the 360 px reference, mirrored (x -> 360 - x), tip at (0, 0).
# Drawn as SVG and rendered at the screen's real pixel density, so it stays sharp at any scaling.
_ARROW = [(0, 0), (152, 57), (90, 92), (60, 152)]
ARROW_PX = 15                                   # arrow height/width in logical px
TIP = 4                                         # tip = click point; 4 x scale is a whole px at 100-200%
# Badge = 20% of the arrow's area: side = sqrt(0.2 * 15 * 15) = 6.7 -> 7 px.
BADGE_PX = round(math.sqrt(0.2 * ARROW_PX * ARROW_PX))
# Badge sits on the arrow's 45-degree axis, just past the tail notch (90, 92 of 152).
# v9 used 4.5 px; halved to 2.25 px on request.
BADGE_GAP = 2.25


def _glyph_svg(kind, x, y, n, ink, u):
    """Tool glyph inside an n x n device-px box at (x, y), snapped to whole pixels.
    u = one stroke width in device px. Lines sit u/2 inside the box, so each covers whole pixels."""
    h = u / 2
    L = lambda a, b: f"{x + a + h:.2f} {y + b + h:.2f}"          # noqa: E731
    m = n - u                                                     # last usable offset
    line = f'fill="none" stroke="{ink}" stroke-width="{u}" stroke-linecap="square" stroke-linejoin="miter"'
    if kind == "pen":
        zig = line.replace('"square"', '"round"').replace('"miter"', '"round"')   # one of each attribute
        return f'<polyline points="{L(0, m)} {L(m * .33, 0)} {L(m * .66, m)} {L(m, 0)}" {zig}/>'
    if kind == "line":
        return f'<path d="M{L(0, m)} L{L(m, 0)}" {line}/>'
    if kind == "arrow":
        k = max(2 * u, round(n * .55))
        return (f'<path d="M{x + n} {y} L{x + n} {y + k} L{x + n - k} {y} Z" fill="{ink}"/>'
                f'<path d="M{L(0, m)} L{L(m - u, u)}" {line}/>')
    if kind == "rect":
        return f'<rect x="{x + h:.2f}" y="{y + h:.2f}" width="{m}" height="{m}" {line}/>'
    if kind == "oval":
        return f'<circle cx="{x + n / 2:.2f}" cy="{y + n / 2:.2f}" r="{(n - u) / 2:.2f}" fill="none" stroke="{ink}" stroke-width="{u}"/>'
    if kind == "marker":
        t = max(u, round(n * .4))
        return f'<rect x="{x}" y="{y + (n - t) // 2}" width="{n}" height="{t}" fill="{ink}"/>'
    return ""


def ink_for(fill):
    """Glyph colour with the higher WCAG contrast against the badge fill."""
    def lum(q):
        v = [x / 255 for x in (q.red(), q.green(), q.blue())]
        v = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in v]
        return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]
    L = lum(QColor(fill))
    return "#111111" if (L + 0.05) / (0.0056 + 0.05) > 1.05 / (L + 0.05) else "#ffffff"


def cursor_svg(kind, color="#1c1c20", dpr=1.0):
    """Cursor as SVG in *device pixels* for this screen scaling, every edge on the pixel grid."""
    sc = dpr
    N = round(32 * sc)
    k = ARROW_PX / 152.0 * sc
    tip = TIP * sc                                   # TIP=4 -> whole px at 100/125/150/175/200%
    # vertices on pixel centres: tip pixel = hotspot pixel
    pts = [(round(tip + x * k) + .5, round(tip + y * k) + .5) for x, y in _ARROW]
    pts[0] = (tip + .5, tip + .5)
    d = "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"
    halo = max(1, round(sc * .8))                    # visible white outside: 1 px (2 px at 200%)
    corner = max(1, round(1.2 * sc))
    # badge: whole-px size and position, on the arrow's axis just past the tail notch
    bs = round(BADGE_PX * sc)
    nx = tip + 90 * k
    bx = by = round(nx + BADGE_GAP * sc)
    fill = QColor(color)
    ring = fill.darker(170).name() if fill.lightness() > 60 else fill.lighter(260).name()
    u = max(1, round(sc))                            # 1 device px ring / glyph stroke
    ink = ink_for(color)
    pad = u + max(1, round(sc * .6))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{N}" height="{N}" viewBox="0 0 {N} {N}">'
        f'<path d="{d}" fill="#fff" stroke="#fff" stroke-width="{corner + 2 * halo}" stroke-linejoin="round"/>'
        f'<path d="{d}" fill="#111" stroke="#111" stroke-width="{corner}" stroke-linejoin="round"/>'
        f'<rect x="{bx}" y="{by}" width="{bs}" height="{bs}" fill="{ring}"/>'
        f'<rect x="{bx + u}" y="{by + u}" width="{bs - 2 * u}" height="{bs - 2 * u}" fill="{fill.name()}"/>'
        + _glyph_svg(kind, bx + pad, by + pad, bs - 2 * pad, ink, max(1, round(sc * .75)))
        + "</svg>")


def crosshair_svg(dpr=1.0):
    """Two-tone crosshair: black core with a white halo, so it shows on white AND black screens.
    Built in device px; arms end on whole pixels; centre gap + dot keep the target pixel visible."""
    N = round(32 * dpr)
    c = N // 2 + .5                                  # centre of the hotspot pixel
    u = max(1, round(dpr))                           # core width
    halo = u + 2 * max(1, round(dpr))                # 1 px white on each side (2 at 200%)
    arm, gap = round(11 * dpr), round(3 * dpr)
    segs = [(c, c - gap - arm, c, c - gap), (c, c + gap, c, c + gap + arm),
            (c - gap - arm, c, c - gap, c), (c + gap, c, c + gap + arm, c)]
    d = " ".join(f"M{x1:.1f} {y1:.1f} L{x2:.1f} {y2:.1f}" for x1, y1, x2, y2 in segs)
    dot = max(1, round(dpr))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{N}" height="{N}" viewBox="0 0 {N} {N}">'
            f'<path d="{d}" stroke="#fff" stroke-width="{halo}" stroke-linecap="square"/>'
            f'<rect x="{c - dot / 2 - 1:.1f}" y="{c - dot / 2 - 1:.1f}" width="{dot + 2}" height="{dot + 2}" fill="#fff"/>'
            f'<path d="{d}" stroke="#000" stroke-width="{u}" stroke-linecap="butt"/>'
            f'<rect x="{c - dot / 2:.1f}" y="{c - dot / 2:.1f}" width="{dot}" height="{dot}" fill="#000"/>'
            '</svg>')


def select_cursor(dpr=1.0):
    key = ("crosshair", round(dpr, 2))
    if key not in _CURSOR_CACHE:
        N = round(32 * dpr)
        pm = QPixmap(N, N)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        QSvgRenderer(QByteArray(crosshair_svg(dpr).encode())).render(p, QRectF(0, 0, N, N))
        p.end()
        pm.setDevicePixelRatio(dpr)
        _CURSOR_CACHE[key] = QCursor(pm, 16, 16)
    return _CURSOR_CACHE[key]


def tool_cursor(kind, dpr=1.0, color="#1c1c20"):
    """Arrow pointer (hotspot at its tip) with the tool badge, in the drawing colour, below its tail."""
    if kind is None:
        return QCursor(Qt.SizeAllCursor)
    if kind == "text":
        return QCursor(Qt.IBeamCursor)
    key = (kind, round(dpr, 2), QColor(color).name())
    if key not in _CURSOR_CACHE:
        N = round(32 * dpr)
        pm = QPixmap(N, N)                           # paint in device px, then tag the scale
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        QSvgRenderer(QByteArray(cursor_svg(kind, color, dpr).encode())).render(p, QRectF(0, 0, N, N))
        p.end()
        pm.setDevicePixelRatio(dpr)
        _CURSOR_CACHE[key] = QCursor(pm, TIP, TIP)   # logical hotspot = the tip pixel
    return _CURSOR_CACHE[key]


BTN = 34
MIN_SEL = 8


class Overlay(QWidget):
    def __init__(self, ctl, screen, pix, stamp_text, edit_index=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow)   # macOS hides tool windows on deactivate
        self.ctl, self.pix, self.screen_ = ctl, pix, screen
        self.edit_index, self._handing_off = edit_index, False
        self.collage = edit_index is not None or bool(getattr(ctl, "session", None))
        self.t = theme()
        self.dim = QPixmap(pix)                    # screenshot with the dark veil baked in once
        dp = QPainter(self.dim)
        dp.fillRect(self.dim.rect(), QColor(0, 0, 0, 120))
        dp.end()
        self.dpr = pix.devicePixelRatio()
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.setMouseTracking(True)
        self.setCursor(select_cursor(screen.devicePixelRatio()))
        self._mouse = None                         # for the full-screen guide lines
        self.setFocusPolicy(Qt.StrongFocus)
        self.sel = QRect()
        self.state = "idle"          # idle -> selecting -> ready
        self.tool = None
        self.shapes, self.cur = [], None
        self.selected, self.history = None, []     # picked mark; undo snapshots
        self.drag, self.drag_origin, self.sel_origin = None, QPoint(), QRect()
        self.text_edit = None
        self.color = QColor(ctl.settings["color"])
        self.sizes = dict(ctl.settings["sizes"])   # defaults from Settings; scroll = this capture only
        self.on_hold, self.hold_bar = False, None
        self._backdrop = blur_backdrop(self.dim)   # glass bars sample this (real backdrop blur)
        self._backdrop_sel = None
        self.size_preview, self._wheel_acc = None, 0
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(1000)
        self._preview_timer.timeout.connect(self._hide_preview)
        self._build(stamp_text)
        self.caption.viewport().installEventFilter(self)   # stop Ctrl+scroll zooming the caption
        self.hindi = HindiTyper(self, self.caption)
        if ctl.settings.get("hindi_mode"):
            self.toggle_hindi(True, quiet=True)

    @property
    def width(self):                      # size of the current tool (shadows QWidget.width; use width_())
        return self.sizes.get(self.tool or "pen", 3)

    @width.setter
    def width(self, w):
        self.sizes[self.tool or "pen"] = w

    # ---- child widgets
    def _bar(self, vertical):
        radius = BTN // 2 + GLASS_PAD                       # capsule ends; buttons concentric inside
        f = GlassFrame(self, radius, backdrop=lambda: self._backdrop)
        f.setCursor(Qt.ArrowCursor)            # buttons must not inherit the crosshair / tool cursor
        f.setObjectName("bar")
        f.setStyleSheet(bar_css(self.t, BTN // 2))
        lay = QVBoxLayout(f) if vertical else QHBoxLayout(f)
        lay.setContentsMargins(GLASS_PAD, GLASS_PAD, GLASS_PAD, GLASS_PAD)
        lay.setSpacing(2)
        lay.setAlignment(Qt.AlignHCenter if vertical else Qt.AlignVCenter)   # one centre line
        return f, lay

    def _btn(self, text_or_icon, slot, tip, checkable=False):
        b = QToolButton()
        if isinstance(text_or_icon, QIcon):
            b.setIcon(text_or_icon)
            b.setIconSize(QSize(20, 20))
            b.setFixedSize(BTN, BTN)
        else:
            b.setText(text_or_icon)
            b.setFixedHeight(BTN)
        b.setToolTip(tip)
        b.setAccessibleName(tip.split(chr(10))[0].split('  (')[0] or b.text())   # screen readers
        b.setCheckable(checkable)
        b.setFocusPolicy(Qt.NoFocus)          # keys must reach the overlay, never a button
        b.clicked.connect(slot)
        return b

    def _sep(self, vertical):
        return divider(vertical)

    def _build(self, stamp_text):
        self.side, lay = self._bar(True)
        self.tool_btns = {}
        for label, kind, icon, key in TOOLS:
            b = self._btn(tinted_icon(icon, self.t), lambda _=False, k=kind: self.set_tool(k),
                          (f"{label}  ({QKeySequence(key).toString()})"
                           + ("" if kind is None else f"\n{MOD} scroll to change size")), True)
            self.tool_btns[kind] = b
            lay.addWidget(b)
        self.tool_btns[None].setChecked(True)
        lay.addWidget(self._sep(True))
        # Colour well (Apple Markup style): shows the colour; click opens the palette. Keys 1-6 pick.
        self.color_btn = self._btn(QIcon(), self.toggle_palette, "Colour  (1–6)")
        self.color_btn.setIconSize(QSize(26, 26))
        lay.addWidget(self.color_btn)
        lay.addWidget(self._btn(tinted_icon("undo", self.t), self.undo, f"Undo  ({MOD}Z)"))
        self.palette, play = self._bar(False)
        self.swatch_btns = []
        for i, c in enumerate(SWATCHES):
            b = self._btn(QIcon(), lambda _=False, col=c: self.pick_swatch(col), f"Colour  ({i + 1})")
            b.setIconSize(QSize(28, 28))
            b.setProperty("swatch", c)
            self.swatch_btns.append(b)
            play.addWidget(b)
        self.palette.hide()
        lay.addWidget(self._sep(True))
        self.hindi_btn = self._btn(tinted_icon("hindi", self.t), lambda: self.toggle_hindi(), "", True)
        self.hindi_btn.setToolTip(f"Hindi typing  ({MOD}G)\nType Hinglish in the caption — space converts "
                                  "to हिंदी.\nWorks without input tools installed.")
        self.hindi_btn.setAccessibleName("Hindi typing")
        self.hold_btn = self._btn(tinted_icon("pause", self.t), self.hold,
                                  f"Hold capture  ({MOD}P)\nHides this screen so you can copy text from "
                                  "anywhere — even under the selection. Resume brings everything back.")
        lay.addWidget(self.hindi_btn)
        lay.addWidget(self.hold_btn)
        self._refresh_style_btns()

        self.caption = QTextEdit(self)
        self.caption.setAcceptRichText(False)
        self.caption.setPlaceholderText("Add a caption…")
        self.caption.setFrameShape(QFrame.NoFrame)
        self.caption.document().setDocumentMargin(PAD)
        self.caption.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)   # long notes scroll, never overlap
        self.caption.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.caption.setFont(_font(CAP_PX))
        self.caption.setStyleSheet("QTextEdit{background:#ffffff;color:#1a1a1a;border:none;}"
                                   "QScrollBar:vertical{background:transparent;width:8px;margin:2px;}"
                                   "QScrollBar::handle:vertical{background:rgba(0,0,0,0.25);"
                                   "border-radius:3px;min-height:24px;}"
                                   "QScrollBar::add-line,QScrollBar::sub-line,QScrollBar::add-page,"
                                   "QScrollBar::sub-page{height:0;background:none;}")
        self.caption.document().documentLayout().documentSizeChanged.connect(self._text_resized)
        self.caption.installEventFilter(self)

        # Wrapping like the output (a one-line field would cut long stamps on screen only)
        self.stamp = QTextEdit(self)
        self.stamp.setAcceptRichText(False)
        self.stamp.setPlainText(stamp_text)
        self.stamp.setPlaceholderText("Proof stamp (empty = none)")
        self.stamp.setFrameShape(QFrame.NoFrame)
        self.stamp.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.stamp.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.stamp.setFont(_font(STAMP_PX))
        self._set_stamp_margins(PAD)
        self.stamp.setStyleSheet("QTextEdit{background:#ffffff;color:#5f5e5a;border:none;}")
        self.stamp.document().documentLayout().documentSizeChanged.connect(self._text_resized)
        self._opaque_vps = []
        for ed in (self.caption, self.stamp):
            # Opaque: typing repaints only this box, never the 4K screenshot behind it.
            # eventFilter paints the white background before the text (see Paint branch).
            vp = ed.viewport()
            vp.setAttribute(Qt.WA_OpaquePaintEvent)
            vp.installEventFilter(self)
            self._opaque_vps.append(vp)
        self._last_heights = None
        self.stamp.installEventFilter(self)

        self.actions, alay = self._bar(False)
        alay.addWidget(self._btn(tinted_icon("close", self.t), self.close, "Close  (Esc)"))
        self.save_btn = self._btn(tinted_icon("save", self.t), self.do_save, "")
        self.save_btn.setFixedSize(BTN + 16, BTN)
        self.save_btn.setPopupMode(QToolButton.MenuButtonPopup)
        self.save_btn.setStyleSheet(
            f"QToolButton::menu-button {{ border:none; width:14px; border-top-right-radius:{BTN // 2}px;"
            f" border-bottom-right-radius:{BTN // 2}px; }}"
            f"QToolButton::menu-button:hover {{ background: {self.t['hover']}; }}"
            f"QToolButton::menu-arrow {{ image: url({chevron_png(self.t['label'])}); width:10px; height:10px; }}")
        self.save_menu = QMenu(self.save_btn)
        style_menu(self.save_menu, self.t)
        self.save_menu.aboutToShow.connect(self._fill_save_menu)
        self.save_btn.setMenu(self.save_menu)
        self._refresh_save_tip()
        alay.addWidget(self.save_btn)
        key = self.ctl.settings.get("key_name", "the hotkey")
        self.add_btn = text_button("Bulk", tinted_icon("stack", self.t),
                                   f"Bulk  ({MOD}N)  —  several screenshots as one image\n"
                                   f"Keeps this shot and pauses: go to any page or scroll, press {key}, drag.\n"
                                   "Each selection is kept. Finish with Copy.", self.t)
        self.add_btn.setCheckable(True)
        self.add_btn.setStyleSheet(self.add_btn.styleSheet().replace("font: 600 13px;", "font: 13px;"))
        self.add_btn.clicked.connect(self.start_bulk)
        self.add_btn.setVisible(self.edit_index is None and not self.collage)
        self._mid_sep = self._sep(False)
        alay.addWidget(self._mid_sep)
        alay.addWidget(self.add_btn)
        collecting = self.collage and self.edit_index is None
        self.arrange_btn = self._btn(tinted_icon("grid", self.t), self.arrange,
                                     "Arrange  —  order, captions, caption for all")
        self.arrange_btn.setVisible(collecting)
        alay.addWidget(self.arrange_btn)
        self._mid_sep.setVisible((self.edit_index is None and not self.collage) or collecting)
        alay.addWidget(self._sep(False))       # actions group: separate from the tools (HIG)
        self.copy_all_btn = text_button("Copy", tinted_icon("copy", self.t),
                                        f"Copy all shots as one image  ({MOD}C)", self.t)
        self.copy_all_btn.clicked.connect(self.copy_action)
        self.copy_all_btn.setVisible(collecting)
        alay.addWidget(self.copy_all_btn)
        capture = collecting and bulk_on(self.ctl) and len(self.ctl.session) + 1 >= 2
        self.copy_all_btn.setVisible(collecting and capture)
        label, tip = (("Done", "Save changes to this shot") if self.edit_index is not None else
                      ("Done", "Keep this shot and open the collage editor") if capture else
                      ("Copy", f"Copy all shots as one image  ({MOD}C)") if collecting else
                      ("Copy", f"Copy image with caption  ({MOD}C)"))
        copy = text_button(label, make_icon("grid" if label == "Done" and self.edit_index is None else "copy",
                                            self.t["on_accent"]), tip, self.t, primary=True)
        copy.clicked.connect(self.do_copy)
        alay.addWidget(elevate(copy, self.t))  # primary action on the trailing edge (HIG), lifted

        self.caption_open = True
        self.card = CaptionCard(self)
        self.card.stackUnder(self.caption)
        self.bubble = CaptionBubble(self, self.expand_caption)
        self.caption.textChanged.connect(self.bubble.refresh)

        for w in (self.side, self.caption, self.stamp, self.actions, self.bubble):
            w.hide()

    # ---- caption: open panel or floating bubble
    def collapse_caption(self):
        """Focus moved to the screenshot: fold the caption into the round chat button."""
        if self.state != "ready" or not self.caption_open:
            return
        self.caption_open = False
        self.hindi.popup.hide()
        self.layout_widgets()

    def expand_caption(self):
        if self.state != "ready":
            return
        self.caption_open = True
        self.layout_widgets()
        self.caption.setFocus()
        self.caption.moveCursor(QTextCursor.End)

    def toggle_hindi(self, on=None, quiet=False):
        on = (not self.hindi.enabled) if on is None else on
        self.hindi.set_enabled(on)
        self.hindi_btn.setChecked(on)
        self.caption.setPlaceholderText("Hinglish में लिखें — space से हिंदी बनेगा…" if on
                                        else "Add a caption…")
        self.ctl.settings["hindi_mode"] = on
        save_settings(self.ctl.settings)
        if not quiet:
            self.ctl.toast("Hindi typing on — type Hinglish, space converts" if on else "Hindi typing off",
                           self.screen_)
        if self.state == "ready":
            self.caption.setFocus()

    def hold(self):
        """Hide the editor (everything kept) so the real screen can be used; Resume restores it."""
        if self.state != "ready" or self.on_hold:
            return
        self.commit_text()
        self.hindi.popup.hide()
        self.on_hold = True
        self.hide()
        self.hold_bar = HoldBar(self.ctl, self, self.screen_)
        self.hold_bar.show()

    def resume(self):
        if not self.on_hold:
            return
        self.on_hold = False
        if self.hold_bar:
            self.hold_bar.close()
            self.hold_bar = None
        self.show()
        QTimer.singleShot(60, self.caption.setFocus)

    def _text_resized(self, *_):
        """Caption or stamp grew/shrank a line: re-place widgets. Not called per keystroke."""
        hs = (self.caption.document().size().height(), self.stamp.document().size().height())
        if hs != self._last_heights:
            self._last_heights = hs
            self.layout_widgets()

    def _set_stamp_margins(self, pad):
        """Same side and bottom padding as the output; the caption above already pads the top."""
        doc = self.stamp.document()
        doc.setDocumentMargin(pad)
        fmt = doc.rootFrame().frameFormat()
        fmt.setTopMargin(0)
        doc.rootFrame().setFrameFormat(fmt)

    def _refresh_style_btns(self):
        cur = self.color.name().lower()
        self.color_btn.setIcon(colour_dot_icon(cur, self.t, selected=True))
        for b in self.swatch_btns:
            c = b.property("swatch")
            b.setIcon(colour_dot_icon(c, self.t, selected=c.lower() == cur))

    def toggle_palette(self):
        if self.palette.isVisible():
            self.palette.hide()
            return
        self.palette.adjustSize()
        g = self.side.geometry()
        cb = self.color_btn.geometry().translated(g.topLeft())
        x = g.left() - self.palette.width() - 8 if g.left() - self.palette.width() - 8 >= 0 else g.right() + 8
        y = max(0, min(cb.center().y() - self.palette.height() // 2, self.rect().bottom() - self.palette.height()))
        self.palette.move(x, y)
        self.palette.show()
        self.palette.raise_()

    def pick_swatch(self, c):
        self.set_color(QColor(c))
        self.palette.hide()

    def show_widgets(self, on):
        for w in (self.side, self.actions):
            w.setVisible(on)
        if not on:
            self.palette.hide()
            for w in (self.caption, self.stamp, self.bubble, self.card):
                w.hide()
        if on:
            self._refresh_backdrop()
            self.layout_widgets()

    def _refresh_backdrop(self):
        """Glass samples what is really behind it: dim screen + the bright selection."""
        if self._backdrop_sel == self.sel:
            return
        self._backdrop_sel = QRect(self.sel)
        comp = QPixmap(self.dim)
        p = QPainter(comp)
        self._blit(p, self.pix, self.sel)
        p.end()
        self._backdrop = blur_backdrop(comp)
        for w in (self.side, self.actions, self.palette):
            w.update()

    def layout_widgets(self):
        """Place toolbar, caption and actions OUTSIDE the selection.
        Wide shots: below, then above, then beside. Tall shots: beside first (left/right of the shot).
        The caption keeps a minimum height and scrolls when the note is long, so it never grows into
        the shot. Only when the shot fills the whole screen is there no outside spot: then the caption
        starts folded into the round chat button."""
        if self.state != "ready":
            return
        s, R, m = self.sel, self.rect(), 8
        self.side.adjustSize()
        sw, sh = self.side.width(), self.side.height()
        if s.right() + m + sw <= R.right():
            x = s.right() + m
        elif s.left() - m - sw >= 0:
            x = s.left() - m - sw
        else:
            x = s.right() - sw - m
        self.side.move(x, max(0, min(s.top(), R.bottom() - sh)))
        side = self.side.geometry()
        side_out = not side.intersects(s)

        self.actions.adjustSize()
        aw, ah = self.actions.width(), self.actions.height()
        sd_h = lambda w: (self.stamp.document().setTextWidth(w), max(20, math.ceil(  # noqa: E731
            self.stamp.document().size().height()) + 2))[1]

        # free areas around the selection (screen minus selection, minus the side toolbar)
        right_x = (side.right() + 1 if side_out and side.left() > s.right() else s.right() + 1) + m
        left_r = (side.left() - 1 if side_out and side.right() < s.left() else s.left() - 1) - m
        areas = {
            "below": QRect(s.left(), s.bottom() + 1 + m, s.width(), R.bottom() - s.bottom() - m),
            "above": QRect(s.left(), 0, s.width(), s.top() - m),
            "right": QRect(right_x, 0, R.right() - right_x - m, R.height()),
            "left": QRect(m, 0, left_r - m, R.height()),
        }
        tall = s.height() > s.width()
        order = ["right", "left", "below", "above"] if tall else ["below", "above", "right", "left"]

        cp = caption_px(self.ctl.settings, s.width())
        min_cap = max(40, cp + 2 * pad_for(cp))       # one line of caption always visible

        def plan(name):
            """(x, y, width, caption_h, stamp_h) for an area, or None if it does not fit."""
            A = areas[name]
            if name in ("below", "above"):
                w = s.width()
            else:
                w = min(380, A.width())
                if w < max(220, aw):
                    return None
            if self.caption_open:
                st = sd_h(w - 2 * CARD_IN) + CARD_IN
                need_min = min_cap + st + m + ah
                if A.height() < need_min:
                    return None
                self.caption.document().setTextWidth(w - 2 * CARD_IN)
                want = max(40, math.ceil(self.caption.document().size().height()) + 2) + CARD_IN
                ch = min(want, A.height() - st - m - ah)
                total = ch + st + m + ah
            else:
                st = ch = 0
                total = max(ah, BUBBLE)
                if A.height() < total:
                    return None
            if name == "below":
                y = A.top()
            elif name == "above":
                y = A.bottom() - total + 1
            else:                                      # beside: level with the top of the shot
                y = max(0, min(s.top(), R.bottom() - total))
            return A.left() if name != "left" else A.right() - w + 1, y, w, ch, st

        chosen = None
        for name in order:
            pl = plan(name)
            if pl:
                chosen = (name,) + pl
                break
        if chosen is None and self.caption_open:      # shot fills the screen: fold, never cover it
            self.caption_open = False
            return self.layout_widgets()
        if chosen is None:                             # even the button row has no outside spot
            chosen = ("inside", max(0, s.right() - aw - BUBBLE - 2 * m), max(0, s.bottom() - ah - m),
                      aw, 0, 0)
        name, x, y, w, ch, st = chosen
        self.caption_place = name

        if self.caption_open:
            if name in ("left", "right"):
                cp = min(cp, 22)                       # side panel is narrow: keep the text readable
            if self.caption.font().pixelSize() != cp:
                self.caption.setFont(_font(cp))
                self.caption.document().setDocumentMargin(pad_for(cp))
                self.stamp.setFont(_font(stamp_px_for(cp)))
                self._set_stamp_margins(pad_for(cp))
            iw = w - 2 * CARD_IN                         # editors inset inside the rounded card
            self.caption.setFixedWidth(iw)
            self.stamp.setFixedWidth(iw)
            if self.caption.document().textWidth() != iw:
                self.caption.document().setTextWidth(iw)
            self.caption.setFixedHeight(ch - CARD_IN)
            self.stamp.setFixedHeight(st - CARD_IN)
            self.caption.move(x + CARD_IN, y + CARD_IN)
            self.stamp.move(x + CARD_IN, y + ch)
            self.card.set_card(QRect(x, y, w, ch + st))
            self.card.show()
            ay = y + ch + st + m
            ax = x + w - aw if name != "right" else x
            self.bubble.hide()
            self.caption.show()
            self.stamp.show()
        else:
            self.caption.hide()
            self.stamp.hide()
            self.card.hide()
            if name == "left":
                bx, ax = x + w - aw - m - BUBBLE, x + w - aw
            else:
                bx, ax = x, x + BUBBLE + m
            self.bubble.move(bx, y + (max(ah, BUBBLE) - BUBBLE) // 2)
            self.bubble.refresh()
            self.bubble.show()
            self.bubble.raise_()
            ay = y + (max(ah, BUBBLE) - ah) // 2
        self.actions.move(max(0, min(ax, R.right() - aw)), ay)

    # ---- tools
    def set_tool(self, kind):
        self.commit_text()
        self.tool = kind
        for k, b in self.tool_btns.items():
            b.setChecked(k == kind)
        self.update_cursor(self.mapFromGlobal(QCursor.pos()))   # change now, not on next move
        self.setFocus()

    def set_color(self, c):
        self.color = QColor(c)
        self.ctl.settings["color"] = self.color.name()
        save_settings(self.ctl.settings)
        self._refresh_style_btns()
        if self.text_edit:
            self._style_text_edit()
        self.update_cursor(self.mapFromGlobal(QCursor.pos()))   # badge shows the new colour now

    def set_width(self, w):
        w = max(MIN_W, min(MAX_W, int(w)))
        if w == self.width:
            return
        self.width = w
        if self.text_edit:                       # live-resize text being typed
            self._style_text_edit()
            fm = QFontMetrics(self.text_edit.font())
            h = fm.height() + 8
            self.text_edit.setFixedHeight(h)
            self.text_edit.resize(max(60, fm.horizontalAdvance(self.text_edit.text()) + 16), h)

    def effective_size(self):
        """Pixel size the current tool actually draws with (matches Shape.paint)."""
        if self.tool == "marker":
            return self.width * 5
        if self.tool == "text":
            return text_font(self.width).pixelSize()
        return self.width

    def size_wheel(self, e):
        """Ctrl + scroll with a drawing tool selected: change its size and show a preview."""
        if not (e.modifiers() & Qt.ControlModifier) or not self.tool or self.state != "ready":
            return False
        self._wheel_acc += e.angleDelta().y()
        steps = int(self._wheel_acc / 120)       # one notch = 120; touchpads send smaller bits
        if steps:
            self._wheel_acc -= steps * 120
            self.set_width(self.width + steps)
        self.size_preview = self.mapFromGlobal(e.globalPosition().toPoint())
        self._preview_timer.start()
        self.update()
        return True

    def wheelEvent(self, e):
        if self.size_wheel(e):
            e.accept()
        else:
            e.ignore()

    def _hide_preview(self):
        self.size_preview = None
        self.update()

    def snapshot(self):
        self.history.append([sh.copy() for sh in self.shapes])
        del self.history[:-100]

    def undo(self):
        if self.text_edit:
            self.cancel_text()
        elif self.history:
            self.shapes = self.history.pop()
            self.selected = None
            self.update()
            self.refresh_cursor()

    def shape_at(self, pos):
        for sh in reversed(self.shapes):         # topmost first
            if sh.hit(pos):
                return sh
        return None

    def delete_selected(self):
        if self.selected in self.shapes:
            self.snapshot()
            self.shapes.remove(self.selected)
        self.selected = None
        self.update()
        self.refresh_cursor()

    # ---- inline text tool
    def _style_text_edit(self):
        c = self.color.name()
        self.text_edit.setFont(text_font(self.width))
        self.text_edit.setStyleSheet(f"QLineEdit{{background:rgba(0,0,0,40);color:{c};"
                                     f"border:1px dashed {c};padding:0 2px;}}")

    def start_text(self, pos):
        self.commit_text()
        ed = QLineEdit(self)
        self.text_edit = ed
        self._style_text_edit()
        fm = QFontMetrics(ed.font())
        h = fm.height() + 8
        ed.setFixedHeight(h)
        ed.resize(60, h)
        ed.move(pos.x() - 3, pos.y() - 4)
        ed.setProperty("anchor", QPointF(pos))
        ed.textChanged.connect(lambda t: ed.resize(max(60, fm.horizontalAdvance(t) + 16), h))
        ed.returnPressed.connect(self.commit_text)
        ed.installEventFilter(self)
        ed.show()
        ed.setFocus()

    def commit_text(self):
        ed, self.text_edit = self.text_edit, None
        if not ed:
            return
        sh = Shape("text", self.color, self.width, ed.property("anchor"))
        sh.text = ed.text()
        if sh.valid():
            self.snapshot()
            self.shapes.append(sh)
        ed.removeEventFilter(self)
        ed.hide()
        ed.deleteLater()
        self.update()

    def cancel_text(self):
        ed, self.text_edit = self.text_edit, None
        if ed:
            ed.removeEventFilter(self)
            ed.hide()
            ed.deleteLater()
        self.setFocus()

    # ---- geometry helpers
    def handle_points(self):
        s = self.sel
        cx, cy = s.center().x(), s.center().y()
        return {"tl": s.topLeft(), "t": QPoint(cx, s.top()), "tr": s.topRight(),
                "r": QPoint(s.right(), cy), "br": s.bottomRight(), "b": QPoint(cx, s.bottom()),
                "bl": s.bottomLeft(), "l": QPoint(s.left(), cy)}

    def hit_handle(self, pos):
        for name, pt in self.handle_points().items():
            if QRect(pt.x() - 7, pt.y() - 7, 15, 15).contains(pos):
                return name
        return None

    def resized(self, handle, delta):
        r = QRect(self.sel_origin)
        if "l" in handle:
            r.setLeft(min(r.left() + delta.x(), r.right() - MIN_SEL))
        if "r" in handle:
            r.setRight(max(r.right() + delta.x(), r.left() + MIN_SEL))
        if handle.startswith("t"):
            r.setTop(min(r.top() + delta.y(), r.bottom() - MIN_SEL))
        if handle.startswith("b"):
            r.setBottom(max(r.bottom() + delta.y(), r.top() + MIN_SEL))
        return r.intersected(self.rect())

    def moved(self, delta):
        r = QRect(self.sel_origin)
        r.translate(delta)
        R = self.rect()
        r.moveLeft(max(R.left(), min(r.left(), R.right() - r.width() + 1)))
        r.moveTop(max(R.top(), min(r.top(), R.bottom() - r.height() + 1)))
        return r

    # ---- mouse
    def mousePressEvent(self, e):
        pos = e.position().toPoint()
        if e.button() == Qt.RightButton:
            if self.cur:
                self.cur = None
                self.update()
            elif self.state != "ready":
                self.close()
            return
        if e.button() != Qt.LeftButton:
            return
        self.commit_text()
        self.palette.hide()
        self.setFocus()
        self.drag_origin, self.sel_origin = pos, QRect(self.sel)
        if self.state == "ready" and self.sel.contains(pos):
            self.collapse_caption()                  # looking at / marking the shot: full view
            handle = self.hit_handle(pos)
            if handle:
                self.drag = handle
            elif self.sel.contains(pos) and self.tool == "text":
                self.start_text(pos)
            elif self.sel.contains(pos) and self.tool:
                self.selected = None
                self.cur = Shape(self.tool, self.color, self.width, pos)
            elif self.sel.contains(pos) and self.shape_at(pos):
                self.selected = self.shape_at(pos)   # pick up a mark: drag to move, Delete to remove
                self.drag, self._shape_moved = "shape", False
                self._shape_before = [sh.copy() for sh in self.shapes]
                self._last = QPoint(pos)
                self.setCursor(Qt.ClosedHandCursor)
                self.update()
            elif self.sel.contains(pos) and self.edit_index is None:
                self.selected = None
                self.drag = "move"
            elif self.edit_index is not None:
                self.selected = None                 # editing: area changes only via the handles
                self.update()
            else:
                self.drag = "pending"     # a click outside keeps the box; a drag starts a new one
            return
        self.drag = "new"
        self.state = "selecting"
        self.sel = QRect(pos, pos)
        self._mouse = None
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if self.drag == "pending" and (pos - self.drag_origin).manhattanLength() > 4:
            self.drag, self.state = "new", "selecting"
            self.show_widgets(False)
        if self.cur:
            self.cur.add(pos)
        elif self.drag == "shape" and self.selected is not None:
            self.selected.translate(pos - self._last)
            self._last = QPoint(pos)
            self._shape_moved = True
        elif self.drag == "new":
            self.sel = QRect(self.drag_origin, pos).normalized().intersected(self.rect())
        elif self.drag == "move":
            self.sel = self.moved(pos - self.drag_origin)
            self.layout_widgets()
        elif self.drag in HANDLES:
            self.sel = self.resized(self.drag, pos - self.drag_origin)
            self.layout_widgets()
        elif self.state == "ready" and not e.buttons():
            self.update_cursor(pos)
            return                                  # hover changes only the cursor: no repaint
        elif self.state == "idle":
            self._move_guides(pos)
            return
        self.update()

    def _guide_rects(self, pt):
        R = self.rect()
        return [QRect(R.left(), pt.y() - 2, R.width(), 5), QRect(pt.x() - 2, R.top(), 5, R.height())]

    def _move_guides(self, pos):
        """Full-screen two-tone guide lines: the pointer is easy to find on any background."""
        old, self._mouse = self._mouse, QPoint(pos)
        for r in (self._guide_rects(old) if old else []) + self._guide_rects(pos):
            self.update(r)

    def update_cursor(self, pos):
        """Cursor shows what a click at pos will do: resize, move, or draw with the tool."""
        if self.state != "ready":
            self.setCursor(select_cursor(self.devicePixelRatioF()))
            return
        h = self.hit_handle(pos)
        if h:
            self.setCursor(HANDLE_CURSORS[h])
        elif self.sel.contains(pos) and self.tool is None and self.shape_at(pos):
            self.setCursor(Qt.OpenHandCursor)     # a mark you can pick up, move or delete
        elif self.sel.contains(pos) and self.tool is None and self.edit_index is not None:
            self.setCursor(Qt.ArrowCursor)        # editing a kept shot: the area stays put
        elif self.sel.contains(pos):
            self.setCursor(tool_cursor(self.tool, self.devicePixelRatioF(), self.color))
        elif self.edit_index is not None:
            self.setCursor(Qt.ArrowCursor)        # editing: no new selection outside, so no crosshair
        else:
            self.setCursor(select_cursor(self.devicePixelRatioF()))   # drag outside = new selection

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self.cur:
            if self.cur.valid():
                self.snapshot()
                self.shapes.append(self.cur)
            self.cur = None
        elif self.drag == "shape":
            if self._shape_moved:
                self.history.append(self._shape_before)
        elif self.drag in HANDLES or self.drag == "move":
            self._refresh_backdrop()
        elif self.drag == "new":
            if self.sel.width() < MIN_SEL or self.sel.height() < MIN_SEL:
                if self.sel_origin.isValid() and self.sel_origin.width() >= MIN_SEL:
                    self.sel, self.state = QRect(self.sel_origin), "ready"   # restore old box
                    self.show_widgets(True)
                else:
                    self.state, self.sel = "idle", QRect()
            elif bulk_on(self.ctl) and self.edit_index is None:
                self.state = "ready"                 # bulk: keep it straight away, then pause again
                QTimer.singleShot(0, self.add_to_collage)
            else:
                self.state = "ready"
                self.caption_open = True             # every new shot starts with the note open
                self.show_widgets(True)
                self.caption.setFocus()
        self.drag = None
        self.update()
        if self.state == "ready":
            self.update_cursor(e.position().toPoint())   # e.g. closed hand -> open hand

    def refresh_cursor(self):
        if self.state == "ready":
            self.update_cursor(self.mapFromGlobal(QCursor.pos()))

    # ---- keys
    def handle_key(self, e):
        k, ctrl = e.key(), bool(e.modifiers() & Qt.ControlModifier)
        if k == Qt.Key_Escape and self.selected is not None:
            self.selected = None                  # first Esc only drops the picked mark
            self.update()
        elif k == Qt.Key_Escape:
            self.close()
        elif ctrl and k == Qt.Key_C:
            self.copy_action()
        elif ctrl and k in (Qt.Key_Return, Qt.Key_Enter):
            self.do_copy()
        elif ctrl and k == Qt.Key_S and e.modifiers() & Qt.ShiftModifier:
            self.do_save_as()
        elif ctrl and k == Qt.Key_S:
            self.do_save()
        elif ctrl and k == Qt.Key_Z:
            self.undo()
        elif ctrl and k == Qt.Key_G:
            self.toggle_hindi()
        elif ctrl and k == Qt.Key_P:
            self.hold()
        elif ctrl and k == Qt.Key_N and self.edit_index is None and not self.collage:
            self.start_bulk()
        else:
            return False
        return True

    def keyPressEvent(self, e):
        if self.handle_key(e):
            return
        if self.state == "ready" and not (e.modifiers() & ~Qt.KeypadModifier):
            if Qt.Key_1 <= e.key() <= Qt.Key_1 + len(SWATCHES) - 1:
                self.pick_swatch(SWATCHES[e.key() - Qt.Key_1])
                return
            if e.key() == Qt.Key_Escape and self.palette.isVisible():
                self.palette.hide()
                return
            if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected is not None:
                self.delete_selected()
                return
            for _, kind, _icon, key in TOOLS:
                if e.key() == key:
                    self.set_tool(kind)
                    return
        super().keyPressEvent(e)

    def eventFilter(self, obj, e):
        if e.type() == e.Type.Paint and obj in getattr(self, "_opaque_vps", ()):
            bg = QPainter(obj)
            bg.fillRect(e.rect(), QColor("#ffffff"))
            bg.end()
            return False                          # then QTextEdit draws the text on top
        if e.type() == e.Type.Wheel and e.modifiers() & Qt.ControlModifier:
            self.size_wheel(e)
            return True                          # never zoom the caption text
        if e.type() == e.Type.KeyPress:
            k, ctrl = e.key(), bool(e.modifiers() & Qt.ControlModifier)
            if obj is self.text_edit:
                if k == Qt.Key_Escape:
                    self.cancel_text()
                    return True
                return False
            if obj is self.caption or obj is self.stamp:
                has_sel = obj.textCursor().hasSelection()
            else:
                return super().eventFilter(obj, e)
            if obj is self.caption and self.hindi.enabled and self.hindi.handle_key(e):
                return True
            if ctrl and k in (Qt.Key_G, Qt.Key_P, Qt.Key_N):
                return self.handle_key(e)
            if obj is self.stamp and k in (Qt.Key_Return, Qt.Key_Enter) and not ctrl:
                return True                      # stamp stays one paragraph
            if k == Qt.Key_Escape or (ctrl and k in (Qt.Key_S, Qt.Key_Return, Qt.Key_Enter)):
                return self.handle_key(e)
            if ctrl and k == Qt.Key_C and not has_sel:   # with text selected, Ctrl+C copies text
                return self.handle_key(e)
        return super().eventFilter(obj, e)

    # ---- paint and export
    def _pill(self, p, rect, text):
        t = self.t
        r = QRectF(rect)
        bd, sc = self._backdrop
        path = QPainterPath()
        path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.save()
        p.setClipPath(path)
        if not t["solid"]:
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(r, bd, QRectF(r.x() * sc, r.y() * sc, r.width() * sc, r.height() * sc))
        p.fillPath(path, t["glass"])
        p.restore()
        p.setPen(QPen(t["border"], 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.setPen(QColor(t["label"]))
        p.drawText(rect, Qt.AlignCenter, text)

    def _blit(self, p, pm, r):
        """Copy only rect r (logical px) of a full-screen pixmap: cost follows r, not the screen."""
        d = pm.devicePixelRatio()
        p.drawPixmap(QRectF(r), pm, QRectF(r.x() * d, r.y() * d, r.width() * d, r.height() * d))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setClipRegion(e.region())
        for rr in e.region():                    # per strip: two guide lines != the whole screen
            self._blit(p, self.dim, rr)
            lit = rr.intersected(self.sel)
            if not lit.isEmpty():
                self._blit(p, self.pix, lit)
        p.setRenderHint(QPainter.Antialiasing)
        if self.sel.isNull() and self._mouse is not None and self.state == "idle":
            m = self._mouse
            p.setRenderHint(QPainter.Antialiasing, False)
            for off, col in ((0, QColor(0, 0, 0, 150)), (1, QColor(255, 255, 255, 190))):
                p.setPen(QPen(col, 1))
                p.drawLine(0, m.y() + off, self.width_(), m.y() + off)
                p.drawLine(m.x() + off, 0, m.x() + off, self.rect().height())
            p.setRenderHint(QPainter.Antialiasing)
        if self.sel.isNull():
            hint = "Drag to select   ·   Esc to cancel"
            if bulk_on(self.ctl) and self.edit_index is None:
                n = len(getattr(self.ctl, "session", [])) + 1
                hint = f"Bulk  ·  drag to keep shot {n}   ·   Esc to stop"
            f = _font(14)
            p.setFont(f)
            w = QFontMetrics(f).horizontalAdvance(hint) + 40
            self._pill(p, QRect(self.width_() // 2 - w // 2, 32, w, 38), hint)
            return
        p.setClipRect(self.sel)
        for sh in self.shapes + ([self.cur] if self.cur else []):
            sh.paint(p)
        p.setClipping(False)
        if self.selected is not None and self.selected in self.shapes:
            b = self.selected.bounds().adjusted(-3, -3, 3, 3)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 230), 3))
            p.drawRoundedRect(b, 4, 4)
            p.setPen(QPen(QColor(self.t["accent"]), 1.5, Qt.DashLine))
            p.drawRoundedRect(b, 4, 4)
        # dotted border: white base with black dots, readable on any background
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor("#ffffff"), 1))
        p.drawRect(self.sel)
        dots = QPen(QColor("#000000"), 1, Qt.CustomDashLine)
        dots.setDashPattern([3, 3])
        p.setPen(dots)
        p.drawRect(self.sel)
        p.setRenderHint(QPainter.Antialiasing)
        # size badge
        f = _font(12)
        p.setFont(f)
        label = f"{round(self.sel.width() * self.dpr)} × {round(self.sel.height() * self.dpr)}"
        bw = QFontMetrics(f).horizontalAdvance(label) + 18
        by = self.sel.top() - 28 if self.sel.top() >= 30 else self.sel.top() + 6
        self._pill(p, QRect(self.sel.left(), by, bw, 22), label)
        if self.state == "ready":
            for pt in self.handle_points().values():          # white knobs with a soft edge
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 55))
                p.drawEllipse(QPointF(pt) + QPointF(0, 0.8), 5.6, 5.6)
                p.setPen(QPen(QColor(0, 0, 0, 40), 0.8))
                p.setBrush(QColor("#ffffff"))
                p.drawEllipse(QPointF(pt), 4.8, 4.8)
        if self.size_preview is not None and self.tool:
            self._paint_size_preview(p, self.size_preview)

    def _paint_size_preview(self, p, pos):
        size = self.effective_size()
        c = QColor(self.color)
        p.save()
        if self.tool == "text":
            f = text_font(self.width)
            p.setFont(f)
            fm = QFontMetrics(f)
            r = QRect(pos.x() + 14, pos.y() - fm.height() // 2, fm.horizontalAdvance("Aa") + 12, fm.height())
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 90))
            p.drawRoundedRect(QRectF(r), 6, 6)
            p.setPen(c)
            p.drawText(r, Qt.AlignCenter, "Aa")
            label, top = f"Text {size}px", r.top()
        else:
            d = max(2.0, float(size))
            if self.tool == "marker":
                c.setAlpha(110)
            p.setPen(QPen(QColor("#ffffff"), 1.5))
            p.setBrush(c)
            p.drawEllipse(QPointF(pos), d / 2 + 1, d / 2 + 1)      # actual stroke size
            p.setPen(QPen(QColor(0, 0, 0, 160), 1))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(pos), d / 2 + 2.5, d / 2 + 2.5)
            label, top = f"Size {self.width}", int(pos.y() - d / 2)
        f = _font(12, bold=True)
        p.setFont(f)
        lw = QFontMetrics(f).horizontalAdvance(label) + 18
        self._pill(p, QRect(pos.x() - lw // 2, top - 34, lw, 24), label)
        p.restore()

    def width_(self):
        return self.rect().width()

    def render_selection(self):
        s, d = self.sel, self.dpr
        img = QImage(max(1, round(s.width() * d)), max(1, round(s.height() * d)), QImage.Format_RGB32)
        img.fill(Qt.black)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(d, d)
        p.translate(-s.topLeft())
        p.drawPixmap(self.rect(), self.pix)
        for sh in self.shapes:
            sh.paint(p)
        p.end()
        return img

    def final_image(self):
        self.commit_text()
        return compose(self.render_selection(), self.caption.toPlainText(), self.stamp.toPlainText(), self.dpr,
                       caption_px(self.ctl.settings, self.sel.width()))

    # ---- collage
    def to_shot(self):
        self.commit_text()
        return Shot(self.pix, self.screen_, self.sel, self.shapes, self.caption.toPlainText(),
                    self.stamp.toPlainText(), self.sizes, self.color)

    def _store_shot(self):
        shot = self.to_shot()
        if self.edit_index is not None and self.edit_index < len(self.ctl.session):
            self.ctl.session[self.edit_index] = shot
        else:
            self.ctl.session.append(shot)
        self._handing_off = True

    def add_to_collage(self):
        """Keep this shot (marks stay editable) and PAUSE: the user browses, then presses the hotkey."""
        if self.state != "ready":
            return
        self._store_shot()
        n = len(self.ctl.session)
        self.close()
        self.ctl.toast(f"Shot {n} kept  ·  browse, then press {self.ctl.settings.get('key_name', 'the hotkey')}",
                       self.screen_)
        self.ctl.pause_collection()

    def start_bulk(self):
        """Bulk toggle on the first shot: keep it and pause; every later drag is kept."""
        if self.state != "ready":
            self.add_btn.setChecked(False)
            return
        self.ctl.bulk = True
        self.add_to_collage()

    def arrange(self):
        if self.state != "ready":
            return
        self._store_shot()
        self.close()
        self.ctl.open_composer()

    def copy_action(self):
        """Ctrl/⌘+C and the Copy button: one shot normally; the whole set while collecting."""
        if self.state != "ready":
            return
        if self.collage and self.edit_index is None:
            self._store_shot()
            self.close()
            self.ctl.copy_collection()
        else:
            self.do_copy()

    def next_shot(self):
        if self.state != "ready":
            return
        self._store_shot()
        self.close()
        self.ctl.open_composer()

    def do_copy(self):
        """Primary button: Copy (single) · Capture (collecting) · Done (editing a kept shot)."""
        if self.state != "ready":
            return
        if self.edit_index is not None:
            self.next_shot()
            return
        if self.collage and bulk_on(self.ctl):
            self.arrange()
            return
        if self.collage:
            self.copy_action()
            return
        QApplication.clipboard().setImage(self.final_image())
        self.ctl.toast(f"Copied with caption  ·  paste with {MOD}V", self.screen_)
        self.close()

    # ---- saving
    def save_dir(self):
        return self.ctl.settings["save_dir"]

    def _refresh_save_tip(self):
        self.save_btn.setToolTip(f"Save to {self.save_dir()}  ({MOD}S)\nArrow: more options")
        self.save_btn.setAccessibleName("Save")

    def _fill_save_menu(self):
        m = self.save_menu
        m.clear()
        head = m.addAction(f"Default folder:  {self._short(self.save_dir())}")
        head.setEnabled(False)
        m.addAction("Save to default folder", self.do_save)
        m.addAction("Save as…", self.do_save_as)
        m.addSeparator()
        m.addAction("Change default folder…", self.change_save_dir)
        m.addAction("Open default folder", self.open_save_dir)

    @staticmethod
    def _short(path):
        home = os.path.expanduser("~")
        return "~" + path[len(home):] if path.startswith(home) else path

    def _write(self, path):
        if self.final_image().save(path, "PNG"):
            self.ctl.toast(f"Saved {os.path.basename(path)}", self.screen_)
            self.close()
            return True
        alert(self, "Couldn't save the screenshot", f"{path} can't be written. Choose another folder.")
        return False

    def do_save(self):
        """One click: numbered file with caption keywords in the default folder."""
        if self.state != "ready":
            return
        try:
            path = next_save_path(self.save_dir(), self.caption.toPlainText())
        except OSError as ex:
            alert(self, "Can't use the save folder", f"{self.save_dir()}\n{ex}\n"
                  "Choose another with the arrow next to Save.")
            return
        self._write(path)

    def _dialog(self, fn):
        """Run a file dialog above the overlay (it is pinned above everything on macOS)."""
        if IS_MAC:
            self.hide()
        try:
            return fn()
        finally:
            if IS_MAC and self.ctl.overlay is self:
                self.show()
            self.setFocus()

    def do_save_as(self):
        if self.state != "ready":
            return
        suggest = next_save_path(self.save_dir(), self.caption.toPlainText()) \
            if os.path.isdir(self.save_dir()) else os.path.expanduser("~")
        path, _ = self._dialog(lambda: QFileDialog.getSaveFileName(
            self, "Save screenshot", suggest, "PNG (*.png)"))
        if path:
            if not path.lower().endswith(".png"):
                path += ".png"
            self._write(path)

    def change_save_dir(self):
        d = self._dialog(lambda: QFileDialog.getExistingDirectory(
            self, "Default folder for screenshots", self.save_dir()))
        if d:
            self.ctl.settings["save_dir"] = d
            save_settings(self.ctl.settings)
            self._refresh_save_tip()
            self.ctl.toast(f"Screenshots now save to {self._short(d)}", self.screen_)

    def open_save_dir(self):
        os.makedirs(self.save_dir(), exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.save_dir()))

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._grab_focus)

    def _grab_focus(self):
        if IS_MAC:
            mac_float_above_all(self)
            mac_activate()
        self.raise_()
        self.activateWindow()
        force_foreground(int(self.winId()))
        self.setFocus()

    def closeEvent(self, e):
        if self.hold_bar:
            self.hold_bar.close()
            self.hold_bar = None
        self.ctl.overlay = None
        super().closeEvent(e)
        if not self._handing_off and getattr(self.ctl, "session", None):
            if self.edit_index is not None:
                QTimer.singleShot(0, self.ctl.open_composer)     # cancelled an edit
            else:
                QTimer.singleShot(0, self.ctl.pause_collection)  # cancelled a shot: keep the others

    def restore(self, shot):
        """Re-open a collage shot for editing: same area, marks, captions."""
        self.sel = QRect(shot.sel)
        self.shapes = [sh.copy() for sh in shot.shapes]
        self.sizes, self.color = dict(shot.sizes), QColor(shot.color)
        self.caption.setPlainText(shot.caption)
        self.stamp.setPlainText(shot.stamp)
        self.state = "ready"
        self.caption_open = True
        self._mouse = None
        self._refresh_style_btns()
        self.show_widgets(True)
        self.update()
        self.refresh_cursor()                      # not the stale start-up crosshair



# ---------------------------------------------------------------- collage (several shots, one image)
class Shot:
    """One screenshot kept for a collage. Marks stay vector shapes, so they remain editable."""

    def __init__(self, pix, screen, sel, shapes, caption, stamp, sizes, color):
        self.pix, self.screen, self.sel = pix, screen, QRect(sel)
        self.shapes = [sh.copy() for sh in shapes]
        self.caption, self.stamp = caption, stamp
        self.sizes, self.color = dict(sizes), QColor(color)

    @property
    def dpr(self):
        return self.pix.devicePixelRatio()

    def image(self):
        """Crop + marks, in device pixels (same as the single-shot output)."""
        s, d = self.sel, self.dpr
        img = QImage(max(1, round(s.width() * d)), max(1, round(s.height() * d)), QImage.Format_RGB32)
        img.fill(Qt.black)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(d, d)
        p.translate(-s.topLeft())
        g = self.screen.geometry() if self.screen else QRect(0, 0, round(self.pix.width() / d),
                                                              round(self.pix.height() / d))
        p.drawPixmap(QRect(0, 0, g.width(), g.height()), self.pix)
        for sh in self.shapes:
            sh.paint(p)
        p.end()
        return img


COLLAGE_BG = QColor("#e9e9ee")


def _badge(img, n, dpr):
    """Number badge on the shot's top-left, so a prompt can say 'in #2 ...'."""
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r = 13 * dpr
    c = QPointF(10 * dpr + r, 10 * dpr + r)
    p.setPen(QPen(QColor("#ffffff"), 2 * dpr))
    p.setBrush(QColor("#0071E3"))
    p.drawEllipse(c, r, r)
    f = _font(14 * dpr, bold=True)
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), Qt.AlignCenter, str(n))
    p.end()


def compose_collage(shots, overall, layout, settings, numbered=True):
    """Each shot keeps its own caption (+ stamp); the caption for all is appended at the end.
    layout: 'stack' (one column) or 'grid' (two columns)."""
    if not shots:
        return QImage()
    dpr = max(s.dpr for s in shots)
    parts = []
    for i, sh in enumerate(shots, 1):
        img = sh.image()
        if numbered and len(shots) > 1:
            _badge(img, i, sh.dpr)
        parts.append(compose(img, sh.caption, sh.stamp, sh.dpr, caption_px(settings, sh.sel.width())))
    gap, margin = round(16 * dpr), round(16 * dpr)
    cols = 2 if layout == "grid" and len(parts) > 1 else 1
    rows = [parts[i:i + cols] for i in range(0, len(parts), cols)]
    colw = [max((r[c].width() for r in rows if c < len(r)), default=0) for c in range(cols)]
    W = sum(colw) + gap * (cols - 1) + 2 * margin
    H = sum(max(im.height() for im in r) for r in rows) + gap * (len(rows) - 1) + 2 * margin
    out = QImage(W, H, QImage.Format_RGB32)
    out.fill(COLLAGE_BG)
    p = QPainter(out)
    y = margin
    for r in rows:
        x = margin
        for c, im in enumerate(r):
            p.drawImage(x + (colw[c] - im.width()) // 2, y, im)   # centred in its column
            x += colw[c] + gap
        y += max(im.height() for im in r) + gap
    p.end()
    return compose(out, overall, "", dpr, caption_px(settings, round(W / dpr)))


class Composer(QWidget):
    """Collage window: order, per-shot captions, edit marks, one caption for all, copy/save."""

    def __init__(self, ctl):
        super().__init__(None, Qt.Window)
        self.ctl, self.t = ctl, theme()
        t = self.t
        self.setWindowTitle(f"{APP_NAME} — Collage")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(1100, 720)
        self.layout_mode = ctl.settings.get("collage_layout", "stack")
        self.setStyleSheet(settings_css(t) + bar_css(t, BTN // 2) + f"""
QWidget#composer {{ background: {t['window']}; }}
QFrame#card {{ background: {t['card']}; border-radius: 12px; border: 1px solid {t['border'].name(QColor.HexArgb)}; }}
QTextEdit {{ background: {t['field']}; color: {t['label']}; border: 1px solid {t['border'].name(QColor.HexArgb)};
            border-radius: 8px; padding: 4px; font: 14px '{UI_FONT}'; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['sep']}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t['label2']}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}
QLabel#title {{ font: 600 15px '{UI_FONT}'; }}
QLabel#hint {{ color: {t['label2']}; font: 12px '{UI_FONT}'; }}
""")
        self.setObjectName("composer")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.typers = []
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(12)

        body = QHBoxLayout()
        body.setSpacing(16)
        root.addLayout(body, 1)

        # left: shot cards
        left = QVBoxLayout()
        head = QHBoxLayout()
        tl = QLabel("Screenshots")
        tl.setObjectName("title")
        head.addWidget(tl, 1)
        add = self._tool("plus", self.add_shot, f"Add another screenshot  ({MOD}N)")
        head.addWidget(add)
        left.addLayout(head)
        self.cards_host = QWidget()
        self.cards = QVBoxLayout(self.cards_host)
        self.cards.setContentsMargins(0, 0, 4, 0)
        self.cards.setSpacing(10)
        self.cards.addStretch(1)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(self.cards_host)
        sa.setFixedWidth(380)
        left.addWidget(sa, 1)
        body.addLayout(left)

        # right: live preview
        right = QVBoxLayout()
        rh = QHBoxLayout()
        pl = QLabel("Preview")
        pl.setObjectName("title")
        rh.addWidget(pl, 1)
        self.stack_btn = self._tool("stack", lambda: self.set_layout("stack"), "One column", True)
        self.grid_btn = self._tool("grid", lambda: self.set_layout("grid"), "Two columns", True)
        rh.addWidget(self.stack_btn)
        rh.addWidget(self.grid_btn)
        right.addLayout(rh)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        pv = QScrollArea()
        pv.setWidgetResizable(True)
        pv.setWidget(self.preview)
        right.addWidget(pv, 1)
        self.preview_area = pv
        body.addLayout(right, 1)

        # bottom: caption for all + actions
        al = QLabel("Caption for all")
        al.setObjectName("title")
        root.addWidget(al)
        self.overall = QTextEdit()
        self.overall.setAcceptRichText(False)
        self.overall.setPlaceholderText("Write one prompt / caption for the whole set…  "
                                        "(each shot's own caption stays under it; this one goes at the end)")
        self.overall.setFixedHeight(84)
        self.overall.textChanged.connect(self.schedule_preview)
        root.addWidget(self.overall)
        self._add_typer(self.overall)

        bar = QHBoxLayout()
        self.hindi_btn = self._tool("hindi", self.toggle_hindi, f"Hindi typing in captions  ({MOD}G)", True)
        bar.addWidget(self.hindi_btn)
        hint = QLabel("Tip: number badges let your prompt say “in #2 …”")
        hint.setObjectName("hint")
        bar.addWidget(hint, 1)
        bar.addWidget(self._tool("close", self.discard, "Discard collage"))
        self.save_btn = self._tool("save", self.save, f"Save to {ctl.settings['save_dir']}  ({MOD}S)")
        bar.addWidget(self.save_btn)
        bar.addWidget(divider(False))
        copy = text_button("Copy", make_icon("copy", t["on_accent"]), f"Copy the whole collage  ({MOD}C)",
                           t, primary=True)
        copy.clicked.connect(self.copy)
        bar.addWidget(elevate(copy, t))
        root.addLayout(bar)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(220)
        self._timer.timeout.connect(self.update_preview)
        self.set_layout(self.layout_mode)
        if ctl.settings.get("hindi_mode"):
            self.toggle_hindi(True)
        self.rebuild()

    # -- helpers
    def _tool(self, icon, slot, tip, checkable=False):
        b = QToolButton()
        b.setIcon(tinted_icon(icon, self.t))
        b.setIconSize(QSize(20, 20))
        b.setFixedSize(BTN, BTN)
        b.setToolTip(tip)
        b.setAccessibleName(tip.split(chr(10))[0].split('  (')[0] or b.text())   # screen readers
        b.setCheckable(checkable)
        b.setFocusPolicy(Qt.NoFocus)
        b.clicked.connect(slot)
        return b

    def _add_typer(self, edit):
        ty = HindiTyper(self, edit)
        ty.set_enabled(getattr(self, "_hindi_on", False))
        edit.installEventFilter(self)
        self.typers.append(ty)
        return ty

    def eventFilter(self, obj, e):
        if e.type() == e.Type.KeyPress:
            for ty in self.typers:
                if ty.edit is obj and ty.enabled and ty.handle_key(e):
                    return True
        return super().eventFilter(obj, e)

    def keyPressEvent(self, e):
        ctrl = bool(e.modifiers() & Qt.ControlModifier)
        if ctrl and e.key() == Qt.Key_C and not (QApplication.focusWidget() and
                                                 hasattr(QApplication.focusWidget(), "textCursor") and
                                                 QApplication.focusWidget().textCursor().hasSelection()):
            self.copy()
        elif ctrl and e.key() == Qt.Key_S:
            self.save()
        elif ctrl and e.key() == Qt.Key_N:
            self.add_shot()
        elif ctrl and e.key() == Qt.Key_G:
            self.toggle_hindi()
        else:
            super().keyPressEvent(e)

    # -- cards
    def rebuild(self):
        """Re-create the cards from ctl.session (order, captions)."""
        self.typers = [ty for ty in self.typers if ty.edit is self.overall]
        while self.cards.count() > 1:
            w = self.cards.takeAt(0).widget()
            if w:
                w.deleteLater()
        n = len(self.ctl.session)
        for i, shot in enumerate(self.ctl.session):
            self.cards.insertWidget(i, self._card(i, shot, n))
        self.schedule_preview()

    def _card(self, i, shot, n):
        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(10)
        num = QLabel(str(i + 1))
        num.setFixedSize(24, 24)
        num.setAlignment(Qt.AlignCenter)
        num.setStyleSheet("background:#0071E3;color:#fff;border-radius:12px;font:600 12px;")
        top.addWidget(num, 0, Qt.AlignTop)
        thumb = QLabel()
        thumb.setAlignment(Qt.AlignCenter)
        img = shot.image()
        pm = QPixmap.fromImage(img.scaled(300, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        thumb.setPixmap(pm)
        thumb.setToolTip("Edit marks")
        thumb.setAccessibleName(f"Edit shot {i + 1}")
        thumb.setAttribute(Qt.WA_Hover)                # hover ring = "you can click this"
        thumb.setStyleSheet(f"QLabel{{border:2px solid transparent;border-radius:6px;}}"
                            f"QLabel:hover{{border-color:{self.t['accent']};}}")
        thumb.mousePressEvent = lambda e, k=i: self.edit_shot(k)
        top.addWidget(thumb, 1, Qt.AlignCenter)
        top.addSpacing(24 + 10)                    # balances the badge: thumbnail truly centred
        v.addLayout(top)
        cap = QTextEdit()
        cap.setAcceptRichText(False)
        cap.setPlaceholderText("Caption for this screenshot (optional)")
        cap.setPlainText(shot.caption)
        cap.setFixedHeight(58)
        cap.textChanged.connect(lambda c=cap, s=shot: (setattr(s, "caption", c.toPlainText()),
                                                       self.schedule_preview()))
        self._add_typer(cap)
        v.addWidget(cap)
        row = QHBoxLayout()
        row.setSpacing(2)
        up = self._tool("up", lambda _=False, k=i: self.move(k, -1), "Move up")
        dn = self._tool("down", lambda _=False, k=i: self.move(k, +1), "Move down")
        up.setEnabled(i > 0)
        dn.setEnabled(i < n - 1)
        row.addWidget(up)
        row.addWidget(dn)
        row.addStretch(1)
        row.addWidget(self._tool("edit", lambda _=False, k=i: self.edit_shot(k), "Edit marks and area"))
        row.addWidget(self._tool("trash", lambda _=False, k=i: self.remove(k), "Remove from collage"))
        v.addLayout(row)
        return card

    def move(self, i, d):
        s = self.ctl.session
        j = i + d
        if 0 <= j < len(s):
            s[i], s[j] = s[j], s[i]
            self.rebuild()

    def remove(self, i):
        del self.ctl.session[i]
        if not self.ctl.session:
            self.close()
            return
        self.rebuild()

    def edit_shot(self, i):
        self.hide()
        QTimer.singleShot(120, lambda: self.ctl.edit_shot(i))

    def add_shot(self):
        self.hide()
        self.ctl.pause_collection()                   # browse first, then the hotkey / Capture

    # -- layout + preview
    def set_layout(self, mode):
        self.layout_mode = mode
        self.stack_btn.setChecked(mode == "stack")
        self.grid_btn.setChecked(mode == "grid")
        self.ctl.settings["collage_layout"] = mode
        save_settings(self.ctl.settings)
        self.schedule_preview()

    def schedule_preview(self):
        self._timer.start()

    def final_image(self):
        return compose_collage(self.ctl.session, self.overall.toPlainText(), self.layout_mode,
                               self.ctl.settings)

    def update_preview(self):
        img = self.final_image()
        if img.isNull():
            self.preview.clear()
            return
        w = max(200, self.preview_area.viewport().width() - 8)
        pm = QPixmap.fromImage(img.scaledToWidth(min(w, img.width()), Qt.SmoothTransformation))
        self.preview.setPixmap(pm)
        self.preview.setMinimumHeight(pm.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.schedule_preview()

    def toggle_hindi(self, on=None):
        if on is None:
            on = not getattr(self, "_hindi_on", False)
        self._hindi_on = bool(on)
        self.hindi_btn.setChecked(self._hindi_on)
        for ty in self.typers:
            ty.set_enabled(self._hindi_on)

    # -- output
    def copy(self):
        img = self.final_image()
        if img.isNull():
            return
        QApplication.clipboard().setImage(img)
        self.ctl.toast(f"Collage copied  ·  paste with {MOD}V", self.screen())
        self.finish()

    def save(self):
        img = self.final_image()
        if img.isNull():
            return
        text = self.overall.toPlainText() or " ".join(s.caption for s in self.ctl.session)
        try:
            path = next_save_path(self.ctl.settings["save_dir"], text)
        except OSError as ex:
            alert(self, "Can't use the save folder", str(ex))
            return
        if img.save(path, "PNG"):
            self.ctl.toast(f"Saved {os.path.basename(path)}", self.screen())
            self.finish()

    def finish(self):
        self.ctl.session.clear()
        self.ctl.bulk = False
        self.ctl.hide_collect_bar()
        self.close()

    def discard(self):
        n = len(self.ctl.session)
        if n and not alert(self, f"Discard {n} screenshot{'s' * (n > 1)}?",
                           "They haven't been copied or saved.", "Discard", "Cancel", destructive=True):
            return
        self.finish()

    def closeEvent(self, e):
        if self.ctl.composer is self:
            self.ctl.composer = None
        super().closeEvent(e)
        if self.ctl.session:                          # closed without Copy/Save/Discard: keep the set
            QTimer.singleShot(0, self.ctl.pause_collection)



# ---------------------------------------------------------------- collecting (paused) bar
class CollectBar(QWidget):
    """Shown between shots: the app is paused so the user can browse or scroll.
    The hotkey or Capture takes the next shot. Never steals focus; can be dragged."""

    def __init__(self, ctl):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow)
        self.ctl = ctl
        self.t = t = dict(theme())
        t["glass"] = QColor(t["glass"].red(), t["glass"].green(), t["glass"].blue(), 238)
        frame = GlassFrame(self, BTN // 2 + GLASS_PAD, shadow=False)
        frame.setStyleSheet(bar_css(t, BTN // 2))
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(16, GLASS_PAD, GLASS_PAD, GLASS_PAD)
        lay.setSpacing(2)
        lay.setAlignment(Qt.AlignVCenter)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{t['accent']};")
        lay.addWidget(dot, 0, Qt.AlignVCenter)
        lay.addSpacing(8)
        self.msg = QLabel()
        self.msg.setFont(_font(13))
        self.msg.setContentsMargins(0, 0, 6, 0)      # breathing room before the divider
        lay.addWidget(self.msg, 0, Qt.AlignVCenter)
        lay.addWidget(divider(False))          # message | actions
        cp = self.cp = text_button("Copy", make_icon("copy", t["on_accent"]), "Copy all shots as one image", t)
        cp.clicked.connect(ctl.copy_collection)
        lay.addWidget(elevate(cp, t))
        done = self.arr = self.done = text_button(          # .arr kept: older callers
            "Done", make_icon("grid", t["on_accent"]),
            "Finish: open the collage editor (order, edit marks, captions, caption for all)", t)
        done.clicked.connect(ctl.open_composer)
        lay.addWidget(elevate(done, t))
        lay.addWidget(divider(False))          # actions | discard
        lay.addWidget(self._b(tinted_icon("close", t), ctl.discard_collection, "Discard all shots"))
        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 18)
        outer.addWidget(frame)
        self._drag = None
        self.refresh()

    def _b(self, icon, slot, tip):
        b = QToolButton()
        b.setIcon(icon)
        b.setIconSize(QSize(18, 18))
        b.setFixedSize(BTN, BTN)
        b.setToolTip(tip)
        b.setAccessibleName(tip.split(chr(10))[0].split('  (')[0] or b.text())   # screen readers
        b.clicked.connect(slot)
        return b

    def refresh(self):
        """Copy is the main button until 2 shots are kept; then Done (collage editor) leads."""
        n = len(self.ctl.session)
        key = self.ctl.settings.get("key_name", "the hotkey")
        self.msg.setText(f"Bulk  ·  {n} shot{'s' * (n != 1)} kept  ·  go to any page or scroll, then press {key}")
        lead_done = n >= 2
        for b, primary in ((self.cp, not lead_done), (self.done, lead_done)):
            b.setObjectName("primary" if primary else "")
            b.setIcon(make_icon("copy" if b is self.cp else "grid",
                                self.t["on_accent"] if primary else self.t["label"]))
            b.setStyleSheet("QToolButton { padding: 0; font: 600 13px; }")   # same box either way
            b.style().unpolish(b)
            b.style().polish(b)
            fx = b.graphicsEffect()
            if fx is not None:
                fx.setEnabled(primary)                # only the main button is lifted
        self.msg.setMinimumWidth(self.msg.sizeHint().width())   # grow with the text, never clip it
        self.layout().activate()
        self.adjustSize()
        if self.isVisible():
            self.place()

    def place(self):
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        self.move(g.center().x() - self.width() // 2, g.top() + 16)

    def paintEvent(self, _):
        paint_soft_shadow(self, QRectF(self.rect()).adjusted(14, 10, -14, -18), BTN // 2 + GLASS_PAD, self.t)

    def mousePressEvent(self, e):
        self._drag = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def showEvent(self, e):
        super().showEvent(e)
        if IS_MAC:
            QTimer.singleShot(0, lambda: mac_float_above_all(self))



# ---------------------------------------------------------------- alerts (same look as the app)
class Alert(QDialog):
    """App-styled alert: glass card, app icon, bold title, message, buttons of equal width
    (secondary left, primary right). Destructive actions use system red (HIG). Esc = Cancel."""

    def __init__(self, parent, title, text, primary="OK", secondary=None, destructive=False):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.t = t = theme()
        self._drag = None
        self.setStyleSheet(bar_css(t, 10) + f"""
QLabel#title {{ color: {t['label']}; font: 600 14px '{UI_FONT}'; }}
QLabel#text {{ color: {t['label2']}; font: 13px '{UI_FONT}'; }}
QToolButton {{ border-radius: 8px; }}
QToolButton#secondary {{ background: {t['hover']}; }}
QToolButton#secondary:hover {{ background: {t['selected']}; }}
QToolButton#destructive {{ background: #D70015; color: #ffffff; border: none; }}
QToolButton#destructive:hover {{ background: #B80012; }}
""")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14 + 22, 10 + 20, 14 + 22, 18 + 18)   # shadow room + card padding
        outer.setSpacing(0)
        icon = QLabel()
        icon.setPixmap(tray_icon().pixmap(48, 48))
        icon.setAlignment(Qt.AlignCenter)
        outer.addWidget(icon)
        outer.addSpacing(12)
        self.title = QLabel(title)
        self.title.setObjectName("title")
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setWordWrap(True)
        outer.addWidget(self.title)
        outer.addSpacing(6)
        self.text = QLabel(text)
        self.text.setObjectName("text")
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setWordWrap(True)
        self.text.setVisible(bool(text))
        outer.addWidget(self.text)
        outer.addSpacing(18)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.buttons = []
        if secondary:
            b = text_button(secondary, None, "", t)
            b.setObjectName("secondary")
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.clicked.connect(self.reject)
            row.addWidget(b)
            self.buttons.append(b)
        if primary:
            b = text_button(primary, None, "", t, primary=not destructive)
            if destructive:
                b.setObjectName("destructive")
                b.t = dict(t, label="#ffffff")
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.clicked.connect(self.accept)
            row.addWidget(b)
            self.buttons.append(b)
            self.primary = b
        outer.addLayout(row)
        self.setFixedWidth(300 + 2 * 36 - 44)

    def paintEvent(self, _):
        r = QRectF(self.rect()).adjusted(14, 10, -14, -18)
        paint_soft_shadow(self, r, 16, self.t)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and getattr(self, "primary", None):
            self.accept()
        else:
            super().keyPressEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        self.adjustSize()
        self.move(g.center().x() - self.width() // 2, g.center().y() - self.height() // 2 - g.height() // 8)
        self.raise_()
        self.activateWindow()

    def mousePressEvent(self, e):
        self._drag = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None


def alert(parent, title, text="", primary="OK", secondary=None, destructive=False):
    """Returns True when the primary button was chosen."""
    return Alert(parent, title, text, primary, secondary, destructive).exec() == QDialog.Accepted


# ---------------------------------------------------------------- settings dialog
class KeyCapture(Alert):
    def __init__(self, parent=None):
        super().__init__(parent, "Press the new hotkey",
                         "Press a key or a combination.\nEsc cancels.", primary=None, secondary="Cancel")
        self.result_key = None
        for b in self.buttons:
            b.setFocusPolicy(Qt.NoFocus)          # every key goes to the picker

    def _take(self, e):
        if e.key() in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, 0) or e.isAutoRepeat():
            return
        if e.key() == Qt.Key_Escape:
            self.reject()
            return
        vk = e.nativeVirtualKey()
        if not vk:
            return
        m = e.modifiers()
        if IS_MAC:   # Carbon flags; Qt reports Command as Control and Control as Meta
            mods = ((0x0100 if m & Qt.ControlModifier else 0) | (0x0200 if m & Qt.ShiftModifier else 0)
                    | (0x0800 if m & Qt.AltModifier else 0) | (0x1000 if m & Qt.MetaModifier else 0))
            if not mods & (0x0100 | 0x1000):
                self.text.setText("A global hotkey on macOS needs ⌘ or ⌃ (for example ⌘⇧2).\nTry again.")
                return
        else:
            mods = ((MOD_CONTROL if m & Qt.ControlModifier else 0) | (MOD_SHIFT if m & Qt.ShiftModifier else 0)
                    | (MOD_ALT if m & Qt.AltModifier else 0) | (MOD_WIN if m & Qt.MetaModifier else 0))
        name = QKeySequence(e.keyCombination()).toString() or f"Key {vk}"
        self.result_key = (vk, mods, name)
        self.accept()

    def keyPressEvent(self, e):
        self._take(e)

    def keyReleaseEvent(self, e):      # Print Screen often arrives only as a release
        if self.result_key is None:
            self._take(e)


def settings_css(t):
    return f"""
QDialog {{ background: {t['window']}; }}
QLabel {{ color: {t['label']}; font: 13px '{UI_FONT}'; background: transparent; }}
QGroupBox {{ background: {t['card']}; border: none; border-radius: 10px; margin-top: 26px;
            padding: 12px 14px 10px 14px; font: 600 12px '{UI_FONT}'; color: {t['label2']}; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 25px; top: 4px;
                   padding: 0; color: {t['label2']}; }}
QCheckBox {{ color: {t['label']}; font: 13px '{UI_FONT}'; spacing: 0px; padding: 4px 0; }}
QCheckBox::indicator {{ width: 38px; height: 22px; }}
QCheckBox::indicator:unchecked {{ image: url({switch_png(False, t)}); }}
QCheckBox::indicator:checked {{ image: url({switch_png(True, t)}); }}
QPushButton {{ background: {t['field']}; color: {t['label']}; border: 1px solid {t['border'].name(QColor.HexArgb)};
              border-radius: 7px; padding: 5px 14px; font: 13px '{UI_FONT}'; }}
QPushButton:hover {{ background: {t['hover']}; }}
QSpinBox {{ background: {t['field']}; color: {t['label']}; border: 1px solid {t['border'].name(QColor.HexArgb)};
           border-radius: 6px; padding: 3px 24px 3px 8px; min-width: 56px; max-width: 84px; font: 13px '{UI_FONT}';
           selection-background-color: {t['accent_fill']}; selection-color: #ffffff; }}
QSpinBox:focus {{ border: 1px solid {t['accent']}; }}
/* Stepper (like macOS): up and down chevrons stacked on the right, each half the height */
QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border; width: 20px; border: none;
           background: transparent; }}
QSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 6px; margin: 1px 1px 0 0; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 6px; margin: 0 1px 1px 0; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {t['hover']}; }}
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {{ background: {t['selected']}; }}
QSpinBox::up-arrow {{ image: url({chevron_png(t['label2'], up=True)}); width: 9px; height: 9px; }}
QSpinBox::down-arrow {{ image: url({chevron_png(t['label2'])}); width: 9px; height: 9px; }}
QSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off {{ image: url({chevron_png(t['border'].name(), up=True)}); }}
QSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off {{ image: url({chevron_png(t['border'].name())}); }}
"""


class SettingsDialog(QDialog):
    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.setWindowTitle(f"{APP_NAME} settings")
        self.setMinimumWidth(420)
        t = self.t = theme()
        self.setStyleSheet(settings_css(t))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 6, 20, 20)
        lay.setSpacing(0)

        def section(title):
            box = QGroupBox(title)
            v = QVBoxLayout(box)
            v.setContentsMargins(14, 8, 14, 8)
            v.setSpacing(0)
            lay.addWidget(box)
            return v

        def row(v, left, right=None, first=False):
            """System-Settings row: label on the leading side, control on the trailing side."""
            if not first:
                line = QFrame()
                line.setFixedHeight(1)
                line.setStyleSheet(f"background:{t['sep']};")
                v.addWidget(line)
            h = QHBoxLayout()
            h.setContentsMargins(0, 7, 0, 7)
            h.addWidget(left, 1)
            if right is not None:
                h.addWidget(right, 0, Qt.AlignRight)
            v.addLayout(h)

        def label(text, secondary=False):
            lb = QLabel(text)
            lb.setWordWrap(True)
            if secondary:
                lb.setStyleSheet(f"color:{t['label2']};")
            return lb

        # General
        g = section("General")
        self.key_lbl = QLabel()
        b = QPushButton("Change…")
        b.clicked.connect(self.change_key)
        row(g, self.key_lbl, b, first=True)
        self.dir_lbl = QLabel()
        self.dir_lbl.setWordWrap(True)
        db = QPushButton("Change…")
        db.clicked.connect(self.change_dir)
        row(g, self.dir_lbl, db)
        self.stamp_cb = QCheckBox()
        self.stamp_cb.setChecked(bool(ctl.settings["stamp"]))
        self.stamp_cb.toggled.connect(self.toggle_stamp)
        row(g, label("Proof stamp (date, time, window)"), self.stamp_cb)
        if IS_WIN or IS_MAC:
            self.auto_cb = QCheckBox()
            self.auto_cb.setChecked(autostart_enabled())
            self.auto_cb.toggled.connect(self.toggle_autostart)
            row(g, label("Start with Windows" if IS_WIN else "Open at login"), self.auto_cb)
        if IS_WIN:
            fb = QPushButton("Free")
            fb.clicked.connect(self.free_key)
            row(g, label("Print Screen key is used by Snipping Tool"), fb)

        # Caption
        c = section("Caption")
        self.cap_spin = QSpinBox()
        self.cap_spin.setRange(12, 64)
        self.cap_spin.setSuffix(" px")
        self.cap_spin.setValue(int(ctl.settings["caption_px"]))
        self.cap_spin.valueChanged.connect(self.set_caption_px)
        row(c, label("Text size"), self.cap_spin, first=True)
        self.fit_cb = QCheckBox()
        self.fit_cb.setChecked(bool(ctl.settings["caption_autofit"]))
        self.fit_cb.toggled.connect(self.set_autofit)
        row(c, label("Grow with wide screenshots (readable on phones)"), self.fit_cb)

        # Tool sizes
        z = section("Default tool sizes")
        self.size_spins = {}
        names = {"pen": "Pen", "line": "Line", "arrow": "Arrow", "rect": "Rectangle",
                 "oval": "Ellipse", "marker": "Highlighter", "text": "Text"}
        for i, k in enumerate(TOOL_KINDS):
            sp = QSpinBox()
            sp.setRange(MIN_W, MAX_W)
            sp.setValue(int(ctl.settings["sizes"][k]))
            sp.valueChanged.connect(lambda v, key=k: self.set_size(key, v))
            self.size_spins[k] = sp
            row(z, label(names[k]), sp, first=i == 0)
        foot = label(f"{MOD.rstrip('+')} + scroll changes the size for one capture.", secondary=True)
        foot.setContentsMargins(28, 8, 4, 0)       # same left edge as the row text (20 + 14 + 14)
        lay.addWidget(foot)
        self._refresh()

    def _refresh(self):
        self.key_lbl.setText(f"Hotkey<br><span style='color:{self.t['label2']}'>"
                             f"{self.ctl.settings['key_name']}</span>")
        self.dir_lbl.setText(f"Save folder<br><span style='color:{self.t['label2']}'>"
                             f"{self.ctl.settings['save_dir']}</span>")

    def set_size(self, key, v):
        self.ctl.settings["sizes"][key] = v
        save_settings(self.ctl.settings)

    def set_caption_px(self, v):
        self.ctl.settings["caption_px"] = v
        save_settings(self.ctl.settings)

    def set_autofit(self, on):
        self.ctl.settings["caption_autofit"] = on
        save_settings(self.ctl.settings)

    def change_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Default folder for screenshots",
                                             self.ctl.settings["save_dir"])
        if d:
            self.ctl.settings["save_dir"] = d
            save_settings(self.ctl.settings)
            self._refresh()

    def change_key(self):
        d = KeyCapture(self)
        if d.exec() and d.result_key:
            vk, mods, name = d.result_key
            self.ctl.settings.update(vk=vk, mods=mods, key_name=name)
            save_settings(self.ctl.settings)
            self.ctl.register_hotkey()
            self._refresh()

    def toggle_stamp(self, on):
        self.ctl.settings["stamp"] = on
        save_settings(self.ctl.settings)

    def toggle_autostart(self, on):
        try:
            set_autostart(on)
        except OSError as ex:
            alert(self, "Couldn't change the start-up setting", str(ex))
            self.auto_cb.blockSignals(True)
            self.auto_cb.setChecked(autostart_enabled())
            self.auto_cb.blockSignals(False)

    def free_key(self):
        try:
            free_prtsc()
            self.ctl.register_hotkey()
            alert(self, "Print Screen is free", "If it still opens Snipping Tool, sign out and sign in again.")
        except OSError as ex:
            alert(self, "Couldn't change the setting", str(ex))


# ---------------------------------------------------------------- tray app
def app_icon_pixmap(size):
    """The app icon drawn natively at any size (64 px design grid, scaled — never upscaled pixels)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 64, size / 64)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(ACCENT))
    p.drawRoundedRect(QRectF(4, 4, 56, 56), 14, 14)
    pen = QPen(QColor("#ffffff"), 4, Qt.CustomDashLine)
    pen.setDashPattern([2, 1.5])
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(15, 15, 34, 22))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(QRectF(15, 42, 34, 7), 3, 3)
    p.end()
    return pm


def tray_icon():
    if not IS_MAC:
        icon = QIcon()
        for sz in (16, 20, 24, 32, 40, 48, 64, 128, 256):   # sharp at every scaling and in Explorer
            icon.addPixmap(app_icon_pixmap(sz))
        return icon
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(ACCENT))
    p.drawRoundedRect(QRectF(4, 4, 56, 56), 14, 14)
    pen = QPen(QColor("#ffffff"), 4, Qt.CustomDashLine)
    pen.setDashPattern([2, 1.5])
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(15, 15, 34, 22))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(QRectF(15, 42, 34, 7), 3, 3)
    p.end()
    if IS_MAC:      # menu bar wants a black template image that macOS tints for light/dark
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#000000"), 5, Qt.CustomDashLine)
        pen.setDashPattern([2, 1.5])
        p.setPen(pen)
        p.drawRect(QRectF(8, 8, 48, 32))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#000000"))
        p.drawRoundedRect(QRectF(8, 46, 48, 10), 4, 4)
        p.end()
        icon = QIcon(pm)
        icon.setIsMask(True)
        return icon
    return QIcon(pm)


class Controller(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.settings = load_settings()
        self.overlay = None
        self.session, self.composer = [], None        # collage in progress
        self.collect_bar = None                       # paused-between-shots bar
        self.bulk = False                             # on only while a set is being collected
        save_settings(self.settings)                  # rewrite once: drops keys no longer used
        self._settings_dlg = None
        self._toasts = []
        self.tray = QSystemTrayIcon(tray_icon())
        menu = self.tray_menu = QMenu()
        self.capture_action = menu.addAction("Capture", lambda: QTimer.singleShot(250, self.capture))
        menu.addAction("Settings…", self.open_settings)
        menu.addSeparator()
        menu.addAction(f"Quit {APP_NAME}", self.quit)
        menu.aboutToShow.connect(self._style_tray_menu)
        self._style_tray_menu()
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_clicked)
        self.tray.show()
        self.hotkey = None
        if IS_WIN or IS_MAC:
            self.hotkey = HotkeyListener() if IS_WIN else MacHotkeyListener()
            self.hotkey.triggered.connect(self.capture)
            self.hotkey.failed.connect(self.notify)
            self.register_hotkey()
        self._update_tooltip()
        where = "menu bar" if IS_MAC else "tray"
        self.notify(f"Running in the {where}. Press {self.settings['key_name']} to capture.")

    def _style_tray_menu(self):
        """Same look as the app's menus; follows light/dark at the moment it opens."""
        style_menu(self.tray_menu, theme())
        self.capture_action.setText(f"Capture\t{self.settings.get('key_name', '')}")

    def _tray_clicked(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            QTimer.singleShot(150, self.capture)

    def _update_tooltip(self):
        self.tray.setToolTip(f"{APP_NAME}  ·  {self.settings['key_name']} to capture")

    def register_hotkey(self):
        s = self.settings
        self._update_tooltip()
        if self.hotkey:
            self.hotkey.start(int(s["vk"]), int(s["mods"]), s["key_name"])
            if int(s["vk"]) == 0x2C and int(s["mods"]) == 0 and prtsc_owned_by_snipping():
                self.notify("Windows still sends Print Screen to Snipping Tool. "
                            "Open Settings and click 'Free Print Screen key'.")

    def notify(self, text):
        """Status messages in the app's own style (glass toast), not the OS balloon."""
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self.toast(text, scr, ms=4500)

    def toast(self, text, screen, ms=1600):
        t = Toast(text, screen, ms)
        self._toasts.append(t)
        t.destroyed.connect(lambda *_: self._toasts.remove(t) if t in self._toasts else None)
        t.show()

    def capture(self):
        if self.overlay:
            if self.overlay.on_hold:
                self.overlay.resume()
            else:
                self.overlay._grab_focus()
            return
        busy = [w for w in (self.composer, self.collect_bar) if w is not None and w.isVisible()]
        if busy:
            for w in busy:
                w.hide()                               # never capture our own windows
            QTimer.singleShot(250, self.capture)
            return
        title = mac_frontmost_app() if IS_MAC else foreground_title()
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if IS_MAC:
            if not mac_can_capture():
                who = APP_NAME if getattr(sys, "frozen", False) else "Python (or Terminal)"
                self.notify("Allow Screen Recording: System Settings > Privacy & Security > "
                            f"Screen & System Audio Recording > turn on {who}. "
                            "Then quit and reopen CaptionShot.")
                return
            pix = mac_grab(screen)
        else:
            pix = screen.grabWindow(0)
        if pix.isNull():
            self.notify("Could not capture the screen. Try again.")
            return
        stamp = ""
        if self.settings["stamp"]:
            stamp = datetime.datetime.now().strftime("%d %b %Y, %H:%M")
            if title:
                stamp += f"  ·  {title}"
        self.overlay = Overlay(self, screen, pix, stamp)
        self.overlay.show()

    def pause_collection(self):
        """Between shots: show the bar; the hotkey or Capture continues the set."""
        if not self.session:
            self.bulk = False
            self.hide_collect_bar()
            return
        if self.collect_bar is None:
            self.collect_bar = CollectBar(self)
        self.collect_bar.refresh()
        self.collect_bar.place()
        self.collect_bar.show()
        self.collect_bar.raise_()

    def hide_collect_bar(self):
        if self.collect_bar is not None:
            self.collect_bar.hide()

    def copy_collection(self):
        if not self.session:
            return
        overall = self.composer.overall.toPlainText() if self.composer is not None else ""
        layout = self.settings.get("collage_layout", "stack")
        img = compose_collage(self.session, overall, layout, self.settings)
        QApplication.clipboard().setImage(img)
        n = len(self.session)
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self.toast(f"{n} shot{'s' * (n != 1)} copied as one image  ·  paste with {MOD}V", scr)
        self.session.clear()
        self.bulk = False
        self.hide_collect_bar()
        if self.composer is not None:
            self.composer.close()

    def discard_collection(self):
        n = len(self.session)
        if n and not alert(None, f"Discard {n} shot{'s' * (n > 1)}?",
                           "They haven't been copied or saved.", "Discard", "Cancel", destructive=True):
            return
        self.session.clear()
        self.bulk = False
        self.hide_collect_bar()
        if self.composer is not None:
            self.composer.close()

    def open_composer(self):
        self.hide_collect_bar()
        if not self.session:
            return
        if self.composer is None:
            self.composer = Composer(self)
        else:
            self.composer.rebuild()
        self.composer.show()
        self.composer.raise_()
        self.composer.activateWindow()

    def edit_shot(self, i):
        if not (0 <= i < len(self.session)) or self.overlay:
            return
        shot = self.session[i]
        screen = shot.screen if shot.screen in QGuiApplication.screens() else QGuiApplication.primaryScreen()
        self.overlay = Overlay(self, screen, shot.pix, shot.stamp, edit_index=i)
        self.overlay.show()
        self.overlay.restore(shot)

    def open_settings(self):
        if self._settings_dlg and self._settings_dlg.isVisible():
            self._settings_dlg.activateWindow()
            return
        self._settings_dlg = SettingsDialog(self)
        self._settings_dlg.show()
        self._settings_dlg.activateWindow()

    def quit(self):
        if self.hotkey:
            self.hotkey.stop()
        self.tray.hide()
        self.app.quit()


_MUTEX = None


def selftest(app):
    """Packaging check (used by build.bat): fonts bundled, icons render, editor builds, Hindi caption
    composes. Never touches the hotkey, tray or settings. Writes the result to %TEMP% because a
    windowed .exe has no console. Exit code 0 = OK."""
    out = os.path.join(tempfile.gettempdir(), "captionshot_selftest.txt")
    problems = []
    try:
        if "Mukta" not in FONT_FAMILIES:
            problems.append("Mukta font not bundled (fonts folder missing)")
        if make_icon("copy").pixmap(24, 24).isNull() or tray_icon().isNull():
            problems.append("icons do not render")
        if tool_cursor("pen", 1.0).pixmap().isNull():
            problems.append("SVG cursors do not render (QtSvg missing)")
        if len(arrow_polyline([(0.0, 0.0), (50.0, 1.0), (100.0, 0.0)])) != 2 \
                or len(arrow_polyline([(0.0, 0.0), (50.0, 60.0), (100.0, 0.0)])) < 3:
            problems.append("curved arrow fitting failed")
        shot = QImage(400, 120, QImage.Format_RGB32)
        shot.fill(QColor("#3366cc"))
        img = compose(shot, "भुगतान सफल रहा · payment done", "stamp", 1.0, 20)
        if img.width() != 400 or img.height() <= 120:
            problems.append("caption compose failed")
        class _Ctl:                                    # minimal stand-in: no hotkey, no tray
            settings = dict(DEFAULTS, sizes=dict(DEFAULTS["sizes"]))
            overlay, session, composer, collect_bar, bulk = None, [], None, None, False
            def toast(self, *a): pass
            def notify(self, *a): pass
        pm = QPixmap(640, 400)
        pm.fill(QColor("#ffffff"))
        Overlay(_Ctl(), QGuiApplication.primaryScreen(), pm, "stamp").deleteLater()
    except Exception as ex:                            # report, never crash the build
        problems.append(f"{type(ex).__name__}: {ex}")
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"{APP_NAME} {APP_VERSION} selftest: " + ("OK" if not problems else "FAIL\n" + "\n".join(problems)))
    return 0 if not problems else 1


def main():
    global _MUTEX
    app = QApplication(sys.argv)                  # first, so even this message looks like the app
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    load_fonts()
    app.setFont(_font(13))
    app.setWindowIcon(tray_icon())
    if "--selftest" in sys.argv:
        return selftest(app)
    where = "menu bar" if IS_MAC else "tray"
    if IS_WIN:
        _MUTEX = kernel32.CreateMutexW(None, False, "Local\\CaptionShot_single_instance")
        if ctypes.get_last_error() == 183:   # ERROR_ALREADY_EXISTS
            alert(None, f"{APP_NAME} is already running", f"Find it in the {where}, or press its hotkey.")
            return 0
    else:
        lock = QLockFile(os.path.join(QDir.tempPath(), "captionshot.lock"))
        if not lock.tryLock(100):
            alert(None, f"{APP_NAME} is already running", f"Find it in the {where}, or press its hotkey.")
            return 0
        app._lock = lock
    if IS_MAC:
        mac_hide_dock_icon()
    _t = theme()
    app.setStyleSheet(f"QToolTip {{ background:{_t['menu']}; color:{_t['label']}; border:1px solid "
                      f"{_t['border'].name(QColor.HexArgb)}; border-radius:6px;"
                      " padding:4px 6px; }")
    if not QSystemTrayIcon.isSystemTrayAvailable():
        alert(None, "No system tray found", f"{APP_NAME} lives in the {where} and can't start without it.")
        return 1
    app.ctl = Controller(app)   # keep a reference for the app's lifetime
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
