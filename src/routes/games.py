from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Literal, Optional

from dependencies import get_org
from models.organization import Organization
from repositories.game_repository import GameRepository

router = APIRouter(prefix="/api/orgs/{org_id}/games", tags=["Games"])
_repo = GameRepository()


class CreateGameRequest(BaseModel):
    name: str
    description: str = ""
    gameplay: str = ""
    platform: Literal["android", "ios", "unity"] = "android"


class UpdateGameRequest(BaseModel):
    description: Optional[str] = None
    gameplay: Optional[str] = None


@router.post("")
async def create_game(
    org_id: str,
    request: CreateGameRequest,
    org: Organization = Depends(get_org),
):
    if str(org.id) != org_id:
        raise HTTPException(status_code=403, detail="Access denied")
    game = await _repo.create(
        org_id=org_id,
        name=request.name,
        description=request.description,
        gameplay=request.gameplay,
        platform=request.platform,
    )
    return {
        "id": str(game.id),
        "org_id": game.org_id,
        "name": game.name,
        "description": game.description,
        "gameplay": game.gameplay,
        "platform": game.platform,
        "created_at": game.created_at,
    }


@router.get("")
async def list_games(org_id: str, org: Organization = Depends(get_org)):
    if str(org.id) != org_id:
        raise HTTPException(status_code=403, detail="Access denied")
    games = await _repo.find_by_org(org_id)
    return [
        {
            "id": str(g.id),
            "org_id": g.org_id,
            "name": g.name,
            "description": g.description,
            "gameplay": g.gameplay,
            "platform": g.platform,
            "created_at": g.created_at,
        }
        for g in games
    ]


@router.patch("/{game_id}")
async def patch_game(
    org_id: str,
    game_id: str,
    request: UpdateGameRequest,
    org: Organization = Depends(get_org),
):
    if str(org.id) != org_id:
        raise HTTPException(status_code=403, detail="Access denied")

    game = await _repo.find_by_id(game_id)
    if not game or game.org_id != org_id:
        raise HTTPException(status_code=404, detail="Game not found")

    if request.description is None and request.gameplay is None:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one field: description or gameplay",
        )

    game = await _repo.update_fields(
        game,
        description=request.description,
        gameplay=request.gameplay,
    )

    return {
        "id": str(game.id),
        "org_id": game.org_id,
        "name": game.name,
        "description": game.description,
        "gameplay": game.gameplay,
        "platform": game.platform,
        "created_at": game.created_at,
    }
