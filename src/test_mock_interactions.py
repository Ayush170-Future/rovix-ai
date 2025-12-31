import unittest
from unittest.mock import MagicMock
import sys
import os
import asyncio

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from tester import InputController

class TestAltTesterInteractionsMock(unittest.TestCase):
    def setUp(self):
        # Create a mock driver
        self.mock_driver = MagicMock()
        # Initialize your controller with the mock driver
        self.input_controller = InputController(self.mock_driver)

    def test_tap_call(self):
        print("\n🧪 Verifying Tap call logic...")
        self.input_controller.tap(100, 200, count=1)
        
        # Verify if driver.tap was called with correct dictionary format
        # AltTester 2.x expects coordinates as a dictionary {"x": ..., "y": ...}
        self.mock_driver.tap.assert_called_once_with(
            {"x": 100, "y": 200}, count=1, interval=0.1, wait=True
        )
        print("✅ Tap logic verified!")

    def test_swipe_call(self):
        print("\n🧪 Verifying Swipe call logic...")
        self.input_controller.swipe(10, 10, 500, 500, duration=0.8)
        
        # Verify if driver.swipe was called with correct start/end dictionaries
        self.mock_driver.swipe.assert_called_once_with(
            {"x": 10, "y": 10},
            {"x": 500, "y": 500},
            duration=0.8,
            wait=True
        )
        print("✅ Swipe logic verified!")

async def run_async_test():
    # Simple check for async methods
    mock_driver = MagicMock()
    input_controller = InputController(mock_driver)
    
    print("\n🧪 Verifying Async Swipe call logic...")
    await input_controller.swipe_async(0, 0, 100, 100, duration=0.1)
    mock_driver.swipe.assert_called_with(
        {"x": 0, "y": 0},
        {"x": 100, "y": 100},
        duration=0.1,
        wait=True
    )
    print("✅ Async Swipe logic verified!")

if __name__ == "__main__":
    # Run synchronous tests
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAltTesterInteractionsMock)
    unittest.TextTestRunner(verbosity=2).run(suite)
    
    # Run async check
    asyncio.run(run_async_test())
