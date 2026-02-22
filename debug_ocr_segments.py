import os
import ast
import re
from PIL import Image, ImageEnhance
import numpy as np
import pytesseract
from dotenv import load_dotenv

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

load_dotenv()

def filter_image(image):
    np_img = np.array(image)
    if np_img.shape[2] == 4:
        np_img = np_img[:, :, :3]
    
    gray = np.mean(np_img, axis=2)
    
    # 60 seems to be the sweet spot:
    # Black text is < 50
    # Colored balls are > 70
    # White circles are > 200
    binary = gray > 60
    
    res = Image.fromarray(np.uint8(binary) * 255)
    
    # Scale x3 for OCR
    w, h = res.size
    res = res.resize((w*3, h*3), Image.LANCZOS)
    return res

def debug_ocr_segments(filename, y_offset=0, y_shrink=0):
    filepath = os.path.join('src', 'agent', 'screenshots', filename)
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
        
    img = Image.open(filepath)
    w, h = img.size
    
    ball_bbox_str = os.getenv("BINGO_CALLED_NUMBER_BBOX", "[65, 170, 145, 715]")
    b_norm = ast.literal_eval(ball_bbox_str)
    
    y1 = int(b_norm[0]*h/1000)
    x1 = int(b_norm[1]*w/1000)
    y2 = int(b_norm[2]*h/1000)
    x2 = int(b_norm[3]*w/1000)
    
    # Apply tighter Y bounds
    y1 += y_offset
    y2 -= y_shrink
    
    b_pixel = [x1, y1, x2, y2]
    
    crop = img.crop(b_pixel)
    
    # Try the segments
    segments = 8
    segment_width = crop.width // segments
    
    all_numbers = []
    
    for i in range(segments):
        left = i * segment_width
        right = (i + 1) * segment_width if i < segments - 1 else crop.width
        segment = crop.crop((left, 0, right, crop.height))
        
        proc_segment = filter_image(segment)
        
        # psm 8 = Treat the image as a single word.
        text = pytesseract.image_to_string(proc_segment, config='-c tessedit_char_whitelist=0123456789 --psm 8')
        nums = re.findall(r'\d+', text)
        valid_nums = [n for n in nums if 1 <= int(n) <= 90]
        if valid_nums:
            all_numbers.extend(valid_nums)
            print(f"Segment {i} OCR: '{text.strip()}' -> Nums: {valid_nums}")
            
    # Full strip with psm 7 (single line)
    full_proc = filter_image(crop)
    text_full = pytesseract.image_to_string(full_proc, config='-c tessedit_char_whitelist=0123456789 --psm 7')
    nums_full = re.findall(r'\d+', text_full)
    valid_nums_full = [n for n in nums_full if 1 <= int(n) <= 90]
    all_numbers.extend(valid_nums_full)
    print(f"Full Strip OCR: '{text_full.strip()}' -> Nums: {valid_nums_full}")
    
    seen = set()
    unique = [n for n in all_numbers if not (n in seen or seen.add(n))]
    print(f"Final Unique Numbers for {filename}: {unique}\n")

if __name__ == "__main__":
    debug_ocr_segments("step_26_frame_26.png", y_offset=18, y_shrink=18)
    debug_ocr_segments("step_32_frame_32.png", y_offset=18, y_shrink=18)
    debug_ocr_segments("step_10_frame_10.png", y_offset=18, y_shrink=18)
