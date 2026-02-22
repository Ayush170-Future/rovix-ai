import os
import ast
from PIL import Image, ImageDraw
import numpy as np
from dotenv import load_dotenv

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from agent.local_ocr import detect_bingo_numbers

load_dotenv()

def draw_and_test(filename):
    filepath = os.path.join('src', 'agent', 'screenshots', filename)
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
        
    img = Image.open(filepath)
    draw = ImageDraw.Draw(img)
    w, h = img.size
    
    # Check Ball BBOX
    ball_bbox_str = os.getenv("BINGO_CALLED_NUMBER_BBOX", "[65, 170, 145, 715]")
    b_norm = ast.literal_eval(ball_bbox_str)
    # ymin, xmin, ymax, xmax
    b_pixel = [int(b_norm[1]*w/1000), int(b_norm[0]*h/1000), int(b_norm[3]*w/1000), int(b_norm[2]*h/1000)]
    
    draw.rectangle([b_pixel[0], b_pixel[1], b_pixel[2], b_pixel[3]], outline="red", width=5)
    
    # Check Powerup BBOX
    p_bbox_str = os.getenv("BINGO_POWERUP_BBOX", "[30, 835, 195, 935]")
    p_norm = ast.literal_eval(p_bbox_str)
    p_pixel = [int(p_norm[1]*w/1000), int(p_norm[0]*h/1000), int(p_norm[3]*w/1000), int(p_norm[2]*h/1000)]
    
    draw.rectangle([p_pixel[0], p_pixel[1], p_pixel[2], p_pixel[3]], outline="green", width=5)
    
    out_path = f"annotated_test_{filename}"
    img.save(out_path)
    print(f"Saved annotated image to {out_path}")
    
    # Run OCR on the ball crop
    crop = img.crop(b_pixel)
    crop.save(f"crop_{filename}")
    
    numbers = detect_bingo_numbers(filepath, b_pixel)
    print(f"OCR Numbers for {filename}: {numbers}")
    
    # Powerup colors
    pcrop = img.crop(p_pixel)
    data = np.array(pcrop)
    avg_color = np.mean(data, axis=(0,1))
    print(f"Powerup Avg Color: R={avg_color[0]:.0f}, G={avg_color[1]:.0f}, B={avg_color[2]:.0f}")

if __name__ == "__main__":
    draw_and_test("step_10_frame_10.png")
