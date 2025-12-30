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
    
    def __init__(self, driver: AltDriver, config_path: Optional[str] = None):
        """
        Initialize ActionHandler.
        
        Args:
            driver: AltDriver instance from service.py
            config_path: Path to action config JSON. If None, uses default config.
        """
        self.driver = driver
        self.input_controller = InputController(driver)
        
        # Load configuration
        if config_path is None:
            # Use default config path
            default_config = os.path.join(
                os.path.dirname(__file__),
                "config",
                "action_config.json"
            )
            config_path = default_config
        
        self.config = self._load_config(config_path)
        
        # Element cache
        self._cached_elements: Optional[List[Dict[str, Any]]] = None
        self._element_cache_timestamp: Optional[float] = None
        
        # Fast lookup dictionaries
        self._elements_by_id: Dict[str, Dict[str, Any]] = {}
    
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
        
        for component_type in component_types:
            try:
                objects = self.driver.find_objects(By.COMPONENT, component_type)
                
                if objects:
                    print(f"   ✅ Found {len(objects)} {component_type} element(s)")
                    
                    for obj in objects:
                        try:
                            element_info = self._extract_element_info(obj, component_type)
                            if element_info:
                                elements.append(element_info)
                        except Exception as e:
                            print(f"   ⚠️  Error processing element: {e}")
                            continue
                            
            except Exception as e:
                print(f"   ⚠️  Error searching for {component_type}: {e}")
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
    
    def _extract_element_info(self, obj: Any, component_type: str) -> Optional[Dict[str, Any]]:
        """
        Extract information from an AltObject.
        
        Args:
            obj: AltObject instance
            component_type: Type of component
            
        Returns:
            Element info dictionary or None if extraction fails
        """
        try:
            element_id = str(obj.id) if hasattr(obj, 'id') else None
            name = obj.name if hasattr(obj, 'name') else "Unknown"
            
            # Get position
            position = None
            if hasattr(obj, 'x') and hasattr(obj, 'y'):
                position = (float(obj.x), float(obj.y))
            
            # Get text if available
            text = None
            try:
                text = obj.get_text()
            except:
                pass
            
            # Get enabled state
            enabled = True
            if hasattr(obj, 'enabled'):
                enabled = obj.enabled
            
            return {
                "id": element_id,
                "name": name,
                "type": component_type,
                "position": position,
                "text": text,
                "enabled": enabled,
                "object": obj  # Keep reference for execution
            }
            
        except Exception as e:
            print(f"      ⚠️  Error extracting info: {e}")
            return None
    
    def get_available_actions(self) -> Dict[str, Any]:
        """
        Get all available actions based on config and current game state.
        
        Returns:
            Dictionary with available primitives:
            {
                "keyboard": {
                    "key_press": {"available_keys": [...]},
                    "key_hold": {"available_keys": [...]}
                },
                "buttons": [
                    {"id": "...", "name": "...", ...},
                    ...
                ]
            }
        """
        available = {
            "keyboard": {},
            "buttons": []
        }
        
        # Keyboard actions
        if self.config.get("input_types", {}).get("keyboard", {}).get("enabled", False):
            available_keys = self.config.get("input_types", {}).get("keyboard", {}).get("available_keys", [])
            available["keyboard"] = {
                "key_press": {"available_keys": available_keys},
                "key_hold": {"available_keys": available_keys}
            }
        
        # Button actions
        if self.config.get("input_types", {}).get("buttons", {}).get("enabled", False):
            elements = self.extract_interactive_elements(force_refresh=True)
            # Return simplified info (without object reference)
            available["buttons"] = [
                {
                    "id": elem["id"],
                    "name": elem["name"],
                    "type": elem["type"],
                    "position": elem["position"],
                    "text": elem.get("text"),
                    "enabled": elem["enabled"]
                }
                for elem in elements
            ]
        
        print(f"✅ Available actions: {available}")
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
                duration = action.duration
            else:
                action_type = action.get("type") or action.get("action_type")
                key_name = action.get("key") or action.get("key_name")
                button_id = action.get("button_id")
                duration = action.get("duration", 0.1)
            
            try:
                if action_type == "key_press":
                    if key_name is None:
                        raise ValueError("key_name is required for key_press")
                    await self.execute_key_press(key_name, duration)
                elif action_type == "button_press":
                    if button_id is None:
                        raise ValueError("button_press requires button_id")
                    await self.execute_button_press(str(button_id))
                elif action_type == "wait":
                    if duration is None:
                        raise ValueError("duration is required for wait")
                    await self.execute_wait(duration)
            except Exception as e:
                print(f"Action failed: {e}")
                continue
        
        self.input_controller.release_all_keys()
    
    def invalidate_element_cache(self) -> None:
        """Invalidate the element cache to force refresh on next extraction"""
        self._cached_elements = None
        self._element_cache_timestamp = None
        self._elements_by_id.clear()
        print("🔄 Element cache invalidated")

