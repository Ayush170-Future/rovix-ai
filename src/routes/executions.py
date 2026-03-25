import asyncio
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.params import Query
from fastapi.responses import StreamingResponse
from google.cloud import storage as gcs

from dependencies import get_org
from models.organization import Organization
from repositories.execution_repository import ExecutionRepository
from repositories.execution_step_repository import ExecutionStepRepository

GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "rovix_ai_bucket")
_gcs_client = gcs.Client()
_gcs_bucket = _gcs_client.bucket(GCS_BUCKET_NAME)

router = APIRouter(prefix="/api/executions", tags=["Executions"])
_execution_repo = ExecutionRepository()
_step_repo = ExecutionStepRepository()


@router.get("/{execution_run_id}")
async def get_execution(execution_run_id: str, org: Organization = Depends(get_org)):
    run = await _execution_repo.find_by_id(execution_run_id)
    if not run or run.org_id != str(org.id):
        raise HTTPException(status_code=404, detail="Execution not found")

    return {
        "id": str(run.id),
        "scenario_id": run.scenario_id,
        "build_id": run.build_id,
        "device_udid": run.device_udid,
        "status": run.status,
        "total_assertions": run.total_assertions,
        "passed": run.passed,
        "failed": run.failed,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "duration_seconds": run.duration_seconds,
        "failure_reason": run.failure_reason,
        "assertion_results": [r.model_dump() for r in run.assertion_results],
    }


@router.get("/{execution_run_id}/steps")
async def get_execution_steps(
    execution_run_id: str,
    since: Optional[datetime] = Query(default=None),
    org: Organization = Depends(get_org),
):
    run = await _execution_repo.find_by_id(execution_run_id)
    if not run or run.org_id != str(org.id):
        raise HTTPException(status_code=404, detail="Execution not found")

    if since:
        steps = await _step_repo.find_since(execution_run_id, since)
    else:
        steps = await _step_repo.find_by_run(execution_run_id)

    return [
        {
            "id": str(s.id),
            "step_number": s.step_number,
            "timestamp": s.timestamp,
            "screenshot_url": s.screenshot_url,
            "game_state_summary": s.game_state_summary,
            "reason": s.reason,
            "actions_taken": s.actions_taken,
            "todo_snapshot": s.todo_snapshot,
            "assertion_results_reported": [r.model_dump() for r in s.assertion_results_reported],
            "token_usage": s.token_usage.model_dump(),
        }
        for s in steps
    ]


@router.get("/{execution_run_id}/steps/{step_num}/screenshot")
async def get_step_screenshot(
    execution_run_id: str,
    step_num: int,
    org: Organization = Depends(get_org),
):
    run = await _execution_repo.find_by_id(execution_run_id)
    if not run or run.org_id != str(org.id):
        raise HTTPException(status_code=404, detail="Execution not found")

    blob_name = f"screenshots/{execution_run_id}/step_{step_num}.png"
    try:
        blob = _gcs_bucket.blob(blob_name)
        data = await asyncio.to_thread(blob.download_as_bytes)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Screenshot not found: {e}")

    return StreamingResponse(
        iter([data]),
        media_type="image/png",
        headers={"Cache-Control": "max-age=86400"},
    )
