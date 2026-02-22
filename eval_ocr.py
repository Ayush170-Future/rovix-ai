import os
import ast
import time
import asyncio
import re
import base64
import requests
from dotenv import load_dotenv

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from agent.local_ocr import detect_bingo_numbers
from agent.vision_element_detector import VisionElementDetector

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GROQ_API_KEY = "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"

async def openrouter_ocr(filepath, bbox_norm, prompt, model_name):
    from PIL import Image
    import io
    image = Image.open(filepath)
    w, h = image.size
    left = int(bbox_norm[1] * w / 1000)
    top = int(bbox_norm[0] * h / 1000)
    right = int(bbox_norm[3] * w / 1000)
    bottom = int(bbox_norm[2] * h / 1000)
    
    crop = image.crop((left, top, right, bottom))
    img_byte_arr = io.BytesIO()
    crop.save(img_byte_arr, format='PNG')
    image_bytes = img_byte_arr.getvalue()
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model_name,
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
    try:
        response = await loop.run_in_executor(None, lambda: requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=15))
        if response.status_code == 200:
            data = response.json()
            if "choices" in data and len(data["choices"]) > 0:
                text = data["choices"][0]["message"]["content"]
                return text
        else:
            print(f"OpenRouter Error: HTTP {response.status_code} - {response.text}")
        return ""
    except Exception as e:
        print(f"OpenRouter Exception ({model_name}): {e}")
        return ""

async def groq_ocr(filepath, bbox_norm, prompt, model_name):
    from PIL import Image
    import io
    image = Image.open(filepath)
    w, h = image.size
    left = int(bbox_norm[1] * w / 1000)
    top = int(bbox_norm[0] * h / 1000)
    right = int(bbox_norm[3] * w / 1000)
    bottom = int(bbox_norm[2] * h / 1000)
    
    crop = image.crop((left, top, right, bottom))
    img_byte_arr = io.BytesIO()
    crop.save(img_byte_arr, format='PNG')
    image_bytes = img_byte_arr.getvalue()
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model_name,
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
    try:
        response = await loop.run_in_executor(None, lambda: requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=15))
        if response.status_code == 200:
            data = response.json()
            if "choices" in data and len(data["choices"]) > 0:
                text = data["choices"][0]["message"]["content"]
                return text
            else:
                print(f"Groq Malformed JSON: {data}")
        else:
            print(f"Groq Error: HTTP {response.status_code} - {response.text}")
        return ""
    except Exception as e:
        print(f"Groq Exception ({model_name}): {e}")
        return ""

async def run_evals():
    screenshots_dir = os.path.join('src', 'agent', 'screenshots')
    
    eval_set = {
        "step_1_frame_1.png": ["1", "19", "67", "3", "14", "13", "10"],
        "step_3_frame_3.png": ["5", "1", "19", "67", "3", "14", "13"],
        "step_13_frame_13.png": ["21", "69", "53", "55", "5", "1", "19"],
        "step_20_frame_20.png": ["43", "37", "21", "69", "53", "55", "5"]
    }
    sample_files = list(eval_set.keys())

    print(f"Starting OCR Evaluation across multiple models on {len(sample_files)} explicit screenshots...\n")
    
    ball_bbox_str = os.getenv("BINGO_CALLED_NUMBER_BBOX", "[65, 170, 145, 715]")
    b_norm = ast.literal_eval(ball_bbox_str)
    
    vision_detector = VisionElementDetector(
        api_key=os.getenv("GOOGLE_API_KEY"),
        model_name="gemini-3.0-flash", # fallback
        timeout=15.0,
        max_retries=1
    )
    
    models = {
        "Local Tesseract": "local",
        "Gemini 3.0 Flash": "google",
        "Qwen 2 VL 7B (OR)": "qwen/qwen-2-vl-7b-instruct",
        "GPT-4o-mini (OR)": "openai/gpt-4o-mini",
        "Llama 4 Scout (Groq)": "meta-llama/llama-4-scout-17b-16e-instruct",
        "Llama 4 Maverick (Groq)": "meta-llama/llama-4-maverick-17b-128e-instruct"
    }
    
    results = {m: [] for m in models.keys()}
    
    prompt = "List all Bingo numbers visible in this Ball History Bar. Return ONLY the numbers separated by commas. Example: 32, 16, 69"

    for filename in sample_files:
        filepath = os.path.join(screenshots_dir, filename)
        if not os.path.exists(filepath):
            print(f"Warning: {filepath} not found!")
            continue
            
        from PIL import Image
        w, h = Image.open(filepath).size
        b_pixel_bbox = [int(b_norm[1]*w/1000), int(b_norm[0]*h/1000), int(b_norm[3]*w/1000), int(b_norm[2]*h/1000)]
        
        print(f"--- Evaluating {filename} ---")
        ground_truth = eval_set[filename]
        print(f"Ground Truth: {ground_truth}")
        
        for name, m_id in models.items():
            start_time = time.time()
            res_text = ""
            
            try:
                if m_id == "local":
                    nums = detect_bingo_numbers(filepath, b_pixel_bbox)
                    elapsed = time.time() - start_time
                    results[name].append({"time": elapsed, "nums": nums, "gt": ground_truth})
                    print(f"[{name:25}] Time: {elapsed:.2f}s | Result: {nums}")
                    continue
                elif m_id == "google":
                    vlm_task = vision_detector.targeted_ocr(filepath, b_norm, prompt)
                    res_text = await asyncio.wait_for(vlm_task, timeout=12.0)
                elif "llama" in m_id:
                    res_text = await groq_ocr(filepath, b_norm, prompt, m_id)
                else:
                    res_text = await openrouter_ocr(filepath, b_norm, prompt, m_id)
            except Exception as e:
                res_text = ""
                
            nums = [n.strip() for n in re.findall(r'\d+', res_text)] if res_text else []
            elapsed = time.time() - start_time
            results[name].append({"time": elapsed, "nums": nums, "gt": ground_truth})
            print(f"[{name:25}] Time: {elapsed:.2f}s | Result: {nums}")
            
        print()
        
    print("\n--- Summary ---")
    for name in models.keys():
        if not results[name]: continue
        times = [r['time'] for r in results[name]]
        avg_time = sum(times) / len(times)
        
        # Calculate exactly how many numbers from ground truth were found
        total_gt = 0
        total_found = 0
        for r in results[name]:
            gt = set(r['gt'])
            pred = set(r['nums'])
            total_gt += len(gt)
            total_found += len(gt.intersection(pred))
            
        accuracy = (total_found / total_gt * 100) if total_gt > 0 else 0
        
        print(f"[{name:25}] Avg Time: {avg_time:.2f}s | Accuracy (Recall): {total_found}/{total_gt} ({accuracy:.1f}%)")

if __name__ == "__main__":
    asyncio.run(run_evals())
