# routes/api.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from repositories.test_case_repository import TestCaseRepository
from repositories.test_run_repository import TestRunRepository
from models.test_case import Test
from models.test_run import TestRun

router = APIRouter(prefix="/api", tags=["Testing"])

test_case_repo = TestCaseRepository()
test_run_repo = TestRunRepository()

class CreateTestCaseRequest(BaseModel):
    name: str
    description: str
    tests: List[Test]

class TriggerTestRunRequest(BaseModel):
    test_case_id: str
    device_udid: str


@router.post("/test-cases")
async def create_test_case(request: CreateTestCaseRequest):
    test_case = await test_case_repo.create(
        name=request.name,
        description=request.description,
        tests=request.tests
    )
    return {
        "id": str(test_case.id),
        "name": test_case.name,
        "description": test_case.description,
        "tests": test_case.tests,
        "created_at": test_case.created_at
    }

@router.post("/test-runs")
async def trigger_test_run(request: TriggerTestRunRequest):
    """Start a new test run for a test case on a device"""
    # Verify test case exists
    test_case = await test_case_repo.find_by_id(request.test_case_id)
    if not test_case:
        raise HTTPException(status_code=404, detail="Test case not found")
    
    # Create test run
    test_run = await test_run_repo.create(
        test_case_id=request.test_case_id,
        device_udid=request.device_udid
    )
    
    # Start the run
    await test_run_repo.start_run(str(test_run.id), len(test_case.tests))
    
    # TODO: Trigger your agent service here to execute tests asynchronously
    # from services.service import GameTestAgentService
    # agent_service = GameTestAgentService()
    # asyncio.create_task(agent_service.execute_test_run(str(test_run.id)))
    
    return {
        "test_run_id": str(test_run.id),
        "test_case_id": test_run.test_case_id,
        "device_udid": test_run.device_udid,
        "status": test_run.status,
        "started_at": test_run.started_at
    }


# 3. Get Test Run Status
@router.get("/test-runs/{test_run_id}")
async def get_test_run_status(test_run_id: str):
    """Fetch the status and results of a test run"""
    test_run = await test_run_repo.find_by_id(test_run_id)
    if not test_run:
        raise HTTPException(status_code=404, detail="Test run not found")
    
    return {
        "test_run_id": str(test_run.id),
        "test_case_id": test_run.test_case_id,
        "device_udid": test_run.device_udid,
        "status": test_run.status,
        "started_at": test_run.started_at,
        "completed_at": test_run.completed_at,
        "duration_seconds": test_run.duration_seconds,
        "stats": {
            "total_tests": test_run.total_tests,
            "passed": test_run.passed_tests,
            "failed": test_run.failed_tests
        },
        "test_results": test_run.test_results
    }