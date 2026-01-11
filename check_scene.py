from alttester import AltDriver, By
import os
from dotenv import load_dotenv

load_dotenv()

app_name = os.getenv("ALT_TESTER_APP_NAME", "Jai Mata Di")
print(f"Connecting to {app_name}...")
driver = AltDriver(app_name=app_name)

print(f"Current Scene: {driver.get_current_scene()}")

driver.stop()
