# Rovix AI Agent Server

This repository contains the AI Agent Server for Rovix AI, a system designed to bridge Unity games with LLM-powered agents for automated testing and gameplay.

## 🏗️ Architecture & How It Works

The system supports two distinct modes of operation:

### 1. Whitebox (SDK Mode)
- **Requirement**: Unity game with Agent Zero SDK and AltTester.
- **How it works**: Deep integration with Unity. The server communicates directly with the game objects via AltTester, allowing for precise frame-based control and object manipulation.
- **Workflow**: Unity pauses -> Server captures screenshot -> LLM analyzes state using AltTester metadata -> Server sends high-level actions (e.g., `jump`, `move`) -> Unity executes and resumes.

### 2. Blackbox Mode
- **Requirement**: Any Android app/game. No Unity or AltTester required.
- **How it works**: Purely visual and external. Uses OCR and visual AI via the `VisionElementDetector` to identify interactable elements on the screen.
- **Workflow**: Server captures screenshot via ADB/Appium -> Vision AI (Gemini) maps interactable elements -> LLM decides actions based on visual mapping -> Server executes low-level interactions (taps, swipes) via ADB/Appium.

---

The system generally operates in a loop:

1.  **Unity Integration**: The Unity game, equipped with the `Agent Zero` SDK, sends a `GamePauseEvent` to this server at fixed intervals or specific game moments.
2.  **Visual Capture**: The server captures a screenshot of the game using either **ADB** (for Android devices) or **Appium**.
3.  **State Analysis**:
    *   **Metadata**: It retrieves additional metadata and object information from the game via **AltTester**.
    *   **LLM Processing**: It sends the screenshot, current objectives (TODOs), and available actions to a vision-capable LLM (e.g., Gemini 1.5 Flash).
4.  **Decision Making**: The LLM analyzes the game state and returns a sequence of actions (clicks, swipes, key presses) and an updated summary of the game state.
5.  **Execution**: The `ActionHandler` executes these actions on the device.
6.  **Resume**: Once actions are completed, the server signals Unity to resume the game until the next event interval.

### Core Components

*   **`src/api/main.py`**: FastAPI server that listens for events from Unity.
*   **`src/agent/service.py`**: The core logic coordinator. Handles LLM communication, context management, and workflow orchestration.
*   **`src/tester.py`**: Wraps the AltTester driver to provide high-level controllers for input, scenes, time, and frame-based logic.
*   **`src/agent/adb_manager.py`**: Manages low-level device interactions (screenshots, input) via ADB.
*   **`src/agent/actions.py`**: Handles the execution of LLM-generated actions.

## ✨ Key Functionality

*   **Multimodal AI**: Uses visual input (screenshots) combined with structured game data (Whitebox) or OCR mapping (Blackbox) for decision-making.
*   **Dynamic TODO Management**: Maintains a persistent list of objectives that the agent tracks across steps.
*   **Mode Versatility**:
    *   **Whitebox**: Requires `SDK_ENABLED=true`. Best for deep testing of Unity projects.
    *   **Blackbox**: Requires `SDK_ENABLED=false`. Uses OCR to map elements and Appium/ADB for interactions. No game instrumentation needed.
*   **Automated Testing**: Built-in support for executing predefined test cases and reporting results.
*   **Resilient Interaction**: Includes retry logic for screenshots and state synchronization to handle network or device instability.

## 📋 Prerequisites

*   Python 3.9+
*   Unity Project with [Agent Zero SDK](https://github.com/Rovix-AI/rovix-agentZero-unity)
*   [AltTester Desktop](https://alttesting.io/) (for SDK mode)
*   ADB (Android Debug Bridge) installed and in PATH
*   Redis server (optional, used for caching)
*   Google API Key (for Gemini)

## 🛠️ Configuration (.env)

The system behavior is controlled via environment variables in the `.env` file:

| Variable | Description |
| :--- | :--- |
| `GOOGLE_API_KEY` | Your Google API key for Gemini models. |
| `SDK_ENABLED` | `true` (Whitebox): Server waits for Unity/AltTester events. `false` (Blackbox): Server polls for screenshots using Vision AI/OCR. |
| `USE_APPIUM` | `true`: Uses Appium for device control and screenshots. `false`: Uses pure ADB (fastest for Android). |
| `DEVICE_NAME` | The name of the device (e.g., "Android Emulator", "iPhone 15"). Used mainly by Appium. |
| `DEVICE_UDID` | (Optional) The unique identifier for the device (from `adb devices`). |
| `POLLING_INTERVAL` | (Blackbox only) Time in seconds to wait between agent steps. Default is 2.5s. |
| `SCREENSHOT_TIMEOUT` | Timeout for capturing screenshots from the device. |
| `GAME_NAME` | The human-readable name of the game (e.g., "Solitaire"). |
| `ANDROID_PACKAGE_NAME` | The Android package identifier of the game. |

## 🧩 Prompts & Game Identification

### Where are the Prompts?
All LLM prompts are stored in [prompts.py](file:///Users/ashwanikottapalli/Documents/GitHub/Ludo_AITest/rovix-ai/src/agent/prompts.py). 
- `SYSTEM_PROMPT`: The core logic for how the agent interacts with games.
- `SYSTEM_PROMPT_WITH_TODO`: An advanced prompt that incorporates QA testing methodologies and task management.
- **Game Descriptions**: Specific game context (like `HITWICKET_GAME_DESCRIPTION`) is injected into the system prompt to give the AI domain knowledge.

### How does the system know which game?
1. **Config**: The system reads `GAME_NAME` and `ANDROID_PACKAGE_NAME` from `.env`.
2. **Context Injection**: In `src/agent/service.py`, these descriptions are passed to the `ContextService` which assembles the final prompt sent to the LLM. 
   > [!NOTE]
   > The system uses a dynamic configuration registry. To add a new game (like **Bingo Blitz**), follow the guide below.

## ➕ How to Add a New Game

To add support for a new game (e.g., for Blackbox testing):

### 1. Define Game Prompts
Open [prompts.py](file:///Users/ashwanikottapalli/Documents/GitHub/Ludo_AITest/rovix-ai/src/agent/prompts.py) and add your game's description and gameplay details:
```python
MY_GAME_DESCRIPTION = "..."
MY_GAMEPLAY_DETAILS = "..."
```

### 2. Register the Game
Add your new game to the `GAME_CONFIGS` dictionary in `prompts.py`:
```python
GAME_CONFIGS = {
    "hitwicket": { ... },
    "my_game": {
        "description": MY_GAME_DESCRIPTION,
        "details": MY_GAMEPLAY_DETAILS
    }
}
```

### 3. Update Environment
Update your `.env` file to point to the new game:
```env
GAME_NAME="my_game"
ANDROID_PACKAGE_NAME="com.example.mygame"
SDK_ENABLED=false  # Set to false for Blackbox/Emulator testing
```

### 4. Run & Test
Launch the game on your emulator and start the server. The AI will now use the specific context for your new game.

## 🛠️ Setup & Installation

### 1. Project Dependencies
1.  **Clone the repository**:
    ```bash
    git clone https://github.com/Ayush170-Future/rovix-ai.git
    cd rovix-ai
    ```

2.  **Create and activate a virtual environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

### 2. Device Control Setup (Choose One)

#### Option A: Pure ADB (Recommended for Android/Emulators)
Fastest and easiest setup for Android. No extra installation required if you have `adb` in your PATH.
- Ensure `USE_APPIUM=false` in your `.env`.
- Ensure your device is visible: `adb devices`.

#### Option B: Appium (Required for iOS or Advanced Interactions)
1.  **Install Appium Server** (requires Node.js):
    ```bash
    npm install -g appium
    ```
2.  **Install Android Driver**:
    ```bash
    appium driver install uiautomator2
    ```
3.  **Run the Server**:
    Start the server in a separate terminal:
    ```bash
    appium
    ```
- Ensure `USE_APPIUM=true` in your `.env`.

## 🏃 Running the Server

1.  **Start your game build** on a device or emulator.
2.  **Start AltTester Desktop** (only if `SDK_ENABLED=true`) and ensure it's connected to the game.
3.  **Run the Python server**:
    ```bash
    python3 src/api/main.py
    ```
    The server will start on `http://0.0.0.0:8000`.

## ⚠️ Potential Issues & Troubleshooting

### Dependency Installation Errors
If `pip install -r requirements.txt` fails to find `alttester>=2.0.0`:
- Ensure you are using `pip3` and a modern version of pip: `pip install --upgrade pip`.
- If the package is still not found, try installing it directly: `pip install AltTester-Python-SDK`.
- Note: Version 2.0+ is required for the latest Agent Zero features.

### Connectivity
- **AltTester Connection Failed**: Ensure AltTester Desktop is running and the port (default 13000) matches the configuration in `tester.py`.
- **ADB Device Not Found**: Run `adb devices` to ensure your device is connected and authorized.
*   **Unity Scene Assembly Errors**: If using the SDK mode, ensure the assembly name in `tester.py` (e.g., `Assembly-CSharp`) matches your Unity project's assembly settings.
*   **LLM Rate Limits/Timeouts**: Complex game states with many screenshots can hit LLM context limits or timeouts. Adjust `SCREENSHOT_TIMEOUT` or use models with larger context windows if necessary.
*   **Screenshot Failures**: If screenshots fail frequently, check ADB connectivity or increase the `screenshot_max_retries` in `.env`.
