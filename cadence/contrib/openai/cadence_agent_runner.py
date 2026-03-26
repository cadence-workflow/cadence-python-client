import dataclasses
import sys
from typing import Any, Unpack, override
from agents import (
    Agent,
    Handoff,
    RunConfig,
    RunResult,
    RunResultStreaming,
    RunState,
    TContext,
    TResponseInputItem,
)
from agents.run import (
    DEFAULT_MAX_TURNS,
    AgentRunner,
    RunOptions,
    set_default_agent_runner,
)
from cadence.contrib.openai.cadence_model import CadenceModel

# TraceCtxManager assumes that the model invocation is running in the same context.
# This is no longer true with Cadence workflows, where each invocation is running in a separate coroutine.
# Thus, suppress the error
_original_unraisablehook = sys.unraisablehook


def _suppress_ctx_error_hook(args) -> None:
    if isinstance(args.exc_value, ValueError) and (
        isinstance(args.exc_value, ValueError)
        and "was created in a different Context" in str(args.exc_value)
    ):
        return
    _original_unraisablehook(args)


sys.unraisablehook = _suppress_ctx_error_hook


def _replace_model_in_agent(
    agent: Agent[Any],
) -> Agent[Any]:
    if isinstance(agent.model, CadenceModel):
        return agent

    name = agent.model
    if not isinstance(name, str):
        raise ValueError("Model name must be a string")

    agent.model = CadenceModel(model_name=name)

    for i, handoff in enumerate(agent.handoffs):
        if isinstance(handoff, Agent):
            agent.handoffs[i] = _replace_model_in_agent(handoff)
        elif isinstance(handoff, Handoff):
            raise ValueError("Handoff is not yet supported")
        else:
            raise TypeError(f"Unknown handoff type: {type(handoff)}")

    return agent


class CadenceAgentRunner(AgentRunner):
    @override
    async def run(
        self,
        starting_agent: Agent[TContext],
        input: str | list[TResponseInputItem] | RunState[TContext],
        **kwargs: Unpack[RunOptions[TContext]],
    ) -> RunResult:

        context = kwargs.get("context")
        max_turns = kwargs.get("max_turns", DEFAULT_MAX_TURNS)
        hooks = kwargs.get("hooks")
        run_config = kwargs.get("run_config")
        error_handlers = kwargs.get("error_handlers")
        previous_response_id = kwargs.get("previous_response_id")
        auto_previous_response_id = kwargs.get("auto_previous_response_id", False)
        conversation_id = kwargs.get("conversation_id")
        session = kwargs.get("session")

        # if starting_agent.tools:
        #     raise ValueError(f"Tools are not yet supported")

        if starting_agent.mcp_servers:
            raise ValueError("MCP servers are not yet supported")

        if not run_config:
            run_config = RunConfig()

        if run_config.model:
            if not isinstance(run_config.model, str):
                raise ValueError("Model must be a string")
            run_config = dataclasses.replace(
                run_config,
                model=CadenceModel(run_config.model),
            )

        return await super().run(
            starting_agent=_replace_model_in_agent(starting_agent),
            input=input,
            context=context,
            max_turns=max_turns,
            hooks=hooks,
            run_config=run_config,
            error_handlers=error_handlers,
            previous_response_id=previous_response_id,
            auto_previous_response_id=auto_previous_response_id,
            conversation_id=conversation_id,
            session=session,
        )

    @override
    def run_sync(
        self,
        starting_agent: Agent[TContext],
        input: str | list[TResponseInputItem],
        **kwargs: Any,
    ) -> RunResult:
        raise RuntimeError("Model run_sync is not yet supported.")

    @override
    def run_streamed(
        self,
        starting_agent: Agent[TContext],
        input: str | list[TResponseInputItem],
        **kwargs: Any,
    ) -> RunResultStreaming:
        raise RuntimeError("Model run_streamed is not yet supported.")


set_default_agent_runner(CadenceAgentRunner())
