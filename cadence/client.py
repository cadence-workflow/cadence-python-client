import os
import socket
import uuid
from datetime import timedelta
from typing import TypedDict, Unpack, Any, cast, Union, Callable

from grpc import ChannelCredentials, Compression
from google.protobuf.duration_pb2 import Duration

from cadence._internal.rpc.error import CadenceErrorInterceptor
from cadence._internal.rpc.retry import RetryInterceptor
from cadence._internal.rpc.yarpc import YarpcMetadataInterceptor
from cadence.api.v1.service_domain_pb2_grpc import DomainAPIStub
from cadence.api.v1.service_worker_pb2_grpc import WorkerAPIStub
from grpc.aio import Channel, ClientInterceptor, secure_channel, insecure_channel
from cadence.api.v1.service_workflow_pb2_grpc import WorkflowAPIStub
from cadence.api.v1.service_workflow_pb2 import (
    StartWorkflowExecutionRequest,
    StartWorkflowExecutionResponse,
    SignalWithStartWorkflowExecutionRequest,
    SignalWithStartWorkflowExecutionResponse,
)
from cadence.api.v1.common_pb2 import WorkflowType, WorkflowExecution
from cadence.api.v1.tasklist_pb2 import TaskList
from cadence.data_converter import DataConverter, DefaultDataConverter
from cadence.metrics import MetricsEmitter, NoOpMetricsEmitter


class StartWorkflowOptions(TypedDict, total=False):
    """Options for starting a workflow execution."""

    task_list: str
    execution_start_to_close_timeout: timedelta
    workflow_id: str
    task_start_to_close_timeout: timedelta
    cron_schedule: str


def _validate_and_apply_defaults(options: StartWorkflowOptions) -> StartWorkflowOptions:
    """Validate required fields and apply defaults to StartWorkflowOptions."""
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
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def _build_start_workflow_request(
        self,
        workflow: Union[str, Callable],
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
            # For callable, use function name or __name__ attribute
            workflow_type_name = getattr(workflow, "__name__", str(workflow))

        # Encode input arguments
        input_payload = None
        if args:
            try:
                input_payload = await self.data_converter.to_data(list(args))
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

        return request

    async def start_workflow(
        self,
        workflow: Union[str, Callable],
        *args,
        **options_kwargs: Unpack[StartWorkflowOptions],
    ) -> WorkflowExecution:
        """
        Start a workflow execution asynchronously.

        Args:
            workflow: Workflow function or workflow type name string
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
        request = await self._build_start_workflow_request(workflow, args, options)

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

    async def signal_with_start_workflow(
        self,
        workflow: Union[str, Callable],
        signal_name: str,
        signal_input: Any = None,
        *args,
        **options_kwargs: Unpack[StartWorkflowOptions],
    ) -> WorkflowExecution:
        """
        Signal a workflow execution, starting it if it is not already running.

        Args:
            workflow: Workflow function or workflow type name string
            signal_name: Name of the signal
            signal_input: Input data for the signal
            *args: Arguments to pass to the workflow if it needs to be started
            **options_kwargs: StartWorkflowOptions as keyword arguments

        Returns:
            WorkflowExecution with workflow_id and run_id

        Raises:
            ValueError: If required parameters are missing or invalid
            Exception: If the gRPC call fails
        """
        # Convert kwargs to StartWorkflowOptions and validate
        options = _validate_and_apply_defaults(StartWorkflowOptions(**options_kwargs))

        # Build the start workflow request
        start_request = await self._build_start_workflow_request(
            workflow, args, options
        )

        # Encode signal input
        signal_payload = None
        if signal_input is not None:
            try:
                signal_payload = await self.data_converter.to_data(signal_input)
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

            # Emit metrics if available
            if self.metrics_emitter:
                # TODO: Add metrics similar to Go client
                pass

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

    if options["credentials"]:
        return secure_channel(
            options["target"],
            options["credentials"],
            options["channel_arguments"],
            options["compression"],
            interceptors,
        )
    else:
        return insecure_channel(
            options["target"],
            options["channel_arguments"],
            options["compression"],
            interceptors,
        )
