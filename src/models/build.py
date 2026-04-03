from beanie import Document
from pydantic import Field
from typing import Literal, Optional
from datetime import datetime


class Build(Document):
    org_id: str
    game_id: str
    platform: Literal["android", "ios", "unity"]
    artifact_type: Literal["apk", "aab", "ipa", "zip"] = "apk"
    object_key: str
    bucket_name: str
    version_name: str = ""
    version_code: Optional[int] = None
    build_number: str = ""
    channel: Literal["dev", "qa", "staging", "prod"] = "qa"
    file_size_bytes: Optional[int] = None
    checksum_sha256: str = ""
    status: Literal["uploading", "ready", "failed", "archived"] = "uploading"
    upload_error: str = ""
    uploaded_by: str = ""
    # Optional; if missing, resolved at execution via `aapt dump badging` after download.
    android_app_package: Optional[str] = None
    android_app_activity: Optional[str] = None
    browserstack_app_url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "builds"
        indexes = [
            "org_id",
            "game_id",
            "platform",
            "status",
            "channel",
            [("game_id", 1), ("platform", 1), ("created_at", -1)],
        ]
