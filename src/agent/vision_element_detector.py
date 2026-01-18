import json
import time
import asyncio
import os
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types
from typing import List, Dict


class VisionElementDetector:
    def __init__(self, api_key: str, model_name: str = "gemini-robotics-er-1.5-preview"):
        self.api_key = api_key
        self.model_name = model_name
        self.client = genai.Client(api_key=api_key)
        
        self.prompt = """
You are a helpful assistant and your job is identify ALL INTERACTABLE UI elements in this screenshot. An interactable element is something a user can tap, click, swipe, or interact with.
The dectected objects have be exhaustive and the bounding boxes has to be accurate. This information will be used to interact with the game. And any wrong detection, missed object or incorrect bounding boxes
will lead to the failure of the game play, which is not acceptable.

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
1. Its bounding box location
2. A brief label identifying what it is
3. A short description of what it does when interacted with

The answer should follow this JSON format:
[
  {
    "bounding_box": [y_min, x_min, y_max, x_max],
    "label": "Brief identifying name (e.g., 'settings button', 'username input field', 'login button')",
    "description": "Short description of what this element does (e.g., 'Opens settings menu', 'Enter username here', 'Submit login form')"
  },
  ...
]

The bounding boxes are in [y_min, x_min, y_max, x_max] format normalized to 0-1000.

Detect as many interactable elements as you can find. Be thorough!"""

    def _parse_gemini_response(self, response_text: str) -> List[Dict]:
        cleaned = response_text.replace("```json", "").replace("```", "").strip()
        
        try:
            start_idx = min(
                cleaned.find('[') if cleaned.find('[') != -1 else len(cleaned),
                cleaned.find('{') if cleaned.find('{') != -1 else len(cleaned)
            )
            
            end_idx = max(
                cleaned.rfind(']') if cleaned.rfind(']') != -1 else 0,
                cleaned.rfind('}') if cleaned.rfind('}') != -1 else 0
            )
            
            json_str = cleaned[start_idx:end_idx+1]
            parsed = json.loads(json_str)
            
            if isinstance(parsed, dict):
                return [parsed]
            return parsed
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}")
            return []

    def _convert_normalized_bbox_to_pixels(self, bbox_norm: List[int], image_width: int, image_height: int) -> dict:
        y_min_norm, x_min_norm, y_max_norm, x_max_norm = bbox_norm
        
        x_min = int((x_min_norm / 1000.0) * image_width)
        y_min = int((y_min_norm / 1000.0) * image_height)
        x_max = int((x_max_norm / 1000.0) * image_width)
        y_max = int((y_max_norm / 1000.0) * image_height)
        
        x_min = max(0, min(x_min, image_width))
        y_min = max(0, min(y_min, image_height))
        x_max = max(0, min(x_max, image_width))
        y_max = max(0, min(y_max, image_height))
        
        center_x = (x_min + x_max) // 2
        center_y = (y_min + y_max) // 2
        
        return {
            'center': (center_x, center_y),
            'bbox': [x_min, y_min, x_max, y_max]
        }

    async def _draw_bounding_boxes_async(self, screenshot_path: str, results: List[Dict]):
        try:
            image = Image.open(screenshot_path)
            draw = ImageDraw.Draw(image)
            
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
            except:
                font = ImageFont.load_default()
            
            colors = ['red', 'green', 'blue', 'yellow', 'purple', 'orange', 'cyan', 'magenta']
            
            for idx, result in enumerate(results):
                bbox = result['bounding_box']
                name = result['name']
                color = colors[idx % len(colors)]
                
                x_min, y_min, x_max, y_max = bbox
                draw.rectangle([x_min, y_min, x_max, y_max], outline=color, width=3)
                
                center_x, center_y = result['screen_position']
                draw.ellipse([center_x-4, center_y-4, center_x+4, center_y+4], fill=color)
                
                text_bbox = draw.textbbox((x_min, y_min - 18), name, font=font)
                draw.rectangle(text_bbox, fill=color)
                draw.text((x_min, y_min - 18), name, fill='white', font=font)
            
            base_name = os.path.splitext(screenshot_path)[0]
            output_path = f"{base_name}_annotated.png"
            
            await asyncio.to_thread(image.save, output_path)
            print(f"📸 Annotated image saved")
        except Exception as e:
            print(f"⚠️  Failed to save annotated image: {e}")

    async def detect_elements(self, screenshot_path: str) -> List[Dict]:
        print(f"🔍 Vision detection")
        
        image = Image.open(screenshot_path)
        image_width, image_height = image.size
        
        with open(screenshot_path, 'rb') as f:
            image_bytes = f.read()
        
        start_time = time.time()
        
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type='image/png',
                    ),
                    self.prompt
                ],
                config=types.GenerateContentConfig(
                    temperature=0.5,
                    thinking_config=types.ThinkingConfig(thinking_budget=0)
                )
            )
            
            output = response.text
            elapsed = time.time() - start_time
            print(f"⏱️  Vision API response time: {elapsed:.2f}s")
            
        except Exception as e:
            print(f"❌ Vision API error: {e}")
            return []
        
        detections = self._parse_gemini_response(output)
        
        results = []
        for detection in detections:
            bbox_norm = detection.get('bounding_box', [0, 0, 0, 0])
            label = detection.get('label', 'Unknown')
            description = detection.get('description', 'No description')
            
            bbox_data = self._convert_normalized_bbox_to_pixels(bbox_norm, image_width, image_height)
            
            results.append({
                'name': label,
                'description': description,
                'screen_position': bbox_data['center'],
                'bounding_box': bbox_data['bbox']
            })
        
        print(f"✅ Detected {len(results)} elements via vision")
        
        if results:
            asyncio.create_task(self._draw_bounding_boxes_async(screenshot_path, results))
        
        return results
