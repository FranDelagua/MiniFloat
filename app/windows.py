import ctypes
import sys
from ctypes import wintypes


def place_directly_below(window_handle: int, upper_handle: int) -> None:
    if sys.platform != "win32":
        raise OSError("El modo PIN OFF solo está disponible en Windows.")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    set_window_pos = user32.SetWindowPos
    set_window_pos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    set_window_pos.restype = wintypes.BOOL
    no_size, no_move, no_activate, no_owner_zorder = 0x0001, 0x0002, 0x0010, 0x0200
    if not set_window_pos(
        window_handle,
        upper_handle,
        0,
        0,
        0,
        0,
        no_size | no_move | no_activate | no_owner_zorder,
    ):
        raise ctypes.WinError(ctypes.get_last_error())
