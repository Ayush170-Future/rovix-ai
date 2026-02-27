import os
import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from langchain_google_genai import ChatGoogleGenerativeAI

from agent.context import ContextService
from agent.prompts import SYSTEM_PROMPT_WITH_TODO
from agent.logger import get_logger
from services.views import Action, AgentOutput, TestResult
from models.test_scenario import TestScenario, Step
from models.game import Game
from models.execution_run import AssertionResult
from models.execution_step import TokenUsage
from repositories.execution_repository import ExecutionRepository
from repositories.execution_step_repository import ExecutionStepRepository
from tools.todo_management import todo_write_handler, get_todo_list_for_context
from tools.todo_management.todo_service import TodoPersistenceService

logger = get_logger("execution_service")

USE_APPIUM = os.getenv("USE_APPIUM", "false").lower() == "true"
POLLING_INTERVAL = float(os.getenv("POLLING_INTERVAL", "2.5"))
MAX_STEPS = int(os.getenv("MAX_STEPS", "1000"))


# ── Session state ────────────────────────────────────────────────────────────

@dataclass
class AgentSession:
    execution_run_id: str
    session_id: str
    device_udid: str
    context_service: ContextService
    force_annotate: bool = False
    step_count: int = 0
    collected_results: List[AssertionResult] = field(default_factory=list)


# ── Service ──────────────────────────────────────────────────────────────────

class ExecutionService:
    def __init__(self):
        self._sessions: Dict[str, AgentSession] = {}
        self._execution_repo = ExecutionRepository()
        self._step_repo = ExecutionStepRepository()
        self._structured_model = self._init_model()
        self._action_executor = self._init_action_executor()
        self._vision_detector = self._init_vision_detector()

    def _init_model(self):
        model = ChatGoogleGenerativeAI(
            model="gemini-3-flash-preview",
            temperature=1.0,
            api_key=os.getenv("GOOGLE_API_KEY"),
        )
        return model.with_structured_output(
            schema=AgentOutput.model_json_schema(),
            method="json_schema",
            include_raw=True,
        )

    def _init_action_executor(self):
        if USE_APPIUM:
            from agent.appium_manager import AppiumManager
            return AppiumManager(
                appium_url=os.getenv("APPIUM_URL", "http://localhost:4723"),
                device_name=os.getenv("DEVICE_NAME"),
                udid=os.getenv("DEVICE_UDID"),
                app_package=os.getenv("APP_PACKAGE"),
                app_activity=os.getenv("APP_ACTIVITY"),
                screenshot_timeout=float(os.getenv("SCREENSHOT_TIMEOUT", "10.0")),
                screenshot_max_retries=int(os.getenv("SCREENSHOT_MAX_RETRIES", "3")),
            )
        from agent.adb_manager import ADBManager
        return ADBManager(
            host="127.0.0.1",
            port=5037,
            screenshot_timeout=float(os.getenv("SCREENSHOT_TIMEOUT", "10.0")),
            screenshot_max_retries=int(os.getenv("SCREENSHOT_MAX_RETRIES", "3")),
        )

    def _init_vision_detector(self):
        from agent.vision_element_detector import VisionElementDetector
        return VisionElementDetector(
            api_key=os.getenv("GOOGLE_API_KEY"),
            model_name="gemini-robotics-er-1.5-preview",
            timeout=float(os.getenv("VISION_TIMEOUT", "45.0")),
            max_retries=int(os.getenv("VISION_MAX_RETRIES", "3")),
        )

    def is_device_busy(self, device_udid: str) -> bool:
        return device_udid in self._sessions

    async def mark_stale_runs_failed(self) -> None:
        count = await self._execution_repo.mark_stale_as_failed()
        if count:
            logger.info(f"Marked {count} stale execution run(s) as failed on startup")

    async def start_execution(
        self,
        run_id: str,
        scenario: TestScenario,
        game: Game,
        device_udid: str,
    ) -> None:
        session_id = run_id
        context_svc = ContextService(system_prompt=SYSTEM_PROMPT_WITH_TODO, keep_full_steps=4)
        context_svc._ensure_session(
            session_id,
            game_description=game.description or "A mobile game application.",
            gameplay_details="",
            test_plan=self._build_test_plan(scenario),
        )

        session = AgentSession(
            execution_run_id=run_id,
            session_id=session_id,
            device_udid=device_udid,
            context_service=context_svc,
        )
        self._sessions[device_udid] = session
        self._seed_todo_list(session, scenario.steps)

        await self._execution_repo.start(run_id)
        asyncio.create_task(self._run_execution(session, scenario))

    def _build_test_plan(self, scenario: TestScenario) -> str:
        lines = [f"Scenario: {scenario.title}", ""]
        for a in scenario.assertions:
            lines.append(f"{a.id} {a.title}: {a.description}")
        return "\n".join(lines)

    def _seed_todo_list(self, session: AgentSession, steps: List[Step]) -> None:
        todos = [
            {
                "id": step.id,
                "content": step.content,
                "status": "pending",
                "todo_type": step.step_type,
                "dependencies": step.dependencies,
            }
            for step in sorted(steps, key=lambda s: s.order)
        ]
        todo_write_handler(json.dumps({"merge": False, "todos": todos}), session.session_id)

    async def _run_execution(self, session: AgentSession, scenario: TestScenario) -> None:
        logger.info(f"Starting execution {session.execution_run_id} on device {session.device_udid}")
        try:
            for step_num in range(MAX_STEPS):
                session.step_count = step_num
                end_game = await self._handle_step(session, step_num)
                if end_game:
                    break
                await asyncio.sleep(POLLING_INTERVAL)

            await self._execution_repo.complete(session.execution_run_id, session.collected_results)
            logger.info(
                f"Execution {session.execution_run_id} completed — "
                f"{len(session.collected_results)} assertion result(s)"
            )
        except Exception as e:
            logger.error(f"Execution {session.execution_run_id} failed: {e}", exc_info=True)
            await self._execution_repo.fail(session.execution_run_id)
        finally:
            self._cleanup_session(session.device_udid)

    async def _handle_step(self, session: AgentSession, step_num: int) -> bool:
        logger.info(f"\n{'='*80}\n🎮 Step {step_num} | Run {session.execution_run_id[:8]}\n{'='*80}")

        todo_list = get_todo_list_for_context(session.session_id)
        logger.info(f"\n{'='*60}\n📋 CURRENT TODO LIST:\n{'='*60}\n{todo_list}\n{'='*60}")

        screenshots_dir = os.path.join("screenshots", session.execution_run_id)
        os.makedirs(screenshots_dir, exist_ok=True)
        screenshot_path = os.path.join(screenshots_dir, f"step_{step_num}.png")

        result = self._action_executor.get_screenshot(screenshot_path)
        if not result.success:
            logger.error(
                f"❌ Screenshot capture failed: {result.error_message} "
                f"(type: {result.error_type}, retries: {result.retry_count})"
            )
            return False

        logger.info(f"💾 step_{step_num}.png (captured in {result.elapsed_time:.2f}s)")
        if result.retry_count > 0:
            logger.warning(f"🔄 Screenshot required {result.retry_count} retry(ies)")

        await session.context_service.add_new_step(
            session_id=session.session_id,
            screenshot_path=screenshot_path,
            available_actions={},
            step=step_num,
            frame=step_num,
            vision_detector=self._vision_detector,
            action_handler=None,
            sdk_enabled=False,
            force_annotate=session.force_annotate,
        )

        messages = session.context_service.get_messages_for_llm(session.session_id)
        logger.info("🤖 Getting agent decision from LLM...")
        start = time.time()
        raw_response = await asyncio.to_thread(self._structured_model.invoke, messages)
        elapsed = time.time() - start
        logger.info(f"⏱️  LLM response time: {elapsed:.2f}s")

        output = self._parse_response(raw_response)
        token_usage = self._extract_token_usage(raw_response)

        logger.info("✅ Agent decision received")
        logger.info(f"   📝 Game state: {output.game_state_summary}")
        logger.info(f"   🤔 Reasoning: {output.reason}")
        logger.info(f"   🔍 Force annotate: {output.force_annotate}")
        logger.info(f"   🎯 Actions count: {len(output.actions)}")
        logger.info(f"   🏁 End game: {output.end_game}")
        logger.info(f"   📋 Test results: {output.test_results}")
        logger.info(
            f"   📊 Token usage — Input: {token_usage.input_tokens}, "
            f"Output: {token_usage.output_tokens}, Total: {token_usage.total_tokens}"
        )

        session.force_annotate = output.force_annotate
        session.context_service.add_ai_response(session.session_id, output)

        step_assertion_results = []
        for r in output.test_results:
            assertion_result = AssertionResult(
                assertion_id=r.test_case_id,
                verdict=r.virdict,
                completion=r.completion,
                failure_reason=r.failure_reason,
                comment=r.comment,
                screenshot_url=screenshot_path,  # TODO: swap for S3 URL
            )
            session.collected_results.append(assertion_result)
            step_assertion_results.append(assertion_result)

        await self._step_repo.create(
            execution_run_id=session.execution_run_id,
            step_number=step_num,
            screenshot_url=screenshot_path,  # TODO: swap for S3 URL after upload
            game_state_summary=output.game_state_summary,
            reason=output.reason,
            actions_taken=[a.model_dump() for a in output.actions],
            todo_snapshot=self._get_todo_snapshot(session.session_id),
            assertion_results_reported=step_assertion_results,
            token_usage=token_usage,
        )
        logger.info(f"💾 ExecutionStep {step_num} written to DB")

        if output.end_game:
            logger.info("🛑 Agent signaled end of execution")
            return True

        await self._execute_actions(session, output.actions)
        session.context_service.cleanup_old_messages(session.session_id)
        return False

    async def _execute_actions(self, session: AgentSession, actions: List[Action]) -> None:
        total = len(actions)
        for idx, action in enumerate(actions, 1):
            if action.action_type == "todo_write":
                import json as _json
                result = todo_write_handler(action.todo_input, session.session_id)
                result_dict = _json.loads(result)
                if result_dict.get("success"):
                    logger.info(
                        f"   todo_write ({idx}/{total}): updated {result_dict.get('totalTasks')} tasks "
                        f"{result_dict.get('taskCounts')}"
                    )
                else:
                    logger.warning(f"   todo_write ({idx}/{total}): failed — {result_dict.get('message')}")
                session.context_service.add_todo_result(session.session_id, result)
            else:
                logger.info(
                    f"   action ({idx}/{total}): {action.action_type} "
                    f"x={action.x} y={action.y} duration={action.duration}"
                )
                await self._action_executor.execute_actions_sequential([action])

    def _parse_response(self, response) -> AgentOutput:
        if isinstance(response, dict) and "parsed" in response:
            parsed = response["parsed"]
            return AgentOutput(**parsed) if isinstance(parsed, dict) else parsed
        return AgentOutput(**response) if isinstance(response, dict) else response

    def _extract_token_usage(self, response) -> TokenUsage:
        try:
            raw = response.get("raw") if isinstance(response, dict) else None
            if raw and hasattr(raw, "usage_metadata") and raw.usage_metadata:
                meta = raw.usage_metadata
                return TokenUsage(
                    input_tokens=getattr(meta, "input_tokens", 0) or 0,
                    output_tokens=getattr(meta, "output_tokens", 0) or 0,
                    total_tokens=getattr(meta, "total_tokens", 0) or 0,
                )
        except Exception:
            pass
        return TokenUsage()

    def _get_todo_snapshot(self, session_id: str) -> List[dict]:
        return [t.to_dict() for t in TodoPersistenceService.get_todo_list(session_id)]

    def _cleanup_session(self, device_udid: str) -> None:
        session = self._sessions.pop(device_udid, None)
        if session:
            TodoPersistenceService.clear_todo_list(session.session_id)
