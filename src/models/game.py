from beanie import Document
from pydantic import Field
from typing import Literal, Optional
from datetime import datetime


class Game(Document):
    org_id: str
    name: str
    description: str = ""
    gameplay: str = ""
    # Custom prompt sent to the vision element detector for this game.
    # When None, the detector's built-in default prompt is used.
    vision_prompt: Optional[str] = None
    platform: Literal["android", "ios", "unity"] = "android"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "games"
        indexes = ["org_id"]
