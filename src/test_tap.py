import asyncio
import sys
import os

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from tester import AltTesterClient, InputController

async def test_tap_only():
    print("🚀 Starting Tap Interaction Test")
    
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

    # 2. Test Touch (Tap)
    # Use coordinates where your button or object is located
    x, y = 0, 0 
    print(f"\n👉 Testing Touch at ({x}, {y})...")
    try:
        input_controller.tap(x, y) # Using synchronous tap to ensure it completes before we wait
        print("✅ Touch command sent successfully")
    except Exception as e:
        print(f"❌ Touch failed: {e}")

    print("\n⏳ Keeping connection alive for 30 seconds for visual verification...")
    print("   Check Unity for the color change!")
    
    # Wait for a while so the user can see the result
    try:
        for i in range(30, 0, -1):
            sys.stdout.write(f"\rClosing in {i} seconds... ")
            sys.stdout.flush()
            await asyncio.sleep(1)
        print("\n🏁 Test completed.")
    except KeyboardInterrupt:
        print("\n🛑 Test stopped by user.")
    finally:
        # client.disconnect() # Keeping it commented out if you want to keep it REALLY open, 
        # but usually it's better to close on exit
        pass

if __name__ == "__main__":
    asyncio.run(test_tap_only())
