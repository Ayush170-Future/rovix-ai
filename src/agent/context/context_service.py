import threading
import base64
import io
import sys
import os
from typing import Dict, List, Optional, Any
import imagehash
from PIL import Image
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

ANNOTATION_CACHE_THRESHOLD = 15  # dhash Hamming distance below which we reuse cached annotations

# TODO: Add a `force_vision_refresh: bool` field to AgentOutput so the LLM can request
# fresh annotation when cached elements don't match what it sees on screen.

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from tools.todo_management import get_todo_list_for_context

try:
    from ..logger import get_logger
except ImportError:
    from agent.logger import get_logger

logger = get_logger("agent.context.context_service")


class ContextService:
    def __init__(self, system_prompt: str, keep_full_steps: int = 4):
        self.system_prompt = system_prompt
        self.keep_full_steps = keep_full_steps
        self._sessions: Dict[str, Dict] = {}
        self._lock = threading.Lock()
    
    def _ensure_session(self, session_id: str, game_description: Optional[str] = None, gameplay_details: Optional[str] = None, test_plan: Optional[str] = None) -> bool:
        if session_id not in self._sessions:
            # These parameters are required when creating a new session
            if game_description is None or gameplay_details is None or test_plan is None:
                return False
            system_prompt = self.system_prompt.format(
                game_description=game_description,
                gameplay_details=gameplay_details,
                test_plan=test_plan
            )
            self._sessions[session_id] = {
                'messages': [SystemMessage(content=system_prompt)],
                'step_counter': 0,
                'last_annotation_hash': None,
                'last_annotation_step': None,
                'last_annotation_message': None,
            }
        return True
    
    async def add_new_step(
        self,
        session_id: str,
        screenshot_path: str,
        available_actions: Dict[str, Any],
        step: int,
        frame: int,
        vision_detector=None,
        action_handler=None,
        sdk_enabled: bool = True,
        force_annotate: bool = False
    ):
        with self._lock:
            self._ensure_session(session_id)
            
            marker_msg = self._build_marker_message(is_current=True)
            screenshot_msg = self._build_screenshot_message(screenshot_path, step, frame)
            actions_msg = await self._build_available_actions_message(
                session_id,
                screenshot_path,
                available_actions,
                vision_detector,
                action_handler,
                sdk_enabled,
                step,
                force_annotate
            )
            todo_msg = self._build_todo_context_message(session_id)
            
            self._sessions[session_id]['messages'].append(marker_msg)
            self._sessions[session_id]['messages'].append(screenshot_msg)
            self._sessions[session_id]['messages'].append(actions_msg)
            self._sessions[session_id]['messages'].append(todo_msg)
    
    def add_ai_response(self, session_id: str, agent_output):
        with self._lock:
            self._ensure_session(session_id)
            
            messages = self._sessions[session_id]['messages']
            
            if len(messages) >= 5 and isinstance(messages[-5], HumanMessage):
                content = str(messages[-5].content)
                if "todo_write result:" in content:
                    messages.pop(-5)
            
            self._sessions[session_id]['messages'].append(
                AIMessage(content=str(agent_output.model_dump()))
            )
            
            if len(self._sessions[session_id]['messages']) >= 2:
                self._sessions[session_id]['messages'].pop(-2)
            
            self._sessions[session_id]['step_counter'] += 1
    
    def add_todo_result(self, session_id: str, result: str):
        with self._lock:
            self._ensure_session(session_id)
            self._sessions[session_id]['messages'].append(
                HumanMessage(content=[{
                    "type": "text",
                    "text": f"todo_write result: {result}"
                }])
            )
    
    def get_messages_for_llm(self, session_id: str) -> List:
        with self._lock:
            self._ensure_session(session_id)
            return self._sessions[session_id]['messages'].copy()
    
    def cleanup_old_messages(self, session_id: str):
        with self._lock:
            self._ensure_session(session_id)
            
            messages = self._sessions[session_id]['messages']
            step_counter = self._sessions[session_id]['step_counter']
            
            has_todo_result = False
            if len(messages) >= 1 and isinstance(messages[-1], HumanMessage):
                content = str(messages[-1].content)
                if "todo_write result:" in content:
                    has_todo_result = True
            
            marker_offset = -5 if has_todo_result else -4
            
            if len(messages) >= abs(marker_offset):
                messages[marker_offset].content[0]["text"] = f"[PAST GAME STATE - Step {step_counter}]"
            
            total_messages = len(messages)
            adjusted_total = total_messages - 1 if has_todo_result else total_messages
            
            if adjusted_total <= 1 + self.keep_full_steps * 4:
                return
            
            oldest_ai_index = adjusted_total - 1 - self.keep_full_steps * 4
            
            messages.pop(oldest_ai_index - 1)
            messages.pop(oldest_ai_index - 2)
    
    def get_message_count(self, session_id: str) -> int:
        with self._lock:
            self._ensure_session(session_id)
            return len(self._sessions[session_id]['messages'])
    
    def get_step_counter(self, session_id: str) -> int:
        with self._lock:
            self._ensure_session(session_id)
            return self._sessions[session_id]['step_counter']
    
    def reset(self, session_id: str):
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
    
    def get_all_sessions(self) -> List[str]:
        with self._lock:
            return list(self._sessions.keys())
    
    def _build_marker_message(self, is_current: bool, step: Optional[int] = None) -> HumanMessage:
        if is_current:
            text = "[CURRENT GAME STATE]"
        else:
            text = f"[PAST GAME STATE - Step {step}]"
        
        return HumanMessage(content=[{"type": "text", "text": text}])
    
    def _build_screenshot_message(self, screenshot_path: str, step: int, frame: int) -> HumanMessage:
        screenshot_base64 = self._image_file_to_base64(screenshot_path)
        
        message_content = [
            {
                "type": "text",
                "text": f"Here is the current game state. This is a 2d game. "
                       f"Your goal is to clearly identify the next set of actions or a single action. "
                       f"Analyze the screenshot and decide on the next actions."
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{screenshot_base64}"
                }
            }
        ]
        
        return HumanMessage(content=message_content)
    
    async def _build_available_actions_message(
        self,
        session_id: str,
        screenshot_path: str,
        available_actions: Dict[str, Any],
        vision_detector,
        action_handler,
        sdk_enabled: bool,
        step: int = 0,
        force_annotate: bool = False
    ) -> HumanMessage:
        
        if not sdk_enabled and vision_detector:
            session = self._sessions[session_id]
            current_hash = imagehash.dhash(Image.open(screenshot_path))

            if force_annotate:
                logger.info(f"🔄 Force annotation requested, bypassing cache")
            elif session['last_annotation_hash'] is None:
                logger.info("🆕 No cached annotation yet, running first annotation")
            else:
                distance = current_hash - session['last_annotation_hash']
                logger.debug(f"🔍 Annotation cache: dhash distance={distance} (threshold={ANNOTATION_CACHE_THRESHOLD})")

                if distance < ANNOTATION_CACHE_THRESHOLD:
                    cached_step = session['last_annotation_step']
                    cached_text = session['last_annotation_message'].content[0]["text"]
                    logger.info(f"♻️  Reusing cached annotations from step {cached_step} (distance={distance} < {ANNOTATION_CACHE_THRESHOLD})")
                    logger.debug(f"   Cached text: {cached_text}")
                    reused_text = cached_text + f"\n\n(Cached from step {cached_step} — screen unchanged, dhash distance={distance})"
                    return HumanMessage(content=[{"type": "text", "text": reused_text}])
                else:
                    logger.info(f"🆕 Screen changed (distance={distance} >= {ANNOTATION_CACHE_THRESHOLD}), running fresh annotation")

            detection_result = await vision_detector.detect_elements(screenshot_path)
            
            if detection_result.success:
                action_message_content = "Detected interactive elements on screen:"
                if detection_result.elements:
                    for element in detection_result.elements:
                        name = element['name']
                        desc = element['description']
                        pos = element['screen_position']
                        bbox = element['bounding_box']
                        action_message_content += f"\n- {name} at ({pos[0]}, {pos[1]}) bbox: [{bbox[0]}, {bbox[1]}, {bbox[2]}, {bbox[3]}] - {desc}"
                else:
                    action_message_content += "\n- No elements detected. Analyze the screenshot to identify clickable areas."
            else:
                action_message_content = (
                    f"⚠️ Vision detection failed after {detection_result.retry_count} attempts: "
                    f"{detection_result.error_message}\n"
                    "Fallback: Analyze the screenshot carefully to identify clickable areas and their positions."
                )
                logger.warning(f"⚠️ Context service: Vision detection failed, providing fallback message")
            
            built_message = HumanMessage(content=[{"type": "text", "text": action_message_content}])

            if detection_result.success:
                session['last_annotation_hash'] = current_hash
                session['last_annotation_step'] = step
                session['last_annotation_message'] = built_message
                logger.debug(f"💾 Annotation cache updated for step {step}")

            return built_message
        
        action_message_content = "You can currently interact with the following controls on the screen: \n Buttons available to click:"
        buttons = available_actions.get("buttons", [])
        if buttons:
            for button in buttons:
                name = button.get("name", "Unknown")
                button_id = button.get("id", "N/A")
                screen_position = button.get("screen_position")
                enabled = button.get("enabled", True)
                
                if screen_position and len(screen_position) == 2:
                    pos_str = f"{int(screen_position[0])} × {int(screen_position[1])}"
                else:
                    pos_str = "N/A"
                
                enabled_str = "Enabled" if enabled else "Disabled"
                action_message_content += f"\n- name = {name}     (Button ID: {button_id}, Position: {pos_str}, {enabled_str})"
        else:
            action_message_content += "\n- No buttons available"
        
        sliders = available_actions.get("sliders", [])
        if sliders:
            action_message_content += "\n Sliders available to adjust:"
            for slider in sliders:
                name = slider.get("name", "Unknown")
                slider_id = slider.get("id", "N/A")
                screen_position = slider.get("screen_position")
                enabled = slider.get("enabled", True)
                min_value = slider.get("minValue")
                max_value = slider.get("maxValue")
                current_value = slider.get("value")
                
                if screen_position and len(screen_position) == 2:
                    pos_str = f"{int(screen_position[0])} × {int(screen_position[1])}"
                else:
                    pos_str = "N/A"
                
                enabled_str = "Enabled" if enabled else "Disabled"
                
                if min_value is not None and max_value is not None:
                    range_str = f"Range: {min_value} - {max_value}"
                else:
                    range_str = "Range: N/A"
                
                if current_value is not None:
                    value_str = f"Current: {current_value}"
                else:
                    value_str = "Current: N/A"
                
                action_message_content += f"\n- name = {name}     (Slider ID: {slider_id}, Position: {pos_str}, {range_str}, {value_str}, {enabled_str})"
        else:
            action_message_content += "\n Sliders available to adjust:\n- No sliders available"
        
        interactable_2ds = available_actions.get("interactable_2d", [])
        if interactable_2ds:
            action_message_content += "\n Interactable 2D available to interact with:"
            for interactable_2d in interactable_2ds:
                name = interactable_2d.get("name", "Unknown")
                item_id = interactable_2d.get("id", "N/A")
                screen_position = interactable_2d.get("screen_position")
                enabled = interactable_2d.get("enabled", True)
                collider = interactable_2d.get("type", "N/A")

                if screen_position and len(screen_position) == 2:
                    pos_str = f"{int(screen_position[0])} × {int(screen_position[1])}"
                else:
                    pos_str = "N/A"

                enabled_str = "Enabled" if enabled else "Disabled"
                action_message_content += f"\n- name = {name}     (Interactable 2D ID: {item_id}, Position: {pos_str}, {enabled_str}, Collider Type: {collider})"
        else:
            action_message_content += "\n Interactable 2D available to interact with:\n- No interactable 2D available"

        available_keys = available_actions.get("keyboard", {}).get("key_press", {}).get("available_keys", [])
        action_message_content += "\n Keys available to press:\n- " + ", ".join(available_keys)
        
        return HumanMessage(content=[{"type": "text", "text": action_message_content}])
    
    def _build_todo_context_message(self, session_id: str) -> HumanMessage:
        try:
            todo_context = get_todo_list_for_context(session_id)
            
            return HumanMessage(content=[{
                "type": "text",
                "text": f"\n{todo_context}"
            }])
        except Exception as e:
            return HumanMessage(content=[{
                "type": "text",
                "text": "No todo context available."
            }])
    
    def _image_file_to_base64(self, filepath: str, max_size=(1024, 1024), quality=75) -> str:
        img = Image.open(filepath).convert("RGB")
        img.thumbnail(max_size)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        image_bytes = buf.getvalue()
        return base64.b64encode(image_bytes).decode("utf-8")
