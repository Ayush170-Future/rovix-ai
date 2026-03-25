import secrets
from beanie import Document
from pydantic import Field
from datetime import datetime


class Organization(Document):
    name: str
    slug: str = Field(default_factory=lambda: "org_" + secrets.token_urlsafe(6))
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "organizations"
        indexes = ["slug"]
