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
- Current test count: 265 passing

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

AI natural-language path:
core.assistant → core.context_assembly (coordinates memories + bounded transcript + prompt)
  → app.ai client → core.response_handler (contract: tools, natural language, fallbacks)
  → core.tools (parse + validation/safety)
  → tools.*.service → repository → SQLite
  Destructive tool requests stop at the confirmation layer and are executed
  only after the user replies with a deterministic confirm command.
  Conversation context is memory-only and disappears when the process exits.
  Persistent memories are written only via the explicit memory.save tool.
```

## Current project structure

```text
project-sirius/
├── app/
│   ├── ai/                   # AI client abstraction, provider + prompts
│   ├── core/                 # assistant, intents, context and tool safety layer
│   ├── storage/              # SQLite setup
│   ├── tools/tasks/          # task service and repository
│   ├── tools/reminders/      # reminder service, repository and scheduler
│   ├── tools/memory/         # memory service and repository
│   ├── cli.py
│   └── main.py
├── tests/
│   ├── test_ai.py
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

## Development roadmap

- Step 1 Architecture ✓
- Step 2 Testing ✓
- Step 3 Assistant Core ✓
- Step 4 Reminders + lightweight scheduler ✓ — Module 1 (Sirius Focus) complete
- Step 5 LLM integration ✓ — Module 2 (2.1-2.8 AI Intelligence & Memory Foundation) complete
- Step 6 Memory ✓ — Module 2.5 foundation, 2.6 retrieval, 2.7 context, 2.8 reliability complete
- Step 7 Voice — Module 3 (NOT started / planned next)
- Step 8 Automation
- Step 9 External integrations

> [!NOTE]
> Module 3 has NOT been started. Module 2 is fully complete and validated.

## Stable Git checkpoint

`140167f` — `Add SIRIUS assistant core and intent routing`

## Development rule

Only one coding agent should modify the repository at a time. Before making changes, every agent must inspect this file, `README.md`, the current tests, and `git status`.
