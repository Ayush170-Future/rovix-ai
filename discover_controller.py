from alttester import AltDriver, By
import os
from dotenv import load_dotenv

load_dotenv()

app_name = os.getenv("ALT_TESTER_APP_NAME", "Jai Mata Di")
print(f"Connecting to {app_name}...")
driver = AltDriver(app_name=app_name)

print("\n--- Searching for 'frameController' by component type ---")
try:
    # Try searching by component type directly
    # The assembly name was seen in tester.py as Unity1a3ce3d71daf1f0d629c.Comrovixagentzero
    objects = driver.find_objects(By.COMPONENT, "frameController")
    print(f"Found {len(objects)} objects with frameController component")
    for obj in objects:
        print(f"Object: {obj.name} (ID: {obj.id})")
except Exception as e:
    print(f"Error: {e}")

driver.stop()
