# AltTester — Claude Code Guide

## Project Overview

AI-powered automated testing framework for mobile games. Combines LLMs, computer vision, and device automation to execute test scenarios on Android devices. Supports two modes:
- **SDK mode** (white-box): AltTester Unity SDK integration for precise component interaction
- **Black-box mode**: Vision-only testing via Appium/ADB + Gemini element detection

## Running the Server

```bash
cd src
python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Run the black-box polling loop directly:
```bash
cd src
python agent/service.py
```

## Key Environment Variables

```bash
# Testing mode
SDK_ENABLED=false          # true = AltTester SDK, false = black-box vision mode
USE_APPIUM=true            # true = Appium, false = ADB direct

# Model selection
MODEL_PROVIDER=google      # google | anthropic | azure | bedrock
GOOGLE_API_KEY=...
GOOGLE_MODEL=gemini-3-flash-preview

# Anthropic via Vertex AI
ANTHROPIC_MODEL=claude-sonnet-4-6
ANTHROPIC_PROJECT_ID=...
ANTHROPIC_LOCATION=us-east5

# Azure OpenAI
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
AZURE_OPENAI_API_INSTANCE_NAME=...

# Device
APPIUM_URL=http://localhost:4723
DEVICE_NAME=...
DEVICE_UDID=...
APP_PACKAGE=...
APP_ACTIVITY=...

# Tuning
POLLING_INTERVAL=2.5       # seconds between black-box steps
MAX_STEPS=1000
SCREENSHOT_TIMEOUT=10.0
VISION_TIMEOUT=45.0
VISION_MAX_RETRIES=3

# Infrastructure
GCS_BUCKET_NAME=...
ANDROID_HOME=...
```

## Architecture

```
src/
├── api/main.py                      # FastAPI entry point
├── tester.py                        # AltTester SDK driver abstractions
├── database.py                      # DB init
├── agent/
│   ├── service.py                   # Main agent loop + LLM orchestration
│   ├── appium_manager.py            # Appium device control (local + BrowserStack)
│   ├── adb_manager.py               # ADB direct control
│   ├── vision_element_detector.py   # Gemini vision API for UI element detection
│   ├── prompts.py                   # LLM system prompts
│   ├── logger.py                    # Logging utilities
│   ├── actions/action_handler.py    # SDK-mode action execution
│   └── context/context_service.py  # Multi-turn conversation memory
├── services/
│   ├── android_build_runner.py      # APK install + app launch pipeline
│   ├── execution_service.py         # Test execution orchestration
│   └── views.py                     # Pydantic schemas (AgentOutput, Action, etc.)
├── models/                          # Data models (Build, Device, TestRun, etc.)
├── routes/                          # FastAPI routers
├── repositories/                    # Data access layer
└── tools/todo_management/           # Persistent test plan tracking
```

## Agent Loop (how it works)

Each step:
1. Capture screenshot via Appium/ADB
2. Gemini detects visible UI elements with bounding boxes (async)
3. Build context: screenshot + element list + todo list + conversation history
4. Call LLM with structured output schema (`AgentOutput`)
5. LLM returns: `actions`, `test_results`, `game_state_summary`, `end_game`
6. Execute actions (click/swipe/wait via Appium; `todo_write` updates test plan)
7. Append test results to `src/agent/test_results.json` (thread-safe, background)
8. Loop until `end_game=true` or `MAX_STEPS` reached

**SDK mode** uses frame-sync via `GameFrameController` (Unity signals each step).  
**Black-box mode** polls on a configurable `POLLING_INTERVAL`.

## Key Schemas (`src/services/views.py`)

- **`AgentOutput`** — LLM structured response: `actions`, `test_results`, `game_state_summary`, `reason`, `end_game`, `force_annotate`
- **`Action`** — `action_type` (click/swipe/multi_swipe/wait/todo_write), coordinates, `duration`, `todo_input`
- **`TestResult`** — `test_case_id`, `status`, `message`
- **`GamePauseEvent`** — `current_step`, `current_frame`

## Build Pipeline

1. Client requests signed GCS upload URL → uploads APK directly to GCS
2. Backend finalizes build: extracts package/activity via `aapt`, marks `ready`
3. Execution: uploads to BrowserStack (gets `bs://` URL) or installs via ADB/device agent
4. Cleanup: HOME keyevent + force-stop after run

## Todo Management

The agent maintains a persistent JSON task list at runtime. The LLM reads the current todo state in every prompt and can update it via `todo_write` actions. Tasks have states: `pending` → `in_progress` → `completed`/`cancelled`.

## Notes

- `SESSION_ID = "game_session_main"` is hardcoded in `service.py` — one session at a time
- Vision detector uses `gemini-robotics-er-1.5-preview` (separate from the main LLM model)
- Bounding boxes from vision API are in normalized [0–1000] format, converted to pixel coords
- Legacy SDK endpoints (`/ai/on-pause`, `/ai/resume`, `/ai/swipe`) only mounted when `SDK_ENABLED=true`
- Test results written to `src/agent/test_results.json` with file lock to prevent corruption
