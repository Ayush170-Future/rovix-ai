import os
import ast
from PIL import Image
import numpy as np
from dotenv import load_dotenv

# Add src to path so we can import local_ocr
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from agent.local_ocr import detect_bingo_numbers, is_powerup_ready

load_dotenv()

def debug_shot(filename):
    print(f"\n{'='*50}\nDEBUGGING: {filename}\n{'='*50}")
    filepath = os.path.join('src', 'agent', 'screenshots', filename)
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
        
    img = Image.open(filepath)
    w, h = img.size
    
    # 1. Powerup bbox check
    powerup_bbox_str = os.getenv("BINGO_POWERUP_BBOX")
    if powerup_bbox_str:
        p_bbox_norm = ast.literal_eval(powerup_bbox_str)
        p_pixel_bbox = [int(p_bbox_norm[1]*w/1000), int(p_bbox_norm[0]*h/1000), int(p_bbox_norm[3]*w/1000), int(p_bbox_norm[2]*h/1000)]
        
        # Test original logic
        is_ready = is_powerup_ready(filepath, p_pixel_bbox)
        print(f"Original Powerup Ready: {is_ready}")
        
        # Debug colors
        crop = img.crop(p_pixel_bbox)
        data = np.array(crop)
        # Check green ratio
        green_pixels_old = (data[:,:,1] > data[:,:,0] + 40) & (data[:,:,1] > data[:,:,2] + 40)
        green_ratio_old = np.sum(green_pixels_old) / green_pixels_old.size
        print(f"Old Green ratio (must be > 0.10): {green_ratio_old:.4f}")
        
        # What if it's lightning (yellow/blue)? In the image, empty is blue/gray. Ready is what color?
        # Let's print average RGB
        avg_color = np.mean(data, axis=(0,1))
        print(f"Average color of powerup region (R, G, B, A): {avg_color}")
        
    # 2. Ball OCR check
    ball_bbox_str = os.getenv("BINGO_CALLED_NUMBER_BBOX")
    if ball_bbox_str:
        b_bbox_norm = ast.literal_eval(ball_bbox_str)
        b_pixel_bbox = [int(b_bbox_norm[1]*w/1000), int(b_bbox_norm[0]*h/1000), int(b_bbox_norm[3]*w/1000), int(b_bbox_norm[2]*h/1000)]
        
        numbers = detect_bingo_numbers(filepath, b_pixel_bbox)
        print(f"Local OCR Ball Numbers: {numbers}")

if __name__ == "__main__":
    debug_shot("step_0_frame_0.png")
    debug_shot("step_10_frame_10.png")
    debug_shot("step_50_frame_50.png")
