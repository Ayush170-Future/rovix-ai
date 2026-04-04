from beanie import Document
from pydantic import Field
from typing import Literal, Optional
from datetime import datetime


class Device(Document):
    """Registered Android target: local ADB/Waydroid or BrowserStack cloud profile."""

    org_id: str
    device_id: str  # unique slug per org, e.g. "emulator-1"
    label: str
    # local: ADB serial (e.g. emulator-5554). browserstack: synthetic id, e.g. "browserstack-pixel9"
    udid: str
    adb_host: str
    adb_port: int = 5037
    appium_url: str  # e.g. http://10.0.0.11:4723
    # When set, the backend delegates APK download+install to this agent running on the VM.
    # e.g. "http://10.0.0.11:8080" — see emulator/device_agent.py
    agent_url: Optional[str] = None
    provider: Literal["local", "browserstack"] = "local"
    # BrowserStack App Automate (when provider == "browserstack"; names must match BS device list)
    bs_device_name: Optional[str] = None
    bs_os_version: Optional[str] = None
    platform: Literal["android"] = "android"
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "devices"
        indexes = [
            [("org_id", 1), ("device_id", 1)],
            [("org_id", 1), ("udid", 1)],
        ]
