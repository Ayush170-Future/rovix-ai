from typing import List, Literal, Optional
from models.game import Game


class GameRepository:
    async def create(
        self,
        org_id: str,
        name: str,
        description: str = "",
        platform: Literal["android", "ios", "unity"] = "android",
    ) -> Game:
        game = Game(org_id=org_id, name=name, description=description, platform=platform)
        await game.insert()
        return game

    async def find_by_id(self, game_id: str) -> Optional[Game]:
        return await Game.get(game_id)

    async def find_by_org(self, org_id: str) -> List[Game]:
        return await Game.find(Game.org_id == org_id).to_list()
