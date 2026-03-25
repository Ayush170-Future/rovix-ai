from beanie import Document
from pydantic import BaseModel, Field
from typing import List
from datetime import datetime
from pymongo import IndexModel, ASCENDING

from models.execution_run import AssertionResult


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class ExecutionStep(Document):
    execution_run_id: str
    step_number: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    screenshot_url: str = ""
    game_state_summary: str = ""
    reason: str = ""
    actions_taken: List[dict] = []
    todo_snapshot: List[dict] = []
    assertion_results_reported: List[AssertionResult] = []
    token_usage: TokenUsage = Field(default_factory=TokenUsage)

    class Settings:
        name = "execution_steps"
        indexes = [
            IndexModel(
                [("execution_run_id", ASCENDING), ("timestamp", ASCENDING)],
                name="run_timeline",
            ),
            IndexModel([("step_number", ASCENDING)], name="step_number"),
        ]
