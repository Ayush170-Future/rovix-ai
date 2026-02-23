import asyncio
import time
import os
from typing import List, Any, Optional, Tuple
from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.common.actions import interaction
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from dataclasses import dataclass
from enum import Enum

try:
    from .logger import get_logger
except ImportError:
    from agent.logger import get_logger

logger = get_logger("agent.appium_manager")


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


class AppiumManager:
    def __init__(
        self, 
        appium_url: str = "http://localhost:4723", 
        device_name: str = None, 
        udid: str = None, 
        app_package: str = None, 
        app_activity: str = None,
        screenshot_timeout: float = 10.0,
        screenshot_max_retries: int = 3
    ):
        self.appium_url = appium_url
        self.device_name = device_name
        self.udid = udid
        self.app_package = app_package
        self.app_activity = app_activity or "com.unity3d.player.UnityPlayerActivity"
        self.screenshot_timeout = screenshot_timeout
        self.screenshot_max_retries = screenshot_max_retries
        self.driver = None
        self._initialize_session()
    
    def _initialize_session(self):
        try:
            options = UiAutomator2Options()
            options.platform_name = "Android"
            options.device_name = self.device_name or "Android Emulator"
            if self.udid:
                options.udid = self.udid
                logger.info(f"📱 Using device with UDID: {self.udid}")
            options.no_reset = True
            options.full_reset = False
            options.new_command_timeout = 3600
            
            if self.app_package:
                options.app_package = self.app_package
                options.app_activity = self.app_activity
                logger.info(f"🎯 Appium will launch app: {self.app_package}")
            else:
                logger.info(f"🖥️  Appium will control current screen (no app launch)")
            
            logger.info(f"🔌 Connecting to Appium server at {self.appium_url}...")
            self.driver = webdriver.Remote(self.appium_url, options=options)
            logger.info(f"✅ Appium session started: {self.driver.session_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to start Appium session: {e}")
            logger.error(f"   Make sure Appium server is running: appium")
            self.driver = None
    
    def is_connected(self) -> bool:
        return self.driver is not None
    
    def press(self, x: int, y: int, duration: float = 0.1):
        if not self.driver:
            raise RuntimeError("No Appium session active")
        
        if duration <= 0.1:
            self.driver.tap([(x, y)])
        else:
            duration_ms = int(duration * 1000)
            self.driver.tap([(x, y)], duration_ms)
    
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float):
        if not self.driver:
            raise RuntimeError("No Appium session active")
        
        duration_ms = int(duration * 1000)
        self.driver.swipe(x1, y1, x2, y2, duration_ms)
        logger.info(f"🔄 SWIPE (Appium): ({x1}, {y1}) → ({x2}, {y2}) duration={duration}s")
    
    def multi_point_swipe(self, waypoints: List[Tuple[int, int]], duration: float):
        if not self.driver:
            raise RuntimeError("No Appium session active")
        
        if len(waypoints) < 2:
            raise ValueError("Need at least 2 waypoints for swipe")
        
        actions = ActionBuilder(self.driver, mouse=PointerInput(interaction.POINTER_TOUCH, "touch"))
        
        start_x, start_y = waypoints[0]
        actions.pointer_action.move_to_location(start_x, start_y)
        actions.pointer_action.pointer_down()
        
        duration_per_segment = duration / (len(waypoints) - 1)
        duration_ms = int(duration_per_segment * 1000)
        
        for x, y in waypoints[1:]:
            actions.pointer_action.pause(duration_ms / 1000)
            actions.pointer_action.move_to_location(x, y)
        
        actions.pointer_action.pointer_up()
        actions.perform()
        
        waypoints_str = " → ".join([f"({x},{y})" for x, y in waypoints])
        logger.info(f"🔄 MULTI-SWIPE (Appium): {waypoints_str} duration={duration}s")
    
    def get_screenshot(self, filepath: str) -> ScreenshotResult:
        """
        Capture screenshot with retry logic.
        
        Args:
            filepath: Path where screenshot should be saved
            
        Returns:
            ScreenshotResult with success status and error details
        """
        if not self.driver:
            return ScreenshotResult(
                success=False,
                filepath=None,
                error_message="No Appium session active",
                error_type=ErrorType.DEVICE_DISCONNECTED,
                retry_count=0
            )
        
        overall_start = time.time()
        last_error = None
        last_error_type = ErrorType.UNKNOWN
        
        for attempt in range(self.screenshot_max_retries):
            try:
                start_time = time.time()
                
                # Capture screenshot with Appium
                self.driver.save_screenshot(filepath)
                
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
                
            except ConnectionError as e:
                last_error = e
                last_error_type = ErrorType.NETWORK_ERROR
                error_msg = f"Connection error: {e}"
                
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
                # Check if it's a session-related error
                if "session" in str(e).lower() or "driver" in str(e).lower():
                    last_error_type = ErrorType.DEVICE_DISCONNECTED
                else:
                    last_error_type = ErrorType.UNKNOWN
                error_msg = f"Screenshot error: {e}"
            
            attempt_num = attempt + 1
            
            if attempt_num < self.screenshot_max_retries:
                # Exponential backoff: 1s, 2s, 4s
                wait_time = 2 ** attempt
                logger.warning(f"⚠️  [RETRY {attempt_num}/{self.screenshot_max_retries}] {error_msg}")
                logger.warning(f"   🔄 Retrying in {wait_time}s...")
                time.sleep(wait_time)
                
                # Try to reconnect if session issue
                if last_error_type == ErrorType.DEVICE_DISCONNECTED:
                    logger.info(f"   🔌 Attempting to reconnect session...")
                    try:
                        self._initialize_session()
                        if not self.driver:
                            logger.error(f"   ❌ Reconnection failed")
                    except Exception as reconnect_error:
                        logger.error(f"   ❌ Reconnection error: {reconnect_error}")
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
            waypoints = getattr(action, 'waypoints', None)
            duration = getattr(action, 'duration', 0.1)
            
            try:
                if action_type == "click":
                    if x is None or y is None:
                        raise ValueError("x and y are required for click action")
                    logger.info(f"👆 CLICK (Appium): ({x}, {y}) duration={duration}s")
                    self.press(x, y, duration)
                
                elif action_type == "swipe":
                    if x is None or y is None or end_x is None or end_y is None:
                        raise ValueError("x, y, end_x, end_y are required for swipe action")
                    logger.info(f"🔄 SWIPE (Appium): ({x}, {y}) → ({end_x}, {end_y}) duration={duration}s")
                    self.swipe(x, y, end_x, end_y, duration)
                
                elif action_type == "multi_swipe":
                    if not waypoints or len(waypoints) < 2:
                        raise ValueError("waypoints with at least 2 points required for multi_swipe")
                    self.multi_point_swipe(waypoints, duration)
                
                elif action_type == "wait":
                    logger.info(f"⏳ WAIT: {duration}s")
                    await asyncio.sleep(duration)
                
                else:
                    logger.warning(f"⚠️  Unsupported action type for Appium: {action_type}")
                    continue
                    
            except Exception as e:
                logger.error(f"❌ Action failed: {e}")
                raise
    
    def close(self):
        if self.driver:
            logger.info("🔌 Closing Appium session...")
            self.driver.quit()
            self.driver = None
    
    def __del__(self):
        self.close()
