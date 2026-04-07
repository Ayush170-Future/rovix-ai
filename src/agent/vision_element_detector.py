import io
import json
import math
import time
import asyncio
import os
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types
from typing import List, Dict, Optional, Tuple, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from services.views import Action

try:
    from .logger import get_logger
except ImportError:
    from agent.logger import get_logger

logger = get_logger("agent.vision_element_detector")

DEFAULT_VISION_PROMPT = """You are an expert UI detection system. Your task is to extract ALL INTERACTABLE elements (buttons, icons, text fields, tabs, sliders, game objects) from the provided screenshot.
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
        self.prompt = DEFAULT_VISION_PROMPT

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
            return None

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

    async def detect_elements(self, screenshot_path: str, prompt: Optional[str] = None) -> VisionDetectionResult:
        logger.info(f"🔍 Vision detection")

        try:
            # Wrap entire detection with timeout
            result = await asyncio.wait_for(
                self._detect_elements_with_retry(screenshot_path, prompt=prompt),
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

    async def _detect_elements_with_retry(self, screenshot_path: str, prompt: Optional[str] = None) -> VisionDetectionResult:
        """Internal method with retry logic"""
        image_bytes, mime_type, image_width, image_height = self._prepare_image_for_api(screenshot_path)
        active_prompt = prompt if prompt else self.prompt

        last_error = None
        overall_start = time.time()

        for attempt in range(self.max_retries):
            try:
                start_time = time.time()

                # Use native async client so asyncio.wait_for timeout works and we avoid thread pool
                response = await self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=[
                        types.Part.from_bytes(
                            data=image_bytes,
                            mime_type=mime_type,
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
                logger.info(f"⏱️  Vision API response time: {elapsed:.2f}s")

                detections = self._parse_gemini_response(output)
                if detections is None:
                    # Parse failure is deterministic; no point retrying
                    total_elapsed = time.time() - overall_start
                    return VisionDetectionResult(
                        success=False,
                        elements=[],
                        error_message="Vision API returned invalid JSON",
                        retry_count=0,
                        elapsed_time=total_elapsed
                    )
                results = self._build_results(detections, image_width, image_height)
                total_elapsed = time.time() - overall_start
                logger.info(f"✅ Detected {len(results)} elements via vision")

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


def annotate_actions(image_path: str, actions: "List[Action]") -> "Optional[str]":
    """
    Draw action overlays onto a copy saved as ``<base>_annotated.png``.
      - click       → yellow filled dot
      - swipe       → orange arrow from start to end
      - multi_swipe → orange polyline with arrowhead on the last segment
    wait / todo_write / key_press are skipped.

    Returns the path to the annotated file, or None when there are no
    visual actions or the source file is missing.
    """
    visual_actions = [
        a for a in (actions or [])
        if a.action_type in ("click", "swipe", "multi_swipe")
    ]
    if not visual_actions:
        logger.info("📍 No visual actions — skipping annotation")
        return None
    if not os.path.exists(image_path):
        logger.warning(f"⚠️  annotate_actions: source file missing: {image_path}")
        return None

    try:
        img = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        w, h = img.size

        dot_r = max(18, int(min(w, h) * 0.012))
        line_w = max(6, int(min(w, h) * 0.005))
        head_size = dot_r * 2

        drawn = 0
        for action in visual_actions:
            if action.action_type == "click" and action.x is not None and action.y is not None:
                _draw_dot(draw, action.x, action.y, dot_r)
                drawn += 1

            elif action.action_type == "swipe":
                if all(v is not None for v in [action.x, action.y, action.end_x, action.end_y]):
                    _draw_arrow(draw, action.x, action.y, action.end_x, action.end_y, line_w, head_size)
                    drawn += 1

            elif action.action_type == "multi_swipe" and action.waypoints:
                pts = [tuple(p) for p in action.waypoints if len(p) == 2]
                if len(pts) >= 2:
                    for i in range(len(pts) - 1):
                        if i == len(pts) - 2:
                            _draw_arrow(draw, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], line_w, head_size)
                        else:
                            draw.line([pts[i], pts[i + 1]], fill=(255, 200, 0), width=line_w)
                    drawn += 1

        base_name = os.path.splitext(image_path)[0]
        output_path = f"{base_name}_action_annotated.png"
        img.save(output_path, format="PNG")
        logger.info(f"✏️  Saved annotated screenshot ({drawn} action(s)) → {output_path}")
        return output_path
    except Exception as e:
        logger.warning(f"⚠️  Failed to annotate actions on screenshot: {e}")
        return None


def _draw_dot(draw: ImageDraw.ImageDraw, x: int, y: int, r: int) -> None:
    draw.ellipse([x - r - 3, y - r - 3, x + r + 3, y + r + 3], fill="black")
    draw.ellipse([x - r, y - r, x + r, y + r], fill=(255, 220, 0))


def _draw_arrow(
    draw: ImageDraw.ImageDraw,
    x1: int, y1: int,
    x2: int, y2: int,
    line_w: int,
    head_size: int,
) -> None:
    draw.line([(x1, y1), (x2, y2)], fill=(255, 80, 0), width=line_w)

    angle = math.atan2(y2 - y1, x2 - x1)
    spread = math.pi / 6  # 30°
    lx = x2 - head_size * math.cos(angle - spread)
    ly = y2 - head_size * math.sin(angle - spread)
    rx = x2 - head_size * math.cos(angle + spread)
    ry = y2 - head_size * math.sin(angle + spread)
    draw.polygon([(x2, y2), (lx, ly), (rx, ry)], fill=(255, 80, 0))

    # Start dot
    draw.ellipse([x1 - line_w, y1 - line_w, x1 + line_w, y1 + line_w], fill=(255, 80, 0))
