import asyncio
from typing import List, Any, Optional, Tuple
from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.common.actions import interaction
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput


class AppiumManager:
    def __init__(self, appium_url: str = "http://localhost:4723", device_name: str = None, app_package: str = None, app_activity: str = None):
        self.appium_url = appium_url
        self.device_name = device_name
        self.app_package = app_package
        self.app_activity = app_activity or "com.unity3d.player.UnityPlayerActivity"
        self.driver = None
        self._initialize_session()
    
    def _initialize_session(self):
        try:
            options = UiAutomator2Options()
            options.platform_name = "Android"
            options.device_name = self.device_name or "Android Emulator"
            options.no_reset = True
            options.full_reset = False
            options.new_command_timeout = 3600
            
            if self.app_package:
                options.app_package = self.app_package
                options.app_activity = self.app_activity
                print(f"🎯 Appium will launch app: {self.app_package}")
            else:
                print(f"🖥️  Appium will control current screen (no app launch)")
            
            print(f"🔌 Connecting to Appium server at {self.appium_url}...")
            self.driver = webdriver.Remote(self.appium_url, options=options)
            print(f"✅ Appium session started: {self.driver.session_id}")
            
        except Exception as e:
            print(f"❌ Failed to start Appium session: {e}")
            print(f"   Make sure Appium server is running: appium")
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
        print(f"🔄 SWIPE (Appium): ({x1}, {y1}) → ({x2}, {y2}) duration={duration}s")
    
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
        print(f"🔄 MULTI-SWIPE (Appium): {waypoints_str} duration={duration}s")
    
    def get_screenshot(self, filepath: str):
        if not self.driver:
            raise RuntimeError("No Appium session active")
        
        self.driver.save_screenshot(filepath)
    
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
                    print(f"👆 CLICK (Appium): ({x}, {y}) duration={duration}s")
                    self.press(x, y, duration)
                
                elif action_type == "swipe":
                    if x is None or y is None or end_x is None or end_y is None:
                        raise ValueError("x, y, end_x, end_y are required for swipe action")
                    print(f"🔄 SWIPE (Appium): ({x}, {y}) → ({end_x}, {end_y}) duration={duration}s")
                    self.swipe(x, y, end_x, end_y, duration)
                
                elif action_type == "multi_swipe":
                    if not waypoints or len(waypoints) < 2:
                        raise ValueError("waypoints with at least 2 points required for multi_swipe")
                    self.multi_point_swipe(waypoints, duration)
                
                elif action_type == "wait":
                    print(f"⏳ WAIT: {duration}s")
                    await asyncio.sleep(duration)
                
                else:
                    print(f"⚠️  Unsupported action type for Appium: {action_type}")
                    continue
                    
            except Exception as e:
                print(f"❌ Action failed: {e}")
                raise
    
    def close(self):
        if self.driver:
            print("🔌 Closing Appium session...")
            self.driver.quit()
            self.driver = None
    
    def __del__(self):
        self.close()
