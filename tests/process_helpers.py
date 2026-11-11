"""Shared process-lifetime checks for subprocess tests, not job-status polling."""

import os
import time
from pathlib import Path


def process_is_running(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER: the process no longer exists.
                return False
            raise ctypes.WinError(error)
        try:
            state = kernel.WaitForSingleObject(handle, 0)
            if state == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
            return state == 0x00000102
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A terminated orphan may remain a zombie until the OS reaps it.
    status = Path(f"/proc/{pid}/status")
    try:
        if status.exists() and "State:\tZ" in status.read_text():
            return False
    except FileNotFoundError:
        return False
    return True


def wait_for_process_exit(pid, timeout=10):
    """Bound cleanup on actual process exit, even without a parent-owned Popen."""
    deadline = time.monotonic() + timeout
    while process_is_running(pid):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Worker {pid} did not exit within {timeout} seconds")
        time.sleep(min(0.02, remaining))
