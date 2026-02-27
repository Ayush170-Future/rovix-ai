from typing import List, Optional
from datetime import datetime
from models.execution_run import ExecutionRun, AssertionResult


class ExecutionRepository:
    async def create(
        self,
        scenario_id: str,
        game_id: str,
        org_id: str,
        device_udid: str,
        total_assertions: int,
    ) -> ExecutionRun:
        run = ExecutionRun(
            scenario_id=scenario_id,
            game_id=game_id,
            org_id=org_id,
            device_udid=device_udid,
            total_assertions=total_assertions,
        )
        await run.insert()
        return run

    async def find_by_id(self, run_id: str) -> Optional[ExecutionRun]:
        return await ExecutionRun.get(run_id)

    async def find_by_scenario(self, scenario_id: str) -> List[ExecutionRun]:
        return await ExecutionRun.find(
            ExecutionRun.scenario_id == scenario_id
        ).sort("-created_at").to_list()

    async def start(self, run_id: str) -> Optional[ExecutionRun]:
        run = await ExecutionRun.get(run_id)
        if not run:
            return None
        run.status = "running"
        run.started_at = datetime.utcnow()
        await run.save()
        return run

    async def complete(
        self, run_id: str, assertion_results: List[AssertionResult]
    ) -> Optional[ExecutionRun]:
        run = await ExecutionRun.get(run_id)
        if not run:
            return None
        run.status = "completed"
        run.assertion_results = assertion_results
        run.passed = sum(1 for r in assertion_results if r.verdict == "pass")
        run.failed = sum(1 for r in assertion_results if r.verdict == "fail")
        run.completed_at = datetime.utcnow()
        if run.started_at:
            run.duration_seconds = int((run.completed_at - run.started_at).total_seconds())
        await run.save()
        return run

    async def fail(self, run_id: str) -> Optional[ExecutionRun]:
        run = await ExecutionRun.get(run_id)
        if not run:
            return None
        run.status = "failed"
        run.completed_at = datetime.utcnow()
        if run.started_at:
            run.duration_seconds = int((run.completed_at - run.started_at).total_seconds())
        await run.save()
        return run

    async def mark_stale_as_failed(self) -> int:
        stale = await ExecutionRun.find(ExecutionRun.status == "running").to_list()
        for run in stale:
            run.status = "failed"
            run.completed_at = datetime.utcnow()
            await run.save()
        return len(stale)
