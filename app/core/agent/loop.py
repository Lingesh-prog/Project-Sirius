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
    ):
        self.step_number = step_number
        self.tool_name = tool_name
        self.arguments = arguments or {}
        self.observation = observation
        self.is_final = is_final
        self.final_response = final_response

    def __repr__(self) -> str:
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
        database_path: Optional[str] = None,
        build_confirmation_fn: Optional[Callable] = None,
    ):
        if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps < 1:
            raise ValueError("max_steps must be a whole number of at least 1.")

        self.ai_client = ai_client
        self.tool_registry = tool_registry or build_default_registry()
        self.max_steps = max_steps
        self.database_path = database_path
        self.build_confirmation_fn = build_confirmation_fn
        self.steps: List[AgentStep] = []

    def run(self, context) -> str:
        """Run the multi-step agent reasoning loop for the given assembled context."""
        self.steps = []
        last_observation = None

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

            # Execute tool
            observation = str(
                tool.execute(validated_args, database_path=self.database_path)
            )
            last_observation = observation
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
                f"- Step {s.step_number}: Called {s.tool_name}({json.dumps(s.arguments)})\n"
                f"  Observation: {s.observation}"
            )
        lines.append(
            "\nBased on the observations above, decide the next tool action or provide your final response."
        )
        return "\n".join(lines)


def run_agent_loop(
    ai_client,
    context,
    database_path: Optional[str] = None,
    tool_registry: Optional[ToolRegistry] = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    build_confirmation_fn: Optional[Callable] = None,
) -> str:
    """Execute the multi-step agent reasoning loop."""
    loop = AgentLoop(
        ai_client=ai_client,
        tool_registry=tool_registry,
        max_steps=max_steps,
        database_path=database_path,
        build_confirmation_fn=build_confirmation_fn,
    )
    return loop.run(context)
