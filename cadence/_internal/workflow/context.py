from typing import Optional
from cadence.client import Client
from cadence.workflow import WorkflowContext, WorkflowInfo


class Context(WorkflowContext):

    def __init__(self, client: Client, info: WorkflowInfo):
        self._client = client
        self._info = info
        self._replay_mode = True
        self._replay_current_time_milliseconds: Optional[int] = None

    def info(self) -> WorkflowInfo:
        return self._info

    def client(self) -> Client:
        return self._client

    def set_replay_mode(self, replay: bool) -> None:
        """Set whether the workflow is currently in replay mode."""
        self._replay_mode = replay

    def is_replay_mode(self) -> bool:
        """Check if the workflow is currently in replay mode."""
        return self._replay_mode

    def set_replay_current_time_milliseconds(self, time_millis: int) -> None:
        """Set the current replay time in milliseconds."""
        self._replay_current_time_milliseconds = time_millis

    def get_replay_current_time_milliseconds(self) -> Optional[int]:
        """Get the current replay time in milliseconds."""
        return self._replay_current_time_milliseconds
