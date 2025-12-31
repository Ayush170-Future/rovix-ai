import asyncio
import sys
import os

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from tester import AltTesterClient, InputController

async def test_swipe_only():
    print("🚀 Starting Swipe Interaction Test")
    
    # 1. Initialize client
    try:
        client = AltTesterClient(host="127.0.0.1", port=13000)
        driver = client.get_driver()
        input_controller = InputController(driver)
        print("✅ Connected to AltTester")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        print("   Make sure the Unity game is running and AltTester is enabled.")
        return

    # 2. Test Swipe
    # Adjust these coordinates based on your game's layout
    start_x, start_y = 0, 0
    end_x, end_y = 500, 500
    duration = 2.0 # 2 seconds sweep (a bit longer)
    
    print(f"\n↔️ Testing Swipe from ({start_x}, {start_y}) to ({end_x}, {end_y}) over {duration}s...")
    try:
        input_controller.swipe(start_x, start_y, end_x, end_y, duration=duration)
        print("✅ Swipe command sent successfully")
    except Exception as e:
        print(f"❌ Swipe failed: {e}")

    print("\n⏳ Keeping connection alive for 30 seconds for visual verification...")
    
    try:
        for i in range(30, 0, -1):
            sys.stdout.write(f"\rClosing in {i} seconds... ")
            sys.stdout.flush()
            await asyncio.sleep(1)
        print("\n🏁 Test completed.")
    except KeyboardInterrupt:
        print("\n🛑 Test stopped by user.")

if __name__ == "__main__":
    asyncio.run(test_swipe_only())
