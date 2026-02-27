from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Literal

from dependencies import get_org
from models.organization import Organization
from repositories.game_repository import GameRepository

router = APIRouter(prefix="/api/orgs/{org_id}/games", tags=["Games"])
_repo = GameRepository()


class CreateGameRequest(BaseModel):
    name: str
    description: str = ""
    platform: Literal["android", "ios", "unity"] = "android"


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
        platform=request.platform,
    )
    return {
        "id": str(game.id),
        "org_id": game.org_id,
        "name": game.name,
        "description": game.description,
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
            "platform": g.platform,
            "created_at": g.created_at,
        }
        for g in games
    ]
