import os
import ast
import asyncio
from dotenv import load_dotenv

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from agent.vision_element_detector import VisionElementDetector

load_dotenv()

async def debug_vision(filename):
    vision_detector = VisionElementDetector(
        api_key=os.getenv("GOOGLE_API_KEY"),
        model_name=os.getenv("AGENT_MODEL", "gemini-1.5-flash"), # Use the faster model for targeted OCR
        timeout=60.0,
        max_retries=1
    )
    
    screenshot_path = os.path.join('src', 'agent', 'screenshots', filename)
    print(f"\n======================================")
    print(f"Testing Targeted VLM OCR on {filename}")
    
    ball_bbox_str = os.getenv("BINGO_CALLED_NUMBER_BBOX", "[65, 170, 145, 715]")
    b_norm = ast.literal_eval(ball_bbox_str)
    
    text = await vision_detector.targeted_ocr(
        screenshot_path,
        b_norm,
        "List all Bingo numbers visible in this Ball History Bar. Return ONLY the numbers separated by commas. Example: 32, 16, 69"
    )
    print(f"Targeted OCR Result: {text}")

if __name__ == "__main__":
    asyncio.run(debug_vision('step_26_frame_26.png'))
    asyncio.run(debug_vision('step_32_frame_32.png'))
    asyncio.run(debug_vision('step_10_frame_10.png'))
