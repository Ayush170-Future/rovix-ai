import os
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from models.test_case import TestCase
from models.test_run import TestRun
from agent.logger import get_logger

logger = get_logger("agent.database")

MONGODB_URL = os.getenv("MONGODB_URL")
DATABASE_NAME = os.getenv("DATABASE_NAME")

async def init_db():
    client = AsyncIOMotorClient(MONGODB_URL)
    await init_beanie(
        database=client[DATABASE_NAME],
        document_models=[
            TestCase,
            TestRun,
            # Add other Document models here as you create them
        ]
    )
    
    logger.info(f"Connected to MongoDB database: {DATABASE_NAME}")


async def close_db():
    pass