from beanie import Document
from pydantic import Field
from typing import Literal
from datetime import datetime


class Game(Document):
    org_id: str
    name: str
    description: str = ""
    gameplay: str = ""
    platform: Literal["android", "ios", "unity"] = "android"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "games"
        indexes = ["org_id"]
