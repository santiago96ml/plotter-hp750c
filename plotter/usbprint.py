"""Raw byte access to USB printer-class devices (USBPRINT) on Windows.

This bypasses the print spooler completely. The DesignJet 750C has no 64-bit
driver, but it does not need one: `usbprint.sys` already exposes the adapter as
a device interface, and the plotter understands HP-GL/2 commands sent as plain
bytes. We open that interface and stream data to the bulk OUT pipe.

No administrator privileges are required.
"""

from __future__ import annotations

import ctypes
import time
import uuid
from ctypes import POINTER, Structure, byref, c_void_p, create_string_buffer, wintypes
from dataclasses import dataclass

# {28d78fad-5a12-11d1-ae5b-0000f803a8c2} == GUID_DEVINTERFACE_USBPRINT
USBPRINT_GUID = "28d78fad-5a12-11d1-ae5b-0000f803a8c2"

GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
ERROR_IO_PENDING = 997
ERROR_NO_MORE_ITEMS = 259
WAIT_OBJECT_0 = 0
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class GUID(Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


class SP_DEVICE_INTERFACE_DATA(Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.c_size_t),
    ]


class SP_DEVICE_INTERFACE_DETAIL_DATA_W(Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("DevicePath", wintypes.WCHAR * 260),
    ]


# cbSize is the size of the fixed header, not of this over-sized buffer.
_DETAIL_CB_SIZE = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6


class OVERLAPPED(Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_setupapi = ctypes.WinDLL("setupapi", use_last_error=True)

_setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
_setupapi.SetupDiGetClassDevsW.argtypes = [
    POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD
]
_setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    wintypes.HANDLE, c_void_p, POINTER(GUID), wintypes.DWORD,
    POINTER(SP_DEVICE_INTERFACE_DATA),
]
_setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wintypes.HANDLE, POINTER(SP_DEVICE_INTERFACE_DATA),
    POINTER(SP_DEVICE_INTERFACE_DETAIL_DATA_W), wintypes.DWORD,
    POINTER(wintypes.DWORD), c_void_p,
]
_setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]

_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, c_void_p,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]
_k32.WriteFile.argtypes = [
    wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
    POINTER(wintypes.DWORD), POINTER(OVERLAPPED),
]
_k32.CreateEventW.restype = wintypes.HANDLE
_k32.CreateEventW.argtypes = [c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.GetOverlappedResult.argtypes = [
    wintypes.HANDLE, POINTER(OVERLAPPED), POINTER(wintypes.DWORD), wintypes.BOOL
]


def _guid(value: str) -> GUID:
    u = uuid.UUID(value)
    return GUID(u.fields[0], u.fields[1], u.fields[2], (wintypes.BYTE * 8)(*u.bytes[8:]))


@dataclass(frozen=True)
class Device:
    path: str

    @property
    def short(self) -> str:
        return self.path.split("#")[1] if "#" in self.path else self.path


def list_devices() -> list[Device]:
    """Return every present USBPRINT device interface."""
    guid = _guid(USBPRINT_GUID)
    flags = DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    handle = _setupapi.SetupDiGetClassDevsW(byref(guid), None, None, flags)
    if handle == INVALID_HANDLE_VALUE:
        raise OSError(f"SetupDiGetClassDevs failed: {ctypes.get_last_error()}")

    found: list[Device] = []
    try:
        index = 0
        while True:
            iface = SP_DEVICE_INTERFACE_DATA()
            iface.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            ok = _setupapi.SetupDiEnumDeviceInterfaces(
                handle, None, byref(guid), index, byref(iface)
            )
            if not ok:
                err = ctypes.get_last_error()
                if err == ERROR_NO_MORE_ITEMS:
                    break
                raise OSError(f"SetupDiEnumDeviceInterfaces failed: {err}")

            required = wintypes.DWORD(0)
            _setupapi.SetupDiGetDeviceInterfaceDetailW(
                handle, byref(iface), None, 0, byref(required), None
            )
            buf = create_string_buffer(
                max(required.value, ctypes.sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_W))
            )
            detail = ctypes.cast(buf, POINTER(SP_DEVICE_INTERFACE_DETAIL_DATA_W))
            detail.contents.cbSize = _DETAIL_CB_SIZE
            if not _setupapi.SetupDiGetDeviceInterfaceDetailW(
                handle, byref(iface), detail, required.value, byref(required), None
            ):
                raise OSError(
                    f"SetupDiGetDeviceInterfaceDetail failed: {ctypes.get_last_error()}"
                )
            found.append(Device(detail.contents.DevicePath))
            index += 1
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(handle)
    return found


class UsbPrinter:
    """Write-only channel to a USB printer-class device."""

    def __init__(self, path: str | None = None, timeout: float = 20.0):
        devices = list_devices()
        if not devices:
            raise RuntimeError(
                "No USB printer device found. Is the plotter adapter plugged in?"
            )
        self.device = Device(path) if path else devices[0]
        self.timeout = timeout
        self._handle = _k32.CreateFileW(
            self.device.path, GENERIC_WRITE, 0, None, OPEN_EXISTING,
            FILE_FLAG_OVERLAPPED, None,
        )
        if self._handle == INVALID_HANDLE_VALUE:
            raise OSError(
                f"Cannot open {self.device.short}: error {ctypes.get_last_error()}"
            )

    def write(self, data: bytes, chunk: int = 4096) -> int:
        sent = 0
        while sent < len(data):
            block = data[sent:sent + chunk]
            event = _k32.CreateEventW(None, True, False, None)
            ov = OVERLAPPED()
            ov.hEvent = event
            written = wintypes.DWORD(0)
            ok = _k32.WriteFile(
                self._handle, block, len(block), byref(written), byref(ov)
            )
            if not ok:
                err = ctypes.get_last_error()
                if err != ERROR_IO_PENDING:
                    _k32.CloseHandle(event)
                    raise OSError(f"WriteFile failed: {err}")
            if _k32.WaitForSingleObject(event, int(self.timeout * 1000)) != WAIT_OBJECT_0:
                _k32.CancelIo(self._handle)
                _k32.CloseHandle(event)
                raise TimeoutError("USB write stalled")
            if not _k32.GetOverlappedResult(
                self._handle, byref(ov), byref(written), False
            ):
                _k32.CloseHandle(event)
                raise OSError(f"Overlapped write failed: {ctypes.get_last_error()}")
            _k32.CloseHandle(event)
            sent += written.value
        return sent

    def send(self, data: bytes) -> float:
        start = time.perf_counter()
        self.write(data)
        return time.perf_counter() - start

    def close(self) -> None:
        if self._handle and self._handle != INVALID_HANDLE_VALUE:
            _k32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> "UsbPrinter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
