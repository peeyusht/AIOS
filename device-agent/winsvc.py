"""
The little that makes a Python program a Windows service: tell the service manager we are running, and stop
when it says so. Standard library only (ctypes), so the installer carries no service wrapper of someone
else's.

    run("ShadowFilerAgent", work)      # work(stop) runs until the threading.Event `stop` is set

`run` returns False when the program was not started by the service manager (somebody ran it by hand).
"""
import ctypes
import threading
from ctypes import wintypes

STOPPED, STOP_PENDING, RUNNING = 1, 3, 4
CONTROL_STOP, CONTROL_INTERROGATE, CONTROL_SHUTDOWN = 1, 4, 5
NOT_STARTED_BY_SERVICE_MANAGER = 1063
STOP_SECONDS = 15


class _Status(ctypes.Structure):
    _fields_ = [(n, wintypes.DWORD) for n in ("type", "state", "accepts", "exit_code", "specific", "checkpoint", "hint")]


_Handler = ctypes.WINFUNCTYPE(wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p)
_Main = ctypes.WINFUNCTYPE(None, wintypes.DWORD, ctypes.c_void_p)


class _Entry(ctypes.Structure):
    _fields_ = [("name", wintypes.LPWSTR), ("main", _Main)]


def run(name: str, work) -> bool:
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    adv.RegisterServiceCtrlHandlerExW.restype = ctypes.c_void_p
    adv.RegisterServiceCtrlHandlerExW.argtypes = [wintypes.LPCWSTR, _Handler, ctypes.c_void_p]
    adv.SetServiceStatus.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Status)]
    adv.StartServiceCtrlDispatcherW.argtypes = [ctypes.POINTER(_Entry)]
    stop, handle = threading.Event(), [None]

    def report(state: int, hint_ms: int = 0) -> None:
        accepts = 0x1 | 0x4 if state == RUNNING else 0        # stop, and the PC shutting down
        adv.SetServiceStatus(handle[0], ctypes.byref(_Status(0x10, state, accepts, 0, 0, 0, hint_ms)))

    def on_control(control, _event, _data, _context):
        if control in (CONTROL_STOP, CONTROL_SHUTDOWN):
            report(STOP_PENDING, (STOP_SECONDS + 5) * 1000)
            stop.set()
            return 0
        return 0 if control == CONTROL_INTERROGATE else 120      # 120: not something this service does

    def main(_argc, _argv):
        handle[0] = adv.RegisterServiceCtrlHandlerExW(name, handler, None)
        if not handle[0]:
            return
        report(RUNNING)
        t = threading.Thread(target=work, args=(stop,), daemon=True, name="work")
        t.start()
        while t.is_alive() and not stop.is_set():
            t.join(1)
        t.join(STOP_SECONDS)       # a reading of the PC in progress is given a moment, then left behind
        report(STOPPED)

    handler, entry = _Handler(on_control), _Main(main)       # kept alive here for as long as the service runs
    table = (_Entry * 2)(_Entry(name, entry), _Entry(None, _Main()))
    if not adv.StartServiceCtrlDispatcherW(table):
        err = ctypes.get_last_error()
        if err == NOT_STARTED_BY_SERVICE_MANAGER:
            return False
        raise ctypes.WinError(err)
    return True
