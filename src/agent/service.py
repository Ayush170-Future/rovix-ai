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
except ImportError:
    from agent.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_WITH_TODO, HITWICKET_GAME_DESCRIPTION, HITWICKET_GAMEPLAY_DETAILS

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

model = ChatGoogleGenerativeAI(
    model="gemini-3-flash-preview",
    temperature=1.0,
    max_tokens=None,
    timeout=None,
    max_retries=2,
    api_key=os.getenv("GOOGLE_API_KEY")
)
print(f"🤖 Using model: gemini-3-flash-preview")

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
    
    print("Initializing Vision Detector...")
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

Note: You have already completed testing till 5.8 and currently the match 3 is running. So just complete it and do the testing from 5.9 onwards only till the end.

1. Initial Setup
1.1 Country Selection: Ensure country selection works properly.
1.2 City Selection: Verify the Back and Submit buttons work correctly.
1.3 Narrative Slides: Ensure slides appear with functional Skip and Next buttons.

2. Scouting Flow and Match 1
2.1 Verify Natasha/Harsha's dialogue appears when scouting a player.
2.2 Ensure only **one player (Master Blaster)** is available for scouting.
2.3 Verify **Master Blaster** appears on screen with player info after the scrolling animation.
2.4 Confirm **Match 1 starts** after scouting Master Blaster.
2.5 Verify Natasha/Harsha's dialogue: **"Score 18 runs in 2 overs."**
2.6 Check that a **soft nudge** appears on **Master Blaster** and a **common player**.
2.7 Verify Natasha/Harsha's dialogue with a **hand pointer** highlighting the play cards (**0, 1, 2, 4, 6**).
2.8 Ensure the **success rate** is highlighted on the **play cards, striker, and bowler**.
2.9 Check the **screen shatter animation** triggers when a successful **six (Straight Drive)** is hit.
2.10 Ensure the opponent team consists of **only common players**, with **no wicket loss** and **no SA active time** for the opponent.
2.11 Verify Natasha/Harsha's dialogue appears when the **SA meter fills with mana**.
2.12 Confirm a **hand pointer with blinking animation** appears on the **SA button** (if activated).
2.13 Verify the **SA info screen** appears after activating the SA (if activated).
2.14 Check that the **fire animation** triggers on **4s and 6s** (if activated).
2.15 Verify the **player dance animation** plays on the **victory screen** after completing **Match 1**.

3. Training Tutorial
3.1 Natasha/Harsha's dialogue provides information about Training Points (TP).
3.2 Natasha/Harsha's dialogue instructs to use TP to train a player.
3.3 Hand pointer appears on the player on the dashboard.
3.4 Natasha/Harsha's dialogue appears on the Player Detail screen.
3.5 Hand pointer highlights the Train button until Level 5 is reached.
3.6 Ensure Back button or other UI buttons are not interactable during dialogue.

4. Match 2 Flow
4.1 Natasha/Harsha's dialogue instructs to play 3 more matches to unlock the League.
4.2 Hand pointer appears on the Play button.
4.3 Edge case: Verify the user can train the player from the VS screen.
4.4 Ensure Play and Lineup buttons are visible on the VS screen.
4.5 Natasha/Harsha's dialogue for Commentary appears (in match).
4.6 FTUE Match 2: Verify SA tutorial appears inside the match (if mana filled).
4.7 On victory screen, Natasha/Harsha's dialogue about player shards and its use.
4.8 Edge case: If the user loses the match, ensure the match is replayable and the goal does not update until the user wins.

5. Store and Super Chest Flow
5.1 Hand pointer appears on the Store icon.
5.2 Natasha/Harsha's dialogue introduces the Super Chest.
5.3 Hand pointer appears on the Buy button with 0 HC (shows 50 HC but allows direct access).
5.4 Ensure no HC is deducted for free Super Chest opening.
5.5 Verify Chest Opening animation plays properly.
5.6 Verify user is redirected directly to the VS screen.
5.7 Ensure the user can train any player from the VS screen.
5.8 Check if user can tap Back, Play and Lineup buttons.
5.9 Ensure Match 3 is playable without any issue.

6. ESP Trigger and Dashboard State
6.1 ESP (Ultimate Finisher Pack) triggers after Match 3.
6.2 Verify arrow animation on the Play button.
6.3 Ensure ESP icon appears on the dashboard.
6.4 PK icon should blink on the dashboard.
6.5 Ensure Events, PvP, and League remain locked (base case).
6.6 Verify Store with Golden glow shows Free tag if a free item is available.
6.7 Ensure Net 2 is locked and requires 400 HC to unlock.
6.8 Verify Match 4 is playable without any issue.

7. League Unlock Flow
7.1 Natasha/Harsha's dialogue appears on dashboard for League Unlock.
7.2 Hand pointer highlights the League button.
7.3 Natasha/Harsha's dialogue appears on the League page about the league journey.
7.4 Hand pointer highlights the Play button on the League screen.
7.5 Verify tapping Play redirects correctly to the VS screen.
7.6 Verify PK Match is playable.
7.7 If user loses the PK Match, verify a 5-minute timer starts and the match becomes playable again.
7.8 Verify PK Match rewards (after winning) and flow (Haryana Hurricane and Athena).
7.9 Verify selected players are added to the squad.

8. Post-League Unlock Flows
8.1 Verify Events tab unlocks after League unlock.
8.2 Verify My Team unlocks after League unlock.
8.3 Ensure Fast Mode is accessible in LM1 (first innings screen).
8.4 Verify Leaderboard appears after winning LM1.
8.5 Verify SP/Quest Challenges are visible on the victory screen - LM1.
8.6 Hand pointer appears on Trophy Road for reward claim.
8.7 Verify Season Pass unlocks after LM1.
8.8 Verify Banner Unlock event (base case) or Thala Epics event.
8.9 Verify All HUD icons are visible.
8.10 EQ Unlocks (Player Card): Ensure equipment unlock flow works correctly.
8.11 Verify Inventory unlocks after League unlock.

9. Fast Mode and LM2 Flow
9.1 Verify Fast Mode Tutorial triggers during LM2 if the user did not interact in LM1.
9.2 Ensure the user can play in Fast Mode if active.
9.3 Verify LM2 is playable without any issues.
9.4 Check if Leaderboard updates correctly after user wins.
9.5 Verify Spitfire tutorial appears correctly.
9.6 Lineup tutorial at LM3 if a powerful player is available.
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
    
    context_service._ensure_session(SESSION_ID, HITWICKET_GAME_DESCRIPTION, HITWICKET_GAMEPLAY_DETAILS, test_plan)
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
