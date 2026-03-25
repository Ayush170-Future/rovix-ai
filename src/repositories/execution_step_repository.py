from typing import List, Optional
from datetime import datetime
from models.execution_step import ExecutionStep, TokenUsage
from models.execution_run import AssertionResult


class ExecutionStepRepository:
    async def create(
        self,
        execution_run_id: str,
        step_number: int,
        screenshot_url: str = "",
        game_state_summary: str = "",
        reason: str = "",
        actions_taken: Optional[List[dict]] = None,
        todo_snapshot: Optional[List[dict]] = None,
        assertion_results_reported: Optional[List[AssertionResult]] = None,
        token_usage: Optional[TokenUsage] = None,
    ) -> ExecutionStep:
        step = ExecutionStep(
            execution_run_id=execution_run_id,
            step_number=step_number,
            screenshot_url=screenshot_url,
            game_state_summary=game_state_summary,
            reason=reason,
            actions_taken=actions_taken or [],
            todo_snapshot=todo_snapshot or [],
            assertion_results_reported=assertion_results_reported or [],
            token_usage=token_usage or TokenUsage(),
        )
        await step.insert()
        return step

    async def find_by_run(self, execution_run_id: str) -> List[ExecutionStep]:
        return await ExecutionStep.find(
            ExecutionStep.execution_run_id == execution_run_id
        ).sort("timestamp").to_list()

    async def find_since(
        self, execution_run_id: str, since: datetime
    ) -> List[ExecutionStep]:
        return await ExecutionStep.find(
            ExecutionStep.execution_run_id == execution_run_id,
            ExecutionStep.timestamp > since,
        ).sort("timestamp").to_list()
