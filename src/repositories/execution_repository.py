from typing import List, Optional
from datetime import datetime
from models.execution_run import ExecutionRun, AssertionResult


class ExecutionRepository:
    async def create(
        self,
        scenario_id: str,
        game_id: str,
        build_id: Optional[str],
        org_id: str,
        device_udid: str,
        total_assertions: int,
    ) -> ExecutionRun:
        run = ExecutionRun(
            scenario_id=scenario_id,
            game_id=game_id,
            build_id=build_id,
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

    async def find_by_game(self, game_id: str) -> List[ExecutionRun]:
        return await ExecutionRun.find(
            ExecutionRun.game_id == game_id
        ).sort("-created_at").to_list()

    async def start(self, run_id: str) -> Optional[ExecutionRun]:
        run = await ExecutionRun.get(run_id)
        if not run:
            return None
        run.status = "running"
        run.started_at = datetime.utcnow()
        await run.save()
        return run

    async def append_assertion_results_delta(
        self, run_id: str, new_results: List[AssertionResult]
    ) -> None:
        """Atomically append assertion rows and bump pass/fail counts (one MongoDB update).

        Safe under overlapping writes: uses $push / $inc, not read-modify-write on the full array.
        """
        if not new_results:
            return
        docs = [r.model_dump(mode="python") for r in new_results]
        delta_pass = sum(1 for r in new_results if r.verdict == "pass")
        delta_fail = sum(1 for r in new_results if r.verdict == "fail")
        await ExecutionRun.find_one(ExecutionRun.id == run_id).update(
            {
                "$push": {"assertion_results": {"$each": docs}},
                "$inc": {"passed": delta_pass, "failed": delta_fail},
            }
        )

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

    async def fail(self, run_id: str, failure_reason: Optional[str] = None) -> Optional[ExecutionRun]:
        run = await ExecutionRun.get(run_id)
        if not run:
            return None
        run.status = "failed"
        run.completed_at = datetime.utcnow()
        if failure_reason is not None:
            run.failure_reason = failure_reason
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
