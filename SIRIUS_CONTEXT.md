# SIRIUS Context

## Vision

SIRIUS is one personal assistant application composed of small, independent modules and tools. Sirius Focus is the first tool.

## Completed milestones

- Step 1: Sirius Focus architecture refactor — COMPLETE
- Step 2: Sirius Focus automated tests — COMPLETE
- Step 3: Core assistant + deterministic intent routing — COMPLETE
- Step 4: Reminders, assistant command routing + lightweight scheduler — COMPLETE
- Module 1: Sirius Focus — COMPLETE
- Module 2.1: AI provider foundation (Gemini behind the app.ai abstraction) — COMPLETE
- Module 2.2: LLM tool calling with validation and confirmation layer — COMPLETE
- Module 2.3: Bounded in-session conversation context — COMPLETE
- Module 2.4: Task update capability (tasks.update via safe NL path) — COMPLETE
- Module 2.5: Persistent memory foundation (explicit memory.save/list/delete) — COMPLETE
- Module 2.6: Memory-aware intelligence (memory.search + deterministic pre-retrieval context) — COMPLETE
- Module 2.7: Context assembly layer (deterministic, clearly separated sections for AI requests) — COMPLETE
- Module 2.8: Reliability and response-handling layer (natural language answers, tool dispatch, graceful error handling) — COMPLETE
- Module 2 (AI Intelligence & Memory Foundation) — COMPLETE
- Module 3.1: Multi-step agent execution loop (core.tool_registry + core.agent) — COMPLETE
- Module 3.2: Agent-loop hardening and observability (repetition guard, agent trace, per-run budget) — COMPLETE
- Module 3.3: Safe automation foundation (automation.open_url + automation.launch_app behind the existing agent loop, registry, and validation layers) — COMPLETE
- Current test count: 384 passing

## Current architecture

```text
run.py
  ↓
app.main
  ↓
app.cli
  ↓
core.assistant
  ↓
core.intents
  ↓
tools.tasks.service / tools.reminders.service / tools.memory.service
  ↓
tools.tasks.repository / tools.reminders.repository / tools.memory.repository
  ↓
storage.database
  ↓
SQLite

tools.reminders.scheduler → background polling → tools.reminders.service

app.ai (AIClient abstraction → create_ai_client() factory → GeminiClient;
google-genai SDK imported lazily and only inside app.ai.client)

AI natural-language path (multi-step agent loop):
core.assistant → core.context_assembly (coordinates memories + bounded transcript + prompt)
  → core.agent (bounded loop: Plan → Tool call → Observation → Next step → Final
    response; max 5 steps, one tool action per step, observations fed back;
    identical repeated tool calls are never re-executed; observations fed back
    are size-bounded per run; each run exposes a deterministic step trace)
  → core.tool_registry (safety tiers: read_only / state_modifying / destructive)
  → core.tools (parse + validation/safety)
  → tools.*.service → repository → SQLite
  Automation requests (automation.open_url, automation.launch_app) follow the
  same loop, registry, and validation layers and end in
  tools.automation.service → OS/browser; only validated http/https URLs and
  the fixed Windows allowlist (Notepad, Calculator) can ever be launched,
  both automation tools are state_modifying, and the service re-checks both
  rules at the OS boundary.
  Natural-language replies end the loop cleanly. State-modifying tools execute
  once and return their service result. Destructive tool requests halt the
  loop immediately, are never executed by the AI path, and run only after the
  user replies with a deterministic confirm command. The CLI can print the
  agent's step trace (opt-in via handle_command(agent_trace=...)); destructive
  confirmation turns produce no trace because the loop records no steps.
  Conversation context is memory-only and disappears when the process exits.
  Persistent memories are written only via the explicit memory.save tool.
```

## Current project structure

```text
project-sirius/
├── app/
│   ├── ai/                   # AI client abstraction, provider + prompts
│   ├── core/                 # assistant, intents, context, agent loop and tool safety layer
│   │   ├── agent/            # bounded multi-step agent execution loop
│   │   └── tool_registry.py  # OO tool specs + safety tiers over core.tools
│   ├── storage/              # SQLite setup
│   ├── tools/tasks/          # task service and repository
│   ├── tools/reminders/      # reminder service, repository and scheduler
│   ├── tools/memory/         # memory service and repository
│   ├── tools/automation/     # safe automation service (browser + allowlisted apps)
│   ├── cli.py
│   └── main.py
├── tests/
│   ├── test_ai.py
│   ├── test_agent_guardrails.py
│   ├── test_agent_loop.py
│   ├── test_automation.py
│   ├── test_ai_assistant.py
│   ├── test_assistant.py
│   ├── test_context_assembly.py
│   ├── test_conversation.py
│   ├── test_intents.py
│   ├── test_memory.py
│   ├── test_memory_context.py
│   ├── test_reminders.py
│   ├── test_response_handler.py
│   ├── test_scheduler.py
│   ├── test_tasks.py
│   ├── test_tool_registry.py
│   └── test_tools.py
├── .env.example              # AI settings template (never commit the real .env)
├── requirements.txt
├── run.py
├── README.md
└── SIRIUS_CONTEXT.md
```

## Architecture rules

- Keep modules small and independent.
- CLI handles user interaction only.
- Services contain business logic.
- Repositories contain persistence and SQL.
- Assistant coordinates tools and must not access SQLite directly.
- Preserve existing user data.
- No unnecessary frameworks or dependencies.
- Every new capability requires tests.
- An LLM must not directly perform destructive actions.
- Do not change the database schema unless explicitly approved.
- All AI access goes through the app.ai abstraction; provider SDKs are
  imported only inside app.ai.client, never in the assistant, CLI, or tools.
- The LLM can only request the explicit tools defined in core.tools; every
  request is parsed and validated before any service call. Destructive
  tools always require explicit user confirmation and can never be bypassed
  by the LLM. The LLM cannot execute code, SQL, or shell commands.

## AI configuration (Module 2.1 + 2.2)

- `SIRIUS_AI_PROVIDER` — provider name; currently only `gemini` (default)
- `SIRIUS_GEMINI_API_KEY` — Gemini API key; required for AI features
- `SIRIUS_GEMINI_MODEL` — optional model override (default: `gemini-3.7-flash`)
- Copy `.env.example` to `.env`, fill in the key, and never commit `.env`.
- Everything outside app.ai uses `create_ai_client()` / `AIClient` only.
- Module 2.2 connects the assistant to the AI through core.tools: nine
  explicit tools (tasks: add, update, list, complete, delete; reminders:
  add, list, complete, delete). Deterministic
  commands keep priority; the AI path only handles unrecognized input. When
  the AI is unconfigured, SIRIUS runs exactly as before.
- Module 2.3 adds `core.conversation.ConversationContext`: a bounded
  (default 12 messages, configurable) in-memory transcript passed to the AI
  with follow-up requests. Nothing is persisted and it disappears on exit;
  validation, safety, and confirmation layers are unchanged.
- Module 2.4 adds `tasks.update` (title, description, due_date, priority).
  The task id is required, at least one field must be supplied, and status,
  created_at, and id are protected. Follow-ups like "make it high priority"
  resolve through the existing conversation context; deletion still requires
  explicit confirmation.
- Module 2.5 adds a persistent `memories` table (key/value with timestamps)
  and three explicit tools (memory.save, memory.list, memory.delete). Memory
  is explicit only: SIRIUS never writes conversation content automatically.
  memory.delete is destructive and uses the same confirmation flow
  ("confirm delete memory <id>").
- Module 2.6 adds `memory.search(query)` (case-insensitive substring search over
  memory key and value, parameterized SQL, 13 total tools in catalog) and
  deterministic pre-retrieval in `core.memory_context`. Stored memories relevant
  to the query are passed to the AI separated from the bounded conversation
  history. Memory remains explicit: no automatic extraction or creation.
- Module 2.7 adds `core.context_assembly`: a dedicated context assembly layer that
  coordinates relevant persistent memories, bounded in-session conversation
  history, the current user request, and system instructions into deterministic,
  unambiguous sections without modifying data, calling tools, or querying SQLite.
- Module 2.8 adds `core.response_handler`: the final reliability and response-handling
  layer for SIRIUS AI interactions. Enforces a deterministic response contract
  supporting valid tool requests, ordinary natural-language answers, and clean,
  graceful error fallbacks (provider errors, empty responses, malformed JSON,
  multiple tool requests, unexpected exceptions) without leaking internal stack
  traces or giving the AI execution authority.
- Module 3.1 adds the agentic execution layer. `core.tool_registry` gives the
  13 core.tools tools an object-oriented Tool/ToolRegistry view with a
  SafetyTier (read_only, state_modifying, destructive); validation always goes
  through the shared core.tools layer, so custom names can never bypass it.
  `core.agent` runs a bounded multi-step loop (Plan -> Tool call -> Observation
  -> Next step -> Final response, default max 5 steps, one tool action per
  step). Read-only observations are fed back so the AI can chain lookups or
  finish with a plain-text answer; state-modifying tools execute once and
  return their service result; destructive tools halt the loop immediately for
  human confirmation and are never executed by the AI path. The AI path now
  routes through this loop; deterministic commands, the confirmation flow, and
  the response contract are unchanged.
- Module 3.2 hardens the agent loop and makes it observable. A repetition
  guard never re-executes an identical (tool, validated arguments) call within
  one run; the observation already produced is returned instead and the step
  is recorded as a skipped repeat (argument order cannot defeat the guard).
  AgentLoop.render_trace() renders a deterministic, compact per-run trace
  ([n] tool(arguments), skipped markers, "final response"); the assistant
  appends it to an optional agent_trace list on AI turns only, and the CLI
  prints it before the answer. A per-run observation budget
  (max_observation_chars, default 1200) bounds how much observation text is
  fed back into follow-up prompts, with an explicit "[observation truncated]"
  marker; full observations are still recorded on the step. No new
  dependencies, no schema changes, and all validation, safety-tier, and
  confirmation rules are unchanged.
- Module 3.3 adds a small, explicitly registered automation layer.
  app/tools/automation is the only layer that touches the OS and exposes two
  fixed actions: automation.open_url opens well-formed http/https URLs in the
  default browser (file, javascript, data, and custom protocol schemes are
  rejected), and automation.launch_app starts only identifiers from a fixed
  Windows-safe allowlist (Notepad, Calculator) through their fixed
  executables -- never paths, shell commands, arguments, or arbitrary
  executables. Both tools are SafetyTier.STATE_MODIFYING because they cause
  external side effects, both are registered in the existing
  core.tool_registry, and every request is validated by the existing
  core.tools layer (new url and app argument kinds) before the service runs;
  the AI never calls the automation service directly. The service re-checks
  both rules at the OS boundary (defense in depth), launchers are injectable
  so tests never open real browsers or applications, failures become clean
  user-facing observations, and the registry now carries 15 tools. No new
  dependencies, no schema changes, and all existing confirmation,
  repetition-guard, budget, and trace behavior is unchanged.

## Development roadmap

- Step 1 Architecture ✓
- Step 2 Testing ✓
- Step 3 Assistant Core ✓
- Step 4 Reminders + lightweight scheduler ✓ — Module 1 (Sirius Focus) complete
- Step 5 LLM integration ✓ — Module 2 (2.1-2.8 AI Intelligence & Memory Foundation) complete
- Step 6 Memory ✓ — Module 2.5 foundation, 2.6 retrieval, 2.7 context, 2.8 reliability complete
- Step 7 Agentic execution ✓ — Module 3.1 (multi-step agent loop + tool registry) and Module 3.2 (hardening + observability) complete; Voice is a later module
- Step 8 Automation — Module 3.3 (safe automation foundation) complete; broader automation still ahead
- Step 9 External integrations

> [!NOTE]
> Module 3.3 (safe automation foundation) is complete and validated
> (384 passing tests). Module 3.4 has NOT been started.

## Stable Git checkpoint

`3a95f7b` — `Harden and add observability to SIRIUS agent loop`

## Development rule

Only one coding agent should modify the repository at a time. Before making changes, every agent must inspect this file, `README.md`, the current tests, and `git status`.
