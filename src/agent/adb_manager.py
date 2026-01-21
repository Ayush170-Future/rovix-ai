import re
import xml.etree.ElementTree as ET
import asyncio
import time
import os
from typing import Optional, Dict, List, Any
from ppadb.client import Client as AdbClient
from dataclasses import dataclass
from enum import Enum


class ErrorType(str, Enum):
    """Types of errors that can occur"""
    DEVICE_DISCONNECTED = "device_disconnected"
    TIMEOUT = "timeout"
    PERMISSION_DENIED = "permission_denied"
    FILE_IO_ERROR = "file_io_error"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"


@dataclass
class ScreenshotResult:
    """Result of screenshot capture operation"""
    success: bool
    filepath: Optional[str] = None
    error_message: Optional[str] = None
    error_type: Optional[ErrorType] = None
    retry_count: int = 0
    elapsed_time: float = 0.0


class ADBManager:
    def __init__(
        self, 
        host: str = "127.0.0.1", 
        port: int = 5037,
        screenshot_timeout: float = 10.0,
        screenshot_max_retries: int = 3
    ):
        self.host = host
        self.port = port
        self.client = None
        self.device = None
        self.screenshot_timeout = screenshot_timeout
        self.screenshot_max_retries = screenshot_max_retries
        self._initialize_connection()
    
    def _initialize_connection(self):
        try:
            self.client = AdbClient(host=self.host, port=self.port)
            devices = self.client.devices()
            
            if not devices:
                print("⚠️  No ADB devices connected")
                return
            
            self.device = devices[0]
            print(f"✅ Connected to ADB device: {self.device.serial}")
            
        except Exception as e:
            print(f"❌ Failed to connect to ADB: {e}")
            print(f"   Make sure ADB server is running: adb start-server")
            self.client = None
            self.device = None
    
    def get_rotation(self) -> int:
        if not self.device:
            return 0
        
        try:
            result = self.device.shell("dumpsys window | grep 'mCurrentRotation'")
            match = re.search(r'ROTATION_(\d+)', result)
            if match:
                rotation_value = int(match.group(1))
                rotation_map = {0: 0, 90: 1, 180: 2, 270: 3}
                return rotation_map.get(rotation_value, 0)
            return 0
        except Exception as e:
            print(f"⚠️  Error getting rotation: {e}")
            return 0
    
    def get_unity_bounds(self) -> Optional[Dict[str, int]]:
        if not self.device:
            return None
        
        try:
            rotation = self.get_rotation()
            
            self.device.shell("uiautomator dump")
            xml_content = self.device.shell("cat /sdcard/window_dump.xml")
            
            root = ET.fromstring(xml_content)
            
            # Have to change this to something that always works
            for node in root.iter('node'):
                if node.get('package') == 'com.ZoltanGubics.Solitaire':
                    bounds_str = node.get('bounds')
                    bounds = self._parse_bounds(bounds_str)
                    if bounds:
                        bounds['rotation'] = rotation
                        return bounds
            
            print("⚠️  Could not find SurfaceView in UI hierarchy")
            return None
            
        except Exception as e:
            print(f"❌ Error getting Unity bounds: {e}")
            return None
    
    def _parse_bounds(self, bounds_str: str) -> Optional[Dict[str, int]]:
        match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str)
        if not match:
            return None
        
        left, top, right, bottom = map(int, match.groups())
        print(f"🔍 Width: {right - left}, Height: {bottom - top}")
        
        return {
            'left': left,
            'top': top,
            'right': right,
            'bottom': bottom,
            'width': right - left,
            'height': bottom - top,
            'offset_x': left,
            'offset_y': top
        }
    
    def press(self, x: int, y: int, duration: float = 0.1):
        if not self.device:
            raise RuntimeError("No ADB device connected")
        
        if duration <= 0.1:
            self.device.shell(f"input tap {x} {y}")
        else:
            duration_ms = int(duration * 1000)
            self.device.shell(f"input swipe {x} {y} {x} {y} {duration_ms}")
    
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float):
        if not self.device:
            raise RuntimeError("No ADB device connected")
        
        duration_ms = int(duration * 1000)
        self.device.shell(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")
        print(f"🔄 SWIPE (ADB): ({x1}, {y1}) → ({x2}, {y2}) duration={duration}s")
    
    def get_screenshot(self, filepath: str) -> ScreenshotResult:
        """
        Capture screenshot with retry logic.
        
        Args:
            filepath: Path where screenshot should be saved
            
        Returns:
            ScreenshotResult with success status and error details
        """
        if not self.device:
            return ScreenshotResult(
                success=False,
                filepath=None,
                error_message="No ADB device connected",
                error_type=ErrorType.DEVICE_DISCONNECTED,
                retry_count=0
            )
        
        overall_start = time.time()
        last_error = None
        last_error_type = ErrorType.UNKNOWN
        
        for attempt in range(self.screenshot_max_retries):
            try:
                start_time = time.time()
                
                # Capture screenshot with timeout
                screenshot_bytes = self.device.screencap()
                
                if not screenshot_bytes:
                    raise RuntimeError("Screenshot capture returned empty data")
                
                # Write to file
                with open(filepath, 'wb') as f:
                    f.write(screenshot_bytes)
                
                # Verify file was written
                if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
                    raise RuntimeError("Screenshot file not created or empty")
                
                elapsed = time.time() - start_time
                total_elapsed = time.time() - overall_start
                
                if attempt > 0:
                    print(f"   ✅ Screenshot captured after {attempt + 1} attempts")
                
                return ScreenshotResult(
                    success=True,
                    filepath=filepath,
                    retry_count=attempt,
                    elapsed_time=total_elapsed
                )
                
            except (ConnectionError, BrokenPipeError, OSError) as e:
                last_error = e
                last_error_type = ErrorType.DEVICE_DISCONNECTED
                error_msg = f"Device connection error: {e}"
                
            except PermissionError as e:
                last_error = e
                last_error_type = ErrorType.PERMISSION_DENIED
                error_msg = f"Permission denied: {e}"
                
            except IOError as e:
                last_error = e
                last_error_type = ErrorType.FILE_IO_ERROR
                error_msg = f"File I/O error: {e}"
                
            except Exception as e:
                last_error = e
                last_error_type = ErrorType.UNKNOWN
                error_msg = f"Screenshot error: {e}"
            
            attempt_num = attempt + 1
            
            if attempt_num < self.screenshot_max_retries:
                # Exponential backoff: 1s, 2s, 4s
                wait_time = 2 ** attempt
                print(f"⚠️  [RETRY {attempt_num}/{self.screenshot_max_retries}] {error_msg}")
                print(f"   🔄 Retrying in {wait_time}s...")
                time.sleep(wait_time)
                
                # Try to reconnect if device issue
                if last_error_type == ErrorType.DEVICE_DISCONNECTED:
                    print(f"   🔌 Attempting to reconnect to device...")
                    self._initialize_connection()
                    if not self.device:
                        print(f"   ❌ Reconnection failed")
            else:
                total_elapsed = time.time() - overall_start
                final_error_msg = f"Screenshot capture failed after {self.screenshot_max_retries} attempts: {last_error}"
                print(f"❌ [FATAL] {final_error_msg}")
                
                return ScreenshotResult(
                    success=False,
                    filepath=None,
                    error_message=final_error_msg,
                    error_type=last_error_type,
                    retry_count=attempt_num,
                    elapsed_time=total_elapsed
                )
        
        # Should never reach here
        return ScreenshotResult(
            success=False,
            filepath=None,
            error_message="Unknown error in retry loop",
            error_type=ErrorType.UNKNOWN,
            retry_count=self.screenshot_max_retries
        )
    
    async def execute_actions_sequential(self, actions: List[Any]) -> None:
        if not actions:
            return
        
        for action in actions:
            action_type = action.action_type
            x = action.x
            y = action.y
            end_x = getattr(action, 'end_x', None)
            end_y = getattr(action, 'end_y', None)
            duration = getattr(action, 'duration', 0.1)
            
            try:
                if action_type == "click":
                    if x is None or y is None:
                        raise ValueError("x and y are required for click action")
                    print(f"👆 CLICK (ADB): ({x}, {y}) duration={duration}s")
                    self.press(x, y, duration)
                
                elif action_type == "swipe":
                    if x is None or y is None or end_x is None or end_y is None:
                        raise ValueError("x, y, end_x, end_y are required for swipe action")
                    print(f"🔄 SWIPE (ADB): ({x}, {y}) → ({end_x}, {end_y}) duration={duration}s")
                    self.swipe(x, y, end_x, end_y, duration)
                
                elif action_type == "wait":
                    print(f"⏳ WAIT: {duration}s")
                    await asyncio.sleep(duration)
                
                else:
                    print(f"⚠️  Unsupported action type for ADB: {action_type}")
                    continue
                    
            except Exception as e:
                print(f"❌ Action failed: {e}")
                raise

