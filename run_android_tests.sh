#!/bin/bash
set -e

PORT=13001

echo "Checking adb..."
adb devices | grep -q "device$" || {
  echo "No Android device connected"
  exit 1
}

echo "Setting adb reverse on port $PORT"
adb reverse tcp:$PORT tcp:$PORT

echo "Running Python tests"
python3 testi.py

echo "Cleaning up adb reverse"
adb reverse --remove tcp:$PORT
