from typing import List, Literal, Optional
from models.game import Game


class GameRepository:
    async def create(
        self,
        org_id: str,
        name: str,
        description: str = "",
        gameplay: str = "",
        vision_prompt: Optional[str] = None,
        platform: Literal["android", "ios", "unity"] = "android",
    ) -> Game:
        game = Game(
            org_id=org_id,
            name=name,
            description=description,
            gameplay=gameplay,
            vision_prompt=vision_prompt,
            platform=platform,
        )
        await game.insert()
        return game

    async def find_by_id(self, game_id: str) -> Optional[Game]:
        return await Game.get(game_id)

    async def find_by_org(self, org_id: str) -> List[Game]:
        return await Game.find(Game.org_id == org_id).to_list()

    async def update_fields(
        self,
        game: Game,
        *,
        description: Optional[str] = None,
        gameplay: Optional[str] = None,
        vision_prompt: Optional[str] = None,
    ) -> Game:
        if description is not None:
            game.description = description
        if gameplay is not None:
            game.gameplay = gameplay
        if vision_prompt is not None:
            game.vision_prompt = vision_prompt
        await game.save()
        return game
