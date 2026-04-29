from datetime import timedelta
from typing import Any

import grpc


class ContinueAsNewError(Exception):
    def __init__(
        self,
        *args: Any,
        workflow_type: str | None = None,
        task_list: str | None = None,
        execution_start_to_close_timeout: timedelta | None = None,
        task_start_to_close_timeout: timedelta | None = None,
    ):
        super().__init__("ContinueAsNew")
        self.workflow_args = args
        self.workflow_type = workflow_type
        self.task_list = task_list
        self.execution_start_to_close_timeout = execution_start_to_close_timeout
        self.task_start_to_close_timeout = task_start_to_close_timeout


class ActivityFailure(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class WorkflowFailure(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class SignalFailure(Exception):
    def __init__(self, message: str | None, signal_name: str) -> None:
        if message is None:
            message = f"Signal {signal_name} failed"
        super().__init__(message)
        self.signal_name = signal_name
        self.message = message


class CadenceRpcError(Exception):
    def __init__(self, message: str | None, code: grpc.StatusCode, *args):
        if message is None:
            super().__init__(code, *args)
        else:
            super().__init__(message, code, *args)
        self.code = code


class WorkflowExecutionAlreadyStartedError(CadenceRpcError):
    def __init__(
        self,
        message: str | None,
        code: grpc.StatusCode,
        start_request_id: str,
        run_id: str,
    ) -> None:
        super().__init__(message, code, start_request_id, run_id)
        self.start_request_id = start_request_id
        self.run_id = run_id


class EntityNotExistsError(CadenceRpcError):
    def __init__(
        self,
        message: str | None,
        code: grpc.StatusCode,
        current_cluster: str,
        active_cluster: str,
        active_clusters: list[str],
    ) -> None:
        super().__init__(
            message, code, current_cluster, active_cluster, active_clusters
        )
        self.current_cluster = current_cluster
        self.active_cluster = active_cluster
        self.active_clusters = active_clusters


class WorkflowExecutionAlreadyCompletedError(CadenceRpcError):
    pass


class DomainNotActiveError(CadenceRpcError):
    def __init__(
        self,
        message: str | None,
        code: grpc.StatusCode,
        domain: str,
        current_cluster: str,
        active_cluster: str,
        active_clusters: list[str],
    ) -> None:
        super().__init__(
            message, code, domain, current_cluster, active_cluster, active_clusters
        )
        self.domain = domain
        self.current_cluster = current_cluster
        self.active_cluster = active_cluster
        self.active_clusters = active_clusters


class ClientVersionNotSupportedError(CadenceRpcError):
    def __init__(
        self,
        message: str | None,
        code: grpc.StatusCode,
        feature_version: str,
        client_impl: str,
        supported_versions: str,
    ) -> None:
        super().__init__(
            message, code, feature_version, client_impl, supported_versions
        )
        self.feature_version = feature_version
        self.client_impl = client_impl
        self.supported_versions = supported_versions


class FeatureNotEnabledError(CadenceRpcError):
    def __init__(
        self, message: str | None, code: grpc.StatusCode, feature_flag: str
    ) -> None:
        super().__init__(message, code, feature_flag)
        self.feature_flag = feature_flag


class CancellationAlreadyRequestedError(CadenceRpcError):
    pass


class DomainAlreadyExistsError(CadenceRpcError):
    pass


class LimitExceededError(CadenceRpcError):
    pass


class QueryFailedError(CadenceRpcError):
    pass


class ServiceBusyError(CadenceRpcError):
    def __init__(self, message: str | None, code: grpc.StatusCode, reason: str) -> None:
        super().__init__(message, code, reason)
        self.reason = reason
