from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import List

from dependencies import get_org
from models.organization import Organization
from models.test_scenario import Step, Assertion
from repositories.game_repository import GameRepository
from repositories.test_scenario_repository import TestScenarioRepository
from repositories.execution_repository import ExecutionRepository
from services.step_generation_service import generate_steps
from services.execution_service import ExecutionService

router = APIRouter(tags=["Test Scenarios"])
_scenario_repo = TestScenarioRepository()
_game_repo = GameRepository()
_execution_repo = ExecutionRepository()


class CreateScenarioRequest(BaseModel):
    title: str
    precondition: str = ""
    gameplay: str = ""
    validations: str = ""


class SaveStepsRequest(BaseModel):
    steps: List[Step]
    assertions: List[Assertion]


class ExecuteRequest(BaseModel):
    device_udid: str


@router.post("/api/games/{game_id}/scenarios")
async def create_scenario(
    game_id: str,
    request: CreateScenarioRequest,
    org: Organization = Depends(get_org),
):
    game = await _game_repo.find_by_id(game_id)
    if not game or game.org_id != str(org.id):
        raise HTTPException(status_code=404, detail="Game not found")

    scenario = await _scenario_repo.create(
        org_id=str(org.id),
        game_id=game_id,
        title=request.title,
        precondition=request.precondition,
        gameplay=request.gameplay,
        validations=request.validations,
    )
    return _scenario_response(scenario)


@router.get("/api/games/{game_id}/scenarios")
async def list_scenarios(game_id: str, org: Organization = Depends(get_org)):
    game = await _game_repo.find_by_id(game_id)
    if not game or game.org_id != str(org.id):
        raise HTTPException(status_code=404, detail="Game not found")
    scenarios = await _scenario_repo.find_by_game(game_id)
    return [_scenario_response(s) for s in scenarios]

# TODO: Add pagination and error handling.
@router.get("/api/games/{game_id}/executions")
async def list_game_executions(game_id: str, org: Organization = Depends(get_org)):
    game = await _game_repo.find_by_id(game_id)
    if not game or game.org_id != str(org.id):
        raise HTTPException(status_code=404, detail="Game not found")
    runs = await _execution_repo.find_by_game(game_id)
    distinct_scenario_ids = list({r.scenario_id for r in runs})
    scenarios = await _scenario_repo.find_by_ids(distinct_scenario_ids)
    title_by_scenario_id = {str(s.id): s.title for s in scenarios}

    return [
        {
            "id": str(r.id),
            "scenario_id": r.scenario_id,
            "scenario_title": title_by_scenario_id.get(r.scenario_id, ""),
            "device_udid": r.device_udid,
            "status": r.status,
            "total_assertions": r.total_assertions,
            "passed": r.passed,
            "failed": r.failed,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "duration_seconds": r.duration_seconds,
            "failure_reason": r.failure_reason,
        }
        for r in runs
    ]


@router.get("/api/scenarios/{scenario_id}")
async def get_scenario(scenario_id: str, org: Organization = Depends(get_org)):
    scenario = await _scenario_repo.find_by_id(scenario_id)
    if not scenario or scenario.org_id != str(org.id):
        raise HTTPException(status_code=404, detail="Scenario not found")
    return _scenario_response(scenario)


@router.post("/api/scenarios/{scenario_id}/generate-steps")
async def generate_scenario_steps(scenario_id: str, org: Organization = Depends(get_org)):
    scenario = await _scenario_repo.find_by_id(scenario_id)
    if not scenario or scenario.org_id != str(org.id):
        raise HTTPException(status_code=404, detail="Scenario not found")

    game = await _game_repo.find_by_id(scenario.game_id)
    generated = await generate_steps(
        precondition=scenario.precondition,
        gameplay=scenario.gameplay,
        validations=scenario.validations,
        game_description=game.description if game else "",
    )

    await _scenario_repo.update_steps_and_assertions(
        scenario_id=scenario_id,
        steps=generated.steps,
        assertions=generated.assertions,
        status="steps_generated",
    )

    return {
        "steps": [s.model_dump() for s in generated.steps],
        "assertions": [a.model_dump() for a in generated.assertions],
        "summary": generated.summary,
    }


@router.put("/api/scenarios/{scenario_id}/steps")
async def save_steps(
    scenario_id: str,
    request: SaveStepsRequest,
    org: Organization = Depends(get_org),
):
    scenario = await _scenario_repo.find_by_id(scenario_id)
    if not scenario or scenario.org_id != str(org.id):
        raise HTTPException(status_code=404, detail="Scenario not found")

    updated = await _scenario_repo.update_steps_and_assertions(
        scenario_id=scenario_id,
        steps=request.steps,
        assertions=request.assertions,
        status="steps_validated",
    )
    return _scenario_response(updated)


@router.post("/api/scenarios/{scenario_id}/execute")
async def execute_scenario(
    scenario_id: str,
    request: ExecuteRequest,
    http_request: Request,
    org: Organization = Depends(get_org),
):
    scenario = await _scenario_repo.find_by_id(scenario_id)
    if not scenario or scenario.org_id != str(org.id):
        raise HTTPException(status_code=404, detail="Scenario not found")

    if scenario.status not in ("steps_validated", "completed", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Scenario must have validated steps before execution (current status: {scenario.status})",
        )

    game = await _game_repo.find_by_id(scenario.game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    execution_service: ExecutionService = http_request.app.state.execution_service
    if execution_service.is_device_busy(request.device_udid):
        raise HTTPException(status_code=409, detail="Device is already running an execution")

    run = await _execution_repo.create(
        scenario_id=scenario_id,
        game_id=scenario.game_id,
        org_id=str(org.id),
        device_udid=request.device_udid,
        total_assertions=len(scenario.assertions),
    )

    await execution_service.start_execution(
        run_id=str(run.id),
        scenario=scenario,
        game=game,
        device_udid=request.device_udid,
    )

    return {
        "execution_run_id": str(run.id),
        "status": run.status,
        "created_at": run.created_at,
    }


def _scenario_response(scenario) -> dict:
    return {
        "id": str(scenario.id),
        "org_id": scenario.org_id,
        "game_id": scenario.game_id,
        "title": scenario.title,
        "precondition": scenario.precondition,
        "gameplay": scenario.gameplay,
        "validations": scenario.validations,
        "status": scenario.status,
        "steps": [s.model_dump() for s in scenario.steps],
        "assertions": [a.model_dump() for a in scenario.assertions],
        "created_at": scenario.created_at,
        "updated_at": scenario.updated_at,
    }
