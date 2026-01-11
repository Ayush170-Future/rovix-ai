import os
import json
import time
import asyncio
from typing import List, Dict, Optional, Any, Tuple
from alttester import AltDriver, By, AltKeyCode
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from tester import InputController

class ActionHandler:
    """
    Unified handler for all game actions.
    Extracts interactive elements on the fly and executes actions.
    """
    
    # ToDo:
    # At times the button name doesn't describe the button's functionality properly.
    # Have to add child elements context to the button as well.
    
    # Key name to AltKeyCode mapping
    KEY_MAPPING = {
        "Space": AltKeyCode.Space,
        "A": AltKeyCode.A,
        "B": AltKeyCode.B,
        "C": AltKeyCode.C,
        "D": AltKeyCode.D,
        "E": AltKeyCode.E,
        "F": AltKeyCode.F,
        "G": AltKeyCode.G,
        "H": AltKeyCode.H,
        "I": AltKeyCode.I,
        "J": AltKeyCode.J,
        "K": AltKeyCode.K,
        "L": AltKeyCode.L,
        "M": AltKeyCode.M,
        "N": AltKeyCode.N,
        "O": AltKeyCode.O,
        "P": AltKeyCode.P,
        "Q": AltKeyCode.Q,
        "R": AltKeyCode.R,
        "S": AltKeyCode.S,
        "T": AltKeyCode.T,
        "U": AltKeyCode.U,
        "V": AltKeyCode.V,
        "W": AltKeyCode.W,
        "X": AltKeyCode.X,
        "Y": AltKeyCode.Y,
        "Z": AltKeyCode.Z,
        "LeftArrow": AltKeyCode.LeftArrow,
        "RightArrow": AltKeyCode.RightArrow,
        "UpArrow": AltKeyCode.UpArrow,
        "DownArrow": AltKeyCode.DownArrow,
        "Enter": AltKeyCode.Return,
        "Return": AltKeyCode.Return,
        "Escape": AltKeyCode.Escape,
        "Tab": AltKeyCode.Tab,
        "Shift": AltKeyCode.LeftShift,
        "Control": AltKeyCode.LeftControl,
        "Alt": AltKeyCode.LeftAlt,
    }
    
    def __init__(self, driver: AltDriver, adb_manager=None, config_path: Optional[str] = None):
        self.driver = driver
        self.input_controller = InputController(driver)
        self.adb_manager = adb_manager
        
        if config_path is None:
            default_config = os.path.join(
                os.path.dirname(__file__),
                "config",
                "action_config.json"
            )
            config_path = default_config
        
        self.config = self._load_config(config_path)
        
        self._cached_elements: Optional[List[Dict[str, Any]]] = None
        self._element_cache_timestamp: Optional[float] = None
        self._elements_by_id: Dict[str, Dict[str, Any]] = {}
        self._bounds: Optional[Dict[str, int]] = None
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """
        Load action configuration from JSON file.
        
        Args:
            config_path: Path to config JSON file
            
        Returns:
            Config dictionary
        """
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            # Validate config structure
            if "input_types" not in config:
                raise ValueError("Config must contain 'input_types' key")
            
            print(f"✅ Loaded action config from: {config_path}")
            return config
            
        except FileNotFoundError:
            print(f"⚠️  Config file not found: {config_path}")
            print("   Using default configuration")
            return self._get_default_config()
        except json.JSONDecodeError as e:
            print(f"❌ Error parsing config JSON: {e}")
            print("   Using default configuration")
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration"""
        return {
            "input_types": {
                "keyboard": {
                    "enabled": True,
                    "available_keys": ["Space", "A", "D", "W", "S"]
                },
                "buttons": {
                    "enabled": True,
                    "extract_on_demand": True,
                    "cache_ttl_seconds": 5.0
                }
            },
            "element_extraction": {
                "components": [
                    "UnityEngine.UI.Button",
                    "UnityEngine.UI.Toggle",
                    "UnityEngine.EventSystems.EventTrigger"
                ],
                "refresh_strategy": "on_demand"
            }
        }
    
    # Gets all the interactive elements from the game screen based on the config
    def extract_interactive_elements(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Extract all interactive elements (buttons, etc.) from the game.
        
        Args:
            force_refresh: If True, force refresh even if cache is valid
            
        Returns:
            List of element info dictionaries with keys:
            - id: Unique identifier
            - name: Element name
            - type: Component type
            - position: (x, y) screen coordinates
            - text: Element text (if available)
            - enabled: Whether element is enabled
            - object: AltObject reference for execution
        """
        # Check cache validity
        if not force_refresh and self._cached_elements is not None:
            cache_ttl = self.config.get("input_types", {}).get("buttons", {}).get("cache_ttl_seconds", 5.0)
            if time.time() - self._element_cache_timestamp < cache_ttl:
                print(f"📋 Using cached elements ({len(self._cached_elements)} elements)")
                return self._cached_elements
        
        print("🔍 Extracting interactive elements from game...")
        
        elements = []
        component_types = self.config.get("element_extraction", {}).get("components", [])
        
        if not component_types:
            print("⚠️  No component types configured for extraction")
            return elements
        
        for component_obj in component_types:
            component_name = component_obj.get("component_name")
            assembly = component_obj.get("assembly")
            try:
                objects = self.driver.find_objects(By.COMPONENT, component_name)
                
                if objects:
                    print(f"   ✅ Found {len(objects)} {component_name} element(s)")
                    
                    for obj in objects:
                        try:
                            element_info = self._extract_element_info(obj, component_name)
                            if element_info:
                                elements.append(element_info)
                        except Exception as e:
                            print(f"   ⚠️  Error processing element: {e}")
                            continue

            except Exception as e:
                print(f"   ⚠️  Error searching for {component_name}: {e}")
                continue
        
        # Remove duplicates by ID
        seen_ids = set()
        unique_elements = []
        for elem in elements:
            elem_id = elem.get("id")
            if elem_id and elem_id not in seen_ids:
                seen_ids.add(elem_id)
                unique_elements.append(elem)
        
        # Update cache and lookup dictionaries
        self._cached_elements = unique_elements
        self._element_cache_timestamp = time.time()
        
        # Populate ID-based lookup dictionary
        self._elements_by_id.clear()
        for elem in unique_elements:
            elem_id = elem.get("id")
            if elem_id:
                self._elements_by_id[str(elem_id)] = elem
        
        print(f"✅ Extracted {len(unique_elements)} unique interactive elements")
        return unique_elements
    
    def _translate_coords(self, unity_x: float, unity_y: float, mobile_y: float, 
                          bounds: Dict[str, int]) -> tuple[int, int]:
        rotation = bounds.get('rotation', 0)
        
        if rotation == 0:
            screen_x = int(round(unity_x + bounds['offset_x']))
            screen_y = int(round(mobile_y + bounds['offset_y']))
        
        elif rotation == 1:
            # screen_x = int(round(unity_y + bounds['offset_x']))
            # screen_y = int(round(unity_x + bounds['offset_y']))
            screen_x = int(round(unity_x + bounds['offset_y']))
            screen_y = int(round(bounds['height'] - unity_y + bounds['offset_x']))
        
        elif rotation == 3:
            screen_x = int(round(mobile_y + bounds['offset_x']))
            screen_y = int(round(bounds['width'] - unity_x + bounds['offset_y']))
        
        elif rotation == 2:
            screen_x = int(round(bounds['width'] - unity_x + bounds['offset_x']))
            screen_y = int(round(bounds['height'] - mobile_y + bounds['offset_y']))
        
        else:
            screen_x = int(round(unity_x + bounds['offset_x']))
            screen_y = int(round(mobile_y + bounds['offset_y']))
        
        return screen_x, screen_y
    
    def _extract_element_info(self, obj: Any, component_type: str) -> Optional[Dict[str, Any]]:
        try:
            element_id = str(obj.id) if hasattr(obj, 'id') else None
            name = obj.name if hasattr(obj, 'name') else "Unknown"
            
            unity_x = float(obj.x) if hasattr(obj, 'x') else None
            unity_y = float(obj.y) if hasattr(obj, 'y') else None
            mobile_y = float(obj.mobileY) if hasattr(obj, 'mobileY') else None
            
            position = (unity_x, unity_y) if unity_x is not None and unity_y is not None else None
            
            screen_position = None
            if self.adb_manager and unity_x is not None and unity_y is not None and mobile_y is not None:
                if self._bounds:
                    screen_x, screen_y = self._translate_coords(
                        unity_x, unity_y, mobile_y, self._bounds
                    )
                    screen_position = (screen_x, screen_y)
            
            text = None
            try:
                text = obj.get_text()
            except:
                pass
            
            enabled = True
            if hasattr(obj, 'enabled'):
                enabled = obj.enabled
            
            element_info = {
                "id": element_id,
                "name": name,
                "type": component_type,
                "position": position,
                "screen_position": screen_position,
                "text": text,
                "enabled": enabled,
                "object": obj
            }
            
            if component_type == "UnityEngine.UI.Slider":
                try:
                    min_val = obj.get_component_property("UnityEngine.UI.Slider", "minValue", "UnityEngine.UI")
                    max_val = obj.get_component_property("UnityEngine.UI.Slider", "maxValue", "UnityEngine.UI")
                    current_val = obj.get_component_property("UnityEngine.UI.Slider", "value", "UnityEngine.UI")
                    element_info["minValue"] = float(min_val) if min_val is not None else None
                    element_info["maxValue"] = float(max_val) if max_val is not None else None
                    element_info["value"] = float(current_val) if current_val is not None else None
                except Exception as e:
                    print(f"      ⚠️  Error getting slider properties for {name}: {e}")
                    element_info["minValue"] = None
                    element_info["maxValue"] = None
                    element_info["value"] = None

            return element_info
            
        except Exception as e:
            print(f"      ⚠️  Error extracting info: {e}")
            return None
    
    def get_available_actions(self) -> Dict[str, Any]:
        self._bounds = self.adb_manager.get_unity_bounds()
        if self._bounds is None:
            raise ValueError("Failed to get Unity bounds")

        available = {
            "keyboard": {},
            "buttons": [],
            "sliders": [],
            "interactable_2d": []
        }
        
        # Keyboard actions
        if self.config.get("input_types", {}).get("keyboard", {}).get("enabled", False):
            available_keys = self.config.get("input_types", {}).get("keyboard", {}).get("available_keys", [])
            available["keyboard"] = {
                "key_press": {"available_keys": available_keys},
                "key_hold": {"available_keys": available_keys}
            }
        
        # Extract all interactive elements
        elements = self.extract_interactive_elements(force_refresh=True)
        
        # Separate buttons and sliders
        for elem in elements:
            elem_type = elem.get("type", "")
            simplified_elem = {
                "id": elem["id"],
                "name": elem["name"],
                "type": elem["type"],
                "position": elem["position"],
                "screen_position": elem.get("screen_position"),
                "text": elem.get("text"),
                "enabled": elem["enabled"]
            }
            
            if elem_type == "UnityEngine.UI.Slider":
                # Add slider-specific properties
                if self.config.get("input_types", {}).get("sliders", {}).get("enabled", False):
                    simplified_elem["minValue"] = elem.get("minValue")
                    simplified_elem["maxValue"] = elem.get("maxValue")
                    simplified_elem["value"] = elem.get("value")
                    available["sliders"].append(simplified_elem)
            elif elem_type == "UnityEngine.UI.Button":
                # Add button to buttons list
                if self.config.get("input_types", {}).get("buttons", {}).get("enabled", False):
                    available["buttons"].append(simplified_elem)
            elif elem_type == "UnityEngine.BoxCollider2D" or elem_type == "UnityEngine.CircleCollider2D" or elem_type == "UnityEngine.PolygonCollider2D":
                # Add collider to interactable_2d list
                if self.config.get("input_types", {}).get("interactable_2d", {}).get("enabled", False):
                    available["interactable_2d"].append(simplified_elem)
            else:
                # For other component types, add to buttons by default (backward compatibility)
                if self.config.get("input_types", {}).get("buttons", {}).get("enabled", False):
                    available["buttons"].append(simplified_elem)
        
        return available
    
    def _map_key_to_altkeycode(self, key: str) -> AltKeyCode:
        """
        Map string key name to AltKeyCode.
        
        Args:
            key: Key name string (e.g., "Space", "A")
            
        Returns:
            AltKeyCode enum value
            
        Raises:
            ValueError: If key is not in mapping
        """
        key_normalized = key.strip()
        
        if key_normalized not in self.KEY_MAPPING:
            available_keys = ", ".join(self.KEY_MAPPING.keys())
            raise ValueError(
                f"Unknown key: '{key}'. Available keys: {available_keys}"
            )
        
        return self.KEY_MAPPING[key_normalized]
    
    async def execute_key_press(self, key: str, duration: float = 0.1) -> None:
        """
        Execute keyboard key press (tap).
        
        Args:
            key: Key name (e.g., "Space", "A")
            duration: Duration to hold key before release (default 0.1s)
        """
        key_code = self._map_key_to_altkeycode(key)
        print(f"⌨️  KEY_PRESS: {key} for {duration}s")
        await self.input_controller.hold_key_async(key_code, duration)
    
    async def execute_button_press(self, button_id: str) -> None:
        # Ensure cache is populated
        self.extract_interactive_elements()
        
        # Use fast ID-based lookup
        element = self._elements_by_id.get(str(button_id))
        
        if element is None:
            raise ValueError(f"Button with ID '{button_id}' not found")
        
        if not element["enabled"]:
            raise ValueError(f"Button '{element['name']}' is not enabled")
        
        obj = element["object"]
        name = element["name"]
        
        print(f"🔘 BUTTON_PRESS: {name} (ID: {button_id})")
        
        try:
            obj.tap()
            print(f"   ✅ Successfully tapped {name}")
        except Exception as e:
            print(f"   ❌ Error tapping {name}: {e}")
            raise
    
    async def execute_wait(self, duration: float) -> None:
        """
        Execute wait/delay action.
        
        Args:
            duration: Duration to wait in seconds
        """
        print(f"⏳ WAIT: {duration}s")
        await asyncio.sleep(duration)

    async def execute_slider_move(self, slider_id: str, value: float) -> None:
        self.extract_interactive_elements()
        element = self._elements_by_id.get(slider_id)
        if element is None:
            raise ValueError(f"Slider with ID '{slider_id}' not found")
        if not element["enabled"]:
            raise ValueError(f"Slider '{element['name']}' is not enabled")
        obj = element["object"]
        name = element["name"]
        print(f"🔄 SLIDER_MOVE: {name} (ID: {slider_id}) to {value}")
        try:
            # Try without assembly first (Unity built-in components often don't need assembly)
            try:
                obj.set_component_property("UnityEngine.UI.Slider", "value", value)
            except Exception:
                # If that fails, try with UnityEngine assembly
                obj.set_component_property("UnityEngine.UI.Slider", "value", value, "UnityEngine")
            print(f"   ✅ Successfully moved {name} to {value}")
        except Exception as e:
            print(f"   ❌ Error moving {name} to {value}: {e}")
            raise
    
    async def execute_actions_parallel(self, actions: List[Dict[str, Any]]) -> None:
        """
        Execute multiple actions in parallel.
        Actions can be keyboard or button presses.
        
        Args:
            actions: List of action dictionaries with structure:
                {
                    "type": "key_press" | "key_hold" | "button_press" | "wait",
                    "key": str (for keyboard actions),
                    "button_id": str (for button by ID),
                    "button_name": str (for button by name),
                    "duration": float,
                    "reason": str (optional)
                }
        """
        if not actions:
            print("No actions to execute")
            return
        
        print(f"🎮 Executing {len(actions)} action(s) in parallel...")
        
        # Release all keys first to reset state
        print("🔧 Releasing all keys to reset state...")
        self.input_controller.release_all_keys()
        
        # Create tasks for all actions
        tasks = []
        for i, action in enumerate(actions):
            action_type = action.get("type")
            reason = action.get("reason", "")
            
            print(f"   [{i+1}/{len(actions)}] {action_type}: {reason}")
            
            try:
                if action_type == "key_press":
                    key = action.get("key")
                    duration = action.get("duration", 0.1)
                    tasks.append(asyncio.create_task(
                        self.execute_key_press(key, duration)
                    ))
                
                elif action_type == "key_hold":
                    key = action.get("key")
                    duration = action.get("duration")
                    if duration is None:
                        raise ValueError("duration is required for key_hold")
                    tasks.append(asyncio.create_task(
                        self.execute_key_hold(key, duration)
                    ))
                
                elif action_type == "button_press":
                    if "button_id" in action:
                        tasks.append(asyncio.create_task(
                            self.execute_button_press(action["button_id"])
                        ))
                    else:
                        raise ValueError("button_press requires either 'button_id' or 'button_name'")
                
                elif action_type == "slider_move":
                    slider_id = action.get("slider_id")
                    slider_value = action.get("slider_value")
                    if slider_id is None or slider_value is None:
                        raise ValueError("slider_move requires 'slider_id' and 'slider_value'")
                    
                    tasks.append(asyncio.create_task(
                        self.execute_slider_move(slider_id, slider_value)
                    ))
                
                elif action_type == "swipe":
                    start_x = action.get("start_x")
                    start_y = action.get("start_y")
                    end_x = action.get("end_x")
                    end_y = action.get("end_y")
                    duration = action.get("duration")
                    tasks.append(asyncio.create_task(self.execute_swipe(start_x, start_y, end_x, end_y, duration)))

                elif action_type == "wait":
                    duration = action.get("duration")
                    if duration is None:
                        raise ValueError("duration is required for wait")
                    tasks.append(asyncio.create_task(
                        self.execute_wait(duration)
                    ))
                
                else:
                    print(f"   ⚠️  Unknown action type: {action_type}")
                    continue
                    
            except Exception as e:
                print(f"   ❌ Error creating task for action {i+1}: {e}")
                continue
        
        # Wait for all tasks to complete
        if tasks:
            print("🔧 Waiting for all actions to complete...")
            # TODO: Investigate this logic because this is supposed to be sequential but we are using gather which is supposed to be parallel
            await asyncio.gather(*tasks, return_exceptions=True)
            
            # Check for exceptions
            for i, task in enumerate(tasks):
                if task.exception():
                    print(f"   ❌ Action {i+1} failed: {task.exception()}")
        
        # Ensure all keys are released after execution
        print("🔧 Releasing all keys after actions...")
        self.input_controller.release_all_keys()
        
        print("✅ All actions completed!")
    
    async def execute_actions_sequential(self, actions: List[Any]) -> None:
        if not actions:
            return
        
        self.input_controller.release_all_keys()
        
        for action in actions:
            if hasattr(action, 'action_type'):
                action_type = action.action_type
                key_name = action.key_name
                button_id = action.button_id
                slider_id = getattr(action, 'slider_id', None)
                slider_value = getattr(action, 'slider_value', None)
                duration = action.duration
                start_x = action.start_x
                start_y = action.start_y
                end_x = action.end_x
                end_y = action.end_y
            else:
                action_type = action.get("type") or action.get("action_type")
                key_name = action.get("key") or action.get("key_name")
                button_id = action.get("button_id")
                slider_id = action.get("slider_id")
                slider_value = action.get("slider_value")
                duration = action.get("duration", 0.1)
                start_x = action.get("start_x")
                start_y = action.get("start_y")
                end_x = action.get("end_x")
                end_y = action.get("end_y")
            
            try:
                if action_type == "key_press":
                    if key_name is None:
                        raise ValueError("key_name is required for key_press")
                    await self.execute_key_press(key_name, duration)
                elif action_type == "button_press":
                    if button_id is None:
                        raise ValueError("button_press requires button_id")
                    await self.execute_button_press(str(button_id))
                elif action_type == "slider_move":
                    if slider_id is None or slider_value is None:
                        raise ValueError("slider_move requires 'slider_id' and 'slider_value'")
                    await self.execute_slider_move(str(slider_id), float(slider_value))
                elif action_type == "swipe":
                    if start_x is None or start_y is None or end_x is None or end_y is None:
                        raise ValueError("Co-ordinates values are required") # TODO: See if these errors are going back to the LLM or not.
                    await self.execute_swipe(start_x, start_y, end_x, end_y, duration)
                elif action_type == "wait":
                    if duration is None:
                        raise ValueError("duration is required for wait")
                    await self.execute_wait(duration)
            except Exception as e:
                print(f"Action failed: {e}")
                continue
        
        self.input_controller.release_all_keys()

    async def execute_swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float) -> None:
        await self.input_controller.swipe_async(start_x, start_y, end_x, end_y, duration)
    
    def invalidate_element_cache(self) -> None:
        """Invalidate the element cache to force refresh on next extraction"""
        self._cached_elements = None
        self._element_cache_timestamp = None
        self._elements_by_id.clear()
        print("🔄 Element cache invalidated")

