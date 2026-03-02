import io
import json
import time
import asyncio
import os
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

try:
    from .logger import get_logger
except ImportError:
    from agent.logger import get_logger

logger = get_logger("agent.vision_element_detector")


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
        timeout: float = 45.0,
        max_retries: int = 3,
        max_image_size: Optional[Tuple[int, int]] = (2024, 2024),
        image_quality: int = 85
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_image_size = max_image_size
        self.image_quality = image_quality
        self.client = genai.Client(api_key=api_key)
        
        self.prompt = """
You are an expert UI detection system. Your task is to extract ALL INTERACTABLE elements (buttons, icons, text fields, tabs, sliders, game objects) from the provided screenshot.
Accuracy and exhaustive detection are critical for the downstream agent. Do not include static non-interactable decorations or background text.

Provide the exact bounding box and a concise classification for each element. The label should be 2-5 words describing WHAT it is and WHAT it does (e.g., "Settings menu icon", "Submit login button", "Red health potion").
To minimize latency, output ONLY a valid JSON list of objects with no markdown formatting. Do not provide detailed descriptions.

Output format:
[
  {
    "bounding_box": [y_min, x_min, y_max, x_max],
    "label": "2-5 word description of element and function"
  }
]

Bounding boxes must be in [y_min, x_min, y_max, x_max] format normalized between 0-1000.
"""

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
            logger.error(f"Error parsing JSON: {e}")
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
            logger.info(f"📸 Annotated image saved")
        except Exception as e:
            logger.warning(f"⚠️  Failed to save annotated image: {e}")

    async def detect_elements(self, screenshot_path: str) -> VisionDetectionResult:
        """
        Detect interactive elements in a screenshot with retry logic and timeout.
        
        Returns:
            VisionDetectionResult with success status, elements list, and error info
        """
        logger.info(f"🔍 Vision detection")
        
        try:
            # Wrap entire detection with timeout
            result = await asyncio.wait_for(
                self._detect_elements_with_retry(screenshot_path),
                timeout=self.timeout
            )
            return result
        except asyncio.TimeoutError:
            error_msg = f"Vision detection timed out after {self.timeout}s"
            logger.error(f"❌ [TIMEOUT] {error_msg}")
            return VisionDetectionResult(
                success=False,
                elements=[],
                error_message=error_msg,
                retry_count=self.max_retries
            )
        except Exception as e:
            error_msg = f"Unexpected error in vision detection: {e}"
            logger.error(f"❌ [FATAL] {error_msg}")
            return VisionDetectionResult(
                success=False,
                elements=[],
                error_message=error_msg,
                retry_count=0
            )
    
    def _prepare_image_for_api(self, screenshot_path: str) -> Tuple[bytes, str, int, int]:
        """Load image, optionally downscale for API, return (bytes, mime_type, original_width, original_height).
        Bbox conversion must use original dimensions so tap coordinates match the device screen."""
        image = Image.open(screenshot_path).convert("RGB")
        original_width, original_height = image.size
        
        if self.max_image_size:
            image = image.copy()
            image.thumbnail(self.max_image_size, Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=self.image_quality, optimize=True)
        return buf.getvalue(), "image/jpeg", original_width, original_height

    async def _detect_elements_with_retry(self, screenshot_path: str) -> VisionDetectionResult:
        """Internal method with retry logic"""
        image_bytes, mime_type, image_width, image_height = self._prepare_image_for_api(screenshot_path)
        
        last_error = None
        overall_start = time.time()
        
        for attempt in range(self.max_retries):
            try:
                start_time = time.time()
                
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=[
                        types.Part.from_bytes(
                            data=image_bytes,
                            mime_type=mime_type,
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
                logger.info(f"⏱️  Vision API response time: {elapsed:.2f}s")
                
                # Successfully got response, parse it
                detections = self._parse_gemini_response(output)
                results = self._build_results(detections, image_width, image_height)
                
                total_elapsed = time.time() - overall_start
                logger.info(f"✅ Detected {len(results)} elements via vision")
                
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
                    logger.warning(f"⚠️  [RETRY {attempt_num}/{self.max_retries}] Vision API error: {e}")
                    logger.warning(f"   🔄 Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    error_msg = f"Vision API failed after {self.max_retries} attempts: {last_error}"
                    logger.error(f"❌ [FATAL] {error_msg}")
                    
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
    
    def _build_results(self, detections: List[Dict], image_width: int, image_height: int) -> List[Dict]:
        """Build results list from detections. Prompt returns bounding_box + label only."""
        results = []
        for detection in detections:
            bbox_norm = detection.get('bounding_box', [0, 0, 0, 0])
            label = detection.get('label', 'Unknown')
            # New prompt omits description; use label for both for downstream compatibility
            description = detection.get('description') or label

            bbox_data = self._convert_normalized_bbox_to_pixels(bbox_norm, image_width, image_height)

            results.append({
                'name': label,
                'description': description,
                'screen_position': bbox_data['center'],
                'bounding_box': bbox_data['bbox']
            })
        return results
