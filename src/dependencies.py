from fastapi import Header, HTTPException
from models.organization import Organization
from repositories.organization_repository import OrganizationRepository

_org_repo = OrganizationRepository()


async def get_org(x_org_slug: str = Header(...)) -> Organization:
    org = await _org_repo.find_by_slug(x_org_slug)
    if not org:
        raise HTTPException(status_code=401, detail="Invalid organization slug")
    return org
