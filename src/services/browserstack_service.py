import os
import requests
from requests.auth import HTTPBasicAuth
from agent.logger import get_logger

logger = get_logger("agent.services.browserstack")

class BrowserstackService:
    _local_instance = None

    @classmethod
    def upload_app(cls, apk_path: str) -> str:
        """Upload an APK to BrowserStack and return the bs:// URL."""
        username = os.getenv("BROWSERSTACK_USERNAME")
        access_key = os.getenv("BROWSERSTACK_ACCESS_KEY")
        
        if not username or not access_key:
            raise RuntimeError("BROWSERSTACK_USERNAME and BROWSERSTACK_ACCESS_KEY must be set in the environment.")
            
        logger.info(f"☁️ Uploading {apk_path} to BrowserStack...")
        
        url = "https://api-cloud.browserstack.com/app-automate/upload"
        
        with open(apk_path, "rb") as f:
            files = {"file": f}
            response = requests.post(url, files=files, auth=HTTPBasicAuth(username, access_key))
            
        if response.status_code != 200:
            raise RuntimeError(f"BrowserStack App Upload Failed: {response.text}")
            
        data = response.json()
        app_url = data.get("app_url")
        if not app_url:
            raise RuntimeError(f"Expected app_url in response but got: {data}")
            
        logger.info(f"✅ Successfully uploaded to BrowserStack: {app_url}")
        return app_url

    @classmethod
    def start_local(cls):
        """Start the BrowserStack Local binary tunnel for accessing localhost backends."""
        if cls._local_instance is not None and cls._local_instance.isRunning():
            return
            
        try:
            from browserstack.local import Local
        except ImportError:
            raise RuntimeError("browserstack-local package is not installed.")
            
        access_key = os.getenv("BROWSERSTACK_ACCESS_KEY")
        if not access_key:
            raise RuntimeError("BROWSERSTACK_ACCESS_KEY must be set to start BrowserStack Local.")
            
        logger.info("🔧 Starting BrowserStack Local tunnel...")
        
        bs_local_args = {
            "key": access_key,
            "force": "true",
            "forcelocal": "true"
        }
        
        try:
            cls._local_instance = Local()
            cls._local_instance.start(**bs_local_args)
            
            if cls._local_instance.isRunning():
                logger.info("✅ BrowserStack Local is running.")
            else:
                raise RuntimeError("BrowserStack Local failed to start.")
        except Exception as e:
             raise RuntimeError(f"Error starting BrowserStack Local: {e}")

    @classmethod
    def stop_local(cls):
        if cls._local_instance is not None:
            logger.info("🛑 Stopping BrowserStack Local...")
            cls._local_instance.stop()
            cls._local_instance = None
