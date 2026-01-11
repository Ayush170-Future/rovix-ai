# Android Run Guide

This guide explains how to set up and run the AI agent on an Android device for the Ludo game.

## Prerequisites

1.  **Android Device**: Connected via USB and with **Developer Options** and **USB Debugging** enabled.
2.  **ADB Installed**: Ensure `adb` is in your system PATH.
3.  **Ludo Game Build**: An Android APK of the Ludo game with **AltTester** and **Rovix AI Unity Package** integrated.

## Setup Steps

### 1. Connect Device & Verify ADB
Connect your device and run:
```bash
adb devices
```
You should see your device serial number in the list.

### 2. Configure Environment Variables
Ensure your `.env` file in the `rovix-ai` directory has the correct package name:
```env
ANDROID_PACKAGE_NAME="com.SoumavoDey.Ludo"
```

### 3. Install and Launch the Game
Install the APK on your device:
```bash
adb install path/to/your/Ludo.apk
```
Launch the game manually on the device.

### 4. Setup Port Forwarding
AltTester communicates over port 13000 by default. Forward this port from your device to your host machine:
```bash
adb reverse tcp:13000 tcp:13000
```
> [!NOTE]
> If you are running the AI server on a different machine than the one connected to the device, ensure the network routing is correctly configured.

### 5. Run the AI Agent Server
From the `rovix-ai` directory, install dependencies and start the server:
```bash
pip install -r requirements.txt
python src/api/main.py
```

### 6. Start the Agent
The server will wait for the game to reach a pause event (configured in Unity) or you can manually trigger a resume if needed via the API:
```bash
curl -X POST http://localhost:8000/ai/resume
```

## Troubleshooting

- **ADB Connection**: If `adb devices` shows "unauthorized", check your device screen for a debug permission prompt.
- **Port 13000**: Ensure no other process is using port 13000 on your host machine.
- **Package Name**: If coordinate mapping fails, verify the package name using:
  ```bash
  adb shell pm list packages | grep Soumavo
  ```
- **Unity View Bounds**: If clicks are offset, the `adb_manager.py` might be failing to find the correct view. Check the logs for `🔍 Width: ..., Height: ...`.
