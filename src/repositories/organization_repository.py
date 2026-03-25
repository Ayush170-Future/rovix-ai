from typing import Optional
from models.organization import Organization


class OrganizationRepository:
    async def create(self, name: str) -> Organization:
        org = Organization(name=name)
        await org.insert()
        return org

    async def find_by_id(self, org_id: str) -> Optional[Organization]:
        return await Organization.get(org_id)

    async def find_by_slug(self, slug: str) -> Optional[Organization]:
        return await Organization.find_one(Organization.slug == slug)
