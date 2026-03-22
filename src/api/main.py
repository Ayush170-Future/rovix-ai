import os
import sys
from contextlib import asynccontextmanager

from dotenv import load_dotenv

from fastapi import FastAPI

load_dotenv()
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database import init_db
from services.execution_service import ExecutionService
from routes.orgs import router as orgs_router
from routes.games import router as games_router
from routes.builds import router as builds_router
from routes.test_scenarios import router as scenarios_router
from routes.executions import router as executions_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    execution_service = ExecutionService()
    await execution_service.mark_stale_runs_failed()
    app.state.execution_service = execution_service
    yield


app = FastAPI(title="AltTester Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(orgs_router)
app.include_router(games_router)
app.include_router(builds_router)
app.include_router(scenarios_router)
app.include_router(executions_router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


# ── Legacy SDK endpoints (Unity event-driven mode) ───────────────────────────
# These remain untouched until the SDK flow is migrated to the new session model.

class SwipeRequest(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    duration: float = 0.5


SDK_ENABLED = os.getenv("SDK_ENABLED", "true").lower() == "true"

if SDK_ENABLED:
    from agent.service import (
        GamePauseEvent,
        frame_controller,
        agent_handler,
        action_handler,
    )

    @app.post("/ai/resume")
    async def resume_game():
        frame_controller.resume()
        return {"status": "ok"}

    @app.post("/ai/on-pause")
    async def on_game_pause(event: GamePauseEvent):
        await agent_handler(event)
        return {"status": "ok"}

    @app.post("/ai/swipe")
    async def swipe_operation(request: SwipeRequest):
        await action_handler.execute_swipe(
            request.x1, request.y1, request.x2, request.y2, request.duration
        )
        return {"status": "ok"}


def start_server(host: str = "0.0.0.0", port: int = 8000):
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start_server()
