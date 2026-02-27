from beanie import Document
from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from datetime import datetime
from uuid import uuid4


class Step(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    content: str
    step_type: Literal["action", "verify"]
    order: int
    dependencies: List[str] = []


class Assertion(BaseModel):
    id: str
    title: str
    description: str


class TestScenario(Document):
    org_id: str
    game_id: str
    title: str
    precondition: str = ""
    gameplay: str = ""
    validations: str = ""
    steps: List[Step] = []
    assertions: List[Assertion] = []
    status: Literal[
        "draft",
        "steps_generated",
        "steps_validated",
        "running",
        "completed",
        "failed",
    ] = "draft"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "test_scenarios"
        indexes = ["org_id", "game_id"]
