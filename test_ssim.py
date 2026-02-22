import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim

img1 = np.array(Image.open("src/agent/screenshots/bingo1.png").convert("L"))
img2 = np.array(Image.open("src/agent/screenshots/bingo1.png").convert("L"))

# Resize to same dimensions if they differ
if img1.shape != img2.shape:
    h = min(img1.shape[0], img2.shape[0])
    w = min(img1.shape[1], img2.shape[1])
    img1 = img1[:h, :w]
    img2 = img2[:h, :w]

score, diff = ssim(img1, img2, full=True, data_range=255)

print(f"SSIM Score: {score:.4f}  (1.0 = identical, 0.0 = completely different)")

if score > 0.95:
    print("→ Same screen (would SKIP annotation)")
elif score > 0.80:
    print("→ Minor changes, probably same screen (consider SKIP)")
else:
    print("→ Screen changed (would ANNOTATE)")
