import grpc


class ActivityFailure(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class CadenceRpcError(Exception):
    def __init__(self, message: str, code: grpc.StatusCode, *args):
        super().__init__(message, code, *args)
        self.code = code


class WorkflowExecutionAlreadyStartedError(CadenceRpcError):
    def __init__(
        self, message: str, code: grpc.StatusCode, start_request_id: str, run_id: str
    ) -> None:
        super().__init__(message, code, start_request_id, run_id)
        self.start_request_id = start_request_id
        self.run_id = run_id


class EntityNotExistsError(CadenceRpcError):
    def __init__(
        self,
        message: str,
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
        message: str,
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
        message: str,
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
    def __init__(self, message: str, code: grpc.StatusCode, feature_flag: str) -> None:
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
    def __init__(self, message: str, code: grpc.StatusCode, reason: str) -> None:
        super().__init__(message, code, reason)
        self.reason = reason
