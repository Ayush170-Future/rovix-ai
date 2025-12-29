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
from prompts import SYSTEM_PROMPT
import sys
import time
from langchain_aws import ChatBedrockConverse
from langchain_google_genai import ChatGoogleGenerativeAI
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from tester import InputController, AltTesterClient, GameFrameController, SceneController, TimeController

load_dotenv()

model = ChatGoogleGenerativeAI(
    model="gemini-3-pro-preview",
    temperature=1.0,
    max_tokens=None,
    timeout=None,
    max_retries=2,
    api_key=os.getenv("GOOGLE_API_KEY")
)

client = AltTesterClient(host="127.0.0.1", port=13000, timeout=60)
driver = client.get_driver()
input_controller = InputController(driver)
time_controller = TimeController(driver)
scene_controller = SceneController(driver)
scene_controller.load_scene("SampleScene")
frame_controller = GameFrameController(driver)

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

class Action(BaseModel):
    action: Literal["do_nothing", "jump", "move_right", "move_left"] = Field(
        description="This represents the action that the player should take. 'do_nothing' means the player should not take any action. Remember there is never a compulsion to make decision, you can always 'do_nothing' when action is not required."
    )
    duration: float = Field(
        default=0.1,
        description="The time measured in seconds to keep the button down. Default is 0.1 second. Duration is equally proportional to the number of blocks the player will move in some direction (right, left, top). Looking at the frame, you should be able to estimate the duration for the action."
    )
    reason: str = Field(
        description="The reason for the action taken by the player."
    )
    end_game: bool = Field(
        default=False,
        description="This represents whether the game has ended or not. If the game has ended, the player should not take any action."
    )


class ActionList(BaseModel):
    actions: List[Action] = Field(
        description="A list of actions to be executed sequentially."
    )


class GamePauseEvent(BaseModel):
    """Data sent from Unity when game pauses"""
    current_step: int
    start_frame: int
    end_frame: int
    start_screenshot: str
    end_screenshot: str
    key_prefix: str
    available_frames: List[int]


structured_model = model.with_structured_output(
    schema=ActionList.model_json_schema(), method="json_schema"
)

# Global game state - maintains conversation history across pause events
game_state_messages = [
    SystemMessage(content=SYSTEM_PROMPT),
]
game_state_lock = threading.Lock()


def reset_game_state():
    """Reset the global game state to initial state with system prompt"""
    global game_state_messages
    with game_state_lock:
        game_state_messages = [
            SystemMessage(content=SYSTEM_PROMPT),
        ]
        print("🔄 Game state reset")


def get_screenshot_base64():
    """Capture screenshot and return as base64 string"""
    # Create snapshots directory if it doesn't exist
    snapshots_dir = os.path.join(os.path.dirname(__file__), "snapshots")
    os.makedirs(snapshots_dir, exist_ok=True)
    
    # Generate filename with timestamp
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"screenshot_{timestamp}.png"
    filepath = os.path.join(snapshots_dir, filename)
    
    driver.get_png_screenshot(filepath)
    
    image_bytes = image_to_bedrock_bytes(filepath)
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
    
    print(f"💾 Screenshot saved: {filepath}")
    
    return image_base64


async def perform_action_async(action: Action):
    """Execute the action specified by the agent asynchronously"""
    print(f"Performing action: {action.action} for {action.duration}s - Reason: {action.reason}")
    
    if action.action == "jump":
        await input_controller.jump_async(hold_duration=action.duration)
    elif action.action == "move_right":
        await input_controller.move_right_async(duration=action.duration)
    elif action.action == "move_left":
        await input_controller.move_left_async(duration=action.duration)
    elif action.action == "do_nothing":
        await asyncio.sleep(action.duration)

async def execute_actions_async(action_list: ActionList):
    """
    Execute actions asynchronously (like jump_and_move_right pattern).
    Actions run concurrently, then keys are released.
    """
    executable_actions = [action for action in action_list.actions if not action.end_game]
    
    if not executable_actions:
        print("No executable actions")
        return
    
    # Release all keys first
    print("🔧 Releasing all keys to reset state...")
    input_controller.release_all_keys()
    
    # Create asyncio tasks for all actions - they run concurrently
    print(f"🔧 Creating {len(executable_actions)} action tasks...")
    tasks = []
    for i, action in enumerate(executable_actions):
        print(f"   Task {i+1}: {action.action} ({action.duration}s)")
        tasks.append(asyncio.create_task(perform_action_async(action)))
    
    # Wait for all actions to complete
    print("🔧 Waiting for all actions to complete...")
    for task in tasks:
        await task
    
    print("✅ All actions completed!")
    
    # Ensure all keys are released after inputs
    print("🔧 Releasing all keys after actions...")
    input_controller.release_all_keys()
    print("✅ All keys released")
    
async def capture_screenshots_async(frames_per_action):
    """
    Capture screenshots at start, middle, and end frames in parallel with actions.
    
    Returns:
        tuple: (screenshots list, screenshot_labels list)
    """
    screenshots = []
    screenshot_labels = []
    
    try:
        # Calculate frame positions
        start_frame = frame_controller.get_current_frame()
        middle_frame = start_frame + (frames_per_action // 2)
        end_frame = start_frame + frames_per_action
        
        print(f"Capturing screenshots at frames: {start_frame}, {middle_frame}, {end_frame}")
        
        # Screenshot 1: Start (immediate) - Run in thread to avoid blocking
        print(f"  📸 Capturing START screenshot at frame {start_frame}")
        screenshot_start = await asyncio.to_thread(get_screenshot_base64)
        screenshots.append(screenshot_start)
        screenshot_labels.append(f"START (frame {start_frame})")
        
        # Wait for middle frame
        timeout = 10  # seconds
        start_time = time.time()
        
        while frame_controller.get_current_frame() < middle_frame:
            if time.time() - start_time > timeout:
                print("Warning: Timeout waiting for middle frame")
                break
            await asyncio.sleep(0.05)
        
        # Screenshot 2: Middle - Run in thread to avoid blocking
        actual_middle_frame = frame_controller.get_current_frame()
        print(f"  📸 Capturing MIDDLE screenshot at frame {actual_middle_frame}")
        screenshot_middle = await asyncio.to_thread(get_screenshot_base64)
        screenshots.append(screenshot_middle)
        screenshot_labels.append(f"MIDDLE (frame {actual_middle_frame})")
        
        # Wait for end frame
        start_time = time.time()
        while frame_controller.get_current_frame() < end_frame:
            if time.time() - start_time > timeout:
                print("Warning: Timeout waiting for end frame")
                break
            await asyncio.sleep(0.05)
        
        # Screenshot 3: End - Run in thread to avoid blocking
        actual_end_frame = frame_controller.get_current_frame()
        print(f"  📸 Capturing END screenshot at frame {actual_end_frame}")
        screenshot_end = await asyncio.to_thread(get_screenshot_base64)
        screenshots.append(screenshot_end)
        screenshot_labels.append(f"END (frame {actual_end_frame})")
        
        print(f"✅ Captured {len(screenshots)} screenshots")
        
        return screenshots, screenshot_labels
        
    except Exception as e:
        print(f"❌ Exception in capture_screenshots_async: {e}")
        print(f"   Exception type: {type(e).__name__}")
        import traceback
        traceback.print_exception(type(e), e, e.__traceback__)
        # Return whatever screenshots we managed to capture
        return screenshots, screenshot_labels
