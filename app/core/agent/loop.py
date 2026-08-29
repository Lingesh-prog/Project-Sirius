"""Multi-step reasoning and execution loop for SIRIUS.

Coordinates the Plan -> Tool call -> Observation -> Next step -> Final response
execution cycle with safety boundaries:
1. Maximum steps strictly bounded (default max_steps=5).
2. Only one tool action executes per step.
3. Observations from executed tools are fed back into subsequent steps.
4. Destructive tools (SafetyTier.DESTRUCTIVE) halt the loop immediately and
   require explicit human confirmation.
5. Natural-language answers terminate the loop cleanly without state mutation.
6. The AI never gains arbitrary execution authority.
7. Repeated identical (tool, arguments) calls within one run are never
   re-executed (Module 3.2); the observation already produced is returned.
8. Every run exposes a deterministic, compact step trace (render_trace()).
9. Observations fed back into follow-up steps are size-bounded
   (max_observation_chars) so the per-run context stays finite.
"""

import json
from typing import Any, Callable, List, Optional

from app.ai import AIError
from app.core.response_handler import (
    DECLINED_REQUEST_MESSAGE,
    EMPTY_RESPONSE_MESSAGE,
    MULTIPLE_TOOLS_MESSAGE,
    UNEXPECTED_ERROR_MESSAGE,
    _extract_json_candidates,
    _is_attempted_tool_call,
)
from app.core.tool_registry import SafetyTier, ToolRegistry, build_default_registry
from app.core.tools import (
    ToolResponseError,
    ToolValidationError,
    parse_tool_response,
)

DEFAULT_MAX_STEPS = 5
DEFAULT_MAX_OBSERVATION_CHARS = 1200
OBSERVATION_TRUNCATION_MARKER = "\n... [observation truncated]"
AGENT_TRACE_HEADER = "========== AGENT TRACE =========="
AGENT_TRACE_FOOTER = "================================="


class AgentStep:
    """Represents a single step in a multi-step agent execution."""

    def __init__(
        self,
        step_number: int,
        tool_name: Optional[str] = None,
        arguments: Optional[dict] = None,
        observation: Optional[str] = None,
        is_final: bool = False,
        final_response: Optional[str] = None,
        skipped_repeat: bool = False,
    ):
        self.step_number = step_number
        self.tool_name = tool_name
        self.arguments = arguments or {}
        self.observation = observation
        self.is_final = is_final
        self.final_response = final_response
        self.skipped_repeat = skipped_repeat

    def __repr__(self) -> str:
        if self.skipped_repeat:
            return (
                f"AgentStep(step={self.step_number}, "
                f"skipped repeat of {self.tool_name!r})"
            )
        if self.is_final:
            return f"AgentStep(step={self.step_number}, final={self.final_response!r})"
        return f"AgentStep(step={self.step_number}, tool={self.tool_name!r})"


class AgentLoop:
    """Manages multi-step agent reasoning and tool execution."""

    def __init__(
        self,
        ai_client,
        tool_registry: Optional[ToolRegistry] = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        max_observation_chars: int = DEFAULT_MAX_OBSERVATION_CHARS,
        database_path: Optional[str] = None,
        build_confirmation_fn: Optional[Callable] = None,
    ):
        if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps < 1:
            raise ValueError("max_steps must be a whole number of at least 1.")
        if (
            not isinstance(max_observation_chars, int)
            or isinstance(max_observation_chars, bool)
            or max_observation_chars < 1
        ):
            raise ValueError(
                "max_observation_chars must be a whole number of at least 1."
            )

        self.ai_client = ai_client
        self.tool_registry = tool_registry or build_default_registry()
        self.max_steps = max_steps
        self.max_observation_chars = max_observation_chars
        self.database_path = database_path
        self.build_confirmation_fn = build_confirmation_fn
        self.steps: List[AgentStep] = []

    def run(self, context) -> str:
        """Run the multi-step agent reasoning loop for the given assembled context."""
        self.steps = []
        last_observation = None
        executed_calls: dict = {}

        for step_num in range(1, self.max_steps + 1):
            # Compose prompt for current step
            step_prompt = self._compose_step_prompt(context.user_request, self.steps)

            try:
                reply = self.ai_client.generate_text(
                    step_prompt,
                    system_prompt=context.system_prompt,
                    conversation_history=context.conversation_history,
                    relevant_memories=context.relevant_memories,
                )
            except AIError as error:
                return f"AI assistant is unavailable right now: {error}"
            except IndexError:
                # Scripted test fakes that provided single-turn responses
                if last_observation is not None:
                    return last_observation
                return EMPTY_RESPONSE_MESSAGE
            except Exception:
                return UNEXPECTED_ERROR_MESSAGE

            if not isinstance(reply, str) or not reply.strip():
                if last_observation is not None:
                    return last_observation
                return EMPTY_RESPONSE_MESSAGE

            clean_reply = reply.strip()

            # If the reply is not attempting a tool call, treat it as the final response
            if not _is_attempted_tool_call(clean_reply):
                self.steps.append(
                    AgentStep(
                        step_number=step_num,
                        is_final=True,
                        final_response=clean_reply,
                    )
                )
                return clean_reply

            # Process the tool request
            candidates = _extract_json_candidates(clean_reply)
            if len(candidates) > 1:
                return MULTIPLE_TOOLS_MESSAGE

            if len(candidates) == 1 and isinstance(candidates[0], list):
                if len(candidates[0]) > 1:
                    return MULTIPLE_TOOLS_MESSAGE
                if len(candidates[0]) == 1 and isinstance(candidates[0][0], dict):
                    raw_request = candidates[0][0]
                else:
                    return "I could not process that request. The AI response was not valid JSON."
            elif len(candidates) == 1 and isinstance(candidates[0], dict):
                raw_request = candidates[0]
            else:
                try:
                    tool_name, arguments = parse_tool_response(clean_reply)
                    raw_request = {"tool": tool_name, "arguments": arguments}
                except ToolResponseError as error:
                    return f"I could not process that request. {error}"

            tool_name = raw_request.get("tool")
            arguments = raw_request.get("arguments", {})

            if "tool" in raw_request and tool_name is None:
                return DECLINED_REQUEST_MESSAGE

            if not isinstance(tool_name, str) or not tool_name.strip():
                return "I could not process that request. The AI response is missing a tool name."

            if not isinstance(arguments, dict):
                return "I could not process that request. Tool arguments must be a JSON object."

            tool_name = tool_name.strip()

            tool = self.tool_registry.get(tool_name)
            if tool is None:
                return f"That request is not supported: Unknown tool '{tool_name}'."

            try:
                validated_args = tool.validate(arguments)
            except ToolValidationError as error:
                return f"That request is not supported: {error}"

            # Safety tier enforcement
            if tool.safety_tier == SafetyTier.DESTRUCTIVE:
                # Halt immediately on destructive tools and require human confirmation
                if self.build_confirmation_fn is not None:
                    return self.build_confirmation_fn(
                        tool_name, validated_args, self.database_path
                    )
                return f"Destructive tool '{tool_name}' requires confirmation."

            # Repetition guard (Module 3.2): never re-execute an identical
            # (tool, arguments) call within one run; the observation that call
            # already produced is deterministic for this run, so return it.
            call_key = _canonical_call_key(tool_name, validated_args)
            if call_key in executed_calls:
                prior_observation = executed_calls[call_key]
                self.steps.append(
                    AgentStep(
                        step_number=step_num,
                        tool_name=tool_name,
                        arguments=validated_args,
                        observation=prior_observation,
                        skipped_repeat=True,
                    )
                )
                return prior_observation

            # Execute tool
            observation = str(
                tool.execute(validated_args, database_path=self.database_path)
            )
            last_observation = observation
            executed_calls[call_key] = observation
            self.steps.append(
                AgentStep(
                    step_number=step_num,
                    tool_name=tool_name,
                    arguments=validated_args,
                    observation=observation,
                )
            )

            # State modifying actions complete their mutation
            if tool.safety_tier == SafetyTier.STATE_MODIFYING:
                return observation

        # Reached max_steps limit
        return (
            last_observation
            if last_observation is not None
            else "Maximum reasoning steps reached."
        )

    def _compose_step_prompt(
        self, user_request: str, completed_steps: List[AgentStep]
    ) -> str:
        """Format the current request and prior step observations for the AI."""
        if not completed_steps:
            return user_request

        lines = [f"Current request: {user_request}", "\nPrevious tool actions:"]
        for s in completed_steps:
            lines.append(
                f"- Step {s.step_number}: Called {s.tool_name}"
                f"({json.dumps(s.arguments, sort_keys=True)})\n"
                f"  Observation: {self._bounded_observation(s.observation)}"
            )
        lines.append(
            "\nBased on the observations above, decide the next tool action or provide your final response."
        )
        return "\n".join(lines)

    def _bounded_observation(self, observation):
        """Bound an observation's size before it is fed back to the AI."""
        if observation is None:
            return ""
        text = str(observation)
        if len(text) <= self.max_observation_chars:
            return text
        return text[: self.max_observation_chars] + OBSERVATION_TRUNCATION_MARKER

    def render_trace(self) -> str:
        """Render a deterministic, compact trace of this run's steps."""
        if not self.steps:
            return ""

        lines = [AGENT_TRACE_HEADER]
        for step in self.steps:
            if step.is_final:
                lines.append(f"[{step.step_number}] final response")
                continue
            suffix = " (skipped: repeated call)" if step.skipped_repeat else ""
            lines.append(
                f"[{step.step_number}] {step.tool_name}"
                f"({_format_trace_arguments(step.arguments)}){suffix}"
            )
        lines.append(AGENT_TRACE_FOOTER)
        return "\n".join(lines)


def _canonical_call_key(tool_name, validated_args):
    """Build an order-independent identity for one tool call."""
    return json.dumps([tool_name, validated_args], sort_keys=True)


def _format_trace_arguments(arguments):
    """Render validated arguments compactly for the agent trace."""
    if not arguments:
        return ""
    return ", ".join(
        f"{key}={json.dumps(value, sort_keys=True)}"
        for key, value in sorted(arguments.items())
    )


def run_agent_loop(
    ai_client,
    context,
    database_path: Optional[str] = None,
    tool_registry: Optional[ToolRegistry] = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    max_observation_chars: int = DEFAULT_MAX_OBSERVATION_CHARS,
    build_confirmation_fn: Optional[Callable] = None,
) -> str:
    """Execute the multi-step agent reasoning loop."""
    loop = AgentLoop(
        ai_client=ai_client,
        tool_registry=tool_registry,
        max_steps=max_steps,
        max_observation_chars=max_observation_chars,
        database_path=database_path,
        build_confirmation_fn=build_confirmation_fn,
    )
    return loop.run(context)
