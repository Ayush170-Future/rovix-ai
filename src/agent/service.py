import getpass
import os
import base64
import tempfile
import io
import asyncio
import threading
from PIL import Image
from pydantic import BaseModel, Field
from typing import Literal, List, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from dotenv import load_dotenv
import sys
import time
from langchain_aws import ChatBedrockConverse
from langchain_google_genai import ChatGoogleGenerativeAI
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from .prompts import SYSTEM_PROMPT
except ImportError:
    from agent.prompts import SYSTEM_PROMPT
from tester import InputController, AltTesterClient, GameFrameController, SceneController, TimeController
from agent.actions import ActionHandler

load_dotenv()

model = ChatGoogleGenerativeAI(
    model="gemini-3-pro-preview",
    temperature=1.0,
    max_tokens=None,
    timeout=None,
    max_retries=2,
    api_key=os.getenv("GOOGLE_API_KEY")
)

print("Initializing AltTesterClient...")
client = AltTesterClient(host="127.0.0.1", port=13000, timeout=60)
print("AltTesterClient initialized")
driver = client.get_driver()
input_controller = InputController(driver)
time_controller = TimeController(driver)
scene_controller = SceneController(driver)
frame_controller = GameFrameController(driver)
frame_controller.mark_actions_executed()
frame_controller.get_current_game_state()

action_handler = ActionHandler(driver)

def image_to_bedrock_bytes(path, max_size=(1024, 1024), quality=75):
    img = Image.open(path).convert("RGB")
    img.thumbnail(max_size)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()

def image_file_to_base64(filepath, max_size=(1024, 1024), quality=75):
    """Convert a saved image file to base64 string"""
    image_bytes = image_to_bedrock_bytes(filepath, max_size=max_size, quality=quality)
    return base64.b64encode(image_bytes).decode("utf-8")

# TODO: Can change this to XML later on.
class Action(BaseModel):
    action_type: Literal["key_press", "button_press", "slider_move", "swipe", "wait"] = Field(
        description="Represents the type of action to be performed. This can be a key press, button press, slider move, or swipe."
    )
    key_name: str | None = Field(
        description="Represents the name of the key to be pressed from the keyboard. All possible keys are listed in the last message. This is going to be N/A if the action is not a key press."
    )
    button_id: int | None = Field(
        description="Represents the ID of the button to be clicked on the screen. This is a unique identifier for the button and you can find the available buttons in the last message. This is going to be N/A if the action is not a button press."
    )
    slider_id: str | None = Field(
        description="Represents the ID of the slider to be moved on the screen. This is a unique identifier for the slider and you can find the available sliders in the last message. This is going to be N/A if the action is not a slider move."
    )
    slider_value: float | None = Field(
        description="Represents the value to be set on the slider. You can find the current value and the allowed range in the previous Game state message and you can find the available values in the last message. This is going to be N/A if the action is not a slider move."
    )
    start_x: int | None = Field(
        description="Represents the x coordinate of the start point of the swipe. This is going to be N/A if the action_type is not a swipe."
    )
    start_y: int | None = Field(
        description="Represents the y coordinate of the start point of the swipe. This is going to be N/A if the action_type is not a swipe."
    )
    end_x: int | None = Field(
        description="Represents the x coordinate of the end point of the swipe. This is going to be N/A if the action_type is not a swipe."
    )
    end_y: int | None = Field(
        description="Represents the y coordinate of the end point of the swipe. This is going to be N/A if the action_type is not a swipe."
    )
    duration: float = Field(
        default=0.1,
        description="Represents the duration of the action in seconds. Default is 0.1 second. This might not be relevant for the button press actions."
    )

# TODO: Add analyze last step and reason next step fields here as well
class AgentOutput(BaseModel):
    game_state_summary: str = Field(
        description="A concise summary of the current game state, key observations, and important context that should be remembered for future steps. This summary will be preserved in the conversation history even when screenshots are removed. Include: current game situation, player status, important objects/entities, recent changes, and any critical information needed for decision-making."
    ),
    reason: str = Field(
        description="Use this field to reason about the current game state and your overall performance, observations, goals that will help you complete the game and figure out the next set of actions."
    ),
    end_game: bool = Field(
        default=False,
        description="This represents whether the game has ended or not. If the game has ended, the player should not take any action."
    ),
    actions: List[Action] = Field(
        description="A list of actions to be executed sequentially. This can be a combination of keyboard and button press actions."
    )

class GamePauseEvent(BaseModel):
    """Data sent from Unity when event interval is reached"""
    current_step: int
    current_frame: int


structured_model = model.with_structured_output(schema=AgentOutput.model_json_schema(), method="json_schema", include_raw=True)

# Global game state - maintains conversation history across pause events
game_state_messages = [
    SystemMessage(content=SYSTEM_PROMPT),
]
game_state_lock = threading.Lock()
KEEP_FULL_STEPS = 4  # Number of complete steps to keep with full screenshots/actions
step_counter = 0  # Global step counter

def cleanup_old_messages():
    """
    1. Update the marker at index -4 to '[PAST GAME STATE - Step X]'
    2. Remove screenshot and available actions from the oldest full step
    """
    with game_state_lock:
        # Step 1: Update the marker at index -4 (always the most recent one)
        game_state_messages[-4].content[0]["text"] = f"[PAST GAME STATE - Step {step_counter}]"
        print(f"📝 Updated marker to [PAST GAME STATE - Step {step_counter}]")
        
        # Step 2: Cleanup old messages if we have more than KEEP_FULL_STEPS
        total_messages = len(game_state_messages)
        
        if total_messages <= 1 + KEEP_FULL_STEPS * 4:
            print(f"📊 {total_messages} messages - no cleanup needed yet")
            return
        
        # Find the AIMessage of the oldest step that should be compressed
        oldest_ai_index = total_messages - 1 - KEEP_FULL_STEPS * 4
        
        # Remove available actions and screenshot
        game_state_messages.pop(oldest_ai_index - 1)  # Remove available actions
        game_state_messages.pop(oldest_ai_index - 2)  # Remove screenshot
        
        print(f"🧹 Cleaned up old messages. Remaining: {len(game_state_messages)} messages")

def parse_llm_response(response: dict) -> AgentOutput:
    agent_output = None
    if isinstance(response, dict) and 'parsed' in response and 'raw' in response:
        parsed_output = response['parsed']
        raw_output = response['raw']
        agent_output = AgentOutput(**parsed_output) if isinstance(parsed_output, dict) else parsed_output
        
        # Access token counts from raw output
        if hasattr(raw_output, 'usage_metadata') and raw_output.usage_metadata:
            token_counts = raw_output.usage_metadata
            print(f"📊 Token counts: {token_counts}")
            cached_tokens = raw_output.cachedContentTokenCount if hasattr(raw_output, 'cachedContentTokenCount') else 1
            input_tokens = token_counts.get('input_tokens') if isinstance(token_counts, dict) else getattr(token_counts, 'input_tokens', None)
            output_tokens = token_counts.get('output_tokens') if isinstance(token_counts, dict) else getattr(token_counts, 'output_tokens', None)
            total_tokens = token_counts.get('total_tokens') if isinstance(token_counts, dict) else getattr(token_counts, 'total_tokens', None)
            
            if input_tokens is not None:
                print(f"📊 Token usage - Input: {input_tokens}, Output: {output_tokens}, Total: {total_tokens}")
                print(f"📊 Cached tokens: {cached_tokens}")
    else:
        # Fallback for older response format
        agent_output = AgentOutput(**response) if isinstance(response, dict) else response

    return agent_output

async def agent_handler(event: GamePauseEvent):
    print(f"\n🎮 Event received - Step: {event.current_step}, Frame: {event.current_frame}")
    
    # Create screenshots directory
    screenshots_dir = os.path.join(os.path.dirname(__file__), "..", "agent", "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)
    
    # Capture screenshot directly from game (current state)
    filename = f"step_{event.current_step}_frame_{event.current_frame}.png"
    filepath = os.path.join(screenshots_dir, filename)
    
    try:
        # Capture screenshot directly from game
        driver.get_png_screenshot(filepath)
        print(f"   💾 {filename} (captured from game)")
        saved_filepaths = [filepath]
    except Exception as e:
        print(f"   ❌ Error capturing screenshot: {e}")
        return {"status": "error", "message": f"Failed to capture screenshot: {e}"}
    
    print(f"✅ Saved screenshot")
    
    # Call LLM and execute actions
    if saved_filepaths:
        try:
            # Convert screenshot to base64
            print("🔄 Converting screenshot to base64...")
            screenshot_base64 = image_file_to_base64(saved_filepaths[0])
            
            # Prepare message for LLM
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
            
            current_game_state_indication_message = HumanMessage(content=[{
                "type": "text",
                "text": f"[CURRENT GAME STATE]"
            }])
            available_actions_message = await get_available_actions_message()
            # Add human message to global game state
            screenshot_message = HumanMessage(content=message_content)
            with game_state_lock:
                # # Removing the previous Current Game State indication message (third-to-last)
                # if len(game_state_messages) >= 4:
                #     # POP the third-to-last message (index -3)
                #     game_state_messages.pop(-3)

                game_state_messages.append(current_game_state_indication_message)
                game_state_messages.append(screenshot_message)

                # Add available actions message
                game_state_messages.append(available_actions_message)

                # Create a copy of messages for this LLM call
                messages = game_state_messages.copy()
            
            # Get agent decision
            print("🤖 Getting agent decision from LLM...")
            response = await asyncio.to_thread(structured_model.invoke, messages)

            agent_output = parse_llm_response(response)
            print(f"✅ Agent decision: {agent_output.model_dump()}")
            
            # Add AI response to global game state
            global step_counter
            with game_state_lock:
                game_state_messages.append(AIMessage(content=str(agent_output.model_dump())))
                step_counter += 1  # Increment step counter

            # Check if game should end
            if agent_output.end_game:
                print("🛑 Agent signaled end of game")
                # Mark actions as executed even if ending game
                try:
                    frame_controller.mark_actions_executed()
                except Exception as e:
                    print(f"⚠️  Warning: Failed to mark actions executed: {e}")
                return {"status": "ok", "saved": 1, "files": [filename], "end_game": True}
            
            # Execute actions synchronously
            print("🎮 Executing actions synchronously...")
            await action_handler.execute_actions_sequential(agent_output.actions)
            print("✅ Actions executed successfully")
            
            # Cleanup old messages
            cleanup_old_messages()
            
            # Mark actions as executed so Unity can send the next event
            try:
                print("✅ Marking actions as executed...")
                frame_controller.mark_actions_executed()
                print("✅ Actions marked as executed - Unity can send next event")
            except Exception as e:
                print(f"❌ Error marking actions executed: {e}")
                return {"status": "error", "message": f"Failed to mark actions executed: {e}"}
            
            # Return success
            return {"status": "ok", "saved": 1, "files": [filename]}
            
        except Exception as e:
            print(f"❌ Error in LLM call or action execution: {e}")
            import traceback
            traceback.print_exception(type(e), e, e.__traceback__)
            # Even on error, mark actions as executed so Unity doesn't get stuck
            try:
                frame_controller.mark_actions_executed()
            except Exception as mark_error:
                print(f"⚠️  Warning: Failed to mark actions executed after error: {mark_error}")
            return {"status": "error", "message": f"Failed to process: {e}"}

async def get_available_actions_message() -> HumanMessage:
    available_actions = action_handler.get_available_actions()

    action_message_content = "You can currently interact with the following controls on the screen: \n Buttons available to click:"
    buttons = available_actions.get("buttons", [])
    if buttons:
        for index, button in enumerate(buttons):
            name = button.get("name", "Unknown")
            button_id = button.get("id", "N/A")
            position = button.get("position")
            enabled = button.get("enabled", True)
            
            # Format position
            if position and len(position) == 2:
                pos_str = f"{int(position[0])} × {int(position[1])}"
            else:
                pos_str = "N/A"
            
            # Format enabled status
            enabled_str = "Enabled" if enabled else "Disabled"
            
            # Add formatted button info
            action_message_content += f"\n- name = {name}     (Button ID: {button_id}, Position: {pos_str}, {enabled_str})"
    else:
        action_message_content += "\n- No buttons available"
    
    # Add sliders
    sliders = available_actions.get("sliders", [])
    if sliders:
        action_message_content += "\n Sliders available to adjust:"
        for slider in sliders:
            name = slider.get("name", "Unknown")
            slider_id = slider.get("id", "N/A")
            position = slider.get("position")
            enabled = slider.get("enabled", True)
            min_value = slider.get("minValue")
            max_value = slider.get("maxValue")
            current_value = slider.get("value")
            
            # Format position
            if position and len(position) == 2:
                pos_str = f"{int(position[0])} × {int(position[1])}"
            else:
                pos_str = "N/A"
            
            # Format enabled status
            enabled_str = "Enabled" if enabled else "Disabled"
            
            # Format min/max values and current value
            if min_value is not None and max_value is not None:
                range_str = f"Range: {min_value} - {max_value}"
            else:
                range_str = "Range: N/A"
            
            if current_value is not None:
                value_str = f"Current: {current_value}"
            else:
                value_str = "Current: N/A"
            
            # Add formatted slider info
            action_message_content += f"\n- name = {name}     (Slider ID: {slider_id}, Position: {pos_str}, {range_str}, {value_str}, {enabled_str})"
    else:
        action_message_content += "\n Sliders available to adjust:\n- No sliders available"
    
    # Add Interactable 2D
    interactable_2ds = available_actions.get("interactable_2d", [])
    if interactable_2ds:
        action_message_content += "\n Interactable 2D available to interact with:"
        for interactable_2d in interactable_2ds:
            name = interactable_2d.get("name", "Unknown")
            item_id = interactable_2d.get("id", "N/A")
            position = interactable_2d.get("position")
            enabled = interactable_2d.get("enabled", True)
            collider = interactable_2d.get("type", "N/A")

            # Format position
            if position and len(position) == 2:
                pos_str = f"{int(position[0])} × {int(position[1])}"
            else:
                pos_str = "N/A"

            # Format enabled status
            enabled_str = "Enabled" if enabled else "Disabled"

            # Add formatted button info
            action_message_content += f"\n- name = {name}     (Interactable 2D ID: {item_id}, Position: {pos_str}, {enabled_str}, Collider Type: {collider})"
    else:
        action_message_content += "\n Interactable 2D available to interact with:\n- No interactable 2D available"

    available_keys = available_actions.get("keyboard", {}).get("key_press", {}).get("available_keys", [])
    action_message_content += "\n Keys available to press:\n- " + ", ".join(available_keys)
    
    print(action_message_content)

    return HumanMessage(content=[{
        "type": "text",
        "text": action_message_content
    }])
