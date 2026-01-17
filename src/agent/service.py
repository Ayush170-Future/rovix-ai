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
    from .prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_WITH_TODO
except ImportError:
    from agent.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_WITH_TODO

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
    model="gemini-3-pro-preview",
    temperature=1.0,
    max_tokens=None,
    timeout=None,
    max_retries=2,
    api_key=os.getenv("GOOGLE_API_KEY")
)

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
            app_package=os.getenv("APP_PACKAGE"),
            app_activity=os.getenv("APP_ACTIVITY")
        )
    else:
        print("Initializing ADB Manager...")
        action_executor = ADBManager(host="127.0.0.1", port=5037)
    
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
            app_package=os.getenv("APP_PACKAGE"),
            app_activity=os.getenv("APP_ACTIVITY")
        )
    else:
        print("Initializing ADB Manager...")
        action_executor = ADBManager(host="127.0.0.1", port=5037)
    
    print("Initializing Vision Detector...")
    vision_detector = VisionElementDetector(
        api_key=os.getenv("GOOGLE_API_KEY"),
        model_name="gemini-robotics-er-1.5-preview"
    )

context_service = ContextService(
    system_prompt=SYSTEM_PROMPT_WITH_TODO,
    keep_full_steps=4
)

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
    print(f"\n{'='*80}")
    print(f"🎮 Step {event.current_step} | Frame {event.current_frame}")
    print(f"{'='*80}")
    
    # Print current todos at the start of each step
    print_current_todos(SESSION_ID)
    
    screenshots_dir = os.path.join(os.path.dirname(__file__), "..", "agent", "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)
    
    filename = f"step_{event.current_step}_frame_{event.current_frame}.png"
    filepath = os.path.join(screenshots_dir, filename)
    
    try:
        action_executor.get_screenshot(filepath)
        print(f"   💾 {filename} (captured)")
        saved_filepaths = [filepath]
    except Exception as e:
        print(f"   ❌ Error capturing screenshot: {e}")
        return {"status": "error", "message": f"Failed to capture screenshot: {e}"}
    
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
            response = await asyncio.to_thread(structured_model.invoke, messages)

            agent_output = parse_llm_response(response)
            print(f"✅ Agent decision received")
            print(f"   📝 Game state: {agent_output.game_state_summary[:100]}..." if len(agent_output.game_state_summary) > 100 else f"   📝 Game state: {agent_output.game_state_summary}")
            print(f"   🤔 Reasoning: {agent_output.reason[:100]}..." if len(agent_output.reason) > 100 else f"   🤔 Reasoning: {agent_output.reason}")
            print(f"   🎯 Actions count: {len(agent_output.actions)}")
            print(f"   🏁 End game: {agent_output.end_game}")
            
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
    initialize_game_todos()
    
    if not SDK_ENABLED:
        print("🎯 Black box mode - starting polling loop")
        asyncio.run(run_blackbox_loop())
    else:
        print("🔌 SDK mode - waiting for Unity events")
