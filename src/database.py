import os
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from models.organization import Organization
from models.game import Game
from models.build import Build
from models.test_scenario import TestScenario
from models.execution_run import ExecutionRun
from models.execution_step import ExecutionStep
from agent.logger import get_logger

logger = get_logger("agent.database")

MONGODB_URL = os.getenv("MONGODB_URL")
DATABASE_NAME = os.getenv("DATABASE_NAME")

async def init_db():
    client = AsyncIOMotorClient(MONGODB_URL)
    await init_beanie(
        database=client[DATABASE_NAME],
        document_models=[
            Organization,
            Game,
            Build,
            TestScenario,
            ExecutionRun,
            ExecutionStep,
        ],
    )
    logger.info(f"Connected to MongoDB: {DATABASE_NAME}")


async def close_db():
    pass
    