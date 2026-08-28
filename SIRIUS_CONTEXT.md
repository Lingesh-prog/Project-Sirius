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
- Current test count: 76 passing

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
tools.tasks.service / tools.reminders.service
  ↓
tools.tasks.repository / tools.reminders.repository
  ↓
storage.database
  ↓
SQLite

tools.reminders.scheduler → background polling → tools.reminders.service

app.ai (AIClient abstraction → create_ai_client() factory → GeminiClient;
google-genai SDK imported lazily and only inside app.ai.client)
```

## Current project structure

```text
project-sirius/
├── app/
│   ├── ai/                   # AI client abstraction, provider + prompts
│   ├── core/                 # assistant and deterministic intents
│   ├── storage/              # SQLite setup
│   ├── tools/tasks/          # task service and repository
│   ├── tools/reminders/      # reminder service, repository and scheduler
│   ├── cli.py
│   └── main.py
├── tests/
│   ├── test_ai.py
│   ├── test_assistant.py
│   ├── test_intents.py
│   ├── test_reminders.py
│   ├── test_scheduler.py
│   └── test_tasks.py
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

## AI configuration (Module 2.1)

- `SIRIUS_AI_PROVIDER` — provider name; currently only `gemini` (default)
- `SIRIUS_GEMINI_API_KEY` — Gemini API key; required for AI features
- `SIRIUS_GEMINI_MODEL` — optional model override (default: `gemini-3.7-flash`)
- Copy `.env.example` to `.env`, fill in the key, and never commit `.env`.
- The rest of SIRIUS uses `create_ai_client()` / `AIClient` only. Tool
  calling, memory, and assistant wiring are NOT part of Module 2.1.

## Development roadmap

- Step 1 Architecture ✓
- Step 2 Testing ✓
- Step 3 Assistant Core ✓
- Step 4 Reminders + lightweight scheduler ✓ — Module 1 (Sirius Focus) complete
- Step 5 LLM integration — Module 2.1 AI provider foundation ✓ (2.2 tool calling next)
- Step 6 Memory
- Step 7 Voice
- Step 8 Automation
- Step 9 External integrations

## Stable Git checkpoint

`140167f` — `Add SIRIUS assistant core and intent routing`

## Development rule

Only one coding agent should modify the repository at a time. Before making changes, every agent must inspect this file, `README.md`, the current tests, and `git status`.
