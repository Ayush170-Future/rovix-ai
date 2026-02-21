from beanie import Document
from pydantic import BaseModel, Field
from typing import List
from datetime import datetime
from uuid import uuid4

class Test(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    objective: str

class TestCase(Document):
    name: str
    description: str
    tests: List[Test] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Settings:
        name = "test_cases"
        indexes = ["name"]