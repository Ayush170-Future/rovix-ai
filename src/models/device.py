from beanie import Document
from pydantic import Field
from typing import Literal, Optional
from datetime import datetime


class Device(Document):
    """Registered Android target: USB-local, VM-hosted, or BrowserStack cloud profile.

    provider="local"       — physical device connected via USB to the machine running the backend.
                             APK is downloaded from GCS on the backend and installed via ADB.
                             agent_url is not used.
    provider="vm"          — device (real or emulator) on a remote VM; APK install is delegated to
                             the device_agent sidecar at agent_url (signed-URL handoff).
    provider="browserstack"— BrowserStack App Automate cloud session.
    """

    org_id: str
    device_id: str  # unique slug per org, e.g. "emulator-1"
    label: str
    # local/vm: ADB serial (e.g. "R38M20LHKEX" or "emulator-5554").
    # browserstack: synthetic unique id, e.g. "browserstack-pixel9"
    udid: str
    adb_host: str
    adb_port: int = 5037
    appium_url: str  # e.g. http://localhost:4723 or http://10.0.0.11:4723
    # VM only: URL of device_agent.py sidecar that downloads+installs the APK on the remote VM.
    # e.g. "http://10.0.0.11:8080" — see emulator/device_agent.py. Not used for local or browserstack.
    agent_url: Optional[str] = None
    provider: Literal["local", "vm", "browserstack"] = "local"
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
