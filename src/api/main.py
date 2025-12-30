import os
import sys
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import redis
import numpy as np
from PIL import Image

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from agent.service import (
    GamePauseEvent,
    frame_controller,
    driver,
    image_file_to_base64,
    game_state_messages,
    game_state_lock,
    structured_model,
    agent_handler
)

app = FastAPI(title="Unity AI Agent Server")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify Unity's origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "message": "AI Agent Server is running"}


@app.post("/ai/resume")
async def resume_game():
    """Resume the game"""
    frame_controller.resume()
    return {"status": "ok", "message": "Game resumed"}


@app.post("/ai/on-pause")
async def on_game_pause(event: GamePauseEvent):
    """Called by Unity when the game pauses. Fetches screenshots from Redis, saves them, calls LLM, and executes actions."""
    await agent_handler(event)
    return {"status": "ok"}


def start_server(host="0.0.0.0", port=8000):
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start_server(host="0.0.0.0", port=8000)

