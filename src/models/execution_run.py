from beanie import Document
from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from datetime import datetime


class AssertionResult(BaseModel):
    assertion_id: str
    verdict: Literal["pass", "fail"]
    completion: bool
    failure_reason: str = "NA"
    comment: str = ""
    screenshot_url: str = ""
    executed_at: datetime = Field(default_factory=datetime.utcnow)


class ExecutionRun(Document):
    scenario_id: str
    game_id: str
    org_id: str
    device_udid: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"] = "queued"
    assertion_results: List[AssertionResult] = []
    total_assertions: int = 0
    passed: int = 0
    failed: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "execution_runs"
        indexes = ["scenario_id", "org_id", "game_id", "status"]
