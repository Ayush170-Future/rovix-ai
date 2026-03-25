"""
Unified result types for device operations (ADB / Appium).

ExecutionService owns retry/abort policy; managers only report outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class DeviceErrorType(str, Enum):
    DEVICE_DISCONNECTED = "device_disconnected"
    TIMEOUT = "timeout"
    PERMISSION_DENIED = "permission_denied"
    FILE_IO_ERROR = "file_io_error"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"
    INVALID_INPUT = "invalid_input"


@dataclass
class ScreenshotResult:
    """Result of screenshot capture (ADB or Appium)."""

    success: bool
    filepath: Optional[str] = None
    error_message: Optional[str] = None
    error_type: Optional[DeviceErrorType] = None
    retry_count: int = 0
    elapsed_time: float = 0.0


@dataclass
class ActionResult:
    """Result of a single action in a batch."""

    success: bool
    action_type: str = ""
    error_message: Optional[str] = None
    error_type: Optional[DeviceErrorType] = None
    skipped: bool = False
    skipped_reason: Optional[str] = None


@dataclass
class ActionBatchResult:
    """Result of execute_actions_sequential."""

    results: List[ActionResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.success for r in self.results)

    @property
    def failed_results(self) -> List[ActionResult]:
        return [r for r in self.results if not r.success]


def classify_exception(exc: Exception) -> DeviceErrorType:
    """Map an exception to DeviceErrorType for action execution."""
    if isinstance(exc, ValueError):
        return DeviceErrorType.INVALID_INPUT
    msg = str(exc).lower()
    if "no appium session" in msg or "no adb device" in msg:
        return DeviceErrorType.DEVICE_DISCONNECTED
    if "session" in msg or "not connected" in msg or "disconnected" in msg:
        return DeviceErrorType.DEVICE_DISCONNECTED
    if isinstance(exc, (ConnectionError, BrokenPipeError, OSError)):
        return DeviceErrorType.NETWORK_ERROR
    if isinstance(exc, PermissionError):
        return DeviceErrorType.PERMISSION_DENIED
    if isinstance(exc, IOError):
        return DeviceErrorType.FILE_IO_ERROR
    return DeviceErrorType.UNKNOWN
