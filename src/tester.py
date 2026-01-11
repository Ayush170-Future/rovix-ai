from alttester import AltDriver
from alttester import By
from alttester import AltKeyCode
import time
import asyncio
print(f"AltTester version: {AltDriver.__version__}")


class AltTesterClient:
    """Manages the AltTester driver connection"""
    
    def __init__(self, host="127.0.0.1", port=13000, timeout=60):
        """
        Initialize AltTester driver connection.
        
        Args:
            host (str): Host address. Default is "127.0.0.1"
            port (int): Port number. Default is 13000
            timeout (int): Connection timeout in seconds. Default is 60
        """
        self.driver = AltDriver(host=host, port=port, timeout=timeout)
    
    def get_driver(self):
        """Get the underlying AltDriver instance"""
        return self.driver
    
    def disconnect(self):
        """Close the AltTester connection"""
        if self.driver:
            self.driver.stop()

class InputController:
    """Handles all keyboard and input-related actions"""
    
    def __init__(self, alt_driver):
        """
        Initialize InputController.
        
        Args:
            alt_driver (AltDriver): The AltDriver instance
        """
        self.driver = alt_driver
    
    def press_key(self, key_code):
        """
        Press a key (tap).
        
        Args:
            key_code (AltKeyCode): The key to press
        """
        self.driver.press_key(key_code)
    
    def release_all_keys(self):
        """
        Release all commonly used game keys (emergency reset).
        Useful when keys get stuck in pressed state after crashes.
        """
        keys_to_release = [
            AltKeyCode.W,
            AltKeyCode.A, 
            AltKeyCode.S,
            AltKeyCode.D,
            AltKeyCode.Space
        ]
        for key in keys_to_release:
            self.driver.key_up(key)
    
    def hold_key(self, key_code, duration):
        """
        Hold a key for a specific duration (synchronous).
        
        Args:
            key_code (AltKeyCode): The key to hold
            duration (float): Duration in seconds to hold the key
        """
        self.driver.key_up(key_code)
        time.sleep(duration)
        self.driver.key_down(key_code)
    
    def jump(self, hold_duration=2):
        """
        Perform a jump action using the Space key (synchronous).
        
        Args:
            hold_duration (float): Duration in seconds to hold the jump key. Default is 2 seconds.
        
        """
        self.driver.key_down(AltKeyCode.Space)
        time.sleep(hold_duration)
        self.driver.key_up(AltKeyCode.Space)
    
    async def hold_key_async(self, key_code, duration):
        """
        Hold a key for a specific duration (asynchronous).
        
        Args:
            key_code (AltKeyCode): The key to hold
            duration (float): Duration in seconds to hold the key
        """
        print(f"  🔽 KEY_DOWN: {key_code.name}")
        self.driver.key_down(key_code)
        print(f"  ⏳ Holding {key_code.name} for {duration}s...")
        await asyncio.sleep(duration)
        print(f"  🔼 KEY_UP: {key_code.name}")
        self.driver.key_up(key_code)

    async def swipe_async(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float):
        print(f"🔄 SWIPE: Starting swipe from ({start_x}, {start_y}) to ({end_x}, {end_y}) for {duration}s")
        finger_id = self.driver.begin_touch([start_x, start_y])
        await asyncio.sleep(3)
        self.driver.move_touch(finger_id, [start_x + 2, start_y + 2])
        await asyncio.sleep(3)
        self.driver.move_touch(finger_id, [end_x, end_y])
        await asyncio.sleep(3)
        self.driver.end_touch(finger_id)
        await asyncio.sleep(3)
        print(f"🔄 SWIPE: Completed") # TODO: See why alttester composite methods are not behaving correctly.
        # Drag and Drop me kuch toh physics adjust nahi ho paa rahi hai. Mujhe manually cards ko hilana pad rha hai
    
    async def jump_async(self, hold_duration=2):
        """
        Perform a jump action using the Space key (asynchronous).
        
        Args:
            hold_duration (float): Duration in seconds to hold the jump key. Default is 2 seconds.
        """
        print(f"🚀 JUMP: Starting jump for {hold_duration}s")
        if hold_duration:
            await self.hold_key_async(AltKeyCode.Space, hold_duration)
        else:
            await self.hold_key_async(AltKeyCode.Space, duration=0.1)
        print(f"🚀 JUMP: Completed")
    
    def move_right(self, duration=None):
        """
        Move right using the D key (synchronous).
        
        Args:
            duration (float, optional): If provided, holds the key for this duration. 
                                       Otherwise, just presses the key.
        """
        if duration:
            self.hold_key(AltKeyCode.D, duration)
        else:
            self.press_key(AltKeyCode.D)
    
    async def move_right_async(self, duration=None):
        """
        Move right using the D key (asynchronous).
        
        Args:
            duration (float, optional): If provided, holds the key for this duration. 
                                       Otherwise, just presses the key.
        """
        print(f"➡️  MOVE_RIGHT: Starting for {duration}s")
        if duration:
            await self.hold_key_async(AltKeyCode.D, duration)
        else:
            await self.hold_key_async(AltKeyCode.D, duration=0.1)
        print(f"➡️  MOVE_RIGHT: Completed")
    
    def move_left(self, duration=None):
        """
        Move left using the A key (synchronous).
        
        Args:
            duration (float, optional): If provided, holds the key for this duration.
                                       Otherwise, just presses the key.
        """
        if duration:
            self.hold_key(AltKeyCode.A, duration)
        else:
            self.press_key(AltKeyCode.A)
    
    async def move_left_async(self, duration=None):
        """
        Move left using the A key (asynchronous).
        
        Args:
            duration (float, optional): If provided, holds the key for this duration.
                                       Otherwise, just presses the key.
        """
        if duration:
            await self.hold_key_async(AltKeyCode.A, duration)
        else:
            await self.hold_key_async(AltKeyCode.A, duration=0.1)


class TimeController:
    """Handles game time manipulation (pause, resume, time scale)"""
    
    def __init__(self, alt_driver):
        """
        Initialize TimeController.
        
        Args:
            alt_driver (AltDriver): The AltDriver instance
        """
        self.driver = alt_driver
    
    def pause_game(self):
        """Pause the game by setting time scale to 0"""
        self.set_time_scale(0)
    
    def resume_game(self):
        """Resume the game by setting time scale to 1"""
        self.set_time_scale(1)
    
    def set_time_scale(self, scale):
        """
        Set the game's time scale.
        
        Args:
            scale (float): The time scale value (0 = paused, 1 = normal, >1 = faster)
        """
        self.driver.call_static_method(
            "UnityEngine.Time",
            "set_timeScale",
            assembly="UnityEngine.CoreModule",
            parameters=[str(scale)],
            type_of_parameters=["System.Single"]
        )
    


class SceneController:
    """Handles scene loading and management"""
    
    def __init__(self, alt_driver):
        """
        Initialize SceneController.
        
        Args:
            alt_driver (AltDriver): The AltDriver instance
        """
        self.driver = alt_driver
    
    def load_scene(self, scene_name):
        """
        Load a scene by name.
        
        Args:
            scene_name (str): The name of the scene to load
        """
        self.driver.load_scene(scene_name)
    


class GameFrameController:
    """Handles frame-based game control using the FrameController component"""
    
    def __init__(self, alt_driver):
        """
        Initialize GameFrameController.
        
        Args:
            alt_driver (AltDriver): The AltDriver instance
        """
        self.driver = alt_driver
        print(f"🔍 Searching for FrameController...")
        self.controller = alt_driver.find_object(By.NAME, "FrameController")
        print(f"🔍 FrameController found: {self.controller}")
        
        # DEBUG: List all components on this GameObject
        try:
            components = self.controller.get_all_components()
            print(f"📋 Components found on FrameController GameObject:")
            for comp in components:
                print(f"🔍 Component: {comp}")
        except Exception as e:
            print(f"⚠️ Could not list components: {e}")
    
    def get_current_frame(self):
        """
        Get the current frame count from FrameController.
        
        Returns:
            int: The current frame number
        """
        return int(self.controller.call_component_method(
            "FrameController",  # Component type name
            "GetCurrentFrame",  # Method name
            assembly="Assembly-CSharp"
        ))
    
    def resume(self):
        """
        Resume the game by calling Resume() on FrameController.
        """
        print(f"🔍 Resuming game...")
        self.controller.call_component_method(
            "FrameController",
            "Resume",
            assembly="Assembly-CSharp"
        )
        print(f"🔍 Game resumed")
    
    def mark_actions_executed(self):
        """
        Mark actions as executed by calling MarkActionsExecuted() on FrameController.
        This allows Unity to send the next event.
        """
        print(f"✅ Marking actions as executed...")
        self.controller.call_component_method(
            "FrameController",
            "MarkActionsExecuted",
            assembly="Assembly-CSharp"
        )
        print(f"✅ Actions marked as executed")

    def get_current_game_state(self):
        objects = self.driver.find_objects(By.COMPONENT, "UnityEngine.UI.Button")
        for obj in objects:
            print(f"🔍 Button: {obj.name}")
            print(f"🔍 Button: {obj.enabled}")
            position = None
            if hasattr(obj, 'x') and hasattr(obj, 'y'):
                position = (float(obj.x), float(obj.worldY))
            print(f"🔍 Button: {position}")

        