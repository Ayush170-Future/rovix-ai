# ADB Integration Summary

## What Was Implemented

### 1. ADB Manager (`src/agent/adb_manager.py`)
- Connects to ADB server on localhost:5037
- Auto-starts ADB server if not running
- Extracts Unity view bounds from Android UI hierarchy
- Finds `android.view.SurfaceView` element
- Parses bounds: `[left,top][right,bottom]`
- Returns offset_x and offset_y for coordinate translation

### 2. Service Updates (`src/agent/service.py`)
- Initializes ADB Manager after AltTester
- Passes adb_manager to ActionHandler

### 3. Action Handler Updates (`src/agent/actions/action_handler.py`)
- Added adb_manager parameter to constructor
- Updated `_extract_element_info()`:
  - Extracts `x` and `mobileY` from AltObject
  - Gets Unity bounds from ADB
  - Calculates screen coordinates: `screen_x = x + offset_x`, `screen_y = mobileY + offset_y`
  - Stores both `position` (Unity coords) and `screen_position` (screen coords)
- Updated `get_available_actions()` to include screen_position in output

### 4. Config Updates (`src/agent/actions/config/action_config.json`)
- Added ADB section with host and port

### 5. Dependencies (`requirements.txt`)
- Added `pure-python-adb>=0.3.0`

### 6. Test Script (`src/test_adb_coords.py`)
- Tests ADB connection
- Extracts Unity bounds
- Gets elements from AltTester
- Prints Unity coords vs Screen coords
- Validates offset is applied correctly

## How to Use

### Run the test:
```bash
python src/test_adb_coords.py
```

### Expected Output Format

Elements now include both coordinate systems:

```python
{
    "buttons": [
        {
            "id": "12345",
            "name": "PlayButton",
            "position": (640.0, 500.0),        # Unity coords
            "screen_position": (640, 780),     # Screen coords for ADB
            "text": "Play",
            "enabled": True
        }
    ]
}
```

## Edge Cases Handled

1. ADB server not running → Auto-starts
2. No device connected → Logs warning, continues without screen_position
3. SurfaceView not found → Returns None for bounds
4. mobileY missing → screen_position will be None

## TODO for Later

- Add caching for bounds (~200-500ms overhead per query)
- Detect orientation changes and refresh bounds
- Add ADB execution methods (Phase 3)

