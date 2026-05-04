import os
import socket
import uuid
from datetime import datetime, timedelta
from typing import Sequence, TypedDict, Unpack, Any, cast, Union

from grpc import ChannelCredentials, Compression
from google.protobuf.duration_pb2 import Duration
from google.protobuf.timestamp_pb2 import Timestamp

from cadence._internal.rpc.error import CadenceErrorInterceptor
from cadence._internal.rpc.retry import RetryInterceptor
from cadence._internal.rpc.yarpc import YarpcMetadataInterceptor
from cadence._internal.workflow.active_cluster_selection_policy import (
    active_cluster_selection_policy_to_proto,
)
from cadence._internal.workflow.retry_policy import retry_policy_to_proto
from cadence.api.v1.service_domain_pb2_grpc import DomainAPIStub
from cadence.api.v1.service_worker_pb2_grpc import WorkerAPIStub
import grpc.aio
from grpc.aio import Channel, ClientInterceptor
from cadence.api.v1.service_workflow_pb2_grpc import WorkflowAPIStub
from cadence.api.v1.service_workflow_pb2 import (
    SignalWorkflowExecutionRequest,
    StartWorkflowExecutionRequest,
    StartWorkflowExecutionResponse,
    SignalWithStartWorkflowExecutionRequest,
    SignalWithStartWorkflowExecutionResponse,
)
from cadence.api.v1.common_pb2 import WorkflowType, WorkflowExecution
from cadence.api.v1 import workflow_pb2
from cadence.api.v1.tasklist_pb2 import TaskList
from cadence.data_converter import DataConverter, DefaultDataConverter
from cadence.metrics import MetricsEmitter, NoOpMetricsEmitter
from cadence.workflow import (
    ActiveClusterSelectionPolicy,
    RetryPolicy,
    WorkflowDefinition,
)


class StartWorkflowOptions(TypedDict, total=False):
    """Options for starting a workflow execution."""

    task_list: str
    execution_start_to_close_timeout: timedelta
    workflow_id: str
    task_start_to_close_timeout: timedelta
    cron_schedule: str
    delay_start: timedelta
    jitter_start: timedelta
    cron_overlap_policy: workflow_pb2.CronOverlapPolicy
    first_run_at: datetime
    workflow_id_reuse_policy: workflow_pb2.WorkflowIdReusePolicy
    retry_policy: RetryPolicy
    active_cluster_selection_policy: ActiveClusterSelectionPolicy


def _validate_and_apply_defaults(
    options: StartWorkflowOptions,
    default_workflow_id_reuse_policy: workflow_pb2.WorkflowIdReusePolicy = workflow_pb2.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE_FAILED_ONLY,
) -> StartWorkflowOptions:
    """Validate required fields and apply defaults to StartWorkflowOptions.

    ``default_workflow_id_reuse_policy`` defaults to the value used by
    ``start_workflow``. ``signal_with_start_workflow`` passes
    ``ALLOW_DUPLICATE`` for Go parity.
    """
    if not options.get("task_list"):
        raise ValueError("task_list is required")

    execution_timeout = options.get("execution_start_to_close_timeout")
    if not execution_timeout:
        raise ValueError("execution_start_to_close_timeout is required")
    if execution_timeout <= timedelta(0):
        raise ValueError("execution_start_to_close_timeout must be greater than 0")

    # Apply default for task_start_to_close_timeout if not provided (matching Go/Java clients)
    task_timeout = options.get("task_start_to_close_timeout")
    if task_timeout is None:
        options["task_start_to_close_timeout"] = timedelta(seconds=10)
    elif task_timeout <= timedelta(0):
        raise ValueError("task_start_to_close_timeout must be greater than 0")

    # Validate delay_start (must be non-negative)
    delay_start = options.get("delay_start")
    if delay_start is not None and delay_start < timedelta(0):
        raise ValueError("delay_start cannot be negative")

    # Validate jitter_start (must be non-negative)
    jitter_start = options.get("jitter_start")
    if jitter_start is not None and jitter_start < timedelta(0):
        raise ValueError("jitter_start cannot be negative")

    if options.get("workflow_id_reuse_policy") is None:
        options["workflow_id_reuse_policy"] = default_workflow_id_reuse_policy
    elif (
        options["workflow_id_reuse_policy"]
        == workflow_pb2.WORKFLOW_ID_REUSE_POLICY_INVALID
    ):
        raise ValueError(
            "workflow_id_reuse_policy cannot be WORKFLOW_ID_REUSE_POLICY_INVALID"
        )

    # Validate first_run_at (must be timezone-aware and not before Unix epoch)
    first_run_at = options.get("first_run_at")
    if first_run_at is not None:
        # Require timezone-aware datetime to prevent ambiguity
        if first_run_at.tzinfo is None:
            raise ValueError(
                "first_run_at must be timezone-aware. "
                "Use datetime.now(timezone.utc) or datetime(..., tzinfo=timezone.utc)"
            )
        # Validate timestamp is not before Unix epoch
        if first_run_at.timestamp() < 0:
            raise ValueError(
                "first_run_at cannot be before Unix epoch (January 1, 1970 UTC)"
            )

    return options


class ClientOptions(TypedDict, total=False):
    domain: str
    target: str
    data_converter: DataConverter
    identity: str
    service_name: str
    caller_name: str
    channel_arguments: dict[str, Any]
    credentials: ChannelCredentials | None
    compression: Compression
    metrics_emitter: MetricsEmitter
    interceptors: list[ClientInterceptor]


_DEFAULT_OPTIONS: ClientOptions = {
    "data_converter": DefaultDataConverter(),
    "identity": f"{os.getpid()}@{socket.gethostname()}",
    "service_name": "cadence-frontend",
    "caller_name": "cadence-client",
    "channel_arguments": {},
    "credentials": None,
    "compression": Compression.NoCompression,
    "metrics_emitter": NoOpMetricsEmitter(),
    "interceptors": [],
}


class Client:
    def __init__(self, **kwargs: Unpack[ClientOptions]) -> None:
        self._options = _validate_and_copy_defaults(ClientOptions(**kwargs))
        self._channel = _create_channel(self._options)
        self._worker_stub = WorkerAPIStub(self._channel)
        self._domain_stub = DomainAPIStub(self._channel)
        self._workflow_stub = WorkflowAPIStub(self._channel)

    @property
    def data_converter(self) -> DataConverter:
        return self._options["data_converter"]

    @property
    def domain(self) -> str:
        return self._options["domain"]

    @property
    def identity(self) -> str:
        return self._options["identity"]

    @property
    def domain_stub(self) -> DomainAPIStub:
        return self._domain_stub

    @property
    def worker_stub(self) -> WorkerAPIStub:
        return self._worker_stub

    @property
    def workflow_stub(self) -> WorkflowAPIStub:
        return self._workflow_stub

    @property
    def metrics_emitter(self) -> MetricsEmitter:
        return self._options["metrics_emitter"]

    async def ready(self) -> None:
        await self._channel.channel_ready()

    async def close(self) -> None:
        await self._channel.close()

    async def __aenter__(self) -> "Client":
        await self.ready()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    def _build_start_workflow_request(
        self,
        workflow: Union[str, WorkflowDefinition],
        args: tuple[Any, ...],
        options: StartWorkflowOptions,
    ) -> StartWorkflowExecutionRequest:
        """Build a StartWorkflowExecutionRequest from parameters."""
        # Generate workflow ID if not provided
        workflow_id = options.get("workflow_id") or str(uuid.uuid4())

        # Determine workflow type name
        if isinstance(workflow, str):
            workflow_type_name = workflow
        else:
            # For WorkflowDefinition, use the name property
            workflow_type_name = workflow.name

        # Encode input arguments
        input_payload = None
        if args:
            try:
                input_payload = self.data_converter.to_data(list(args))
            except Exception as e:
                raise ValueError(f"Failed to encode workflow arguments: {e}")

        # Convert timedelta to protobuf Duration
        execution_timeout = Duration()
        execution_timeout.FromTimedelta(options["execution_start_to_close_timeout"])

        task_timeout = Duration()
        task_timeout.FromTimedelta(options["task_start_to_close_timeout"])

        # Build the request
        request = StartWorkflowExecutionRequest(
            domain=self.domain,
            workflow_id=workflow_id,
            workflow_type=WorkflowType(name=workflow_type_name),
            task_list=TaskList(name=options["task_list"]),
            identity=self.identity,
            request_id=str(uuid.uuid4()),
        )

        # Set required timeout fields
        request.execution_start_to_close_timeout.CopyFrom(execution_timeout)
        request.task_start_to_close_timeout.CopyFrom(task_timeout)

        # Set optional fields
        if input_payload:
            request.input.CopyFrom(input_payload)
        if options.get("cron_schedule"):
            request.cron_schedule = options["cron_schedule"]
        if options.get("cron_overlap_policy") is not None:
            request.cron_overlap_policy = options["cron_overlap_policy"]
        if options.get("workflow_id_reuse_policy") is not None:
            request.workflow_id_reuse_policy = options["workflow_id_reuse_policy"]

        # Set delay_start if provided
        delay_start = options.get("delay_start")
        if delay_start is not None:
            delay_duration = Duration()
            delay_duration.FromTimedelta(delay_start)
            request.delay_start.CopyFrom(delay_duration)

        # Set jitter_start if provided
        jitter_start = options.get("jitter_start")
        if jitter_start is not None:
            jitter_duration = Duration()
            jitter_duration.FromTimedelta(jitter_start)
            request.jitter_start.CopyFrom(jitter_duration)

        # Set first_run_at if provided
        first_run_at = options.get("first_run_at")
        if first_run_at is not None:
            first_run_timestamp = Timestamp()
            first_run_timestamp.FromDatetime(first_run_at)
            request.first_run_at.CopyFrom(first_run_timestamp)

        # Set retry_policy if provided
        retry_proto = retry_policy_to_proto(options.get("retry_policy"))
        if retry_proto is not None:
            request.retry_policy.CopyFrom(retry_proto)

        acsp_proto = active_cluster_selection_policy_to_proto(
            options.get("active_cluster_selection_policy")
        )
        if acsp_proto is not None:
            request.active_cluster_selection_policy.CopyFrom(acsp_proto)

        return request

    async def start_workflow(
        self,
        workflow: Union[str, WorkflowDefinition],
        *args,
        **options_kwargs: Unpack[StartWorkflowOptions],
    ) -> WorkflowExecution:
        """
        Start a workflow execution asynchronously.

        Args:
            workflow: WorkflowDefinition or workflow type name string
            *args: Arguments to pass to the workflow
            **options_kwargs: StartWorkflowOptions as keyword arguments

        Returns:
            WorkflowExecution with workflow_id and run_id

        Raises:
            ValueError: If required parameters are missing or invalid
            Exception: If the gRPC call fails
        """
        # Convert kwargs to StartWorkflowOptions and validate
        options = _validate_and_apply_defaults(StartWorkflowOptions(**options_kwargs))

        # Build the gRPC request
        request = self._build_start_workflow_request(workflow, args, options)

        # Execute the gRPC call
        try:
            response: StartWorkflowExecutionResponse = (
                await self.workflow_stub.StartWorkflowExecution(request)
            )

            # Emit metrics if available
            if self.metrics_emitter:
                # TODO: Add workflow start metrics similar to Go client
                pass

            execution = WorkflowExecution()
            execution.workflow_id = request.workflow_id
            execution.run_id = response.run_id
            return execution
        except Exception:
            raise

    async def signal_workflow(
        self,
        workflow_id: str,
        run_id: str,
        signal_name: str,
        *signal_args: Any,
    ) -> None:
        """
        Send a signal to a running workflow execution.

        Args:
            workflow_id: The workflow ID
            run_id: The run ID (can be empty string to signal current run)
            signal_name: Name of the signal
            *signal_args: Arguments to pass to the signal handler

        Raises:
            ValueError: If signal encoding fails
            Exception: If the gRPC call fails
        """
        signal_payload = None
        if signal_args:
            try:
                signal_payload = self.data_converter.to_data(list[Any](signal_args))
            except Exception as e:
                raise ValueError(f"Failed to encode signal input: {e}")

        workflow_execution = WorkflowExecution()
        workflow_execution.workflow_id = workflow_id
        if run_id:
            workflow_execution.run_id = run_id

        signal_request = SignalWorkflowExecutionRequest(
            domain=self.domain,
            workflow_execution=workflow_execution,
            identity=self.identity,
            request_id=str(uuid.uuid4()),
            signal_name=signal_name,
        )

        if signal_payload:
            signal_request.signal_input.CopyFrom(signal_payload)

        await self.workflow_stub.SignalWorkflowExecution(signal_request)

    async def signal_with_start_workflow(
        self,
        workflow: Union[str, WorkflowDefinition],
        signal_name: str,
        signal_args: list[Any],
        *workflow_args: Any,
        **options_kwargs: Unpack[StartWorkflowOptions],
    ) -> WorkflowExecution:
        """
        Signal a workflow execution, starting it if it is not already running.

        Args:
            workflow: WorkflowDefinition or workflow type name string
            signal_name: Name of the signal
            signal_args: List of arguments to pass to the signal handler
            *workflow_args: Arguments to pass to the workflow if it needs to be started
            **options_kwargs: StartWorkflowOptions as keyword arguments

        Returns:
            WorkflowExecution with workflow_id and run_id

        Raises:
            ValueError: If required parameters are missing or invalid
            Exception: If the gRPC call fails
        """
        # Convert kwargs to StartWorkflowOptions and validate
        options = _validate_and_apply_defaults(
            StartWorkflowOptions(**options_kwargs),
            workflow_pb2.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE,
        )

        # Build the start workflow request
        start_request = self._build_start_workflow_request(
            workflow, workflow_args, options
        )

        # Encode signal input
        signal_payload = None
        if signal_args:
            try:
                signal_payload = self.data_converter.to_data(signal_args)
            except Exception as e:
                raise ValueError(f"Failed to encode signal input: {e}")

        # Build the SignalWithStartWorkflowExecution request
        request = SignalWithStartWorkflowExecutionRequest(
            start_request=start_request,
            signal_name=signal_name,
        )

        if signal_payload:
            request.signal_input.CopyFrom(signal_payload)

        # Execute the gRPC call
        try:
            response: SignalWithStartWorkflowExecutionResponse = (
                await self.workflow_stub.SignalWithStartWorkflowExecution(request)
            )

            execution = WorkflowExecution()
            execution.workflow_id = start_request.workflow_id
            execution.run_id = response.run_id
            return execution
        except Exception:
            raise


def _validate_and_copy_defaults(options: ClientOptions) -> ClientOptions:
    if "target" not in options:
        raise ValueError("target must be specified")

    if "domain" not in options:
        raise ValueError("domain must be specified")

    # Set default values for missing options
    for key, value in _DEFAULT_OPTIONS.items():
        if key not in options:
            cast(dict, options)[key] = value

    return options


def _create_channel(options: ClientOptions) -> Channel:
    interceptors = list(options["interceptors"])
    interceptors.append(
        YarpcMetadataInterceptor(options["service_name"], options["caller_name"])
    )
    interceptors.append(RetryInterceptor())
    interceptors.append(CadenceErrorInterceptor())

    channel_arguments = options.get("channel_arguments") or {}
    grpc_channel_options: Sequence[tuple[str, Any]] = tuple(channel_arguments.items())

    if options["credentials"]:
        return grpc.aio.secure_channel(
            options["target"],
            options["credentials"],
            options=grpc_channel_options,
            compression=options["compression"],
            interceptors=interceptors,
        )
    else:
        return grpc.aio.insecure_channel(
            options["target"],
            options=grpc_channel_options,
            compression=options["compression"],
            interceptors=interceptors,
        )
