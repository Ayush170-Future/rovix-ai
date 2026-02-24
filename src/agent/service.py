import getpass
import os
import base64
import tempfile
import io
import asyncio
import threading
import json
from datetime import datetime
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
    from .prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_WITH_TODO, GAME_CONFIGS
except ImportError:
    from agent.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_WITH_TODO, GAME_CONFIGS

# --- GLOBAL LOGGER SETUP ---
_original_print = print
_run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
_log_file = f"run_log_{_run_id}.txt"

def _run_logger_print(*args, **kwargs):
    # Check if 'file' argument was supplied. If so, let built-in print handle it.
    if 'file' in kwargs:
        _original_print(*args, **kwargs)
        return

    # Convert all args to string
    msg = " ".join(str(a) for a in args)
    
    # 1. Print to console exactly as requested (no timestamp prefix)
    _original_print(msg, **kwargs)
    
    # 2. Append to run-specific log file
    try:
        with open(_log_file, "a") as f:
            f.write(msg + "\n")
    except Exception:
        pass

# Override built-in print for this module
import builtins
builtins.print = _run_logger_print
# ---------------------------

from tester import InputController, AltTesterClient, GameFrameController, SceneController, TimeController
from agent.actions import ActionHandler
from agent.adb_manager import ADBManager
from agent.appium_manager import AppiumManager
from agent.vision_element_detector import VisionElementDetector
from agent.context import ContextService
from agent.local_ocr import detect_bingo_numbers, detect_text, is_powerup_ready
from tools.todo_management import todo_write_handler, TODO_WRITE_INPUT_DESCRIPTION, get_todo_list_for_context
from tools.todo_management.todo_service import TodoPersistenceService

load_dotenv()

SDK_ENABLED = os.getenv("SDK_ENABLED", "true").lower() == "true"
USE_APPIUM = os.getenv("USE_APPIUM", "false").lower() == "true"
POLLING_INTERVAL = float(os.getenv("POLLING_INTERVAL", "2.5"))
MAX_STEPS = int(os.getenv("MAX_STEPS", "1000"))
SESSION_ID = "game_session_main"

AGENT_MODEL = os.getenv("AGENT_MODEL", "gemini-1.5-flash")
model = ChatGoogleGenerativeAI(
    model=AGENT_MODEL,
    temperature=1.0,
    max_tokens=None,
    timeout=None,
    max_retries=2,
    api_key=os.getenv("GOOGLE_API_KEY")
)
print(f"🤖 Using model: {AGENT_MODEL}")

if SDK_ENABLED:
    print("Initializing AltTesterClient...")
    client = AltTesterClient(host="127.0.0.1", port=13000, timeout=60)
    print("AltTesterClient initialized")
    driver = client.get_driver()
    input_controller = InputController(driver)
    time_controller = TimeController(driver)
    scene_controller = SceneController(driver)
    frame_controller = GameFrameController(driver)
    frame_controller.mark_actions_executed()
    
    if USE_APPIUM:
        print("Initializing Appium Manager...")
        action_executor = AppiumManager(
            appium_url=os.getenv("APPIUM_URL", "http://localhost:4723"),
            device_name=os.getenv("DEVICE_NAME"),
            udid=os.getenv("DEVICE_UDID"),
            app_package=os.getenv("APP_PACKAGE"),
            app_activity=os.getenv("APP_ACTIVITY"),
            screenshot_timeout=float(os.getenv("SCREENSHOT_TIMEOUT", "10.0")),
            screenshot_max_retries=int(os.getenv("SCREENSHOT_MAX_RETRIES", "3"))
        )
    else:
        print("Initializing ADB Manager...")
        action_executor = ADBManager(
            host="127.0.0.1", 
            port=5037,
            screenshot_timeout=float(os.getenv("SCREENSHOT_TIMEOUT", "10.0")),
            screenshot_max_retries=int(os.getenv("SCREENSHOT_MAX_RETRIES", "3"))
        )
    
    action_handler = ActionHandler(driver, adb_manager=action_executor)
    vision_detector = None
else:
    print("Black box mode - skipping AltTester initialization")
    client = None
    driver = None
    input_controller = None
    time_controller = None
    scene_controller = None
    frame_controller = None
    action_handler = None
    
    if USE_APPIUM:
        print("Initializing Appium Manager...")
        action_executor = AppiumManager(
            appium_url=os.getenv("APPIUM_URL", "http://localhost:4723"),
            device_name=os.getenv("DEVICE_NAME"),
            udid=os.getenv("DEVICE_UDID"),
            app_package=os.getenv("APP_PACKAGE"),
            app_activity=os.getenv("APP_ACTIVITY"),
            screenshot_timeout=float(os.getenv("SCREENSHOT_TIMEOUT", "10.0")),
            screenshot_max_retries=int(os.getenv("SCREENSHOT_MAX_RETRIES", "3"))
        )
    else:
        print("Initializing ADB Manager...")
        action_executor = ADBManager(
            host="127.0.0.1", 
            port=5037,
            screenshot_timeout=float(os.getenv("SCREENSHOT_TIMEOUT", "10.0")),
            screenshot_max_retries=int(os.getenv("SCREENSHOT_MAX_RETRIES", "3"))
        )
    
# Determine game configuration based on .env
GAME_NAME = os.getenv("GAME_NAME", "hitwicket").lower()
game_config = GAME_CONFIGS.get(GAME_NAME, GAME_CONFIGS["hitwicket"])

print(f"🎮 Target Game: {GAME_NAME.upper()}")

vision_detector = VisionElementDetector(
    api_key=os.getenv("GOOGLE_API_KEY"),
    model_name=os.getenv("VISION_MODEL", "gemini-robotics-er-1.5-preview"),
    timeout=float(os.getenv("VISION_TIMEOUT", "90.0")),
    max_retries=int(os.getenv("VISION_MAX_RETRIES", "3"))
)

context_service = ContextService(
    system_prompt=SYSTEM_PROMPT_WITH_TODO,
    keep_full_steps=4
)

test_plan = """
Execute the following test cases in order. Report each result with test_case_id matching the id below (e.g. 1.1, 2.3).

1.⁠ ⁠Onboarding & Login
1.1 New Player Login: Launch the app and complete the new player login or sign-up flow. Verify the welcome/login screen appears and the player successfully enters the game.
1.2 Accept Regulations: Accept any terms of service, privacy policy, or regulation prompts that appear. Verify all consent screens are dismissed and the game proceeds.

2.⁠ ⁠Navigation & Tutorial
2.1 Go to Catalina City: Navigate to the world map, locate Catalina City, and tap on it to enter. Verify the Catalina City room or its entry screen is visible.
2.2 How to Play Tutorial: Follow all tutorial prompts and complete the how-to-play walkthrough inside Catalina City. Verify the tutorial is marked complete and normal gameplay is accessible.

3.⁠ ⁠Bingo Round
3.1 Select 2 Cards: At the card selection screen, select exactly 2 bingo cards and confirm to start the round. Verify the round begins with 2 cards visible on screen.
3.2 Daub Matched Numbers: As numbers are called during the round, tap the matching cells on both cards to daub them. Verify daubed numbers are visually marked on the cards.
3.3 Complete the Round: Continue daubing called numbers until the round ends (all bingos claimed). Verify the Round Summary screen appears confirming the round is complete.

4.⁠ ⁠Post-Round
4.1 Return to Main Map: From the post-round screen or in-game navigation, tap to return to the main world map. Verify the main world map is visible and accessible.
"""

def initialize_game_todos():
    """Initialize the todo list for completing 6 levels of the word game"""
    import json
    
    initial_todos = {
        "merge": False,
        "todos": [
            {
                "id": "1",
                "content": "Start and complete level 1",
                "status": "pending",
                "todo_type": "action",
                "dependencies": []
            },
            {
                "id": "2",
                "content": "Start and complete level 2",
                "status": "pending",
                "todo_type": "action",
                "dependencies": ["1"]
            },
            {
                "id": "3",
                "content": "Start and complete level 3",
                "status": "pending",
                "todo_type": "action",
                "dependencies": ["2"]
            },
            {
                "id": "4",
                "content": "Start and complete level 4",
                "status": "pending",
                "todo_type": "action",
                "dependencies": ["3"]
            },
            {
                "id": "5",
                "content": "Start and complete level 5",
                "status": "pending",
                "todo_type": "action",
                "dependencies": ["4"]
            },
            {
                "id": "6",
                "content": "Start and complete level 6",
                "status": "pending",
                "todo_type": "action",
                "dependencies": ["5"]
            }
        ]
    }
    
    todo_input_json = json.dumps(initial_todos)
    result = todo_write_handler(todo_input_json, SESSION_ID)
    result_dict = json.loads(result)
    print(f"✅ Initial todos created: {result_dict.get('totalTasks')} tasks")
    print(f"   📋 Task counts: {result_dict.get('taskCounts')}")
    return result

def print_current_todos(session_id: str):
    """Print the current todo list in a readable format"""
    todo_list_text = get_todo_list_for_context(session_id)
    print("\n" + "="*60)
    print("📋 CURRENT TODO LIST:")
    print("="*60)
    print(todo_list_text)
    print("="*60 + "\n")

class Action(BaseModel):
    action_type: Literal["key_press", "click", "swipe", "multi_swipe", "wait", "todo_write"] = Field(
        description="Represents the type of action to be performed. This can be a key press, click on a coordinate, swipe, multi-point swipe, wait, or todo_write for managing task lists."
    )
    x: int | None = Field(
        default=None,
        description="X-coordinate on the screen. Required for 'click' action. For 'swipe' action, this is the starting X-coordinate. Not used for 'multi_swipe' or 'todo_write'."
    )
    y: int | None = Field(
        default=None,
        description="Y-coordinate on the screen. Required for 'click' action. For 'swipe' action, this is the starting Y-coordinate. Not used for 'multi_swipe' or 'todo_write'."
    )
    end_x: int | None = Field(
        default=None,
        description="Ending X-coordinate for 'swipe' action. Required only for 'swipe'. Not used for 'multi_swipe' or 'todo_write'."
    )
    end_y: int | None = Field(
        default=None,
        description="Ending Y-coordinate for 'swipe' action. Required only for 'swipe'. Not used for 'multi_swipe' or 'todo_write'."
    )
    waypoints: List[tuple[int, int]] | None = Field(
        default=None,
        description="List of (x, y) coordinate tuples for 'multi_swipe' action ONLY. The gesture will follow this path smoothly from first point to last. Includes start, middle, and end points. Example: [(100, 100), (200, 150), (300, 100)] creates a curved path starting at (100,100) and ending at (300,100). Required for 'multi_swipe', ignored for other actions."
    )
    key_name: str | None = Field(
        default=None,
        description="Name of the keyboard key to press. All possible keys are listed in the last message. Required only for 'key_press' action."
    )
    duration: float = Field(
        default=0.1,
        description="Duration of the action in seconds. For 'click': hold duration (0.1 = quick tap). For 'swipe': time to complete the swipe. For 'multi_swipe': total time for entire path. For 'wait': how long to wait. Not used for 'todo_write'. Default: 0.1s."
    )
    todo_input: str | None = Field(
        default=None,
        description=TODO_WRITE_INPUT_DESCRIPTION
    )

class TestResult(BaseModel):
    test_case_id: str = Field(
        description="The id of the test case that you are reporting the result for."
    )
    completion: bool = Field(
        description="True if you were able to complete the test case successfully, false if you failed to achieve the condition required to run the test case."
    )
    failure_reason: str = Field(
        description="If completion is false, provide a brief explanation of why you failed to complete the test case. Otherwise NA."
    )
    virdict: Literal["pass", "fail"] = Field(
        description="Pass if the actual outcome matches the expected outcome, fail if it does not."
    )
    comment: str = Field(
        description="Free field to comment on the test case. You can use this to provide information about how the actual outcome differed from the expected outcome."
    )

# TODO: Add analyze last step and reason next step fields here as well
class AgentOutput(BaseModel):
    game_state_summary: str = Field(
        description="A concise summary of the current game state, key observations, and important context that should be remembered for future steps. This summary will be preserved in the conversation history even when screenshots are removed. Include: current game situation, player status, important objects/entities, recent changes, and any critical information needed for decision-making."
    )
    bingo_state: Literal["menu", "in_game", "unspecified"] = Field(
        default="unspecified",
        description="For Bingo Blitz ONLY: Set to 'in_game' when the bingo board is fully visible and a round is actively being played. Set to 'menu' for all other screens (menus, popups, loading, results). Default is 'unspecified'."
    )
    reason: str = Field(
        description="Use this field to reason about the current game state and your overall performance, observations, goals that will help you complete the game and figure out the next set of actions."
    )
    end_game: bool = Field(
        default=False,
        description="This represents whether the game has ended or not. If the game has ended, the player should not take any action."
    )
    actions: List[Action] = Field(
        description="A list of actions to be executed sequentially. This can be a combination of keyboard and button press actions."
    )
    test_results: List[TestResult] = Field(
        description="List of test results. You are not expected to fill this always. Only fill it when you have executed atleast one test case and have a result to report otherwise keep it empty."
    )

class GamePauseEvent(BaseModel):
    """Data sent from Unity when event interval is reached"""
    current_step: int
    current_frame: int


structured_model = model.with_structured_output(schema=AgentOutput.model_json_schema(), method="json_schema", include_raw=True)

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


_test_results_file_lock = threading.Lock()


def _append_test_results_to_file(filepath: str, rows: List[dict]) -> None:
    """Append test result rows to JSON file. Runs off the main thread. Uses a lock so concurrent appends do not overwrite each other."""
    with _test_results_file_lock:
        existing = []
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, OSError):
                existing = []
        if not isinstance(existing, list):
            existing = []
        existing.extend(rows)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, default=str)


async def agent_handler(event: GamePauseEvent):
    print(f"\n{'='*80}")
    print(f"🎮 Step {event.current_step} | Frame {event.current_frame}")
    print(f"{'='*80}")
    
    # Print current todos at the start of each step
    print_current_todos(SESSION_ID)
    
    screenshots_dir = os.path.join(os.path.dirname(__file__), "..", "agent", "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)
    
    filename = f"step_{event.current_step}_frame_{event.current_frame}.png"
    filepath = os.path.join(screenshots_dir, filename)
    
    # Capture screenshot with retry logic
    screenshot_result = action_executor.get_screenshot(filepath)
    
    if not screenshot_result.success:
        error_details = f"{screenshot_result.error_message} (type: {screenshot_result.error_type}, retries: {screenshot_result.retry_count})"
        print(f"   ❌ Screenshot capture failed: {error_details}")
        
        # Return error with detailed information
        return {
            "status": "error", 
            "message": f"Failed to capture screenshot: {error_details}",
            "error_type": str(screenshot_result.error_type),
            "retry_count": screenshot_result.retry_count
        }
    
    print(f"   💾 {filename} (captured in {screenshot_result.elapsed_time:.2f}s)")
    if screenshot_result.retry_count > 0:
        print(f"   🔄 Required {screenshot_result.retry_count} retry(ies)")
    
    saved_filepaths = [filepath]
    print(f"✅ Saved screenshot")
    
    if saved_filepaths:
        try:
            if SDK_ENABLED:
                available_actions = action_handler.get_available_actions()
            else:
                available_actions = {}
            
            # --- LOCAL OCR OPTIMIZATION FOR BINGO BLITZ ---
            optimize_bingo = os.getenv("OPTIMIZED_BINGO_MODE", "true").lower() == "true"
            is_bingo_blitz = GAME_NAME == "bingo_blitz"
            latest_bingo_state = context_service.get_latest_bingo_state(SESSION_ID)
            
            # --- FAST STATE PRE-CHECK VIA GROQ ---
            if is_bingo_blitz and optimize_bingo and latest_bingo_state != "in_game":
                # Check if we transitioned to in_game quickly
                is_in_game_now = await vision_detector.check_bingo_state_groq(saved_filepaths[0])
                if is_in_game_now:
                    print(f"🎯 Groq detected 'in_game' state! Forcing immediate optimized transition.")
                    context_service._sessions[SESSION_ID]['latest_bingo_state'] = "in_game"
                    context_service._sessions[SESSION_ID]['cached_vision_elements'] = None
                    context_service._sessions[SESSION_ID]['pending_balls'] = []
                    context_service._sessions[SESSION_ID]['vision_task'] = None
                    latest_bingo_state = "in_game"
            
            # Optimization ONLY runs during active 'in_game' play (not in menus)
            if is_bingo_blitz and optimize_bingo and latest_bingo_state == "in_game":
                try:
                    import ast
                    with Image.open(saved_filepaths[0]) as img:
                        w, h = img.size
                    quick_actions = []
                    cached_elements = context_service.get_cached_vision_elements(SESSION_ID)
                    vision_task = context_service.get_vision_task(SESSION_ID)
                    p_ready = False
                    
                    # --- Start Background ER 1.5 Task if needed ---
                    if cached_elements is None:
                        if vision_task is None or vision_task.done():
                            print(f"🔄 Starting background ER 1.5 detection task...")
                            # Create the background task
                            task = asyncio.create_task(vision_detector.detect_elements(saved_filepaths[0], is_in_game=True))
                            context_service.set_vision_task(SESSION_ID, task)
                            
                            # Add a callback to save the result to cache when done
                            def _on_vision_done(f):
                                try:
                                    res = f.result()
                                    if res.success:
                                        print(f"✅ Background vision task completed successfully. Elements cached.")
                                        # Note: We need to access standard session dictionary safely here or set a flag.
                                        # Since we don't have a dedicated setter, we'll let context_service handle it 
                                        # in _build_available_actions_message on the NEXT frame, but let's pre-populate 
                                        # it if possible.
                                        context_service._sessions[SESSION_ID]['cached_vision_elements'] = res.elements
                                    else:
                                        print(f"⚠️ Background vision task failed.")
                                except Exception as e:
                                    print(f"❌ Background vision task error: {e}")
                            
                            task.add_done_callback(_on_vision_done)
                            vision_task = task
                        else:
                            print(f"⏳ Waiting for background ER 1.5 detection...")
                    
                    # --- DYNAMIC ANCHORING ---
                    # Look for ball history and powerup in the cached elements
                    dynamic_ball_bbox = None
                    dynamic_power_bbox = None
                    
                    if cached_elements:
                        for el in cached_elements:
                            name = el['name'].lower()
                            if any(x in name for x in ["ball history", "called number", "drawn number", "top bar"]):
                                dynamic_ball_bbox = el['bounding_box']
                            if any(x in name for x in ["power-up", "powerup", "booster button"]):
                                dynamic_power_bbox = el['bounding_box']

                    # 1. CHECK POWER-UP
                    p_ready = False
                    powerup_bbox_str = os.getenv("BINGO_POWERUP_BBOX")
                    if powerup_bbox_str:
                        p_bbox_norm = ast.literal_eval(powerup_bbox_str)
                        p_pixel_bbox = [int(p_bbox_norm[1]*w/1000), int(p_bbox_norm[0]*h/1000), int(p_bbox_norm[3]*w/1000), int(p_bbox_norm[2]*h/1000)]
                        
                        # Use color analysis to check for readiness
                        p_ready = await asyncio.to_thread(is_powerup_ready, saved_filepaths[0], p_pixel_bbox)
                        
                        # Cooldown
                        last_p_time = context_service.get_last_powerup_time(SESSION_ID)
                        current_time = time.time()
                        
                        if p_ready and (current_time - last_p_time > 10):
                            print(f"🎯 Power-up is READY! Clicking...")
                            quick_actions.append(Action(
                                action_type="click",
                                x=p_pixel_bbox[0] + (p_pixel_bbox[2]-p_pixel_bbox[0])//2,
                                y=p_pixel_bbox[1] + (p_pixel_bbox[3]-p_pixel_bbox[1])//2
                            ))
                            context_service.set_last_powerup_time(SESSION_ID, current_time)

                    # 2. CHECK BINGO NUMBERS
                    called_numbers = []
                    ball_bbox_str = os.getenv("BINGO_CALLED_NUMBER_BBOX")
                    if ball_bbox_str:
                        b_bbox_norm = ast.literal_eval(ball_bbox_str)
                        prompt = "List all Bingo numbers visible in this Ball History Bar. Return ONLY the numbers separated by commas. Example: 32, 16, 69"
                        res_text = await vision_detector.targeted_ocr(saved_filepaths[0], b_bbox_norm, prompt)
                        import re
                        called_numbers = [n.strip() for n in re.findall(r'\d+', res_text)] if res_text else []
                        
                        # --- LOG OCR RESULTS ---
                        numbers_str = ", ".join(called_numbers) if called_numbers else "Missed"
                        tally_entry = f"[{datetime.now().strftime('%H:%M:%S')}] Frame: {event.current_frame} | Ball OCR: [{numbers_str}] | Powerup Ready: {p_ready} | Method: GroqVLM\n"
                        try:
                            with open("ocr_tally.txt", "a") as f:
                                f.write(tally_entry)
                        except: pass

                        if called_numbers:
                            # Add to pending balls
                            context_service.add_pending_balls(SESSION_ID, called_numbers)
                            
                            if cached_elements:
                                # Retrieve ALL pending balls to process them retroactively
                                all_pending = context_service.get_pending_balls(SESSION_ID)
                                print(f"🔍 Processing retroactively {len(all_pending)} pending balls: {all_pending}")
                                
                                balls_processed = 0
                                for num in all_pending:
                                    matching_element = None
                                    for element in cached_elements:
                                        name = element.get('name', '').lower()
                                        desc = element.get('description', '').lower()
                                        
                                        # Enforce that the element is a card number, not a player profile/rank
                                        if "card" in name or "number" in name or "bingo" in name:
                                            # Relaxed match: check last word in name or desc
                                            if num == name.split()[-1] or (desc and num == desc.split()[-1]):
                                                matching_element = element
                                                break
                                    
                                    if matching_element:
                                        print(f"🚀 MATCH FOUND! Clicking {matching_element['name']} (Number: {num})")
                                        quick_actions.append(Action(
                                            action_type="click",
                                            x=matching_element['screen_position'][0],
                                            y=matching_element['screen_position'][1]
                                        ))
                                        balls_processed += 1
                                
                                # If we successfully mapped balls to clicks using the cache, clear the pending queue
                                if balls_processed > 0:
                                    context_service.clear_pending_balls(SESSION_ID)
                    
                    # If we don't have cached elements yet but we are accumulating pendings,
                    # we still want to skip LLM to maintain fast frame rate. Let's return a special optimized status.
                    if quick_actions:
                        print(f"⚡ Executing {len(quick_actions)} optimized actions (bypassing LLM)")
                        await execute_agent_actions(quick_actions)
                        if SDK_ENABLED:
                            try: frame_controller.mark_actions_executed()
                            except Exception: pass
                        return {"status": "ok", "optimized": True, "method": "local_ocr", "actions_count": len(quick_actions)}
                    elif cached_elements is None and latest_bingo_state == "in_game":
                        # We are waiting for background scan. Skip LLM entirely to keep local OCR loop very fast.
                        print(f"⚡ Skipping LLM while waiting for background ER 1.5 scan. Accumulated {len(context_service.get_pending_balls(SESSION_ID))} pending balls.")
                        return {"status": "ok", "optimized": True, "method": "waiting_for_vision"}
                        
                except Exception as e:
                    print(f"⚠️ Local OCR optimization failed: {e}")
            # --- END OPTIMIZATION ---

            await context_service.add_new_step(
                session_id=SESSION_ID,
                screenshot_path=saved_filepaths[0],
                available_actions=available_actions,
                step=event.current_step,
                frame=event.current_frame,
                vision_detector=vision_detector,
                action_handler=action_handler,
                sdk_enabled=SDK_ENABLED
            )
            
            messages = context_service.get_messages_for_llm(SESSION_ID)
            
            print("🤖 Getting agent decision from LLM...")
            start_time = time.time()
            response = await asyncio.to_thread(structured_model.invoke, messages)
            elapsed = time.time() - start_time
            print(f"⏱️  LLM response time: {elapsed:.2f}s")

            agent_output = parse_llm_response(response)
            print(f"✅ Agent decision received")
            print(f"   📝 Game state: {agent_output.game_state_summary}")
            print(f"   🤔 Reasoning: {agent_output.reason}")
            print(f"   🎯 Actions count: {len(agent_output.actions)}")
            print(f"   🏁 End game: {agent_output.end_game}")
            print(f"   📋 Test results: {agent_output.test_results}")

            # Append test results to file in background (does not block agent execution)
            if agent_output.test_results:
                now_iso = datetime.utcnow().isoformat() + "Z"
                test_results_dir = os.path.join(os.path.dirname(__file__), "..", "agent")
                os.makedirs(test_results_dir, exist_ok=True)
                test_results_path = os.path.join(test_results_dir, "test_results.json")
                rows = [
                    {**r.model_dump(), "screenshot_id": filename, "timestamp": now_iso}
                    for r in agent_output.test_results
                ]
                asyncio.create_task(asyncio.to_thread(_append_test_results_to_file, test_results_path, rows))
                print(f"   📄 Appending {len(agent_output.test_results)} test result(s) to {test_results_path} (async)")

            context_service.add_ai_response(SESSION_ID, agent_output)

            if agent_output.end_game:
                print("🛑 Agent signaled end of game")
                if SDK_ENABLED:
                    try:
                        frame_controller.mark_actions_executed()
                    except Exception as e:
                        print(f"⚠️  Warning: Failed to mark actions executed: {e}")
                else:
                    await asyncio.sleep(POLLING_INTERVAL)
                return {"status": "ok", "saved": 1, "files": [filename], "end_game": True}
            
            print("🎮 Executing actions...")
            await execute_agent_actions(agent_output.actions)
            print("✅ Actions executed successfully")
            
            context_service.cleanup_old_messages(SESSION_ID)
            
            if SDK_ENABLED:
                try:
                    print("✅ Marking actions as executed...")
                    frame_controller.mark_actions_executed()
                    print("✅ Actions marked as executed - Unity can send next event")
                except Exception as e:
                    print(f"❌ Error marking actions executed: {e}")
                    return {"status": "error", "message": f"Failed to mark actions executed: {e}"}
            else:
                print(f"⏳ Waiting {POLLING_INTERVAL}s for game to process actions...")
                await asyncio.sleep(POLLING_INTERVAL)
            
            return {"status": "ok", "saved": 1, "files": [filename]}
            
        except Exception as e:
            print(f"❌ Error in LLM call or action execution: {e}")
            import traceback
            traceback.print_exception(type(e), e, e.__traceback__)
            if SDK_ENABLED:
                try:
                    frame_controller.mark_actions_executed()
                except Exception as mark_error:
                    print(f"⚠️  Warning: Failed to mark actions executed after error: {mark_error}")
            return {"status": "error", "message": f"Failed to process: {e}"}

async def execute_agent_actions(actions: List[Action]):
    for idx, action in enumerate(actions, 1):
        if action.action_type == "todo_write":
            import json
            print(f"\n📝 Executing todo_write action ({idx}/{len(actions)})")
            print(f"   📋 Todo input received: {action.todo_input}")
            result = todo_write_handler(action.todo_input, SESSION_ID)
            result_dict = json.loads(result)
            
            if result_dict.get("success"):
                print(f"   ✅ Todo list updated successfully")
                print(f"   📊 Total tasks: {result_dict.get('totalTasks')}")
                print(f"   📈 Task counts: {result_dict.get('taskCounts')}")
                
                # Print the updated todo list
                print_current_todos(SESSION_ID)
            else:
                print(f"   ❌ Todo update failed: {result_dict.get('message')}")
            
            context_service.add_todo_result(SESSION_ID, result)
        else:
            print(f"   🎮 Executing {action.action_type} action ({idx}/{len(actions)})")
            await action_executor.execute_actions_sequential([action])

async def run_blackbox_loop():
    print("🎮 Starting black box polling loop")
    step = 0
    
    context_service._ensure_session(SESSION_ID, game_config["description"], game_config["details"], test_plan)
    while step < MAX_STEPS:
        print(f"\n🔄 Black box iteration {step}")
        
        fake_event = GamePauseEvent(current_step=step, current_frame=step)
        result = await agent_handler(fake_event)
        
        if result.get("end_game"):
            print("🛑 Game ended")
            break
            
        step += 1
    
    print(f"✅ Completed {step} steps")

if __name__ == "__main__":
    # Initialize the todo list for the 6-level word game
    print("🎯 Initializing game todos for 6 levels...")
    # initialize_game_todos()
    
    if not SDK_ENABLED:
        print("🎯 Black box mode - starting polling loop")
        asyncio.run(run_blackbox_loop())
    else:
        print("🔌 SDK mode - waiting for Unity events")
