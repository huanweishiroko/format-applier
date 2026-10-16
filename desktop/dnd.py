# -*- coding: utf-8 -*-
"""Windows 原生文件拖放（WM_DROPFILES），不依赖 tkdnd。

为什么要有这个模块（Phase 4 实测结论）：
    tkinterdnd2/tkdnd 的"接收拖放"在本机实测完全失效 —— 连官方用法
    （``TkinterDnD.Tk()`` + 普通 ``tkinter.Frame`` + ``drop_target_register``）
    都收不到任何 ``<<DropEnter>>`` / ``<<Drop>>`` 事件，而拖放**源**侧是正常的，
    OLE 层注册也是成功的（``RevokeDragDrop`` 返回 S_OK），但 drop 就是不进 Tk。
    结论：tkdnd 的接收侧在这套环境里不可用，必须换实现。

本模块的做法：用纯 ctypes 走 Windows 老牌的 ``WM_DROPFILES`` 通道 ——
    ``DragAcceptFiles`` 让窗口成为投放目标（拖进来时光标会出现加号），
    再用两条路把 ``WM_DROPFILES`` 捞出来：
      1. 子类化顶层窗口过程（消息被 Send 到窗口时命中）；
      2. Tk 定时器里用 ``PeekMessage`` 从消息队列里捞（消息被 Post 时命中）。
    两条路谁先拿到算谁的，同一个 HDROP 只会被处理一次。

线程/GIL 注意（踩过的坑）：
    窗口过程在 Win32 消息分发里执行，**此时不持有 CPython 的 GIL**。在里面调用
    任何 Python 代码都会崩：``Fatal Python error: PyEval_RestoreThread: the
    function must be called with the GIL held``。所以窗口过程里只做纯 C 的事
    （把 HDROP 句柄写进 ctypes 数组），解析与用户回调都由 Tk 定时器在主线程执行。

用法::

    import dnd
    dnd.hook(widget, on_drop)    # on_drop(paths: list[str]) -> None，在 Tk 主线程调用
    ...
    dnd.unhook()                 # 退出前调用，恢复原窗口过程
"""

from __future__ import annotations

import ctypes
import os as _os
import sys as _sys
import time as _time
from typing import Callable, Dict, List

__all__ = ["hook", "unhook", "available", "is_hooked", "parse_drop_files",
           "set_hover_callback"]

# 设 DND_DEBUG=1 会在控制台打印每个收到的 WM_DROPFILES，用于排查
_DEBUG = bool(_os.environ.get("DND_DEBUG"))

WM_DROPFILES = 0x0233
GWL_WNDPROC = -4
GA_ROOT = 2
PM_REMOVE = 0x0001
DND_FILES = "DND_Files"  # 与 tkinterdnd2 同名常量，便于上层统一处理

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, ctypes.c_uint,
                             ctypes.c_size_t, ctypes.c_ssize_t)


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                ("time", ctypes.c_uint32), ("pt_x", ctypes.c_long),
                ("pt_y", ctypes.c_long)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("flags", ctypes.c_uint32),
                ("hCursor", ctypes.c_void_p), ("ptScreenPos", POINT)]


VK_LBUTTON = 0x01
CURSOR_SHOWING = 0x00000001
IDC_ARROW = 32512
IDC_IBEAM = 32513
_HOVER_POLL_MS = 60     # 悬停检测轮询间隔
_HOVER_MIN_MS = 250     # 按住鼠标多久才算"正在拖东西"（压住误触又不至于太迟钝）


# --- 窗口过程只碰这几个纯 C 对象，绝不调用 Python ---
_MAX_SLOTS = 8
_PENDING = (ctypes.c_int * _MAX_SLOTS)()
_PENDING_HDROP = (ctypes.c_ssize_t * _MAX_SLOTS)()
_SLOTS: Dict[int, int] = {}      # hwnd -> 槽位下标 + 1
_STATE: Dict[int, dict] = {}     # hwnd -> {old_proc, proc, widget}
_OUR_PID = 0                     # 本进程 pid，用于判断光标是否在自家窗口上

_user32 = None
_shell32 = None
_CallWindowProcW = None
_DragAcceptFiles = None
_DragQueryFileW = None
_DragFinish = None
_PeekMessageW = None


def _libs():
    """惰性加载并缓存 Win32 函数（顺带缓存函数指针，供窗口过程直接用）。"""
    global _user32, _shell32, _CallWindowProcW, _DragAcceptFiles
    global _DragQueryFileW, _DragFinish, _PeekMessageW
    if _user32 is not None:
        return _user32, _shell32

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetAncestor.restype = ctypes.c_void_p
    user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_void_p
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                                       ctypes.c_size_t, ctypes.c_ssize_t]
    user32.CallWindowProcW.restype = LRESULT
    user32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), ctypes.c_void_p, ctypes.c_uint,
                                    ctypes.c_uint, ctypes.c_uint]
    user32.PeekMessageW.restype = ctypes.c_bool
    user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetWindow.restype = ctypes.c_void_p
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.EnumWindows.argtypes = [ctypes.c_void_p, ctypes.c_ssize_t]
    user32.EnumWindows.restype = ctypes.c_bool
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.GetCursorPos.restype = ctypes.c_bool
    user32.WindowFromPoint.argtypes = [POINT]
    user32.WindowFromPoint.restype = ctypes.c_void_p
    user32.GetCursorInfo.argtypes = [ctypes.POINTER(CURSORINFO)]
    user32.GetCursorInfo.restype = ctypes.c_bool
    user32.LoadCursorW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.LoadCursorW.restype = ctypes.c_void_p
    shell32.DragAcceptFiles.argtypes = [ctypes.c_void_p, ctypes.c_bool]
    shell32.DragAcceptFiles.restype = None
    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                       ctypes.c_wchar_p, ctypes.c_uint]
    shell32.DragQueryFileW.restype = ctypes.c_uint
    shell32.DragFinish.argtypes = [ctypes.c_void_p]
    shell32.DragFinish.restype = None

    _user32, _shell32 = user32, shell32
    _CallWindowProcW = user32.CallWindowProcW
    _DragAcceptFiles = shell32.DragAcceptFiles
    _DragQueryFileW = shell32.DragQueryFileW
    _DragFinish = shell32.DragFinish
    _PeekMessageW = user32.PeekMessageW
    return user32, shell32


def available() -> bool:
    """当前平台是否支持（仅 Windows）。"""
    if not hasattr(ctypes, "WinDLL"):
        return False
    try:
        _libs()
    except OSError:
        return False
    return True


def parse_drop_files(hdrop) -> List[str]:
    """从 HDROP 句柄里读出被拖入的文件路径列表。"""
    _libs()
    handle = ctypes.c_void_p(hdrop)
    count = _DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
    paths: List[str] = []
    for i in range(count):
        need = _DragQueryFileW(handle, i, None, 0)
        buf = ctypes.create_unicode_buffer(need + 1)
        _DragQueryFileW(handle, i, buf, need + 1)
        if buf.value:
            paths.append(buf.value)
    return paths


def _candidate_hwnds(widget) -> List[int]:
    """找出所有可能收到拖放消息的窗口。

    Tk 在 Windows 上一个 toplevel 不止一个窗口：外壳包装窗口、Tk 自己的 child
    窗口，以及一批无名子窗口。「哪个窗口实际收到 WM_DROPFILES」在不同环境里
    并不一致（实测：只挂包装窗口时，真实拖放收不到，而合成 PostMessage 能收到）。
    所以这里把本进程所有窗口枚举一遍，挑出属于本 toplevel 的，一个都不漏。
    """
    user32, _ = _libs()
    child = int(widget.winfo_id())
    top = int(user32.GetAncestor(ctypes.c_void_p(child), GA_ROOT) or 0)

    found: List[int] = []
    for hwnd in (top, child):
        if hwnd and hwnd not in found:
            found.append(hwnd)

    pid = _window_pid(top or child)
    for hwnd in _process_windows(pid):
        if hwnd not in found:
            found.append(hwnd)
    return found[: _MAX_SLOTS]


def _window_pid(hwnd: int) -> int:
    user32, _ = _libs()
    pid = ctypes.c_ulong(0)
    user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
    return int(pid.value)


def _window_title(hwnd: int) -> str:
    user32, _ = _libs()
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(ctypes.c_void_p(hwnd), buf, 256)
    return buf.value


def _window_class(hwnd: int) -> str:
    user32, _ = _libs()
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(ctypes.c_void_p(hwnd), buf, 256)
    return buf.value


def _direct_children(hwnd: int) -> List[int]:
    """直接子窗口列表。"""
    user32, _ = _libs()
    out: List[int] = []
    child = user32.GetWindow(ctypes.c_void_p(hwnd), 5)  # GW_CHILD
    while child:
        c = int(child)
        out.append(c)
        child = user32.GetWindow(ctypes.c_void_p(c), 2)  # GW_HWNDNEXT
    return out


def _process_windows(pid: int) -> List[int]:
    """本进程的所有窗口：所有顶层窗口 + 递归子窗口。"""
    user32, _ = _libs()
    tops: List[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_ssize_t)
    def collect(hwnd, _lparam):
        tops.append(int(hwnd))
        return True

    user32.EnumWindows(collect, 0)

    out: List[int] = []
    for hwnd in tops:
        if _window_pid(hwnd) != pid:
            continue
        out.append(hwnd)
        stack = [hwnd]
        guard = 0
        while stack and guard < 500:
            guard += 1
            for sub in _direct_children(stack.pop()):
                if sub not in out:
                    out.append(sub)
                    stack.append(sub)
    return out


def _make_proc(hwnd_key: int) -> WNDPROC:
    @WNDPROC
    def proc(hwnd, msg, wparam, lparam):  # noqa: WPS430 - 闭包捕获 hwnd_key
        if msg == WM_DROPFILES:
            slot = _SLOTS.get(hwnd_key, 0)
            if slot and not _PENDING[slot - 1]:
                _PENDING[slot - 1] = 1
                _PENDING_HDROP[slot - 1] = wparam
            if _DEBUG:
                print(f"[dnd.debug] 窗口 hwnd={hwnd_key} 收到 WM_DROPFILES "
                      f"slot={slot}", file=_sys.stderr)
            return 0
        state = _STATE.get(hwnd_key)
        if state is None:
            return 0
        return _CallWindowProcW(state["old_proc"], ctypes.c_void_p(hwnd), msg,
                                wparam, lparam)

    return proc


def _allow_message(hwnd: int) -> None:
    """让 UIPI 别拦 WM_DROPFILES（拖放源提权时会被拦掉）。"""
    user32, _ = _libs()
    changer = getattr(user32, "ChangeWindowMessageFilterEx", None)
    if changer is None:
        return
    try:
        changer.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
                            ctypes.c_void_p]
        changer.restype = ctypes.c_bool
        MSGFLT_ALLOW = 1
        changer(ctypes.c_void_p(hwnd), WM_DROPFILES, MSGFLT_ALLOW, None)
        changer(ctypes.c_void_p(hwnd), 0x0049, MSGFLT_ALLOW, None)  # WM_COPYGLOBALDATA
    except Exception:  # noqa: BLE001
        pass


def _verify_subclass(hwnd: int) -> bool:
    """确认窗口过程真的换成了我们的（SetWindowLongPtrW 可能静默失败）。"""
    user32, _ = _libs()
    state = _STATE.get(hwnd)
    if state is None:
        return False
    current = int(user32.GetWindowLongPtrW(ctypes.c_void_p(hwnd), GWL_WNDPROC) or 0)
    expected = ctypes.cast(state["proc"], ctypes.c_void_p).value or 0
    return current == expected


def _sniff_queue() -> int:
    """从本线程消息队列里取出一条 WM_DROPFILES，返回 HDROP（没有则 0）。"""
    if _PeekMessageW is None:
        return 0
    msg = MSG()
    if _PeekMessageW(ctypes.byref(msg), None, WM_DROPFILES, WM_DROPFILES, PM_REMOVE):
        return int(msg.wParam)
    return 0


# --------------------------------------------------------------------------- #
# 悬停（拖东西经过窗口）检测
# --------------------------------------------------------------------------- #
# WM_DROPFILES 只在"松开"时到达，中间悬停阶段没有任何消息。而窗口一旦
# DragAcceptFiles，Windows 在拖动经过时就会把光标显示成加号 —— 我们据此反推：
# 左键按住 + 光标在本窗口上，就认为"有东西正被拖到窗口上"，用于给用户视觉反馈。
_HOVER_CB = None
_HOVER_ON = False
_HOVER_SINCE = 0.0


def set_hover_callback(cb) -> None:
    """注册悬停状态回调：``cb(hovering: bool)``，只能设一个。

    回调在 Tk 主线程被调用（由定时器投递），可直接操作控件。
    """
    global _HOVER_CB
    _HOVER_CB = cb


def _cursor_over_our_windows() -> bool:
    """光标是否落在本进程的窗口上（拖放到窗口任意位置都算）。

    用"窗口属于本进程"判断比枚举具体 HWND 更稳：拖拽区里的 CTk 子控件、
    滚动容器等都是本进程的窗口，都会命中。
    """
    user32, _ = _libs()
    pt = POINT()
    if not user32.GetCursorPos(ctypes.byref(pt)):
        return False
    if not _OUR_PID:
        return False
    hwnd = int(user32.WindowFromPoint(pt) or 0)
    return bool(hwnd) and _window_pid(hwnd) == _OUR_PID


def _hover_dbg(msg: str) -> None:
    if _DEBUG:
        print(f"[dnd.debug] {msg}", file=_sys.stderr)


def _hover_tick() -> None:
    """由 _pump 驱动的悬停状态机。

    判断口径：左键按住超过 ``_HOVER_MIN_MS`` 且光标落在本进程窗口上。
    为什么不看光标形状：实测真实拖放过程中 ``GetCursorInfo`` 返回的仍是标准箭头
    （0x10003），靠"光标不是箭头"来判断不可行。而"拖拽区是否高亮"最终由使用者
    自己的回调决定（可以再去判断光标是否落在拖拽区上）。
    """
    global _HOVER_ON, _HOVER_SINCE
    user32, _ = _libs()
    pressed = bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
    now = _time.monotonic()
    if pressed:
        if not _HOVER_SINCE:
            _HOVER_SINCE = now
        held_ms = (now - _HOVER_SINCE) * 1000
        hovering = held_ms >= _HOVER_MIN_MS and _cursor_over_our_windows()
        if _DEBUG and hovering != _HOVER_ON:
            _hover_dbg(f"held={int(held_ms)}ms -> hovering={hovering}")
    else:
        _HOVER_SINCE = 0.0
        hovering = False
    if hovering != _HOVER_ON:
        _HOVER_ON = hovering
        if _HOVER_CB is not None:
            try:
                _HOVER_CB(hovering)
            except Exception as exc:  # noqa: BLE001 - 回调异常不影响消息循环
                print(f"[dnd] 悬停回调异常：{exc}", file=_sys.stderr)


def _emit(widget, hdrop: int, via: str) -> None:
    """解析 HDROP 并回调（主线程）。"""
    if not hdrop:
        return
    try:
        paths = parse_drop_files(hdrop)
    except Exception as exc:  # noqa: BLE001
        paths = []
        print(f"[dnd] 解析 HDROP 失败（{via}）：{exc}", file=_sys.stderr)
    finally:
        try:
            _DragFinish(ctypes.c_void_p(hdrop))
        except Exception:  # noqa: BLE001
            pass
    if not paths:
        return
    for state in _STATE.values():
        if state["widget"] is widget:
            try:
                state["callback"](paths)
            except Exception as exc:  # noqa: BLE001 - 回调异常不影响消息循环
                print(f"[dnd] 回调异常（{via}）：{exc}", file=_sys.stderr)
            break


def _pump(widget, hwnd: int) -> None:
    """Tk 定时器（主线程）：取窗口过程暂存的 HDROP；取不到再从消息队列捞。"""
    state = _STATE.get(hwnd)
    if state is None or state["widget"] is not widget:
        return
    try:
        widget.after(60, lambda: _pump(widget, hwnd))  # 先排下一次，抛错也不停摆
    except Exception:  # noqa: BLE001 - 窗口正在销毁
        return

    slot = _SLOTS.get(hwnd, 0)
    if slot and _PENDING[slot - 1]:
        hdrop = int(_PENDING_HDROP[slot - 1])
        _PENDING[slot - 1] = 0
        _PENDING_HDROP[slot - 1] = 0
        _emit(widget, hdrop, via="窗口过程")
        return
    sniffed = _sniff_queue()
    if sniffed:
        _emit(widget, sniffed, via="消息队列")
        return
    _hover_tick()
    _adopt_new_windows(widget)


def _adopt_new_windows(widget) -> None:
    """补挂界面后续新建的窗口。

    Tk/CTk 在启动之后还会创建窗口（换页、弹窗等），只在启动时枚举一遍会漏掉它们，
    而漏掉的那个窗口如果正好是真实拖放的目标，就会「光标有加号但收不到消息」。
    这里定时复查一遍，把新窗口补挂上。
    """
    user32, shell32 = _libs()
    try:
        child = int(widget.winfo_id())
        top = int(user32.GetAncestor(ctypes.c_void_p(child), GA_ROOT) or 0)
        pid = _window_pid(top or child)
        known = set(_STATE)
        for hwnd in _process_windows(pid):
            if hwnd in known or len(_SLOTS) >= _MAX_SLOTS:
                continue
            slot = len(_SLOTS) + 1
            proc = _make_proc(hwnd)
            old = user32.SetWindowLongPtrW(ctypes.c_void_p(hwnd), GWL_WNDPROC,
                                           ctypes.cast(proc, ctypes.c_void_p))
            if not old:
                continue
            shell32.DragAcceptFiles(ctypes.c_void_p(hwnd), True)
            _allow_message(hwnd)
            _SLOTS[hwnd] = slot
            _STATE[hwnd] = {"old_proc": old, "proc": proc, "widget": widget,
                            "callback": _callback_of(widget)}
            _pump(widget, hwnd)
            if _DEBUG:
                print(f"[dnd] 补挂新窗口 hwnd={hwnd} class={_window_class(hwnd)}",
                      file=_sys.stderr)
    except Exception:  # noqa: BLE001
        pass


def _callback_of(widget):
    for state in _STATE.values():
        if state["widget"] is widget:
            return state["callback"]
    return lambda _paths: None


def hook(widget, on_drop: Callable[[List[str]], None]) -> bool:
    """让 ``widget`` 所属的顶层窗口接收文件拖放。成功返回 True。

    重复对同一个 widget 调用是幂等的（只更新回调）。
    """
    if not available():
        return False
    user32, shell32 = _libs()
    try:
        hwnds = _candidate_hwnds(widget)
    except Exception:  # noqa: BLE001
        return False
    if not hwnds:
        return False

    global _OUR_PID
    _OUR_PID = _window_pid(hwnds[0])

    # 已经挂过 -> 只更新回调
    if any(h in _STATE for h in hwnds):
        for h in hwnds:
            st = _STATE.get(h)
            if st is not None:
                st["callback"] = on_drop
        return True

    installed = []
    for hwnd in hwnds:
        if len(_SLOTS) >= _MAX_SLOTS:
            break
        slot = len(_SLOTS) + 1
        proc = _make_proc(hwnd)
        old = user32.SetWindowLongPtrW(ctypes.c_void_p(hwnd), GWL_WNDPROC,
                                       ctypes.cast(proc, ctypes.c_void_p))
        if not old:
            continue
        shell32.DragAcceptFiles(ctypes.c_void_p(hwnd), True)
        _allow_message(hwnd)
        _SLOTS[hwnd] = slot
        _STATE[hwnd] = {"old_proc": old, "proc": proc, "widget": widget,
                        "callback": on_drop}
        installed.append(hwnd)

    if not installed:
        return False
    for hwnd in installed:  # 每个已挂窗口各起一个 Tk 定时器
        _pump(widget, hwnd)
    if _DEBUG:
        print(f"[dnd] 拖放目标窗口 {len(installed)} 个：", file=_sys.stderr)
        for hwnd in installed:
            print(f"       hwnd={hwnd:<10d} class={_window_class(hwnd):<16s} "
                  f"子类化生效={_verify_subclass(hwnd)} title={_window_title(hwnd)!r}",
                  file=_sys.stderr)
    return True


def is_hooked(widget) -> bool:
    try:
        return any(h in _STATE for h in _candidate_hwnds(widget))
    except Exception:  # noqa: BLE001
        return False


def unhook(widget=None) -> None:
    """恢复原窗口过程。不调用也能跑，但退出前调用更稳。"""
    if not _STATE:
        return
    user32, shell32 = _libs()
    for hwnd in list(_STATE):
        state = _STATE.pop(hwnd, None)
        if state is None:
            continue
        slot = _SLOTS.pop(hwnd, 0)
        if slot:
            _PENDING[slot - 1] = 0
            _PENDING_HDROP[slot - 1] = 0
        try:
            shell32.DragAcceptFiles(ctypes.c_void_p(hwnd), False)
            user32.SetWindowLongPtrW(ctypes.c_void_p(hwnd), GWL_WNDPROC,
                                     ctypes.cast(state["old_proc"], ctypes.c_void_p))
        except Exception:  # noqa: BLE001
            pass
