import imagehash
from PIL import Image

img1 = Image.open("src/agent/screenshots/step_2_frame_2.png")
img2 = Image.open("src/agent/screenshots/step_67_frame_67.png")

hash1 = imagehash.dhash(img1)
hash2 = imagehash.dhash(img2)

distance = hash1 - hash2

print(f"Hash 1:   {hash1}")
print(f"Hash 2:   {hash2}")
print(f"Distance: {distance}")

if distance < 15:
    print("→ Same screen (would SKIP annotation)")
else:
    print("→ Screen changed (would ANNOTATE)")

# 15 seems fine here.