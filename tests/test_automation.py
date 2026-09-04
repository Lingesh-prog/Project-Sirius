"""Tests for the Module 3.3 safe automation foundation.

automation.open_url and automation.launch_app are the only automation actions
SIRIUS exposes. Every test injects fake browser/application launchers, so no
test can open a real browser, start a real application, or reach the network.
The security tests prove that shell commands, executable paths, PowerShell,
cmd, Python, and dangerous URL schemes are rejected before any OS call.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.core.agent.loop import AgentLoop
from app.core.assistant import handle_command
from app.core.tool_registry import SafetyTier, build_default_registry
from app.core.tools import (
    ALLOWED_URL_SCHEMES,
    DESTRUCTIVE_TOOLS,
    SAFE_AUTOMATION_APPS,
    TOOL_ARGUMENT_SPECS,
    TOOL_AUTOMATION_LAUNCH_APP,
    TOOL_AUTOMATION_OPEN_URL,
    ToolValidationError,
    build_tool_catalog,
    validate_tool_request,
)
from app.storage.database import initialize_database
from app.tools.automation import service as automation_service

from tests.test_agent_loop import ScriptedAgentClient, make_context, tool_json


class FakeLauncher:
    """Fake browser/application launcher that records calls, never the OS."""

    def __init__(self, result=True, error=None):
        self.result = result
        self.error = error
        self.targets = []
        self.extra_args = []
        self.extra_kwargs = []

    def __call__(self, target, *extra, **kwargs):
        self.targets.append(target)
        self.extra_args.append(extra)
        self.extra_kwargs.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


class UrlValidationTests(unittest.TestCase):
    """core.tools accepts only well-formed http(s) URLs for automation.open_url."""

    def validate(self, url):
        return validate_tool_request(TOOL_AUTOMATION_OPEN_URL, {"url": url})

    def test_valid_http_and_https_urls_are_accepted(self):
        for url in (
            "https://example.com",
            "http://example.com",
            "https://example.com/search?q=sirius",
            "http://example.com/path/to/page",
            "HTTPS://EXAMPLE.COM",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.validate(url), {"url": url})

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(
            self.validate("  https://example.com  "), {"url": "https://example.com"}
        )

    def test_the_url_argument_is_required(self):
        for arguments in ({}, {"url": ""}, {"url": "   "}):
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(ToolValidationError, "url"):
                    validate_tool_request(TOOL_AUTOMATION_OPEN_URL, arguments)

    def test_the_url_must_be_a_string(self):
        for bad in (123, 1.5, True, None, ["https://example.com"]):
            with self.subTest(value=bad):
                with self.assertRaises(ToolValidationError):
                    self.validate(bad)

    def test_dangerous_url_schemes_are_rejected(self):
        for url in (
            "file:///C:/Windows/System32/calc.exe",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "data:text/html;base64,PHNjcmlwdD4=",
            "vbscript:msgbox",
            "ftp://example.com/file",
            "chrome://settings",
            "myapp://open",
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(ToolValidationError, "http"):
                    self.validate(url)

    def test_urls_without_a_scheme_or_host_are_rejected(self):
        for url in (
            "example.com",
            "www.example.com",
            "https:",
            "https://",
            "//example.com",
            "https:/example.com",
            "/etc/passwd",
            "C:\\Windows\\notepad.exe",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ToolValidationError):
                    self.validate(url)

    def test_urls_containing_whitespace_are_rejected(self):
        for url in (
            "https://ex ample.com",
            "https://example.com/a b",
            "https://example.com\r\nSet-Cookie: x=1",
            "https://example.com\tpath",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ToolValidationError):
                    self.validate(url)


class AppValidationTests(unittest.TestCase):
    """core.tools accepts only identifiers from the fixed safe allowlist."""

    def validate(self, app):
        return validate_tool_request(TOOL_AUTOMATION_LAUNCH_APP, {"app": app})

    def test_allowlisted_apps_are_accepted_case_insensitively(self):
        self.assertEqual(self.validate("notepad"), {"app": "notepad"})
        self.assertEqual(self.validate("Notepad"), {"app": "notepad"})
        self.assertEqual(self.validate("  NOTEPAD  "), {"app": "notepad"})
        self.assertEqual(self.validate("Calculator"), {"app": "calculator"})

    def test_the_app_argument_is_required(self):
        for arguments in ({}, {"app": ""}, {"app": "   "}):
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(ToolValidationError, "app"):
                    validate_tool_request(TOOL_AUTOMATION_LAUNCH_APP, arguments)

    def test_the_app_argument_must_be_a_string(self):
        for bad in (1, 1.5, True, None, ["notepad"]):
            with self.subTest(value=bad):
                with self.assertRaises(ToolValidationError):
                    self.validate(bad)

    def test_unknown_applications_are_rejected(self):
        for app in ("paint", "mspaint", "edge", "explorer", "spotify"):
            with self.subTest(app=app):
                with self.assertRaisesRegex(ToolValidationError, "SIRIUS can launch"):
                    self.validate(app)

    def test_executable_names_and_paths_are_rejected(self):
        for app in (
            "notepad.exe",
            "calc.exe",
            "cmd.exe",
            "C:\\Windows\\System32\\calc.exe",
            "C:\\Windows\\notepad.exe",
            "%SystemRoot%\\notepad.exe",
            ".\\notepad",
        ):
            with self.subTest(app=app):
                with self.assertRaises(ToolValidationError):
                    self.validate(app)

    def test_shell_and_interpreter_names_are_rejected(self):
        for app in ("cmd", "powershell", "pwsh", "python", "python3", "bash", "sh"):
            with self.subTest(app=app):
                with self.assertRaises(ToolValidationError):
                    self.validate(app)

    def test_shell_composites_are_rejected(self):
        for app in (
            "notepad & calc",
            "notepad && calc",
            "notepad; calc",
            "notepad | calc",
        ):
            with self.subTest(app=app):
                with self.assertRaises(ToolValidationError):
                    self.validate(app)


class AutomationServiceTests(unittest.TestCase):
    """The service launches only validated targets through injectable launchers."""

    def test_open_url_opens_through_the_injected_opener(self):
        opener = FakeLauncher()

        self.assertTrue(
            automation_service.open_url("https://example.com", open_url_fn=opener)
        )
        self.assertEqual(opener.targets, ["https://example.com"])

    def test_open_url_reports_failure_without_raising(self):
        failing = FakeLauncher(error=OSError("no default browser"))
        self.assertFalse(
            automation_service.open_url("https://example.com", open_url_fn=failing)
        )
        returning_false = FakeLauncher(result=False)
        self.assertFalse(
            automation_service.open_url(
                "https://example.com", open_url_fn=returning_false
            )
        )

    def test_open_url_revalidates_the_url_rules_at_the_os_boundary(self):
        opener = FakeLauncher()
        for bad in (
            "javascript:alert(1)",
            "file:///C:/x",
            "ftp://example.com",
            "",
            "   ",
            None,
            123,
            "not a url",
            "https://ex ample.com",
        ):
            with self.subTest(url=bad):
                with self.assertRaises(ValueError):
                    automation_service.open_url(bad, open_url_fn=opener)
        self.assertEqual(opener.targets, [])

    def test_launch_app_starts_the_fixed_allowlisted_executable(self):
        launcher = FakeLauncher()
        self.assertTrue(automation_service.launch_app("notepad", launch_fn=launcher))
        self.assertEqual(launcher.targets, ["notepad.exe"])

        launcher = FakeLauncher()
        self.assertTrue(
            automation_service.launch_app("Calculator", launch_fn=launcher)
        )
        self.assertEqual(launcher.targets, ["calc.exe"])

    def test_launch_app_never_passes_extra_arguments_or_a_shell(self):
        launcher = FakeLauncher()
        automation_service.launch_app("notepad", launch_fn=launcher)

        self.assertEqual(launcher.extra_args, [()])
        self.assertEqual(launcher.extra_kwargs, [{}])

    def test_launch_app_reports_failure_without_raising(self):
        failing = FakeLauncher(error=OSError("application missing"))
        self.assertFalse(automation_service.launch_app("notepad", launch_fn=failing))
        returning_false = FakeLauncher(result=False)
        self.assertFalse(
            automation_service.launch_app("notepad", launch_fn=returning_false)
        )

    def test_launch_app_rejects_everything_off_the_allowlist(self):
        launcher = FakeLauncher()
        for app in (
            "paint",
            "cmd",
            "powershell",
            "python",
            "notepad.exe",
            "C:\\Windows\\notepad.exe",
            "",
            "   ",
            None,
            1,
        ):
            with self.subTest(app=app):
                with self.assertRaises(ValueError):
                    automation_service.launch_app(app, launch_fn=launcher)
        self.assertEqual(launcher.targets, [])


class AllowlistAndCatalogTests(unittest.TestCase):
    """The safety constants and the AI-facing catalog expose exactly the two actions."""

    def test_url_schemes_are_pinned_to_http_and_https(self):
        self.assertEqual(ALLOWED_URL_SCHEMES, ("http", "https"))

    def test_the_application_allowlist_is_small_and_windows_safe(self):
        self.assertEqual(
            {name: info["executable"] for name, info in SAFE_AUTOMATION_APPS.items()},
            {"notepad": "notepad.exe", "calculator": "calc.exe"},
        )

    def test_automation_tools_are_in_the_shared_argument_specs(self):
        self.assertEqual(
            TOOL_ARGUMENT_SPECS[TOOL_AUTOMATION_OPEN_URL], {"url": (True, "url")}
        )
        self.assertEqual(
            TOOL_ARGUMENT_SPECS[TOOL_AUTOMATION_LAUNCH_APP], {"app": (True, "app")}
        )

    def test_catalog_lists_the_automation_tools(self):
        catalog = build_tool_catalog()

        self.assertIn("- automation.open_url(url: <http or https URL>)", catalog)
        self.assertIn("- automation.launch_app(app: <allowlisted app>)", catalog)


class RegistryAutomationTests(unittest.TestCase):
    """Both automation tools are registered with the shared safety machinery."""

    def setUp(self):
        self.registry = build_default_registry()

    def test_both_automation_tools_are_registered(self):
        names = self.registry.get_tool_names()

        self.assertIn(TOOL_AUTOMATION_OPEN_URL, names)
        self.assertIn(TOOL_AUTOMATION_LAUNCH_APP, names)
        self.assertEqual(len(names), 15)

    def test_automation_tools_are_state_modifying_never_destructive(self):
        for name in (TOOL_AUTOMATION_OPEN_URL, TOOL_AUTOMATION_LAUNCH_APP):
            with self.subTest(tool=name):
                tool = self.registry.get(name)
                self.assertEqual(tool.safety_tier, SafetyTier.STATE_MODIFYING)
                self.assertNotIn(name, DESTRUCTIVE_TOOLS)

    def test_automation_tools_reuse_the_shared_specs_and_describe_themselves(self):
        for name in (TOOL_AUTOMATION_OPEN_URL, TOOL_AUTOMATION_LAUNCH_APP):
            with self.subTest(tool=name):
                tool = self.registry.get(name)
                self.assertEqual(tool.argument_spec, TOOL_ARGUMENT_SPECS[name])
                self.assertTrue(tool.description)

    def test_registry_validation_goes_through_core_tools(self):
        self.assertEqual(
            self.registry.validate_tool_call(
                TOOL_AUTOMATION_OPEN_URL, {"url": "https://example.com"}
            ),
            {"url": "https://example.com"},
        )
        self.assertEqual(
            self.registry.validate_tool_call(
                TOOL_AUTOMATION_LAUNCH_APP, {"app": "Notepad"}
            ),
            {"app": "notepad"},
        )
        with self.assertRaises(ToolValidationError):
            self.registry.validate_tool_call(
                TOOL_AUTOMATION_OPEN_URL, {"url": "javascript:alert(1)"}
            )
        with self.assertRaises(ToolValidationError):
            self.registry.validate_tool_call(
                TOOL_AUTOMATION_LAUNCH_APP, {"app": "powershell"}
            )

    def test_open_url_executor_reports_success_and_clean_failures(self):
        with mock.patch(
            "app.tools.automation.service._open_in_browser", FakeLauncher()
        ) as opener:
            response = self.registry.execute(
                TOOL_AUTOMATION_OPEN_URL, {"url": "https://example.com"}
            )
        self.assertEqual(response, "Opening https://example.com in your default browser.")
        self.assertEqual(opener.targets, ["https://example.com"])

        with mock.patch(
            "app.tools.automation.service._open_in_browser",
            FakeLauncher(error=OSError("browser unavailable")),
        ):
            response = self.registry.execute(
                TOOL_AUTOMATION_OPEN_URL, {"url": "https://example.com"}
            )
        self.assertEqual(
            response, "Could not open https://example.com in your default browser."
        )
        self.assertNotIn("OSError", response)
        self.assertNotIn("Traceback", response)

    def test_launch_app_executor_reports_success_and_clean_failures(self):
        with mock.patch(
            "app.tools.automation.service._launch_executable", FakeLauncher()
        ):
            response = self.registry.execute(
                TOOL_AUTOMATION_LAUNCH_APP, {"app": "notepad"}
            )
        self.assertEqual(response, "Launching Notepad.")

        with mock.patch(
            "app.tools.automation.service._launch_executable",
            FakeLauncher(error=OSError("missing")),
        ):
            response = self.registry.execute(
                TOOL_AUTOMATION_LAUNCH_APP, {"app": "calculator"}
            )
        self.assertEqual(response, "Could not launch Calculator.")
        self.assertNotIn("OSError", response)
        self.assertNotIn("Traceback", response)

    def test_automation_executors_do_not_need_a_database(self):
        with mock.patch(
            "app.tools.automation.service._launch_executable", FakeLauncher()
        ):
            response = self.registry.execute(
                TOOL_AUTOMATION_LAUNCH_APP, {"app": "notepad"}, database_path=None
            )
        self.assertEqual(response, "Launching Notepad.")


class AgentLoopAutomationTests(unittest.TestCase):
    """Automation runs through the existing Module 3.1/3.2 agent-loop pathway."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.temporary_directory.name) / "automation-loop-test.db"
        )
        initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def make_loop(self, client, **overrides):
        options = {"ai_client": client, "database_path": self.database_path}
        options.update(overrides)
        return AgentLoop(**options)

    def test_ai_can_open_a_url_through_the_agent_loop(self):
        opener = FakeLauncher()
        client = ScriptedAgentClient(
            replies=[
                tool_json(TOOL_AUTOMATION_OPEN_URL, {"url": "https://example.com"})
            ]
        )
        loop = self.make_loop(client)

        with mock.patch("app.tools.automation.service._open_in_browser", opener):
            response = loop.run(make_context("Open example.com"))

        self.assertEqual(
            response, "Opening https://example.com in your default browser."
        )
        self.assertEqual(opener.targets, ["https://example.com"])
        self.assertEqual(client.calls, 1)  # state-modifying: run ends after one action
        self.assertEqual(
            [step.tool_name for step in loop.steps], [TOOL_AUTOMATION_OPEN_URL]
        )
        self.assertFalse(loop.steps[0].is_final)

    def test_ai_can_launch_an_allowlisted_app_through_the_agent_loop(self):
        launcher = FakeLauncher()
        client = ScriptedAgentClient(
            replies=[tool_json(TOOL_AUTOMATION_LAUNCH_APP, {"app": "Calculator"})]
        )
        loop = self.make_loop(client)

        with mock.patch("app.tools.automation.service._launch_executable", launcher):
            response = loop.run(make_context("Open the calculator"))

        self.assertEqual(response, "Launching Calculator.")
        self.assertEqual(launcher.targets, ["calc.exe"])

    def test_automation_failures_produce_clean_observations(self):
        client = ScriptedAgentClient(
            replies=[
                tool_json(TOOL_AUTOMATION_OPEN_URL, {"url": "https://example.com"})
            ]
        )
        loop = self.make_loop(client)

        with mock.patch(
            "app.tools.automation.service._open_in_browser",
            FakeLauncher(error=OSError("browser exploded")),
        ):
            response = loop.run(make_context("Open example.com"))

        self.assertEqual(
            response, "Could not open https://example.com in your default browser."
        )
        self.assertNotIn("OSError", response)
        self.assertNotIn("browser exploded", response)
        self.assertNotIn("Traceback", response)

    def test_the_run_ends_after_one_automation_action_so_repeats_cannot_execute(self):
        # Automation tools are state modifying: the Module 3.1 loop returns
        # immediately after the first execution, so an identical repeated
        # automation call inside one run can never even be attempted. The
        # launcher must therefore run exactly once, whatever the AI replies.
        opener = FakeLauncher()
        client = ScriptedAgentClient(
            replies=[
                tool_json(TOOL_AUTOMATION_OPEN_URL, {"url": "https://example.com"}),
                tool_json(TOOL_AUTOMATION_OPEN_URL, {"url": "https://example.com"}),
                "this reply must never be consumed",
            ]
        )
        loop = self.make_loop(client)

        with mock.patch("app.tools.automation.service._open_in_browser", opener):
            response = loop.run(make_context("Open example.com"))

        self.assertEqual(
            response, "Opening https://example.com in your default browser."
        )
        self.assertEqual(opener.targets, ["https://example.com"])  # executed once
        self.assertEqual(client.calls, 1)  # run ended before the repeat was generated
        self.assertEqual(
            [(step.tool_name, step.skipped_repeat) for step in loop.steps],
            [(TOOL_AUTOMATION_OPEN_URL, False)],
        )


    def test_a_second_automation_action_is_never_executed_in_the_same_run(self):
        opener = FakeLauncher()
        client = ScriptedAgentClient(
            replies=[
                tool_json(TOOL_AUTOMATION_OPEN_URL, {"url": "https://example.com"}),
                tool_json(TOOL_AUTOMATION_OPEN_URL, {"url": "https://example.org"}),
                "done",
            ]
        )
        loop = self.make_loop(client)

        with mock.patch("app.tools.automation.service._open_in_browser", opener):
            response = loop.run(make_context("Open two sites"))

        self.assertEqual(
            response, "Opening https://example.com in your default browser."
        )
        self.assertEqual(opener.targets, ["https://example.com"])
        self.assertEqual(client.calls, 1)

    def test_security_attempts_never_reach_the_launcher(self):
        attempts = [
            tool_json(TOOL_AUTOMATION_LAUNCH_APP, {"app": "powershell"}),
            tool_json(TOOL_AUTOMATION_LAUNCH_APP, {"app": "cmd"}),
            tool_json(TOOL_AUTOMATION_LAUNCH_APP, {"app": "python"}),
            tool_json(TOOL_AUTOMATION_LAUNCH_APP, {"app": "notepad.exe"}),
            tool_json(
                TOOL_AUTOMATION_LAUNCH_APP,
                {"app": "C:\\Windows\\System32\\calc.exe"},
            ),
            tool_json(
                TOOL_AUTOMATION_OPEN_URL,
                {"url": "file:///C:/Windows/System32/calc.exe"},
            ),
            tool_json(TOOL_AUTOMATION_OPEN_URL, {"url": "javascript:alert(1)"}),
            tool_json(TOOL_AUTOMATION_OPEN_URL, {"url": "data:text/html,hi"}),
        ]
        launcher = FakeLauncher()

        for attempt in attempts:
            with self.subTest(attempt=attempt):
                client = ScriptedAgentClient(replies=[attempt])
                loop = self.make_loop(client)
                with mock.patch(
                    "app.tools.automation.service._launch_executable", launcher
                ), mock.patch(
                    "app.tools.automation.service._open_in_browser", launcher
                ):
                    response = loop.run(make_context("do it"))
                self.assertIn("That request is not supported:", response)

        self.assertEqual(launcher.targets, [])

    def test_automation_trace_is_deterministic(self):
        client = ScriptedAgentClient(
            replies=[
                tool_json(TOOL_AUTOMATION_OPEN_URL, {"url": "https://example.com"})
            ]
        )
        loop = self.make_loop(client)

        with mock.patch(
            "app.tools.automation.service._open_in_browser", FakeLauncher()
        ):
            loop.run(make_context("Open example.com"))

        lines = loop.render_trace().splitlines()
        self.assertEqual(
            lines[1], '[1] automation.open_url(url="https://example.com")'
        )

    def test_assistant_routes_automation_through_the_same_agent_path(self):
        opener = FakeLauncher()
        client = ScriptedAgentClient(
            replies=[
                tool_json(TOOL_AUTOMATION_OPEN_URL, {"url": "https://example.com"})
            ]
        )
        trace = []

        with mock.patch("app.tools.automation.service._open_in_browser", opener):
            response = handle_command(
                "please open https://example.com in my browser",
                database_path=self.database_path,
                ai_client=client,
                agent_trace=trace,
            )

        self.assertEqual(
            response, "Opening https://example.com in your default browser."
        )
        self.assertEqual(opener.targets, ["https://example.com"])
        self.assertEqual(len(trace), 1)
        self.assertIn("automation.open_url", trace[0])


if __name__ == "__main__":
    unittest.main()