import json
import time
import asyncio
import os
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class VisionDetectionResult:
    """Result of vision element detection"""
    success: bool
    elements: List[Dict]
    error_message: Optional[str] = None
    retry_count: int = 0
    elapsed_time: float = 0.0


class VisionElementDetector:
    def __init__(
        self, 
        api_key: str, 
        model_name: str = "gemini-robotics-er-1.5-preview",
        timeout: float = 90.0,
        max_retries: int = 3
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout
        self.max_retries = max_retries
        self.client = genai.Client(api_key=api_key)
        
        self.prompt_generic = """
Identify all interactable elements in this screenshot (e.g., buttons, tabs, input fields, icons, banners).
Provide a concise label and description for each.

Format: JSON list of objects with [bounding_box, label, description].
Bounding boxes: [y_min, x_min, y_max, x_max] normalized (0-1000).
Be exhaustive.
"""

        self.prompt_ingame = """
Identify all interactable elements in this Bingo Blitz screenshot.
CRITICAL:
1. BALL_HISTORY_BAR: Identify the ENTIRE horizontal area at the top where called balls appear (capture the full width).
2. POWERUP_BUTTON: Identify the power-up activation button.
3. BINGO_NUMBERS: Identify each individual number on the bingo cards. Label them as "Card X - Number Y".

Format: JSON list of objects with [bounding_box, label, description].
Bounding boxes: [y_min, x_min, y_max, x_max] normalized (0-1000).
Be exhaustive.
"""
    def _parse_gemini_response(self, response_text: str) -> List[Dict]:
        if not response_text or not response_text.strip():
            print("⚠️ Vision model returned an empty string.")
            return []
            
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
            
            if start_idx >= len(cleaned) or end_idx == 0 or start_idx > end_idx:
                print(f"⚠️ Could not find valid JSON boundaries in response.\nRaw Response Snippet: {response_text[:200]}...")
                return []
                
            json_str = cleaned[start_idx:end_idx+1]
            parsed = json.loads(json_str)
            
            if isinstance(parsed, dict):
                return [parsed]
            return parsed
        except json.JSONDecodeError as e:
            print(f"⚠️ Error parsing JSON: {e}\nRaw Response Snippet: {response_text[:200]}...")
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

    async def detect_elements(self, screenshot_path: str, is_in_game: bool = False) -> VisionDetectionResult:
        """
        Detect interactive elements in a screenshot with retry logic and timeout.
        
        Returns:
            VisionDetectionResult with success status, elements list, and error info
        """
        print(f"🔍 Vision detection")
        
        try:
            # Wrap entire detection with timeout
            result = await asyncio.wait_for(
                self._detect_elements_with_retry(screenshot_path, is_in_game),
                timeout=self.timeout
            )
            return result
        except asyncio.TimeoutError:
            error_msg = f"Vision detection timed out after {self.timeout}s"
            print(f"❌ [TIMEOUT] {error_msg}")
            return VisionDetectionResult(
                success=False,
                elements=[],
                error_message=error_msg,
                retry_count=self.max_retries
            )
        except Exception as e:
            error_msg = f"Unexpected error in vision detection: {e}"
            print(f"❌ [FATAL] {error_msg}")
            return VisionDetectionResult(
                success=False,
                elements=[],
                error_message=error_msg,
                retry_count=0
            )
    
    async def _detect_elements_with_retry(self, screenshot_path: str, is_in_game: bool = False) -> VisionDetectionResult:
        """Internal method with retry logic"""
        image = Image.open(screenshot_path)
        image_width, image_height = image.size
        
        with open(screenshot_path, 'rb') as f:
            image_bytes = f.read()
        
        last_error = None
        overall_start = time.time()
        
        for attempt in range(self.max_retries):
            try:
                start_time = time.time()
                
                active_prompt = self.prompt_ingame if is_in_game else self.prompt_generic
                
                response = await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=self.model_name,
                    contents=[
                        types.Part.from_bytes(
                            data=image_bytes,
                            mime_type='image/png',
                        ),
                        active_prompt
                    ],
                    config=types.GenerateContentConfig(
                        temperature=0.5,
                        thinking_config=types.ThinkingConfig(thinking_budget=0)
                    )
                )
                
                output = response.text
                elapsed = time.time() - start_time
                print(f"⏱️  Vision API response time: {elapsed:.2f}s")
                
                # Successfully got response, parse it
                detections = self._parse_gemini_response(output)
                results = self._build_results(detections, image_width, image_height)
                
                total_elapsed = time.time() - overall_start
                print(f"✅ Detected {len(results)} elements via vision")
                
                # Draw bounding boxes asynchronously
                if results:
                    asyncio.create_task(self._draw_bounding_boxes_async(screenshot_path, results))
                
                return VisionDetectionResult(
                    success=True,
                    elements=results,
                    retry_count=attempt,
                    elapsed_time=total_elapsed
                )
                
            except Exception as e:
                last_error = e
                attempt_num = attempt + 1
                
                if attempt_num < self.max_retries:
                    # Exponential backoff: 2^attempt seconds
                    wait_time = 2 ** attempt
                    print(f"⚠️  [RETRY {attempt_num}/{self.max_retries}] Vision API error: {e}")
                    print(f"   🔄 Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    error_msg = f"Vision API failed after {self.max_retries} attempts: {last_error}"
                    print(f"❌ [FATAL] {error_msg}")
                    
                    total_elapsed = time.time() - overall_start
                    return VisionDetectionResult(
                        success=False,
                        elements=[],
                        error_message=error_msg,
                        retry_count=attempt_num,
                        elapsed_time=total_elapsed
                    )
        
        # Should never reach here, but just in case
        return VisionDetectionResult(
            success=False,
            elements=[],
            error_message="Unknown error in retry loop",
            retry_count=self.max_retries
        )
    
    async def targeted_ocr(self, screenshot_path: str, bbox_norm: List[int], prompt: str) -> str:
        """Perform OCR on a specific cropped region using the VLM"""
        try:
            image = Image.open(screenshot_path)
            w, h = image.size
            
            # Crop using normalized coordinates [y1, x1, y2, x2]
            left = int(bbox_norm[1] * w / 1000)
            top = int(bbox_norm[0] * h / 1000)
            right = int(bbox_norm[3] * w / 1000)
            bottom = int(bbox_norm[2] * h / 1000)
            
            crop = image.crop((left, top, right, bottom))
            import io
            img_byte_arr = io.BytesIO()
            crop.save(img_byte_arr, format='PNG')
            image_bytes = img_byte_arr.getvalue()
            
            groq_key = os.getenv("GROQ_API_KEY")
            if groq_key:
                import base64
                import requests
                base64_image = base64.b64encode(image_bytes).decode('utf-8')
                headers = {
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                            ]
                        }
                    ],
                    "temperature": 0.0
                }
                
                loop = asyncio.get_event_loop()
                api_response = await loop.run_in_executor(
                    None, 
                    lambda: requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=10)
                )
                if api_response.status_code == 200:
                    data = api_response.json()
                    if "choices" in data and len(data["choices"]) > 0:
                        return data["choices"][0]["message"]["content"].strip()
                else:
                    print(f"⚠️ Groq API error: {api_response.status_code} - {api_response.text}")
            
            # Use explicit gemini-3-flash-preview since 1.5 is causing 404s on this v1beta
            fast_model = "gemini-3-flash-preview"
            
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=fast_model, 
                contents=[
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type='image/png',
                    ),
                    prompt
                ],
                config=types.GenerateContentConfig(
                    temperature=0.0, # Greedier for OCR
                )
            )
            
            if not response or getattr(response, 'text', None) is None:
                return ""
                
            return response.text.strip()
        except Exception as e:
            print(f"⚠️ Targeted VLM OCR failed: {e}")
            return ""

    async def check_bingo_state_groq(self, screenshot_path: str) -> bool:
        """Fast binary check using Groq Llama to see if we are actively in a bingo game"""
        try:
            image = Image.open(screenshot_path)
            # Try to shrink the image slightly to make it even faster/smaller for Groq
            image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            
            # Convert RGBA to RGB before saving as JPEG
            if image.mode in ('RGBA', 'P'):
                image = image.convert('RGB')
                
            import io
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='JPEG', quality=75)
            image_bytes = img_byte_arr.getvalue()
            
            groq_key = os.getenv("GROQ_API_KEY")
            if groq_key:
                import base64
                import requests
                base64_image = base64.b64encode(image_bytes).decode('utf-8')
                headers = {
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json"
                }
                
                prompt = "Look carefully at this image. Are there 1 or 2 bingo cards visible on the screen with numbers on them? This indicates we are in an active game of Bingo. Ignore any popups or menus blocking part of the screen. Reply ONLY 'YES' if 1 or 2 Bingo cards are clearly visible, otherwise reply 'NO'."
                
                payload = {
                    "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                            ]
                        }
                    ],
                    "temperature": 0.0,
                    "max_tokens": 10
                }
                
                loop = asyncio.get_event_loop()
                start_time = time.time()
                api_response = await loop.run_in_executor(
                    None, 
                    lambda: requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=5)
                )
                elapsed = time.time() - start_time
                
                if api_response.status_code == 200:
                    data = api_response.json()
                    if "choices" in data and len(data["choices"]) > 0:
                        ans = data["choices"][0]["message"]["content"].strip().upper()
                        print(f"⚡ Fast State Check (GroqVLM) [{elapsed:.2f}s]: {ans}")
                        return "YES" in ans
                else:
                    print(f"⚠️ Groq state check error: {api_response.status_code} - {api_response.text}")
            
            return False
            
        except Exception as e:
            print(f"⚠️ Fast state check failed: {e}")
            return False

    def _build_results(self, detections: List[Dict], image_width: int, image_height: int) -> List[Dict]:
        """Build results list from detections"""
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
        
        return results
