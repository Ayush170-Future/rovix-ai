---
name: English to Execution Backend
overview: "Add persistence and a multi-tenant data model (Org → Game → TestScenario) and build the \"English to Execution\" feature: user writes loose English, backend generates validated steps via LLM, triggers agent execution, and streams real-time step-by-step visibility via polling."
todos:
  - id: models
    content: "Create Organization, Game models; rewrite TestScenario (rename from TestCase: add game_id, org_id, precondition/gameplay/validations fields, steps, assertions, status); create ExecutionRun and ExecutionStep (separate table); update database.py to register all models"
    status: completed
  - id: repositories
    content: Create organization_repository.py, game_repository.py, execution_repository.py, execution_step_repository.py; update test_scenario_repository.py to support step and assertion storage and status transitions
    status: completed
  - id: step-gen-service
    content: "Create src/services/step_generation_service.py: LLM call (Gemini) that converts precondition + gameplay + validations fields into List[Step] and List[Assertion] with action/verify types and dependency ordering"
    status: completed
  - id: agent-deglobalize
    content: "Refactor src/agent/service.py: wrap global state into AgentSession dataclass, make agent_handler and execute_agent_actions instance methods, accept execution_run_id and steps from DB; write ExecutionStep to DB after each iteration"
    status: cancelled
  - id: execution-service
    content: "Create src/services/execution_service.py: manages active AgentSessions per device, seeds todo list from validated steps, writes ExecutionStep records (with S3 screenshot URL) and AssertionResults back to MongoDB"
    status: completed
  - id: routes
    content: Create routes/orgs.py, routes/games.py, routes/test_scenarios.py (with generate-steps and steps validation endpoints), routes/executions.py (with /steps polling endpoint); update api/main.py to register all routers
    status: completed
  - id: auth-obfuscation
    content: Add X-Org-Slug header middleware that validates slug against DB and attaches org context to request state
    status: completed
isProject: false
---

# English to Execution Backend

## What Already Exists (keep as-is)

- `src/tools/todo_management/` — step execution mechanism, this IS the step runtime
- `src/agent/context/context_service.py` — LLM context management
- `src/agent/action_handler.py`, `adb_manager.py`, `appium_manager.py` — device layer
- `src/models/test_run.py` — being superseded by `ExecutionRun` + `ExecutionStep`
- `src/database.py` — MongoDB/Beanie init (needs new models registered)

---

## Data Model

```mermaid
erDiagram
    Organization ||--o{ Game : contains
    Game ||--o{ TestScenario : contains
    TestScenario ||--o{ Assertion : defines
    TestScenario ||--o{ ExecutionRun : triggers
    ExecutionRun ||--o{ ExecutionStep : records
    ExecutionRun ||--o{ AssertionResult : records

    Organization {
        str id
        str name
        str slug
    }
    Game {
        str id
        str org_id
        str name
        str description
        str platform
    }
    TestScenario {
        str id
        str game_id
        str org_id
        str title
        str precondition
        str gameplay
        str validations
        list steps
        list assertions
        str status
    }
    Assertion {
        str id
        str title
        str description
    }
    ExecutionRun {
        str id
        str scenario_id
        str device_udid
        str status
        int total_assertions
        int passed
        int failed
        datetime started_at
        datetime completed_at
    }
    ExecutionStep {
        str id
        str execution_run_id
        int step_number
        datetime timestamp
        str screenshot_url
        str game_state_summary
        str reason
        list actions_taken
        list todo_snapshot
        list assertion_results_reported
        dict token_usage
    }
    AssertionResult {
        str assertion_id
        str verdict
        bool completion
        str failure_reason
        str comment
        str screenshot_url
        datetime executed_at
    }
```



**Naming clarified:**

- `TestScenario` — the thing the QA writes in English (replaces `TestCase`). Contains the English input fields, generated steps, and assertion definitions.
- `Assertion` — each individual checkable condition inside a scenario (e.g. "1.1 New Player Login"). Stored on `TestScenario`, stable across runs.
- `AssertionResult` — the outcome of one assertion in one run. Stored on `ExecutionRun`.
- `ExecutionStep` — one row per agent iteration (screenshot → LLM → actions). Separate table for real-time polling.

`**TestScenario.status` lifecycle:**
`draft` → `steps_generated` → `steps_validated` → `running` → `completed | failed`

`**TestScenario` English input fields** (what the QA fills in):

- `precondition` — where the game needs to be when the test starts (e.g. "Player is logged in and on the main world map")
- `gameplay` — what the agent should do (e.g. "Navigate to Catalina City and complete a bingo round")
- `validations` — what to assert (e.g. "Verify the round summary screen appears")

These three fields feed the step generation LLM.

`**TestScenario.steps`** (stored as `List[Step]`, loaded as the agent's todo list on execution):

```python
class Step(BaseModel):
    id: str
    content: str
    step_type: Literal["action", "verify"]
    order: int
    dependencies: List[str] = []
```

`**ExecutionStep` indexes:**

- Compound index on `(execution_run_id, timestamp)` — covers timeline fetch and incremental polling
- Index on `step_number` — for direct step lookup

---

## New File Structure

```
src/
  models/
    organization.py           # NEW
    game.py                   # NEW
    test_scenario.py          # NEW (replaces test_case.py)
    execution_run.py          # NEW (supersedes test_run.py)
    execution_step.py         # NEW
  services/
    step_generation_service.py   # NEW: English → Steps + Assertions via LLM
    execution_service.py         # NEW: agent session management per run
  repositories/
    organization_repository.py   # NEW
    game_repository.py           # NEW
    test_scenario_repository.py  # NEW (replaces test_case_repository.py)
    execution_repository.py      # NEW (replaces test_run_repository.py)
    execution_step_repository.py # NEW
  routes/
    orgs.py               # NEW
    games.py              # NEW
    test_scenarios.py     # NEW (replaces routes/api.py)
    executions.py         # NEW
  agent/
    service.py            # UPDATE: de-globalize into AgentSession
  api/
    main.py               # UPDATE: register new routers
  database.py             # UPDATE: register new models
```

---

## API Endpoints

**Orgs & Games**

- `POST /api/orgs` — create org, returns `org_id` + `slug`
- `GET /api/orgs/{org_id}/games`
- `POST /api/orgs/{org_id}/games`

**Test Scenarios**

- `POST /api/games/{game_id}/scenarios` — body: `{ title, precondition, gameplay, validations }`
- `GET /api/games/{game_id}/scenarios`
- `GET /api/scenarios/{scenario_id}`

**English → Execution Flow**

- `POST /api/scenarios/{scenario_id}/generate-steps` — LLM call, returns steps + assertions, status → `steps_generated`
- `PUT /api/scenarios/{scenario_id}/steps` — user submits approved/edited steps + assertions, status → `steps_validated`
- `POST /api/scenarios/{scenario_id}/execute` — body: `{ device_udid }`, returns `execution_run_id` immediately (async)
- `GET /api/scenarios/{scenario_id}/executions` — list runs

**Execution Polling**

- `GET /api/executions/{execution_run_id}` — status + assertion_results summary
- `GET /api/executions/{execution_run_id}/steps` — paginated step timeline (for real-time UI)
- `GET /api/executions/{execution_run_id}/steps?since=<timestamp>` — incremental poll for new steps only

---

## Step Generation Service

New file: `src/services/step_generation_service.py`

- Takes `precondition` + `gameplay` + `validations` + `game.description`
- Single LLM call to Gemini with structured output
- Returns `List[Step]` (the agent todo list) and `List[Assertion]` (the named checks the agent will report on)

```python
class GeneratedOutput(BaseModel):
    steps: List[Step]
    assertions: List[Assertion]  # e.g. [{"id": "1.1", "title": "New Player Login", "description": "..."}]
    summary: str
```

---

## Agent De-globalization + ExecutionStep Persistence

`src/agent/service.py` currently uses module-level globals. Changes:

- Wrap agent state into `AgentSession` dataclass: holds `session_id`, `context_service` instance, `execution_run_id`, `force_annotate`
- `ExecutionService` holds `active_sessions: Dict[str, AgentSession]` keyed by `device_udid`
- `agent_handler` and `execute_agent_actions` become methods of `AgentSession`
- After each agent iteration, write one `ExecutionStep` to MongoDB (screenshot uploaded to S3 first, URL stored)
- On `end_game`: write `AssertionResult` list to `ExecutionRun`, set status `completed`
- On startup: mark any stuck `running` executions as `failed`

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant StepGen as StepGenerationService
    participant DB as MongoDB
    participant S3
    participant ExecSvc as ExecutionService
    participant Agent as AgentSession

    Client->>API: POST /scenarios/{id}/generate-steps
    API->>StepGen: generate(precondition, gameplay, validations)
    StepGen->>API: steps + assertions
    API->>DB: save steps + assertions, status=steps_generated

    Client->>API: PUT /scenarios/{id}/steps (approved)
    API->>DB: save validated steps, status=steps_validated

    Client->>API: POST /scenarios/{id}/execute
    API->>DB: create ExecutionRun(status=queued)
    API->>ExecSvc: start_execution(run_id, scenario)
    ExecSvc->>Agent: new AgentSession(run_id, steps)
    Agent-->>Client: execution_run_id (returns immediately)

    loop each agent iteration
        Agent->>Agent: screenshot → upload to S3
        S3-->>Agent: screenshot_url
        Agent->>Agent: LLM call → AgentOutput
        Agent->>DB: write ExecutionStep(screenshot_url, summary, reason, actions, todo_snapshot)
        Agent->>Agent: execute actions
    end

    Agent->>DB: write AssertionResults to ExecutionRun
    Agent->>DB: ExecutionRun status=completed

    Client->>API: GET /executions/{id}/steps?since=timestamp
    API->>DB: query ExecutionStep by run_id + timestamp
    API-->>Client: new steps since last poll
```



---

## Auth (Obfuscation Only)

- Each org gets a `slug` (e.g. `org_xk9p2m`) on creation
- All routes require `X-Org-Slug` header — validated against DB, no JWT
- Attaches `org_id` to request state for downstream filtering

---

## Key Files to Modify

- `[src/agent/service.py](src/agent/service.py)` — de-globalize into `AgentSession` class
- `[src/models/test_case.py](src/models/test_case.py)` — superseded by `test_scenario.py`
- `[src/api/main.py](src/api/main.py)` — register routers
- `[src/database.py](src/database.py)` — register new models

## Deferred (not in this scope)

- Cron scheduling / CI-CD webhooks
- Real authentication (JWT/OAuth)
- Crash-resume: persisting todo list state mid-run for recovery
- Context setup via debug API (navigation pre-steps are `precondition` text only for now)

