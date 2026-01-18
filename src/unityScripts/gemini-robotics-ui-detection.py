"""
General-Purpose Interactable Element Detection via Gemini Robotics 1.5
======================================================================

This script detects ALL interactable UI elements in any screenshot using
Google's Gemini Robotics ER 1.5 Preview model.

What it does:
1. Detects ALL interactable elements (buttons, icons, input fields, clickable items)
2. Provides a short description of what each element does
3. Returns point coordinates + labels for each element
4. Provides tap coordinates for Android/UI automation

Perfect for:
- Android app automation
- Web UI testing
- Game automation
- Screen reader applications
- Any UI interaction tasks

Key Features:
- Uses Google Gemini Robotics API directly
- Returns point coordinates in [y, x] format normalized to 0-1000
- Converts normalized coords to actual pixel coordinates
- Includes descriptions of what each element does
- Works with any screenshot or UI image

Output:
- Each interactable element gets its own point coordinate
- Element identification + description
- Normalized coordinates scaled to image size
"""

import json
import time
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types
import os


# ============================================================================
# CONFIGURATION
# ============================================================================

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "<GOOGLE_API_KEY>")
MODEL_NAME = "gemini-robotics-er-1.5-preview"
IMAGE_PATH = "image.png"


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def parse_gemini_response(response_text):
    """
    Parse the JSON string output from Gemini Robotics model.
    
    The model returns points in [y, x] format normalized to 0-1000.
    
    Args:
        response_text: String containing JSON output
    
    Returns:
        List of dictionaries with point and label keys
    """
    cleaned = response_text.replace("```json", "").replace("```", "").strip()
    
    try:
        # Find the first [ or { to start of JSON
        start_idx = min(
            cleaned.find('[') if cleaned.find('[') != -1 else len(cleaned),
            cleaned.find('{') if cleaned.find('{') != -1 else len(cleaned)
        )
        
        # Find the last ] or }
        end_idx = max(
            cleaned.rfind(']') if cleaned.rfind(']') != -1 else 0,
            cleaned.rfind('}') if cleaned.rfind('}') != -1 else 0
        )
        
        json_str = cleaned[start_idx:end_idx+1]
        parsed = json.loads(json_str)
        
        # If it's a single object, wrap it in a list
        if isinstance(parsed, dict):
            return [parsed]
        return parsed
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        print(f"Cleaned string: {cleaned}")
        return []


def convert_normalized_to_bbox(point, image_width, image_height, box_size=30):
    """
    Convert Gemini's normalized point [y, x] to bounding box in pixel coordinates.
    
    Gemini returns points in [y, x] format normalized to 0-1000.
    We need to convert to [x_min, y_min, x_max, y_max] in pixels.
    
    Args:
        point: [y, x] in normalized 0-1000 format
        image_width: Width of the image in pixels
        image_height: Height of the image in pixels
        box_size: Size of the box to draw around the point (default 30px)
    
    Returns:
        [x_min, y_min, x_max, y_max] in pixel coordinates
    """
    # Point is [y, x] in 0-1000 range
    y_norm, x_norm = point
    
    # Convert to pixel coordinates
    x_pixel = int((x_norm / 1000.0) * image_width)
    y_pixel = int((y_norm / 1000.0) * image_height)
    
    # Create a bounding box around the point
    half_box = box_size // 2
    x_min = max(0, x_pixel - half_box)
    y_min = max(0, y_pixel - half_box)
    x_max = min(image_width, x_pixel + half_box)
    y_max = min(image_height, y_pixel + half_box)
    
    return [x_min, y_min, x_max, y_max]


def draw_bounding_boxes(image, detections, output_path="output_with_boxes_gemini.png"):
    """
    Draw bounding boxes on the image and save the result.
    
    Args:
        image: PIL Image object
        detections: List of dictionaries with 'bbox_2d' and 'label' keys
        output_path: Path to save the annotated image
    
    Returns:
        PIL Image with bounding boxes drawn
    """
    img_copy = image.copy()
    draw = ImageDraw.Draw(img_copy)
    
    # Try to use a nice font, fall back to default if not available
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
        font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
    except:
        font = ImageFont.load_default()
        font_small = font
    
    # Define colors for different objects
    colors = ['red', 'green', 'blue', 'yellow', 'purple', 'orange', 'cyan', 'magenta']
    
    for idx, detection in enumerate(detections):
        bbox = detection['bbox_2d']
        label = detection['label']
        color = colors[idx % len(colors)]
        
        # Draw rectangle
        x_min, y_min, x_max, y_max = bbox
        draw.rectangle([x_min, y_min, x_max, y_max], outline=color, width=3)
        
        # Draw center point
        center_x = (x_min + x_max) // 2
        center_y = (y_min + y_max) // 2
        draw.ellipse([center_x-3, center_y-3, center_x+3, center_y+3], fill=color)
        
        # Draw label background and text
        text_bbox = draw.textbbox((x_min, y_min - 20), label, font=font_small)
        draw.rectangle(text_bbox, fill=color)
        draw.text((x_min, y_min - 20), label, fill='white', font=font_small)
    
    img_copy.save(output_path)
    print(f"Annotated image saved to: {output_path}")
    return img_copy


# ============================================================================
# MAIN DETECTION FUNCTION
# ============================================================================

def detect_interactable_elements(image_path, api_key=GOOGLE_API_KEY, model_name=MODEL_NAME):
    """
    Detect all interactable UI elements in a screenshot using Gemini Robotics 1.5.
    
    Process:
    1. Load the screenshot image
    2. Send to Gemini Robotics with interactable element detection prompt
    3. Parse the response with point coordinates and descriptions
    4. Convert normalized points to bounding boxes
    5. Visualize results with boxes on each element
    
    Args:
        image_path: Path to the screenshot (any UI/app/game screenshot)
        api_key: Google API key for Gemini
        model_name: Model to use (default: gemini-robotics-er-1.5-preview)
    
    Returns:
        List of detected interactable elements, each with:
        - 'point': [y, x] in normalized 0-1000 format
        - 'bbox_2d': [x_min, y_min, x_max, y_max] in pixel coordinates
        - 'label': Brief name of the element
        - 'description': What the element does
        - 'center': (x, y) tap coordinates in pixels
    """
    total_start_time = time.time()
    
    print(f"Using model: {model_name}")
    print(f"Loading image: {image_path}")
    
    # Load the image
    image = Image.open(image_path)
    image_width, image_height = image.size
    print(f"Image dimensions: {image_width}x{image_height}")
    
    # Load image bytes
    print("Loading image bytes...")
    with open(image_path, 'rb') as f:
        image_bytes = f.read()
    
    # ========================================================================
    # STEP 1: Set up Gemini client
    # ========================================================================
    print("Setting up Gemini Robotics client...")
    
    if api_key == "<GOOGLE_API_KEY>":
        raise ValueError("Please set your GOOGLE_API_KEY!")
    
    client = genai.Client(api_key=api_key)
    
    # ========================================================================
    # STEP 2: Prepare the prompt
    # ========================================================================
    # General-purpose interactable element detection prompt
    PROMPT = """Identify ALL INTERACTABLE UI elements in this screenshot. An interactable element is something a user can tap, click, swipe, or interact with.

Examples of interactable elements to detect:
- Buttons (submit, cancel, back, menu, navigation, etc.)
- Icons (settings, share, home, search, profile, etc.)
- Text input fields and text boxes
- Checkboxes, radio buttons, toggles, switches
- Dropdown menus and selectors
- Tabs and navigation items
- Clickable cards or tiles
- Links and clickable text
- Sliders and scroll bars
- Game pieces or interactive objects (if it's a game)
- Any other elements users can interact with

DO NOT include:
- Static text labels (unless they're clickable)
- Background images
- Decorative elements
- Non-interactive text

For each interactable element, provide:
1. Its location (point)
2. A brief label identifying what it is
3. A short description of what it does when interacted with

The answer should follow this JSON format:
[
  {
    "point": [y, x],
    "label": "Brief identifying name (e.g., 'settings button', 'username input field', 'login button')",
    "description": "Short description of what this element does (e.g., 'Opens settings menu', 'Enter username here', 'Submit login form')"
  },
  ...
]

The points are in [y, x] format normalized to 0-1000.

Detect as many interactable elements as you can find. Be thorough!"""
    
    # ========================================================================
    # STEP 3: Call the API
    # ========================================================================
    print("Calling Gemini Robotics API...")
    print("(This may take 10-30 seconds depending on image size)")
    
    start_time = time.time()
    
    try:
        image_response = client.models.generate_content(
            model=model_name,
            contents=[
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type='image/png',
                ),
                PROMPT
            ],
            config=types.GenerateContentConfig(
                temperature=0.5,
                thinking_config=types.ThinkingConfig(thinking_budget=0)
            )
        )
        
        output = image_response.text
        
        end_time = time.time()
        elapsed_time = end_time - start_time
        
        print(f"\n⏱️  API Response Time: {elapsed_time:.2f} seconds")
        
        print("\n" + "="*80)
        print("RAW MODEL OUTPUT:")
        print("="*80)
        print(output)
        print("="*80 + "\n")
        
    except Exception as e:
        end_time = time.time()
        elapsed_time = end_time - start_time
        print(f"⏱️  Time before error: {elapsed_time:.2f} seconds")
        print(f"Error calling API: {e}")
        return []
    
    # ========================================================================
    # STEP 4: Parse the response
    # ========================================================================
    try:
        detections = parse_gemini_response(output)
        print(f"Detected {len(detections)} element(s)")
    except Exception as e:
        print(f"Error parsing response: {e}")
        print("Model output may not be valid JSON")
        return []
    
    # ========================================================================
    # STEP 5: Convert normalized points to bounding boxes
    # ========================================================================
    results = []
    print("\n📍 Converting normalized coordinates to bounding boxes:")
    print("-" * 80)
    
    for idx, detection in enumerate(detections, 1):
        point = detection.get('point', [0, 0])
        label = detection.get('label', 'Unknown')
        description = detection.get('description', 'No description provided')
        
        # Convert normalized point to bounding box
        bbox = convert_normalized_to_bbox(point, image_width, image_height, box_size=30)
        
        # Calculate center for tapping
        center_x = (bbox[0] + bbox[2]) // 2
        center_y = (bbox[1] + bbox[3]) // 2
        
        result = {
            'point': point,  # Original normalized [y, x]
            'bbox_2d': bbox,  # Converted [x_min, y_min, x_max, y_max]
            'label': label,
            'description': description,
            'center': (center_x, center_y)
        }
        results.append(result)
        
        print(f"{idx}. {label}")
        print(f"   📝 Description: {description}")
        print(f"   📊 Normalized point: {point} (y, x in 0-1000)")
        print(f"   📍 Bounding box: {bbox}")
        print(f"   🎯 Center (tap here): ({center_x}, {center_y})")
        print(f"   📏 Size: {bbox[2] - bbox[0]}x{bbox[3] - bbox[1]} pixels")
    
    # ========================================================================
    # STEP 6: Visualize the results
    # ========================================================================
    if results:
        draw_bounding_boxes(image, results, "output_with_boxes_gemini.png")
    
    total_end_time = time.time()
    total_elapsed = total_end_time - total_start_time
    print(f"\n⏱️  Total Execution Time: {total_elapsed:.2f} seconds")
    
    return results


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    script_start_time = time.time()
    
    print("="*80)
    print("Interactable UI Element Detection (Gemini Robotics 1.5)")
    print("="*80 + "\n")
    
    # Check for API key
    if GOOGLE_API_KEY == "<GOOGLE_API_KEY>":
        print("⚠️  WARNING: Please set your GOOGLE_API_KEY!")
        print("You can set it as an environment variable:")
        print('  export GOOGLE_API_KEY="your-key-here"')
        print("\nOr edit the script and replace <GOOGLE_API_KEY> with your actual key.")
        print("\nGet your API key from: https://aistudio.google.com/apikey")
        exit(1)
    
    # Run the detection
    detections = detect_interactable_elements(IMAGE_PATH)
    
    # Print final results
    print("\n" + "="*80)
    print(f"FINAL RESULTS - {len(detections)} Interactable Element(s) Detected:")
    print("="*80)
    
    if detections:
        print("\n📋 ALL ELEMENTS:")
        print(json.dumps(detections, indent=2))
        
        print(f"\n✅ SUCCESS! Found {len(detections)} interactable element(s):")
        print("=" * 80)
        
        for i, obj in enumerate(detections, 1):
            bbox = obj['bbox_2d']
            label = obj.get('label', 'Unknown')
            description = obj.get('description', 'No description')
            center = obj['center']
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            
            # Determine emoji based on element type
            label_lower = label.lower()
            if 'button' in label_lower:
                emoji = "🔘"
            elif 'input' in label_lower or 'field' in label_lower:
                emoji = "📝"
            elif 'icon' in label_lower:
                emoji = "⚙️"
            elif 'menu' in label_lower:
                emoji = "☰"
            elif 'search' in label_lower:
                emoji = "🔍"
            else:
                emoji = "🎯"
            
            print(f"\n┌─ {i}. {emoji} {label}")
            print(f"│  📄 {description}")
            print(f"│  🎯 Tap at: {center}")
            print(f"│  📍 Bbox: {bbox}")
            print(f"│  📏 Size: {width}x{height}px")
            print(f"└─")
        
        print("\n" + "=" * 80)
        print(f"🖼️  Check 'output_with_boxes_gemini.png' to see all elements marked!")
        print(f"💡 All interactable elements detected - ready for automation!")
    else:
        print("\n❌ No interactable elements detected in the image.")
    
    script_end_time = time.time()
    script_total_time = script_end_time - script_start_time
    
    print("\n" + "="*80)
    print("⏱️  TIMING SUMMARY")
    print("="*80)
    print(f"Total Script Execution: {script_total_time:.2f} seconds")
    print("="*80)
