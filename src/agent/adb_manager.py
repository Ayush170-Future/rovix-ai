import re
import xml.etree.ElementTree as ET
import asyncio
import time
import os
from typing import Optional, Dict, List, Any
from ppadb.client import Client as AdbClient

try:
    from .logger import get_logger
except ImportError:
    from agent.logger import get_logger

from agent.device_results import (
    ActionBatchResult,
    ActionResult,
    DeviceErrorType,
    ScreenshotResult,
    classify_exception,
)

logger = get_logger("agent.adb_manager")


class ADBManager:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5037,
        serial: Optional[str] = None,
        screenshot_timeout: float = 10.0,
        screenshot_max_retries: int = 3,
    ):
        self.host = host
        self.port = port
        self.serial = serial
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
                logger.warning("⚠️  No ADB devices connected")
                return

            if self.serial:
                for d in devices:
                    if d.serial == self.serial:
                        self.device = d
                        logger.info(f"✅ Connected to ADB device: {self.device.serial}")
                        return
                logger.error(f"❌ No ADB device with serial {self.serial!r} (available: {[d.serial for d in devices]})")
                self.device = None
                return

            self.device = devices[0]
            logger.info(f"✅ Connected to ADB device: {self.device.serial}")
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to ADB: {e}")
            logger.error(f"   Make sure ADB server is running: adb start-server")
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
            logger.warning(f"⚠️  Error getting rotation: {e}")
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
            
            logger.warning("⚠️  Could not find SurfaceView in UI hierarchy")
            return None
            
        except Exception as e:
            logger.error(f"❌ Error getting Unity bounds: {e}")
            return None
    
    def _parse_bounds(self, bounds_str: str) -> Optional[Dict[str, int]]:
        match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str)
        if not match:
            return None
        
        left, top, right, bottom = map(int, match.groups())
        logger.debug(f"🔍 Width: {right - left}, Height: {bottom - top}")
        
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
        logger.info(f"🔄 SWIPE (ADB): ({x1}, {y1}) → ({x2}, {y2}) duration={duration}s")
    
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
                error_type=DeviceErrorType.DEVICE_DISCONNECTED,
                retry_count=0,
            )
        
        overall_start = time.time()
        last_error = None
        last_error_type = DeviceErrorType.UNKNOWN
        
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
                    logger.info(f"   ✅ Screenshot captured after {attempt + 1} attempts")
                
                return ScreenshotResult(
                    success=True,
                    filepath=filepath,
                    retry_count=attempt,
                    elapsed_time=total_elapsed
                )
                
            except (ConnectionError, BrokenPipeError, OSError) as e:
                last_error = e
                last_error_type = DeviceErrorType.DEVICE_DISCONNECTED
                error_msg = f"Device connection error: {e}"

            except PermissionError as e:
                last_error = e
                last_error_type = DeviceErrorType.PERMISSION_DENIED
                error_msg = f"Permission denied: {e}"

            except IOError as e:
                last_error = e
                last_error_type = DeviceErrorType.FILE_IO_ERROR
                error_msg = f"File I/O error: {e}"

            except Exception as e:
                last_error = e
                last_error_type = DeviceErrorType.UNKNOWN
                error_msg = f"Screenshot error: {e}"
            
            attempt_num = attempt + 1
            
            if attempt_num < self.screenshot_max_retries:
                # Exponential backoff: 1s, 2s, 4s
                wait_time = 2 ** attempt
                logger.warning(f"⚠️  [RETRY {attempt_num}/{self.screenshot_max_retries}] {error_msg}")
                logger.warning(f"   🔄 Retrying in {wait_time}s...")
                time.sleep(wait_time)
                
                # Try to reconnect if device issue
                if last_error_type == DeviceErrorType.DEVICE_DISCONNECTED:
                    logger.info(f"   🔌 Attempting to reconnect to device...")
                    self._initialize_connection()
                    if not self.device:
                        logger.error(f"   ❌ Reconnection failed")
            else:
                total_elapsed = time.time() - overall_start
                final_error_msg = f"Screenshot capture failed after {self.screenshot_max_retries} attempts: {last_error}"
                logger.error(f"❌ [FATAL] {final_error_msg}")
                
                return ScreenshotResult(
                    success=False,
                    filepath=None,
                    error_message=final_error_msg,
                    error_type=last_error_type,
                    retry_count=attempt_num,
                    elapsed_time=total_elapsed,
                )

        # Should never reach here
        return ScreenshotResult(
            success=False,
            filepath=None,
            error_message="Unknown error in retry loop",
            error_type=DeviceErrorType.UNKNOWN,
            retry_count=self.screenshot_max_retries,
        )

    async def execute_actions_sequential(self, actions: List[Any]) -> ActionBatchResult:
        if not actions:
            return ActionBatchResult(results=[])

        results: List[ActionResult] = []

        for action in actions:
            action_type = action.action_type
            x = action.x
            y = action.y
            end_x = getattr(action, "end_x", None)
            end_y = getattr(action, "end_y", None)
            duration = getattr(action, "duration", 0.1)

            try:
                if action_type == "click":
                    if x is None or y is None:
                        raise ValueError("x and y are required for click action")
                    logger.info(f"👆 CLICK (ADB): ({x}, {y}) duration={duration}s")
                    self.press(x, y, duration)
                    results.append(ActionResult(success=True, action_type=action_type))

                elif action_type == "swipe":
                    if x is None or y is None or end_x is None or end_y is None:
                        raise ValueError("x, y, end_x, end_y are required for swipe action")
                    logger.info(f"🔄 SWIPE (ADB): ({x}, {y}) → ({end_x}, {end_y}) duration={duration}s")
                    self.swipe(x, y, end_x, end_y, duration)
                    results.append(ActionResult(success=True, action_type=action_type))

                elif action_type == "multi_swipe":
                    logger.warning(f"⚠️  multi_swipe not supported on ADB path; skipping")
                    results.append(
                        ActionResult(
                            success=True,
                            action_type=action_type,
                            skipped=True,
                            skipped_reason="unsupported_on_adb",
                        )
                    )

                elif action_type == "wait":
                    logger.info(f"⏳ WAIT: {duration}s")
                    await asyncio.sleep(duration)
                    results.append(ActionResult(success=True, action_type=action_type))

                else:
                    logger.warning(f"⚠️  Unsupported action type for ADB: {action_type}")
                    results.append(
                        ActionResult(
                            success=True,
                            action_type=str(action_type),
                            skipped=True,
                            skipped_reason="unsupported_action",
                        )
                    )

            except Exception as e:
                et = classify_exception(e)
                logger.error(f"❌ Action failed: {e}")
                results.append(
                    ActionResult(
                        success=False,
                        action_type=str(action_type),
                        error_message=str(e),
                        error_type=et,
                    )
                )

        return ActionBatchResult(results=results)

