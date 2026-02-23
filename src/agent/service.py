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
    from .prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_WITH_TODO, HITWICKET_GAME_DESCRIPTION, HITWICKET_GAMEPLAY_DETAILS
    from .logger import get_logger
except ImportError:
    from agent.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_WITH_TODO, HITWICKET_GAME_DESCRIPTION, HITWICKET_GAMEPLAY_DETAILS
    from agent.logger import get_logger

logger = get_logger("agent.service")

from tester import InputController, AltTesterClient, GameFrameController, SceneController, TimeController
from agent.actions import ActionHandler
from agent.adb_manager import ADBManager
from agent.appium_manager import AppiumManager
from agent.vision_element_detector import VisionElementDetector
from agent.context import ContextService
from tools.todo_management import todo_write_handler, TODO_WRITE_INPUT_DESCRIPTION, get_todo_list_for_context
from tools.todo_management.todo_service import TodoPersistenceService

load_dotenv()

SDK_ENABLED = os.getenv("SDK_ENABLED", "true").lower() == "true"
USE_APPIUM = os.getenv("USE_APPIUM", "false").lower() == "true"
POLLING_INTERVAL = float(os.getenv("POLLING_INTERVAL", "2.5"))
MAX_STEPS = int(os.getenv("MAX_STEPS", "1000"))
SESSION_ID = "game_session_main"
FORCE_ANNOTATE = False

model = ChatGoogleGenerativeAI(
    model="gemini-3-flash-preview",
    temperature=1.0,
    max_tokens=None,
    timeout=None,
    max_retries=2,
    api_key=os.getenv("GOOGLE_API_KEY")
)
logger.info("🤖 Using model: gemini-3-flash-preview")

if SDK_ENABLED:
    logger.info("Initializing AltTesterClient...")
    client = AltTesterClient(host="127.0.0.1", port=13000, timeout=60)
    logger.info("AltTesterClient initialized")
    driver = client.get_driver()
    input_controller = InputController(driver)
    time_controller = TimeController(driver)
    scene_controller = SceneController(driver)
    frame_controller = GameFrameController(driver)
    frame_controller.mark_actions_executed()
    
    if USE_APPIUM:
        logger.info("Initializing Appium Manager...")
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
        logger.info("Initializing ADB Manager...")
        action_executor = ADBManager(
            host="127.0.0.1", 
            port=5037,
            screenshot_timeout=float(os.getenv("SCREENSHOT_TIMEOUT", "10.0")),
            screenshot_max_retries=int(os.getenv("SCREENSHOT_MAX_RETRIES", "3"))
        )
    
    action_handler = ActionHandler(driver, adb_manager=action_executor)
    vision_detector = None
else:
    logger.info("Black box mode - skipping AltTester initialization")
    client = None
    driver = None
    input_controller = None
    time_controller = None
    scene_controller = None
    frame_controller = None
    action_handler = None
    
    if USE_APPIUM:
        logger.info("Initializing Appium Manager...")
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
        logger.info("Initializing ADB Manager...")
        action_executor = ADBManager(
            host="127.0.0.1", 
            port=5037,
            screenshot_timeout=float(os.getenv("SCREENSHOT_TIMEOUT", "10.0")),
            screenshot_max_retries=int(os.getenv("SCREENSHOT_MAX_RETRIES", "3"))
        )
    
    logger.info("Initializing Vision Detector...")
    vision_detector = VisionElementDetector(
        api_key=os.getenv("GOOGLE_API_KEY"),
        model_name="gemini-robotics-er-1.5-preview",
        timeout=float(os.getenv("VISION_TIMEOUT", "45.0")),
        max_retries=int(os.getenv("VISION_MAX_RETRIES", "3"))
    )

context_service = ContextService(
    system_prompt=SYSTEM_PROMPT_WITH_TODO,
    keep_full_steps=4
)

test_plan = """
Execute the following test cases in order. Report each result with test_case_id matching the id below (e.g. 1.1, 2.3).

1. Onboarding & Login
1.1 New Player Login: Launch the app and complete the new player login or sign-up flow. Verify the welcome/login screen appears and the player successfully enters the game.
1.2 Accept Regulations: Accept any terms of service, privacy policy, or regulation prompts that appear. Verify all consent screens are dismissed and the game proceeds.

2. Navigation & Tutorial
2.1 Go to Catalina City: Navigate to the world map, locate Catalina City, and tap on it to enter. Verify the Catalina City room or its entry screen is visible.
2.2 How to Play Tutorial: Follow all tutorial prompts and complete the how-to-play walkthrough inside Catalina City. Verify the tutorial is marked complete and normal gameplay is accessible.

3. Bingo Round
3.1 Select 2 Cards: At the card selection screen, select exactly 2 bingo cards and confirm to start the round. Verify the round begins with 2 cards visible on screen.
3.2 Daub Matched Numbers: As numbers are called during the round, tap the matching cells on both cards to daub them. Verify daubed numbers are visually marked on the cards.
3.3 Complete the Round: Continue daubing called numbers until the round ends (all bingos claimed). Verify the Round Summary screen appears confirming the round is complete.

4. Post-Round
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
            }
        ]
    }
    
    todo_input_json = json.dumps(initial_todos)
    result = todo_write_handler(todo_input_json, SESSION_ID)
    result_dict = json.loads(result)
    logger.info(f"✅ Initial todos created: {result_dict.get('totalTasks')} tasks")
    logger.info(f"   📋 Task counts: {result_dict.get('taskCounts')}")
    return result

def print_current_todos(session_id: str):
    """Log the current todo list in a readable format"""
    todo_list_text = get_todo_list_for_context(session_id)
    logger.info("\n" + "="*60 + "\n📋 CURRENT TODO LIST:\n" + "="*60 + "\n" + todo_list_text + "\n" + "="*60)

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
    reason: str = Field(
        description="Use this field to reason about the current game state and your overall performance, observations, goals that will help you complete the game and figure out the next set of actions."
    )
    end_game: bool = Field(
        default=False,
        description="This represents whether the game has ended or not. If the game has ended, the player should not take any action."
    )
    force_annotate: bool = Field(
        default=False,
        description="'true' if you think the cached annotation does not match the current game screen, otherwise 'false'. No need to execute any actions when this is 'true'."
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
            logger.debug(f"📊 Token counts: {token_counts}")
            cached_tokens = raw_output.cachedContentTokenCount if hasattr(raw_output, 'cachedContentTokenCount') else 1
            input_tokens = token_counts.get('input_tokens') if isinstance(token_counts, dict) else getattr(token_counts, 'input_tokens', None)
            output_tokens = token_counts.get('output_tokens') if isinstance(token_counts, dict) else getattr(token_counts, 'output_tokens', None)
            total_tokens = token_counts.get('total_tokens') if isinstance(token_counts, dict) else getattr(token_counts, 'total_tokens', None)
            
            if input_tokens is not None:
                logger.info(f"📊 Token usage - Input: {input_tokens}, Output: {output_tokens}, Total: {total_tokens}")
                logger.debug(f"📊 Cached tokens: {cached_tokens}")
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
    global FORCE_ANNOTATE
    logger.info(f"\n{'='*80}\n🎮 Step {event.current_step} | Frame {event.current_frame}\n{'='*80}")
    
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
        logger.error(f"❌ Screenshot capture failed: {error_details}")
        return {
            "status": "error", 
            "message": f"Failed to capture screenshot: {error_details}",
            "error_type": str(screenshot_result.error_type),
            "retry_count": screenshot_result.retry_count
        }
    
    logger.info(f"💾 {filename} (captured in {screenshot_result.elapsed_time:.2f}s)")
    if screenshot_result.retry_count > 0:
        logger.warning(f"🔄 Screenshot required {screenshot_result.retry_count} retry(ies)")
    
    saved_filepaths = [filepath]
    logger.info("✅ Saved screenshot")
    
    if saved_filepaths:
        try:
            if SDK_ENABLED:
                available_actions = action_handler.get_available_actions()
            else:
                available_actions = {}
            
            await context_service.add_new_step(
                session_id=SESSION_ID,
                screenshot_path=saved_filepaths[0],
                available_actions=available_actions,
                step=event.current_step,
                frame=event.current_frame,
                vision_detector=vision_detector,
                action_handler=action_handler,
                sdk_enabled=SDK_ENABLED,
                force_annotate=FORCE_ANNOTATE
            )
            
            messages = context_service.get_messages_for_llm(SESSION_ID)
            
            logger.info("🤖 Getting agent decision from LLM...")
            start_time = time.time()
            response = await asyncio.to_thread(structured_model.invoke, messages)
            elapsed = time.time() - start_time
            logger.info(f"⏱️  LLM response time: {elapsed:.2f}s")

            agent_output = parse_llm_response(response)
            logger.info("✅ Agent decision received")
            logger.info(f"   📝 Game state: {agent_output.game_state_summary}")
            logger.info(f"   🤔 Reasoning: {agent_output.reason}")
            logger.info(f"   🔍 Force annotate: {agent_output.force_annotate}")
            logger.info(f"   🎯 Actions count: {len(agent_output.actions)}")
            logger.info(f"   🏁 End game: {agent_output.end_game}")
            logger.info(f"   📋 Test results: {agent_output.test_results}")

            FORCE_ANNOTATE = agent_output.force_annotate

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
                logger.info(f"   📄 Appending {len(agent_output.test_results)} test result(s) to {test_results_path} (async)")

            context_service.add_ai_response(SESSION_ID, agent_output)

            if agent_output.end_game:
                logger.info("🛑 Agent signaled end of game")
                if SDK_ENABLED:
                    try:
                        frame_controller.mark_actions_executed()
                    except Exception as e:
                        logger.warning(f"⚠️  Warning: Failed to mark actions executed: {e}")
                else:
                    await asyncio.sleep(POLLING_INTERVAL)
                return {"status": "ok", "saved": 1, "files": [filename], "end_game": True}
            
            await execute_agent_actions(agent_output.actions)
            
            context_service.cleanup_old_messages(SESSION_ID)
            
            if SDK_ENABLED:
                try:
                    logger.info("✅ Marking actions as executed...")
                    frame_controller.mark_actions_executed()
                    logger.info("✅ Actions marked as executed - Unity can send next event")
                except Exception as e:
                    logger.error(f"❌ Error marking actions executed: {e}")
                    return {"status": "error", "message": f"Failed to mark actions executed: {e}"}
            else:
                logger.debug(f"⏳ Waiting {POLLING_INTERVAL}s for game to process actions...")
                await asyncio.sleep(POLLING_INTERVAL)
            
            return {"status": "ok", "saved": 1, "files": [filename]}
            
        except Exception as e:
            logger.error(f"❌ Error in LLM call or action execution: {e}", exc_info=True)
            if SDK_ENABLED:
                try:
                    frame_controller.mark_actions_executed()
                except Exception as mark_error:
                    logger.warning(f"⚠️  Warning: Failed to mark actions executed after error: {mark_error}")
            return {"status": "error", "message": f"Failed to process: {e}"}

async def execute_agent_actions(actions: List[Action]):
    for idx, action in enumerate(actions, 1):
        if action.action_type == "todo_write":
            import json
            result = todo_write_handler(action.todo_input, SESSION_ID)
            result_dict = json.loads(result)
            
            if result_dict.get("success"):
                logger.info(f"todo_write ({idx}/{len(actions)}): updated {result_dict.get('totalTasks')} tasks {result_dict.get('taskCounts')}")
                print_current_todos(SESSION_ID)
            else:
                logger.warning(f"todo_write ({idx}/{len(actions)}): failed - {result_dict.get('message')}")
            
            context_service.add_todo_result(SESSION_ID, result)
        else:
            logger.info(f"action ({idx}/{len(actions)}): {action.action_type} x={action.x} y={action.y} duration={action.duration}")
            await action_executor.execute_actions_sequential([action])

async def run_blackbox_loop():
    logger.info("🎮 Starting black box polling loop")
    step = 0
    
    context_service._ensure_session(SESSION_ID, HITWICKET_GAME_DESCRIPTION, HITWICKET_GAMEPLAY_DETAILS, test_plan)
    while step < MAX_STEPS:
        logger.info(f"🔄 Black box iteration {step}")
        
        fake_event = GamePauseEvent(current_step=step, current_frame=step)
        result = await agent_handler(fake_event)
        
        if result.get("end_game"):
            logger.info("🛑 Game ended")
            break
            
        step += 1
    
    logger.info(f"✅ Completed {step} steps")

if __name__ == "__main__":
    logger.info("🎯 Initializing game todos for 6 levels...")
    # initialize_game_todos()
    
    if not SDK_ENABLED:
        logger.info("🎯 Black box mode - starting polling loop")
        asyncio.run(run_blackbox_loop())
    else:
        logger.info("🔌 SDK mode - waiting for Unity events")
