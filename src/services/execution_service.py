import os
import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

from google.cloud import storage as gcs

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_vertexai.model_garden import ChatAnthropicVertex
from langchain_openai import AzureChatOpenAI

from agent.context import ContextService
from agent.device_results import ActionResult, DeviceErrorType, ScreenshotResult
from agent.prompts import SYSTEM_PROMPT_WITH_TODO, SYSTEM_PROMPT_WITH_TODO_IMPROVED
from agent.logger import get_logger
from services.views import Action, AgentOutput
from models.test_scenario import TestScenario, Step
from models.game import Game
from models.build import Build
from models.execution_run import AssertionResult
from models.execution_step import TokenUsage
from repositories.execution_repository import ExecutionRepository
from repositories.execution_step_repository import ExecutionStepRepository
from services.android_build_runner import create_action_executor_for_build
from tools.todo_management import todo_write_handler, get_todo_list_for_context
from tools.todo_management.todo_service import TodoPersistenceService

logger = get_logger("agent.services.execution_service")

USE_APPIUM = os.getenv("USE_APPIUM", "false").lower() == "true"
POLLING_INTERVAL = float(os.getenv("POLLING_INTERVAL", "2.5"))
MAX_STEPS = int(os.getenv("MAX_STEPS", "1000"))
MAX_CONSECUTIVE_DEVICE_FAILURES = int(os.getenv("MAX_CONSECUTIVE_DEVICE_FAILURES", "3"))
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "rovix_ai_bucket")

# Model provider selection: "google" (default) | "anthropic" | "azure"
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "google")

# Google / Gemini
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-3-pro-preview")

# Anthropic via Vertex AI
ANTHROPIC_PROJECT_ID = os.getenv("ANTHROPIC_PROJECT_ID", "")
ANTHROPIC_LOCATION = os.getenv("ANTHROPIC_LOCATION", "us-east5")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# Azure OpenAI
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_INSTANCE_NAME = os.getenv("AZURE_OPENAI_API_INSTANCE_NAME", "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")


class FatalExecutionError(Exception):
    """Stops the run with a persisted failure_reason (device / invalid action)."""
    pass


# ── Session state ────────────────────────────────────────────────────────────

@dataclass
class AgentSession:
    execution_run_id: str
    session_id: str
    device_udid: str
    context_service: ContextService
    action_executor: Any = None  # ADBManager | AppiumManager — set after APK install
    force_annotate: bool = False
    step_count: int = 0
    collected_results: List[AssertionResult] = field(default_factory=list)
    consecutive_device_failures: int = 0
    screen_width: int = 0   # set from first screenshot; used to de-normalise 0-1000 coords
    screen_height: int = 0


# ── Service ──────────────────────────────────────────────────────────────────

class ExecutionService:
    def __init__(self):
        self._sessions: Dict[str, AgentSession] = {}
        self._execution_repo = ExecutionRepository()
        self._step_repo = ExecutionStepRepository()
        self._structured_model = self._init_model()
        self._vision_detector = self._init_vision_detector()
        self._gcs_client = gcs.Client()
        self._gcs_bucket = self._gcs_client.bucket(GCS_BUCKET_NAME)

    @staticmethod
    def _bg_task(coro, label: str = "background task"):
        """Fire-and-forget a coroutine, logging any exception instead of silently swallowing it."""
        task = asyncio.create_task(coro)
        task.add_done_callback(
            lambda t: logger.error(f"❌ {label} failed: {t.exception()}")
            if not t.cancelled() and t.exception()
            else None
        )
        return task

    def _init_model(self):
        if MODEL_PROVIDER == "anthropic":
            logger.info(f"🤖 Using Anthropic model: {ANTHROPIC_MODEL} (Vertex AI, location={ANTHROPIC_LOCATION})")
            model = ChatAnthropicVertex(
                model_name=ANTHROPIC_MODEL,
                project=ANTHROPIC_PROJECT_ID,
                location=ANTHROPIC_LOCATION,
                max_tokens=4096,
            )
        elif MODEL_PROVIDER == "azure":
            logger.info(f"🤖 Using Azure OpenAI model: {AZURE_OPENAI_DEPLOYMENT} (instance={AZURE_OPENAI_INSTANCE_NAME})")
            model = AzureChatOpenAI(
                temperature=0.0,
                azure_deployment=AZURE_OPENAI_DEPLOYMENT,
                azure_endpoint=f"https://{AZURE_OPENAI_INSTANCE_NAME}.openai.azure.com",
                api_key=AZURE_OPENAI_API_KEY,
                api_version=AZURE_OPENAI_API_VERSION,
            )
        else:
            logger.info(f"🤖 Using Google model: {GOOGLE_MODEL}")
            model = ChatGoogleGenerativeAI(
                model=GOOGLE_MODEL,
                temperature=1.0,
                api_key=os.getenv("GOOGLE_API_KEY"),
            )

        return model.with_structured_output(
            schema=AgentOutput.model_json_schema(),
            method="json_schema",
            include_raw=True,
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
        build: Build,
    ) -> None:
        session_id = run_id
        context_svc = ContextService(system_prompt=SYSTEM_PROMPT_WITH_TODO_IMPROVED, keep_full_steps=4)
        context_svc._ensure_session(
            session_id,
            game_description=game.description or "A mobile game application.",
            gameplay_details=scenario.gameplay or game.gameplay or "",
            test_plan=self._build_test_plan(scenario),
        )

        session = AgentSession(
            execution_run_id=run_id,
            session_id=session_id,
            device_udid=device_udid,
            context_service=context_svc,
        )

        try:
            session.action_executor = await asyncio.to_thread(
                create_action_executor_for_build,
                device_udid=device_udid,
                build=build,
                use_appium=USE_APPIUM,
            )
        except Exception as e:
            logger.error(f"Build prepare / install failed for run {run_id}: {e}", exc_info=True)
            await self._execution_repo.fail(run_id, failure_reason=f"Build prepare failed: {e}")
            return

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
        except FatalExecutionError as e:
            msg = str(e)
            logger.error(f"Execution {session.execution_run_id} aborted: {msg}")
            await self._execution_repo.fail(session.execution_run_id, failure_reason=msg)
        except Exception as e:
            logger.error(f"Execution {session.execution_run_id} failed: {e}", exc_info=True)
            await self._execution_repo.fail(session.execution_run_id, failure_reason=str(e))
        finally:
            self._cleanup_session(session.device_udid)

    async def _handle_step(self, session: AgentSession, step_num: int) -> bool:
        logger.info(f"\n{'='*80}\n🎮 Step {step_num} | Run {session.execution_run_id[:8]}\n{'='*80}")

        todo_list = get_todo_list_for_context(session.session_id)
        logger.info(f"\n{'='*60}\n📋 CURRENT TODO LIST:\n{'='*60}\n{todo_list}\n{'='*60}")

        screenshots_dir = os.path.join("screenshots", session.execution_run_id)
        os.makedirs(screenshots_dir, exist_ok=True)
        screenshot_path = os.path.join(screenshots_dir, f"step_{step_num}.png")

        result = session.action_executor.get_screenshot(screenshot_path)
        if not result.success:
            logger.error(
                f"❌ Screenshot capture failed: {result.error_message} "
                f"(type: {result.error_type}, retries: {result.retry_count})"
            )
            self._on_screenshot_failure(session, result)
            return False

        session.consecutive_device_failures = 0

        # Cache screen dimensions for 0-1000 → pixel de-normalisation (read once; stable across steps)
        if session.screen_width == 0:
            with Image.open(screenshot_path) as _img:
                session.screen_width, session.screen_height = _img.size
            logger.info(f"📐 Screen dimensions: {session.screen_width}×{session.screen_height}")

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

        # Upload runs concurrently with LLM inference; we await the result after LLM returns.
        # Upload failure is non-fatal — we fall back to an empty URL and log the error.
        upload_task = asyncio.create_task(
            self._upload_screenshot(screenshot_path, session.execution_run_id, step_num)
        )

        messages = session.context_service.get_messages_for_llm(session.session_id)
        logger.info("🤖 Getting agent decision from LLM...")
        start = time.time()

        # TODO: add time limit to the LLM call like vision api call.
        raw_response = await asyncio.to_thread(self._structured_model.invoke, messages)
        elapsed = time.time() - start
        logger.info(f"⏱️  LLM response time: {elapsed:.2f}s")

        try:
            screenshot_url = await upload_task
            logger.info(f"☁️  Screenshot uploaded: {screenshot_url}")
        except Exception as exc:
            logger.error(f"❌ Screenshot upload failed (non-fatal): {exc}")
            screenshot_url = ""

        try:
            output = self._parse_response(raw_response)
        except Exception as parse_err:
            # TODO: fix _parse_response to handle double-encoded fields (e.g. actions as a JSON string)
            # For now, skip this step and let the LLM course-correct on the next iteration
            logger.warning(f"Step {step_num}: failed to parse LLM response, skipping — {parse_err}")
            session.context_service.add_parse_error(session.session_id, str(parse_err))
            return False
        token_usage = self._extract_token_usage(raw_response)

        logger.info("✅ Agent decision received")
        logger.info(f"   📝 Game state: {output.game_state_summary}")
        logger.info(f"   🤔 Reasoning: {output.reason}")
        logger.info(f"   Grounded objects: {output.grounded_objects}")
        # logger.info(f"   Co-ordinates reasoning: {output.co_ordinates_reasoning}")
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

        if output.grounded_objects:
            self._bg_task(
                self._save_grounded_annotation(screenshot_path, output.grounded_objects),
                label=f"Grounded annotation step {step_num}",
            )

        step_assertion_results = []
        for r in output.test_results:
            assertion_result = AssertionResult(
                assertion_id=r.test_case_id,
                verdict=r.virdict,
                completion=r.completion,
                failure_reason=r.failure_reason,
                comment=r.comment,
                screenshot_url=screenshot_url,
            )
            session.collected_results.append(assertion_result)
            step_assertion_results.append(assertion_result)

        self._bg_task(
            self._step_repo.create(
                execution_run_id=session.execution_run_id,
                step_number=step_num,
                screenshot_url=screenshot_url,
                game_state_summary=output.game_state_summary,
                reason=output.reason,
                actions_taken=[a.model_dump() for a in output.actions],
                todo_snapshot=self._get_todo_snapshot(session.session_id),
                assertion_results_reported=step_assertion_results,
                token_usage=token_usage,
            ),
            label=f"ExecutionStep {step_num} DB write",
        )
        logger.info(f"💾 ExecutionStep {step_num} DB write dispatched (background)")

        if output.end_game:
            logger.info("🛑 Agent signaled end of execution")
            return True

        await self._execute_actions(session, output.actions)
        session.context_service.cleanup_old_messages(session.session_id)
        return False

    def _on_screenshot_failure(self, session: AgentSession, result: ScreenshotResult) -> None:
        """Raises FatalExecutionError when the run must stop."""
        if result.error_type == DeviceErrorType.DEVICE_DISCONNECTED:
            raise FatalExecutionError(result.error_message or "Device disconnected (screenshot)")
        session.consecutive_device_failures += 1
        if session.consecutive_device_failures >= MAX_CONSECUTIVE_DEVICE_FAILURES:
            raise FatalExecutionError(
                f"Screenshot failed {session.consecutive_device_failures} time(s) in a row "
                f"(last: {result.error_message})"
            )

    def _on_action_batch_results(self, session: AgentSession, results: List[ActionResult]) -> None:
        """Raises FatalExecutionError on device loss, invalid actions, or too many failures."""
        for r in results:
            if r.skipped:
                continue
            if r.success:
                session.consecutive_device_failures = 0
                continue
            logger.error(
                f"❌ Action failed: type={r.action_type} error={r.error_message} "
                f"(type={r.error_type})"
            )
            if r.error_type == DeviceErrorType.DEVICE_DISCONNECTED:
                raise FatalExecutionError(r.error_message or "Device disconnected (action)")
            if r.error_type == DeviceErrorType.INVALID_INPUT:
                logger.error(f"Invalid input: {r.error_message}")
            session.consecutive_device_failures += 1
            if session.consecutive_device_failures >= MAX_CONSECUTIVE_DEVICE_FAILURES:
                raise FatalExecutionError(
                    f"Exceeded {MAX_CONSECUTIVE_DEVICE_FAILURES} consecutive device failures "
                    f"(last action: {r.error_message})"
                )

    def _denorm_action(self, action: Action, screen_w: int, screen_h: int) -> Action:
        """Convert a 0-1000 normalised action to actual pixel coordinates."""
        def sx(v): return int((v / 1000.0) * screen_w) if v is not None else None
        def sy(v): return int((v / 1000.0) * screen_h) if v is not None else None

        converted_waypoints = None
        if action.waypoints:
            converted_waypoints = [[sx(wp[0]), sy(wp[1])] for wp in action.waypoints]

        return Action(
            action_type=action.action_type,
            x=sx(action.x),
            y=sy(action.y),
            end_x=sx(action.end_x),
            end_y=sy(action.end_y),
            waypoints=converted_waypoints,
            key_name=action.key_name,
            duration=action.duration,
            todo_input=action.todo_input,
        )

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
                pixel_action = self._denorm_action(action, session.screen_width, session.screen_height)
                logger.info(
                    f"   action ({idx}/{total}): {action.action_type} "
                    f"norm=({action.x},{action.y}) → px=({pixel_action.x},{pixel_action.y}) "
                    f"duration={action.duration}"
                )
                batch = await session.action_executor.execute_actions_sequential([pixel_action])
                self._on_action_batch_results(session, batch.results)

    def _parse_response(self, response) -> AgentOutput:
        if isinstance(response, dict) and "parsed" in response:
            parsed = response["parsed"]
            return AgentOutput(**parsed) if isinstance(parsed, dict) else parsed
        return AgentOutput(**response) if isinstance(response, dict) else response

    def _extract_token_usage(self, response) -> TokenUsage:
        try:
            raw = response.get("raw") if isinstance(response, dict) else None
            if raw is None:
                return TokenUsage()

            input_tokens, output_tokens, total_tokens = 0, 0, 0

            usage_meta = getattr(raw, "usage_metadata", None)
            if usage_meta:
                if isinstance(usage_meta, dict):
                    input_tokens = usage_meta.get("input_tokens", 0) or 0
                    output_tokens = usage_meta.get("output_tokens", 0) or 0
                    total_tokens = usage_meta.get("total_tokens", 0) or 0
                else:
                    input_tokens = getattr(usage_meta, "input_tokens", 0) or 0
                    output_tokens = getattr(usage_meta, "output_tokens", 0) or 0
                    total_tokens = getattr(usage_meta, "total_tokens", 0) or 0

            if input_tokens == 0 and output_tokens == 0:
                usage = (getattr(raw, "response_metadata", {}) or {}).get("usage", {}) or {}
                input_tokens = usage.get("input_tokens", 0) or 0
                output_tokens = usage.get("output_tokens", 0) or 0

            return TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens or (input_tokens + output_tokens),
            )
        except Exception as e:
            logger.warning(f"⚠️  Failed to extract token usage: {e}")
        return TokenUsage()

    async def _upload_screenshot(self, local_path: str, execution_run_id: str, step_num: int) -> str:
        blob_name = f"screenshots/{execution_run_id}/step_{step_num}.png"

        def _do_upload():
            blob = self._gcs_bucket.blob(blob_name)
            blob.upload_from_filename(local_path)

        await asyncio.to_thread(_do_upload)
        return f"/api/executions/{execution_run_id}/steps/{step_num}/screenshot"

    def _get_todo_snapshot(self, session_id: str) -> List[dict]:
        return [t.to_dict() for t in TodoPersistenceService.get_todo_list(session_id)]

    async def _save_grounded_annotation(self, screenshot_path: str, grounded_objects: List) -> None:
        """Draw a small square marker for every grounded object the LLM reported and save as *_annotated.png.
        grounded_objects carry 0-1000 normalised coordinates; we convert to pixels using the image dimensions."""
        def _draw():
            image = Image.open(screenshot_path)
            img_w, img_h = image.size
            draw = ImageDraw.Draw(image)

            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 11)
            except Exception:
                font = ImageFont.load_default()

            colors = ['red', 'green', 'blue', 'yellow', 'purple', 'orange', 'cyan', 'magenta']
            dot_half = 8

            for idx, obj in enumerate(grounded_objects):
                color = colors[idx % len(colors)]
                # Convert 0-1000 normalised → pixel coordinates
                cx = int((obj.x / 1000.0) * img_w)
                cy = int((obj.y / 1000.0) * img_h)
                cx = max(dot_half, min(cx, img_w - dot_half))
                cy = max(dot_half, min(cy, img_h - dot_half))

                draw.rectangle(
                    [cx - dot_half, cy - dot_half, cx + dot_half, cy + dot_half],
                    fill=color,
                    outline='white',
                    width=1,
                )
                draw.text((cx + dot_half + 3, cy - 6), obj.name, fill=color, font=font)

            base = os.path.splitext(screenshot_path)[0]
            image.save(f"{base}_annotated.png")

        await asyncio.to_thread(_draw)
        logger.info(f"📸 Grounded annotation saved ({len(grounded_objects)} objects)")

    def _cleanup_session(self, device_udid: str) -> None:
        session = self._sessions.pop(device_udid, None)
        if session:
            TodoPersistenceService.clear_todo_list(session.session_id)
