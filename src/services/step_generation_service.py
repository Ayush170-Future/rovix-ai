import os
import asyncio
from typing import List
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI

from models.test_scenario import Step, Assertion

# TODO: Add error handling and logging.

class GeneratedScenario(BaseModel):
    steps: List[Step]
    assertions: List[Assertion]
    summary: str


def _build_prompt(
    precondition: str, gameplay: str, validations: str, game_description: str
) -> str:
    return f"""You are a QA engineer converting a test scenario into structured executable steps and assertions.

<game-context>
{game_description or "A mobile game application."}
</game-context>

<precondition>
{precondition or "App is installed and launched."}
</precondition>

<gameplay>
{gameplay}
</gameplay>

<validations>
{validations}
</validations>

Produce a JSON object with:
- steps: ordered executable steps, each with id (string), content (string), step_type ("action" or "verify"), order (int), dependencies (list of step ids that must complete first)
- assertions: named checkable conditions, each with id (like "1.1"), title (≤5 words), description (exact condition to validate)
- summary: one sentence describing what is tested

ACTION steps perform operations: navigate, tap, swipe, scroll, wait.
VERIFY steps check state: assert element visible, confirm text, validate outcome.
Each step must be atomic. Each VERIFY step should correspond to one assertion."""


async def generate_steps(
    precondition: str,
    gameplay: str,
    validations: str,
    game_description: str = "",
) -> GeneratedScenario:
    model = ChatGoogleGenerativeAI(
        model="gemini-3-flash-preview",
        temperature=0.3,
        api_key=os.getenv("GOOGLE_API_KEY"),
    )
    structured = model.with_structured_output(
        schema=GeneratedScenario.model_json_schema(),
        method="json_schema",
    )
    prompt = _build_prompt(precondition, gameplay, validations, game_description)
    result = await asyncio.to_thread(structured.invoke, prompt)
    return GeneratedScenario(**result) if isinstance(result, dict) else result
