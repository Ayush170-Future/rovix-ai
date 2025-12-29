import os
import sys
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import redis
import numpy as np
from PIL import Image

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from agent.service import (
    GamePauseEvent,
    reset_game_state,
    execute_actions_async,
    frame_controller,
    driver,
    image_file_to_base64,
    game_state_messages,
    game_state_lock,
    structured_model,
    ActionList,
)

app = FastAPI(title="Unity AI Agent Server")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify Unity's origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

redis_client = redis.Redis(host='localhost', port=6379, decode_responses=False)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "message": "AI Agent Server is running"}


@app.post("/ai/reset-state")
async def reset_state():
    """Reset the global game state"""
    reset_game_state()
    return {"status": "ok", "message": "Game state reset"}


@app.post("/ai/resume")
async def resume_game():
    """Resume the game"""
    frame_controller.resume()
    return {"status": "ok", "message": "Game resumed"}


@app.post("/ai/on-pause")
async def on_game_pause(event: GamePauseEvent):
    """Called by Unity when the game pauses. Fetches screenshots from Redis, saves them, calls LLM, and executes actions."""
    print(f"\n🎮 Pause event - Step: {event.current_step}, Frames: {event.start_frame}-{event.end_frame}")
    print(f"   Available: {event.available_frames}")
    
    # Select 3 evenly-spaced frames
    frames = event.available_frames
    frames.append(frame_controller.get_current_frame())

    if len(frames) <= 3:
        selected = frames
    else:
        step = (len(frames) - 1) / 2
        selected = [frames[0], frames[int(step)], frames[-1]]
    
    # Create screenshots directory
    screenshots_dir = os.path.join(os.path.dirname(__file__), "..", "agent", "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)
    saved_files = []
    saved_filepaths = []
    
    # Fetch from Redis and save
    for i, frame_num in enumerate(selected):
        try:
            if frame_num == selected[-1]:
                # Get the screenshot directly from the game (current frame after pause)
                filename = f"step_{event.current_step}_frame_{frame_num}_pos_{i+1}_current.png"
                filepath = os.path.join(screenshots_dir, filename)
                
                # Capture screenshot directly from game
                driver.get_png_screenshot(filepath)
                
                saved_files.append(filename)
                saved_filepaths.append(filepath)
                print(f"   💾 {filename} (captured from game)")
                continue
            else:
                # Get from Redis
                key = f"{event.key_prefix}{frame_num}"
                raw_data = redis_client.get(key)
                meta_data = redis_client.get(f"{key}_meta")
                
                if not raw_data or not meta_data:
                    print(f"   ❌ Frame {frame_num} not found in Redis")
                    continue
                
                # Convert raw RGB24 to image
                width, height = map(int, meta_data.decode().split('x'))
                img_array = np.frombuffer(raw_data, dtype=np.uint8).reshape((height, width, 3))
                img = Image.fromarray(np.flipud(img_array), 'RGB')
                
                # Save
                filename = f"step_{event.current_step}_frame_{frame_num}_pos_{i+1}.png"
                filepath = os.path.join(screenshots_dir, filename)
                img.save(filepath, format='PNG')
                saved_files.append(filename)
                saved_filepaths.append(filepath)
                print(f"   💾 {filename}")
            
        except Exception as e:
            print(f"   ❌ Error on frame {frame_num}: {e}")
    
    print(f"✅ Saved {len(saved_files)} screenshots")
    
    # If we have screenshots, call LLM and execute actions
    if saved_filepaths:
        try:
            # Convert saved screenshots to base64
            print("🔄 Converting screenshots to base64...")
            screenshot_base64_list = []
            for filepath in saved_filepaths:
                screenshot_base64 = image_file_to_base64(filepath)
                screenshot_base64_list.append(screenshot_base64)
            
            # Prepare message for LLM
            message_content = [
                {
                    "type": "text",
                    "text":f"Here is the current game state after your previous action execution. The state is represented by Screenshots of the game. "
                           f"Your goal is to clearly identify the next set of actions or a single action depending upon the last screenshot. The initial screenshots are given to give the sense of direction of velocity. This is a 2d game."
                           f"Remember to use the last screenshot as the current state and use the initial screenshots to get the sense of movement for better decision making."
                           f"Here are {len(saved_filepaths)} screenshots showing the game state. Analyze and decide on the next actions."
                }
            ]
            
            # Add all screenshots to the message
            for i, screenshot_base64 in enumerate(screenshot_base64_list):
                message_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{screenshot_base64}"
                    }
                })
            
            current_game_state_indication_message = HumanMessage(content=[{
                "type": "text",
                "text": f"[CURRENT GAME STATE]"
            }])

            # Add human message to global game state
            human_message = HumanMessage(content=message_content)
            with game_state_lock:
                # Removing the previous Current Game State indication message (third-to-last)
                if len(game_state_messages) >= 4:
                    # POP the third-to-last message (index -3)
                    game_state_messages.pop(-3)

                game_state_messages.append(current_game_state_indication_message)
                game_state_messages.append(human_message)
                # Create a copy of messages for this LLM call
                messages = game_state_messages.copy()
            
            # Get agent decision
            print("🤖 Getting agent decision from LLM...")
            response = await asyncio.to_thread(structured_model.invoke, messages)
            action_list = ActionList(**response) if isinstance(response, dict) else response
            
            print(f"✅ Agent decision: {action_list.model_dump()}")
            
            # Add AI response to global game state
            with game_state_lock:
                game_state_messages.append(AIMessage(content=str(action_list.model_dump())))
            
            # Check if game should end
            if any(action.end_game for action in action_list.actions):
                print("🛑 Agent signaled end of game")
                reset_game_state()  # Reset state for next game
                return {"status": "ok", "saved": len(saved_files), "files": saved_files, "end_game": True}

            # Resume the game before calling LLM and executing actions
            try:
                print("▶️ Resuming game...")
                frame_controller.resume()
                print("✅ Game resumed")
            except Exception as e:
                print(f"❌ Error resuming game: {e}")
                return {"status": "error", "message": f"Failed to resume game: {e}"}
            
            # Execute actions asynchronously
            print("🎮 Executing actions asynchronously...")
            await execute_actions_async(action_list)
            print("✅ Actions executed successfully")
            
        except Exception as e:
            print(f"❌ Error in LLM call or action execution: {e}")
            import traceback
            traceback.print_exception(type(e), e, e.__traceback__)
            return {"status": "error", "message": f"Failed to process: {e}"}
    return {"status": "ok", "saved": len(saved_files), "files": saved_files}


def start_server(host="0.0.0.0", port=8000):
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start_server(host="0.0.0.0", port=8000)

