# async def run_agent_game_loop_async(frames_per_action=20, max_iterations=2):
#     """
#     Main game loop that runs at a controlled frame rate with sequential action execution.
    
#     Args:
#         frames_per_action: Number of frames to advance between agent decisions
#         max_iterations: Maximum number of agent decisions to make
#     """
#     messages = [
#         SystemMessage(content=SYSTEM_PROMPT),
#     ]
    
#     time_controller.pause_game()
#     print("Game paused. Starting agent loop...")
    
#     iteration = 0
    
#     while iteration < max_iterations:
#         print(f"\n=== Iteration {iteration + 1} ===")
        
#         current_frame = frame_controller.get_current_frame()
#         print(f"Current frame: {current_frame}")
        
#         # On first iteration, capture initial screenshot before making first decision
#         if iteration == 0:
#             print("📸 Capturing initial screenshot for first decision...")
#             initial_screenshot = get_screenshot_base64()
#             initial_message = HumanMessage(content=[
#                 {"type": "text", "text": f"Initial game state at frame {current_frame}. Analyze and decide on the first action."},
#                 {
#                     "type": "image_url",
#                     "image_url": {
#                         "url": f"data:image/jpeg;base64,{initial_screenshot}"
#                     }
#                 }
#             ])
#             messages.append(initial_message)
        
#         # Get agent decision
#         print("Getting agent decision...")
#         response = structured_model.invoke(messages)
#         action_list = ActionList(**response) if isinstance(response, dict) else response
        
#         print(f"Agent decision: {action_list.model_dump()}")
        
#         # Add AI response to message history
#         messages.append(AIMessage(content=str(action_list.model_dump())))
        
#         # Check if game should end
#         if any(action.end_game for action in action_list.actions):
#             print("Agent signaled end of game. Stopping...")
#             break
        
#         # Resume game to perform actions
#         time_controller.resume_game()
        
#         # Execute actions sequentially while capturing screenshots in parallel
#         screenshots, screenshot_labels = await execute_actions_and_capture_async(
#             action_list, 
#             frames_per_action
#         )
        
#         print("Pausing game after actions complete")
#         # Pause game after actions complete
#         time_controller.pause_game()
        
#         if screenshots:
#             # Build message content with all 3 screenshots
#             action_descriptions = [f"{a.action} ({a.duration}s)" for a in action_list.actions if not a.end_game]
#             message_content = [
#                 {
#                     "type": "text", 
#                     "text": f"Actions executed in parallel: {', '.join(action_descriptions)}. Here are 3 sequential screenshots showing the player's movement:\n" +
#                             "\n".join([f"- {label}" for label in screenshot_labels]) +
#                             "\n\nUse these images to understand the direction and velocity of movement."
#                 }
#             ]
            
#             # Add all 3 screenshots to the message
#             for screenshot in screenshots:
#                 message_content.append({
#                     "type": "image_url",
#                     "image_url": {
#                         "url": f"data:image/jpeg;base64,{screenshot}"
#                     }
#                 })
            
#             human_message = HumanMessage(content=message_content)
#             messages.append(human_message)
        
#         iteration += 1
    
#     print(f"\n=== Game loop finished after {iteration} iterations ===")
    
#     time_controller.resume_game()
#     client.disconnect()


# def run_agent_game_loop(frames_per_action=20, max_iterations=2):
#     """Wrapper to run the async game loop"""
#     asyncio.run(run_agent_game_loop_async(frames_per_action, max_iterations))

# async def execute_actions_and_capture_async(action_list: ActionList, frames_per_action: int):
#     """
#     Execute actions SEQUENTIALLY (one by one) while capturing screenshots in parallel.
    
#     Returns:
#         tuple: (screenshots list, screenshot_labels list)
#     """
#     # Filter out end_game actions
#     executable_actions = [action for action in action_list.actions if not action.end_game]
    
#     if not executable_actions:
#         return [], []
    
#     # Start screenshot capture task (runs in parallel)
#     screenshot_task = asyncio.create_task(capture_screenshots_async(frames_per_action))
    
#     # Execute actions SEQUENTIALLY (one after another)
#     print("🔄 Executing actions sequentially...")
#     for i, action in enumerate(executable_actions):
#         try:
#             print(f"   Action {i+1}/{len(executable_actions)}: {action.action}")
#             await perform_action_async(action)
#         except Exception as e:
#             print(f"❌ Error executing action {i}: {e}")
    
#     # Wait for screenshots to complete
#     try:
#         screenshots, screenshot_labels = await screenshot_task
#     except Exception as screenshot_result:
#         print(f"❌ Error capturing screenshots: {screenshot_result}")
#         print(f"   Exception type: {type(screenshot_result).__name__}")
#         import traceback
#         traceback.print_exception(type(screenshot_result), screenshot_result, screenshot_result.__traceback__)
#         return [], []
    
#     return screenshots, screenshot_labels

# async def jump_and_move_right():
#     input_controller.release_all_keys()
#     task1 = asyncio.create_task(input_controller.jump_async(hold_duration=1.0))
#     task2 = asyncio.create_task(input_controller.move_right_async(duration=1.0))
#     task3 = asyncio.create_task(capture_screenshots_async(frames_per_action=20))
#     await task1
#     await task2
#     input_controller.release_all_keys()
#     screenshots, labels = await task3