# SIRIUS Context

## Vision

SIRIUS is one personal assistant application composed of small, independent modules and tools. Sirius Focus is the first tool.

## Completed milestones

- Step 1: Sirius Focus architecture refactor — COMPLETE
- Step 2: Sirius Focus automated tests — COMPLETE
- Step 3: Core assistant + deterministic intent routing — COMPLETE
- Step 4: Reminder tool + assistant command routing — COMPLETE (scheduler deferred)
- Current test count: 44 passing

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
```

## Current project structure

```text
project-sirius/
├── app/
│   ├── core/                 # assistant and deterministic intents
│   ├── storage/              # SQLite setup
│   ├── tools/tasks/          # task service and repository
│   ├── tools/reminders/      # reminder service and repository
│   ├── cli.py
│   └── main.py
├── tests/
│   ├── test_assistant.py
│   ├── test_intents.py
│   ├── test_reminders.py
│   └── test_tasks.py
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

## Development roadmap

- Step 1 Architecture ✓
- Step 2 Testing ✓
- Step 3 Assistant Core ✓
- Step 4 Reminders ✓ (scheduler deferred to a later step by explicit instruction)
- Step 5 LLM integration
- Step 6 Memory
- Step 7 Voice
- Step 8 Automation
- Step 9 External integrations

## Stable Git checkpoint

`140167f` — `Add SIRIUS assistant core and intent routing`

## Development rule

Only one coding agent should modify the repository at a time. Before making changes, every agent must inspect this file, `README.md`, the current tests, and `git status`.
