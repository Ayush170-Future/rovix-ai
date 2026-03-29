from beanie import Document
from pydantic import Field
from typing import Literal
from datetime import datetime


class Device(Document):
    """Registered Android target (emulator or physical) with per-device ADB/Appium endpoints."""

    org_id: str
    device_id: str  # unique slug per org, e.g. "emulator-1"
    label: str
    udid: str  # ADB serial, e.g. emulator-5554
    adb_host: str
    adb_port: int = 5037
    appium_url: str  # e.g. http://10.0.0.11:4723
    platform: Literal["android"] = "android"
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "devices"
        indexes = [
            [("org_id", 1), ("device_id", 1)],
            [("org_id", 1), ("udid", 1)],
        ]
