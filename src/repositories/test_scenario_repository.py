from typing import List, Literal, Optional
from datetime import datetime
from models.test_scenario import TestScenario, Step, Assertion

# TODO: Error handling and logging is missing.

class TestScenarioRepository:
    async def create(
        self,
        org_id: str,
        game_id: str,
        title: str,
        precondition: str = "",
        gameplay: str = "",
        validations: str = "",
    ) -> TestScenario:
        scenario = TestScenario(
            org_id=org_id,
            game_id=game_id,
            title=title,
            precondition=precondition,
            gameplay=gameplay,
            validations=validations,
        )
        await scenario.insert()
        return scenario

    async def find_by_id(self, scenario_id: str) -> Optional[TestScenario]:
        return await TestScenario.get(scenario_id)

    async def find_by_game(self, game_id: str) -> List[TestScenario]:
        return await TestScenario.find(TestScenario.game_id == game_id).to_list()

    async def update_steps_and_assertions(
        self,
        scenario_id: str,
        steps: List[Step],
        assertions: List[Assertion],
        status: Literal["steps_generated", "steps_validated"],
    ) -> Optional[TestScenario]:
        scenario = await TestScenario.get(scenario_id)
        if not scenario:
            return None
        scenario.steps = steps
        scenario.assertions = assertions
        scenario.status = status
        scenario.updated_at = datetime.utcnow()
        await scenario.save()
        return scenario

    async def update_status(
        self,
        scenario_id: str,
        status: Literal["draft", "steps_generated", "steps_validated", "running", "completed", "failed"],
    ) -> Optional[TestScenario]:
        scenario = await TestScenario.get(scenario_id)
        if not scenario:
            return None
        scenario.status = status
        scenario.updated_at = datetime.utcnow()
        await scenario.save()
        return scenario
