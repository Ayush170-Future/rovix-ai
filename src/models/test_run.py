from beanie import Document
from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from datetime import datetime

class TestResult(BaseModel):
    test_id: str
    completion: bool
    failure_reason: str = "NA"
    verdict: Literal["pass", "fail"]
    comment: str = ""
    executed_at: datetime = Field(default_factory=datetime.utcnow)

class TestRun(Document):
    test_case_id: str  # Reference to TestCase
    device_udid: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"] = "queued"
    test_results: List[TestResult] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Stats
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    
    class Settings:
        name = "test_runs"
        indexes = ["test_case_id", "device_udid", "status", "started_at"]
