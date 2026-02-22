import imagehash
from PIL import Image

img1 = Image.open("src/agent/screenshots/bingo1.png")
img2 = Image.open("src/agent/screenshots/bingo2.png")

hash1 = imagehash.phash(img1)
hash2 = imagehash.phash(img2)

distance = hash1 - hash2

print(f"Hash 1:   {hash1}")
print(f"Hash 2:   {hash2}")
print(f"Distance: {distance}")

if distance < 15:
    print("→ Same screen (would SKIP annotation)")
else:
    print("→ Screen changed (would ANNOTATE)")

# For bingo blitz, we can take number as 20. if the dis > 20, we should annotate the screen.
