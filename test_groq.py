import requests
from dotenv import load_dotenv
import base64
import os

GROQ_API_KEY = "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"

headers = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json"
}

# Use a specific screenshot
filepath = "src/agent/screenshots/step_10_frame_10.png"
if not os.path.exists(filepath):
    print("Test image not found.")
    exit()

with open(filepath, "rb") as image_file:
    base64_image = base64.b64encode(image_file.read()).decode('utf-8')

for model in ["meta-llama/llama-4-scout-17b-16e-instruct", "meta-llama/llama-4-maverick-17b-128e-instruct"]:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "List any numbers in this image."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                ]
            }
        ],
        "temperature": 0.0
    }

    try:
        print(f"Testing {model}...")
        response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
        print(f"Status: {response.status_code}")
        print(response.json())
        print("-" * 20)
    except Exception as e:
        print(e)
