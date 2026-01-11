from alttester import AltDriver, By
import os
from dotenv import load_dotenv

load_dotenv()

app_name = os.getenv("ALT_TESTER_APP_NAME", "Jai Mata Di")
print(f"Connecting to {app_name}...")
driver = AltDriver(app_name=app_name)

print("\n--- Searching for components by pattern ---")
all_objs = driver.find_objects(By.NAME, "*")
for obj in all_objs:
    try:
        comps = obj.get_all_components()
        for comp in comps:
            c_name = comp.get('componentName', '').lower()
            if "frame" in c_name or "test" in c_name or "rovix" in c_name:
                print(f"Found match on Object '{obj.name}' (ID: {obj.id}):")
                print(f"  - Component: {comp}")
    except:
        pass

driver.stop()
