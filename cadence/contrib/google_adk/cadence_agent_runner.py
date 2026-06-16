from __future__ import annotations

import sys
import threading
from typing import Any, Callable

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.run_config import StreamingMode
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import Runner

from cadence.contrib.google_adk.cadence_model import CadenceModel

_original_unraisablehook: Callable[[Any], None] | None = None
_hooks_install_lock = threading.Lock()


def _suppress_adk_cleanup_error_hook(args) -> None:
    message = str(args.exc_value)
    if isinstance(args.exc_value, ValueError) and (
        "was created in a different Context" in message
    ):
        return
    if isinstance(args.exc_value, RuntimeError) and (
        "aclose(): asynchronous generator is already running" in message
    ):
        return
    if _original_unraisablehook is not None:
        _original_unraisablehook(args)
        return
    sys.__unraisablehook__(args)


def _install_suppression_hooks() -> None:
    global _original_unraisablehook
    if sys.unraisablehook is _suppress_adk_cleanup_error_hook:
        return
    _original_unraisablehook = sys.unraisablehook
    sys.unraisablehook = _suppress_adk_cleanup_error_hook

    try:
        from opentelemetry import context as otel_context
    except ImportError:
        return

    def _suppress_otel_context_detach(token) -> None:
        try:
            otel_context._RUNTIME_CONTEXT.detach(token)
        except ValueError as exc:
            if "was created in a different Context" in str(exc):
                return
            raise

    otel_context.detach = _suppress_otel_context_detach


class CadenceAgentRunner(Runner):
    """ADK runner that routes model calls through Cadence activities.

    Register GoogleADKActivities with the worker registry used for these workflows.
    Pass suppress_adk_cleanup_errors=False to avoid installing cleanup-error hooks.
    """

    _hooks_installed: bool = False

    def __init__(self, **kwargs: Any) -> None:
        suppress_adk_cleanup_errors = kwargs.pop("suppress_adk_cleanup_errors", True)
        if suppress_adk_cleanup_errors:
            with _hooks_install_lock:
                if not CadenceAgentRunner._hooks_installed:
                    _install_suppression_hooks()
                    CadenceAgentRunner._hooks_installed = True

        agent = kwargs.get("agent")
        app = kwargs.get("app")

        if agent is not None:
            kwargs["agent"] = _replace_model_in_agent(agent)
        elif app is not None:
            _replace_model_in_agent(app.root_agent)

        super().__init__(**kwargs)

    async def run_async(self, **kwargs: Any):
        run_config = kwargs.get("run_config")
        if run_config and run_config.streaming_mode != StreamingMode.NONE:
            raise RuntimeError("Streaming is not supported")
        async for event in super().run_async(**kwargs):
            yield event


def _replace_model_in_agent(agent: BaseAgent) -> BaseAgent:
    if isinstance(agent, LlmAgent):
        model = agent.model
        if isinstance(model, CadenceModel):
            pass  # already wired
        elif isinstance(model, BaseLlm):
            raise ValueError("Model must be a string")
        elif isinstance(model, str):
            if not model:
                raise ValueError("Model name must be set")
            agent.model = CadenceModel(model=model)
        else:
            raise ValueError("Model must be a string")

    for sub_agent in getattr(agent, "sub_agents", []) or []:
        _replace_model_in_agent(sub_agent)

    return agent
