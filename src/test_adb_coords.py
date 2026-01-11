import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent.adb_manager import ADBManager
from tester import AltTesterClient
from agent.actions import ActionHandler


def main():
    print("🔌 Connecting to ADB...")
    adb_manager = ADBManager(host="127.0.0.1", port=5037)
    
    adb_manager.swipe(911, 1948, 791, 2226, 1)

if __name__ == "__main__":
    main()