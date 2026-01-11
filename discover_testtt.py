from alttester import AltDriver, By
import os
from dotenv import load_dotenv

load_dotenv()

app_name = os.getenv("ALT_TESTER_APP_NAME", "Jai Mata Di")
print(f"Connecting to {app_name}...")
driver = AltDriver(app_name=app_name)

print("\n--- Searching for 'testtt' by component type ---")
try:
    objects = driver.find_objects(By.COMPONENT, "testtt")
    print(f"Found {len(objects)} objects with testtt component")
    for obj in objects:
        print(f"Object: {obj.name} (ID: {obj.id})")
except Exception as e:
    print(f"Error: {e}")

driver.stop()
