import grpc


class CadenceError(Exception):

    def __init__(self, message: str, code: grpc.StatusCode, *args):
        super().__init__(message, code, *args)
        self.code = code
    pass


class WorkflowExecutionAlreadyStartedError(CadenceError):

    def __init__(self, message: str, code: grpc.StatusCode, start_request_id: str, run_id: str) -> None:
        super().__init__(message, code, start_request_id, run_id)
        self.start_request_id = start_request_id
        self.run_id = run_id

class EntityNotExistsError(CadenceError):

    def __init__(self, message: str, code: grpc.StatusCode, current_cluster: str, active_cluster: str, active_clusters: list[str]) -> None:
        super().__init__(message, code, current_cluster, active_cluster, active_clusters)
        self.current_cluster = current_cluster
        self.active_cluster = active_cluster
        self.active_clusters = active_clusters

class WorkflowExecutionAlreadyCompletedError(CadenceError):
    pass

class DomainNotActiveError(CadenceError):
    def __init__(self, message: str, code: grpc.StatusCode, domain: str, current_cluster: str, active_cluster: str, active_clusters: list[str]) -> None:
        super().__init__(message, code, domain, current_cluster, active_cluster, active_clusters)
        self.domain = domain
        self.current_cluster = current_cluster
        self.active_cluster = active_cluster
        self.active_clusters = active_clusters

class ClientVersionNotSupportedError(CadenceError):
    def __init__(self, message: str, code: grpc.StatusCode, feature_version: str, client_impl: str, supported_versions: str) -> None:
        super().__init__(message, code, feature_version, client_impl, supported_versions)
        self.feature_version = feature_version
        self.client_impl = client_impl
        self.supported_versions = supported_versions

class FeatureNotEnabledError(CadenceError):
    def __init__(self, message: str, code: grpc.StatusCode, feature_flag: str) -> None:
        super().__init__(message, code, feature_flag)
        self.feature_flag = feature_flag

class CancellationAlreadyRequestedError(CadenceError):
    pass

class DomainAlreadyExistsError(CadenceError):
    pass

class LimitExceededError(CadenceError):
    pass

class QueryFailedError(CadenceError):
    pass

class ServiceBusyError(CadenceError):
    def __init__(self, message: str, code: grpc.StatusCode, reason: str) -> None:
        super().__init__(message, code, reason)
        self.reason = reason
