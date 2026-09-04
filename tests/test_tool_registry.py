"""Tests for the Module 3.1 tool specification and registry layer.

The registry wraps the existing core.tools validation/safety layer and the
service layer; executors run against a temporary database, so no test touches
real user data and no destructive executor runs against existing rows.
"""

import tempfile
import unittest
from pathlib import Path

from app.core.tool_registry import (
    SafetyTier,
    Tool,
    ToolRegistry,
    build_default_registry,
)
from app.core.tools import (
    DESTRUCTIVE_TOOLS,
    TOOL_ARGUMENT_SPECS,
    TOOL_AUTOMATION_LAUNCH_APP,
    TOOL_AUTOMATION_OPEN_URL,
    TOOL_MEMORY_DELETE,
    TOOL_MEMORY_LIST,
    TOOL_MEMORY_SAVE,
    TOOL_MEMORY_SEARCH,
    TOOL_REMINDERS_ADD,
    TOOL_REMINDERS_COMPLETE,
    TOOL_REMINDERS_DELETE,
    TOOL_REMINDERS_LIST,
    TOOL_TASKS_ADD,
    TOOL_TASKS_COMPLETE,
    TOOL_TASKS_DELETE,
    TOOL_TASKS_LIST,
    TOOL_TASKS_UPDATE,
    ToolValidationError,
)
from app.storage.database import initialize_database
from app.tools.memory import service as memory_service
from app.tools.reminders import service as reminder_service
from app.tools.tasks import service


EXPECTED_SAFETY_TIERS = {
    TOOL_TASKS_ADD: SafetyTier.STATE_MODIFYING,
    TOOL_TASKS_LIST: SafetyTier.READ_ONLY,
    TOOL_TASKS_COMPLETE: SafetyTier.STATE_MODIFYING,
    TOOL_TASKS_UPDATE: SafetyTier.STATE_MODIFYING,
    TOOL_TASKS_DELETE: SafetyTier.DESTRUCTIVE,
    TOOL_REMINDERS_ADD: SafetyTier.STATE_MODIFYING,
    TOOL_REMINDERS_LIST: SafetyTier.READ_ONLY,
    TOOL_REMINDERS_COMPLETE: SafetyTier.STATE_MODIFYING,
    TOOL_REMINDERS_DELETE: SafetyTier.DESTRUCTIVE,
    TOOL_MEMORY_SAVE: SafetyTier.STATE_MODIFYING,
    TOOL_MEMORY_LIST: SafetyTier.READ_ONLY,
    TOOL_MEMORY_SEARCH: SafetyTier.READ_ONLY,
    TOOL_MEMORY_DELETE: SafetyTier.DESTRUCTIVE,
    TOOL_AUTOMATION_OPEN_URL: SafetyTier.STATE_MODIFYING,
    TOOL_AUTOMATION_LAUNCH_APP: SafetyTier.STATE_MODIFYING,
}


class SafetyTierTests(unittest.TestCase):
    def test_tier_values_are_stable_strings(self):
        self.assertEqual(SafetyTier.READ_ONLY.value, "read_only")
        self.assertEqual(SafetyTier.STATE_MODIFYING.value, "state_modifying")
        self.assertEqual(SafetyTier.DESTRUCTIVE.value, "destructive")


class DefaultRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = build_default_registry()

    def test_contains_exactly_the_fifteen_standard_tools(self):
        self.assertEqual(len(self.registry.list_tools()), 15)
        self.assertEqual(set(self.registry.get_tool_names()), set(EXPECTED_SAFETY_TIERS))

    def test_every_tool_has_the_correct_safety_tier(self):
        for name, tier in EXPECTED_SAFETY_TIERS.items():
            with self.subTest(tool=name):
                self.assertEqual(self.registry.get(name).safety_tier, tier)

    def test_destructive_registry_tools_match_the_core_safety_set(self):
        destructive = {
            tool.name
            for tool in self.registry.list_tools()
            if tool.safety_tier == SafetyTier.DESTRUCTIVE
        }
        self.assertEqual(destructive, set(DESTRUCTIVE_TOOLS))

    def test_every_tool_reuses_the_shared_argument_spec(self):
        for tool in self.registry.list_tools():
            with self.subTest(tool=tool.name):
                self.assertEqual(tool.argument_spec, TOOL_ARGUMENT_SPECS[tool.name])

    def test_every_tool_carries_a_description(self):
        for tool in self.registry.list_tools():
            with self.subTest(tool=tool.name):
                self.assertTrue(tool.description)


class ToolRegistryApiTests(unittest.TestCase):
    def make_probe_tool(self, name="probe.tool", executor=None):
        return Tool(
            name=name,
            description="A probe tool used by registry tests.",
            argument_spec={},
            safety_tier=SafetyTier.READ_ONLY,
            executor=executor or (lambda arguments, database_path=None: "probe ok"),
        )

    def test_register_get_has_roundtrip(self):
        registry = ToolRegistry()
        tool = self.make_probe_tool()

        self.assertFalse(registry.has("probe.tool"))
        self.assertIsNone(registry.get("probe.tool"))

        registry.register(tool)

        self.assertTrue(registry.has("probe.tool"))
        self.assertIs(registry.get("probe.tool"), tool)
        self.assertEqual(registry.list_tools(), [tool])
        self.assertEqual(registry.get_tool_names(), ["probe.tool"])

    def test_get_unknown_tool_returns_none(self):
        self.assertIsNone(build_default_registry().get("does.not_exist"))

    def test_unregister_removes_and_returns_the_tool(self):
        registry = ToolRegistry()
        tool = self.make_probe_tool()
        registry.register(tool)

        self.assertIs(registry.unregister("probe.tool"), tool)
        self.assertFalse(registry.has("probe.tool"))
        self.assertIsNone(registry.unregister("probe.tool"))

    def test_register_rejects_non_tool_objects(self):
        registry = ToolRegistry()
        with self.assertRaises(TypeError):
            registry.register("not a tool")

    def test_registering_the_same_name_overwrites_the_tool(self):
        registry = ToolRegistry()
        first = self.make_probe_tool()
        second = self.make_probe_tool()

        registry.register(first)
        registry.register(second)

        self.assertIs(registry.get("probe.tool"), second)
        self.assertEqual(len(registry.list_tools()), 1)

    def test_validate_tool_call_normalizes_arguments(self):
        registry = build_default_registry()

        validated = registry.validate_tool_call(
            TOOL_TASKS_ADD, {"title": "  Buy milk  ", "priority": "high"}
        )

        self.assertEqual(validated, {"title": "Buy milk", "priority": "High"})

    def test_validate_tool_call_unknown_tool_raises(self):
        registry = build_default_registry()
        with self.assertRaises(ToolValidationError):
            registry.validate_tool_call("tasks.drop_all", {})

    def test_validate_tool_call_invalid_arguments_raise(self):
        registry = build_default_registry()
        with self.assertRaises(ToolValidationError):
            registry.validate_tool_call(TOOL_TASKS_COMPLETE, {"task_id": "abc"})

    def test_execute_unknown_tool_raises(self):
        with self.assertRaises(ToolValidationError):
            build_default_registry().execute("tasks.drop_all", {})

    def test_tool_without_executor_raises_on_execute(self):
        registry = ToolRegistry()
        registry.register(
            Tool(
                name=TOOL_MEMORY_LIST,
                description="A standard tool with no executor.",
                argument_spec=TOOL_ARGUMENT_SPECS[TOOL_MEMORY_LIST],
                safety_tier=SafetyTier.READ_ONLY,
            )
        )
        with self.assertRaises(RuntimeError):
            registry.execute(TOOL_MEMORY_LIST, {})

    def test_execute_passes_the_database_path_to_the_executor(self):
        registry = ToolRegistry()
        seen = []
        registry.register(
            Tool(
                name=TOOL_TASKS_LIST,
                description="Probe tool overriding tasks.list.",
                argument_spec=TOOL_ARGUMENT_SPECS[TOOL_TASKS_LIST],
                safety_tier=SafetyTier.READ_ONLY,
                executor=lambda arguments, database_path=None: seen.append(database_path)
                or "ok",
            )
        )

        result = registry.execute(TOOL_TASKS_LIST, {}, database_path="db.sqlite")

        self.assertEqual(result, "ok")
        self.assertEqual(seen, ["db.sqlite"])

    def test_custom_tool_names_cannot_bypass_the_shared_validation_layer(self):
        # Every request is validated through core.tools, which only knows the
        # standard SIRIUS tools; custom names can never sneak past the shared
        # validation and safety layer.
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="probe.custom",
                description="A tool with a non-standard name.",
                argument_spec={},
                safety_tier=SafetyTier.READ_ONLY,
                executor=lambda arguments, database_path=None: "should never run",
            )
        )
        with self.assertRaises(ToolValidationError):
            registry.execute("probe.custom", {})

    def test_tool_execute_validates_arguments_before_the_executor(self):
        seen = []
        tool = Tool(
            name=TOOL_TASKS_ADD,
            description="Probe with the real tasks.add spec.",
            argument_spec=TOOL_ARGUMENT_SPECS[TOOL_TASKS_ADD],
            safety_tier=SafetyTier.STATE_MODIFYING,
            executor=lambda arguments, database_path=None: seen.append(arguments) or "ok",
        )

        result = tool.execute({"title": "  Buy milk  ", "priority": "high"})

        self.assertEqual(result, "ok")
        self.assertEqual(seen, [{"title": "Buy milk", "priority": "High"}])


class DefaultRegistryExecutorTests(unittest.TestCase):
    """Executors run against the real services and a temporary database."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "registry-test.db"
        initialize_database(self.database_path)
        self.registry = build_default_registry()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_tasks_add_executor_creates_a_task(self):
        response = self.registry.execute(
            TOOL_TASKS_ADD,
            {"title": "Buy milk", "priority": "high"},
            database_path=self.database_path,
        )

        self.assertEqual(response, "Task created successfully! ID: 1")
        task = service.get_tasks(database_path=self.database_path)[0]
        self.assertEqual(task[1], "Buy milk")
        self.assertEqual(task[4], "High")

    def test_tasks_list_executor_formats_existing_tasks(self):
        service.add_task("Buy milk", database_path=self.database_path)

        response = self.registry.execute(
            TOOL_TASKS_LIST, {}, database_path=self.database_path
        )

        self.assertIn("[1] Buy milk", response)

    def test_tasks_complete_executor_reports_missing_tasks(self):
        response = self.registry.execute(
            TOOL_TASKS_COMPLETE, {"task_id": 42}, database_path=self.database_path
        )
        self.assertEqual(response, "Task not found.")

    def test_tasks_update_executor_updates_a_task(self):
        service.add_task("DSD assignment", database_path=self.database_path)

        response = self.registry.execute(
            TOOL_TASKS_UPDATE,
            {"task_id": 1, "priority": "high"},
            database_path=self.database_path,
        )

        self.assertEqual(response, "Task updated.")
        self.assertEqual(
            service.get_tasks(database_path=self.database_path)[0][4], "High"
        )

    def test_tasks_update_executor_reports_missing_tasks(self):
        response = self.registry.execute(
            TOOL_TASKS_UPDATE,
            {"task_id": 42, "title": "Ghost"},
            database_path=self.database_path,
        )
        self.assertEqual(response, "Task not found.")

    def test_tasks_update_rejects_protected_fields_before_execution(self):
        service.add_task("Protected", database_path=self.database_path)

        with self.assertRaises(ToolValidationError):
            self.registry.execute(
                TOOL_TASKS_UPDATE,
                {"task_id": 1, "status": "Completed"},
                database_path=self.database_path,
            )

        self.assertEqual(
            service.get_tasks(database_path=self.database_path)[0][5], "Pending"
        )

    def test_reminders_add_executor_creates_a_reminder(self):
        response = self.registry.execute(
            TOOL_REMINDERS_ADD,
            {"text": "Call dentist", "remind_at": "2026-09-01T10:00"},
            database_path=self.database_path,
        )
        self.assertEqual(response, "Reminder created successfully! ID: 1")

    def test_reminders_add_executor_rejects_invalid_datetimes_before_execution(self):
        with self.assertRaises(ToolValidationError):
            self.registry.execute(
                TOOL_REMINDERS_ADD,
                {"text": "Call dentist", "remind_at": "tomorrow"},
                database_path=self.database_path,
            )
        self.assertEqual(reminder_service.list_reminders(self.database_path), [])

    def test_reminders_list_executor_formats_existing_reminders(self):
        reminder_service.create_reminder(
            "Call dentist", "2026-09-01T10:00", self.database_path
        )

        response = self.registry.execute(
            TOOL_REMINDERS_LIST, {}, database_path=self.database_path
        )

        self.assertIn("[1] Call dentist", response)

    def test_reminders_complete_executor_reports_missing_reminders(self):
        response = self.registry.execute(
            TOOL_REMINDERS_COMPLETE,
            {"reminder_id": 42},
            database_path=self.database_path,
        )
        self.assertEqual(response, "Reminder not found.")

    def test_destructive_executors_are_wired_and_report_misses_safely(self):
        # The registry wires destructive executors (the deterministic command
        # path and the confirmation flow stay in charge of real deletions);
        # here we only prove the wiring against IDs that do not exist.
        self.assertEqual(
            self.registry.execute(
                TOOL_TASKS_DELETE, {"task_id": 42}, database_path=self.database_path
            ),
            "Task not found.",
        )
        self.assertEqual(
            self.registry.execute(
                TOOL_REMINDERS_DELETE,
                {"reminder_id": 42},
                database_path=self.database_path,
            ),
            "Reminder not found.",
        )
        self.assertEqual(
            self.registry.execute(
                TOOL_MEMORY_DELETE,
                {"memory_id": 42},
                database_path=self.database_path,
            ),
            "Memory not found.",
        )

    def test_memory_save_executor_saves_then_updates_the_same_key(self):
        first = self.registry.execute(
            TOOL_MEMORY_SAVE,
            {"key": "wifi password", "value": "secret123"},
            database_path=self.database_path,
        )
        self.assertEqual(first, "Memory saved with ID: 1.")

        second = self.registry.execute(
            TOOL_MEMORY_SAVE,
            {"key": "wifi password", "value": "new"},
            database_path=self.database_path,
        )
        self.assertEqual(second, "Memory saved with ID: 1.")

        memories = memory_service.list_memories(self.database_path)
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0][2], "new")

    def test_memory_list_executor_formats_memories(self):
        memory_service.save_memory("wifi password", "secret123", self.database_path)

        response = self.registry.execute(
            TOOL_MEMORY_LIST, {}, database_path=self.database_path
        )

        self.assertIn("[1] wifi password", response)
        self.assertIn("secret123", response)

    def test_memory_search_executor_reports_misses_and_matches(self):
        self.assertEqual(
            self.registry.execute(
                TOOL_MEMORY_SEARCH, {"query": "wifi"}, database_path=self.database_path
            ),
            "No matching memories found.",
        )

        memory_service.save_memory("wifi password", "secret123", self.database_path)
        memory_service.save_memory("birthday", "May 5", self.database_path)

        response = self.registry.execute(
            TOOL_MEMORY_SEARCH, {"query": "wifi"}, database_path=self.database_path
        )
        self.assertIn("secret123", response)
        self.assertNotIn("birthday", response)


if __name__ == "__main__":
    unittest.main()


