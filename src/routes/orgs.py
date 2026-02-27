from fastapi import APIRouter
from pydantic import BaseModel
from repositories.organization_repository import OrganizationRepository

router = APIRouter(prefix="/api/orgs", tags=["Organizations"])
_repo = OrganizationRepository()


class CreateOrgRequest(BaseModel):
    name: str


@router.post("")
async def create_org(request: CreateOrgRequest):
    org = await _repo.create(name=request.name)
    return {
        "id": str(org.id),
        "name": org.name,
        "slug": org.slug,
        "created_at": org.created_at,
    }
