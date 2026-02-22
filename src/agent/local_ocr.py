import pytesseract
from PIL import Image, ImageOps, ImageEnhance
import os
import re
import numpy as np

class LocalOCRManager:
    def __init__(self, bbox=None):
        """
        bbox: [x_min, y_min, x_max, y_max] in pixels
        """
        self.bbox = bbox
        
    def set_bbox(self, bbox):
        self.bbox = bbox
        
    def _preprocess_image(self, image):
        # Goal: isolate the black numbers on the white circles, ignore everything else
        np_img = np.array(image)
        if np_img.shape[2] == 4:
            np_img = np_img[:, :, :3]
        
        gray = np.mean(np_img, axis=2)
        
        # 60 seems to be the sweet spot:
        # Black text is < 50
        # Colored balls are > 70
        # White circles are > 200
        binary = gray > 60
        
        from PIL import Image
        res = Image.fromarray(np.uint8(binary) * 255)
        
        # Scale x3 for OCR
        w, h = res.size
        res = res.resize((w*3, h*3), Image.LANCZOS)
        return res

    def get_numbers_from_screenshot(self, screenshot_path):
        if not self.bbox:
            return []
            
        try:
            image = Image.open(screenshot_path)
            # Full crop of the strip
            strip = image.crop((self.bbox[0], self.bbox[1], self.bbox[2], self.bbox[3]))
            
            # Divide into 8 segments (usual history length)
            # This prevents numbers from merging
            w, h = strip.size
            segment_w = w // 8
            all_numbers = []
            
            for i in range(8):
                left = i * segment_w
                right = (i + 1) * segment_w
                segment = strip.crop((left, 0, right, h))
                
                # Preprocess segment
                proc_segment = self._preprocess_image(segment)
                
                # OCR the segment
                # psm 8 to treat the segment as a single word
                text = pytesseract.image_to_string(proc_segment, config='-c tessedit_char_whitelist=0123456789 --psm 8')
                nums = re.findall(r'\d+', text)
                # Keep only valid bingo numbers (1-75 or 1-90)
                all_numbers.extend([n for n in nums if 1 <= int(n) <= 90])
            
            # Also try the whole strip just in case
            full_proc = self._preprocess_image(strip)
            text_full = pytesseract.image_to_string(full_proc, config='-c tessedit_char_whitelist=0123456789 --psm 7')
            nums_full = re.findall(r'\d+', text_full)
            all_numbers.extend([n for n in nums_full if 1 <= int(n) <= 90])

            # Deduplicate while preserving some order (though order is roughly left to right)
            seen = set()
            unique_numbers = []
            for n in all_numbers:
                if n not in seen:
                    unique_numbers.append(n)
                    seen.add(n)
            
            return unique_numbers
        except Exception as e:
            print(f"⚠️ Local OCR error: {e}")
            return []

    def is_powerup_ready(self, screenshot_path):
        if not self.bbox:
            return False
            
        try:
            image = Image.open(screenshot_path)
            cropped_image = image.crop((self.bbox[0], self.bbox[1], self.bbox[2], self.bbox[3]))
            data = np.array(cropped_image)
            
            # In Bingo Blitz, the unready powerup is very dark blue/gray
            # When ready, it turns bright pink/purple or yellow
            # Check for pixels with significant brightness (e.g., R > 100 or G > 100)
            bright_pixels = (data[:,:,0] > 100) | (data[:,:,1] > 100)
            bright_ratio = np.sum(bright_pixels) / bright_pixels.size
            
            return bright_ratio > 0.15
        except Exception as e:
            print(f"⚠️ Power-up detection error: {e}")
            return False

def detect_bingo_numbers(screenshot_path, bbox):
    ocr = LocalOCRManager(bbox)
    return ocr.get_numbers_from_screenshot(screenshot_path)

def detect_text(screenshot_path, bbox):
    ocr = LocalOCRManager(bbox)
    # Basic logic for general text
    try:
        image = Image.open(screenshot_path)
        crop = image.crop((bbox[0], bbox[1], bbox[2], bbox[3]))
        gray = crop.convert('L')
        text = pytesseract.image_to_string(gray, config='--psm 7')
        return text.strip()
    except:
        return ""

def is_powerup_ready(screenshot_path, bbox):
    ocr = LocalOCRManager(bbox)
    return ocr.is_powerup_ready(screenshot_path)
