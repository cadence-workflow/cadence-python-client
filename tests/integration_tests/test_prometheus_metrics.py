import asyncio
import threading
from contextlib import contextmanager
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator, cast
from urllib.parse import urlencode
from urllib.request import urlopen
import json

from prometheus_client import CollectorRegistry
from pytest_docker import Services

from cadence import Registry, workflow
from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryRequest,
    GetWorkflowExecutionHistoryResponse,
)
from cadence.metrics import PrometheusConfig, PrometheusMetrics
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME


PROMETHEUS_SCRAPE_PORT = 9108

registry = Registry()


@registry.activity()
async def echo_for_metrics(message: str) -> str:
    return message


@registry.workflow()
class WorkflowWithMetrics:
    @workflow.run
    async def run(self, message: str) -> str:
        return await echo_for_metrics.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute(message)


@contextmanager
def metrics_endpoint(metrics: PrometheusMetrics) -> Iterator[None]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/metrics":
                self.send_response(404)
                self.end_headers()
                return

            body = metrics.get_metrics_text().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("0.0.0.0", PROMETHEUS_SCRAPE_PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=5) as response:
        return cast(dict[str, Any], json.loads(response.read().decode()))


def _get_text(url: str) -> str:
    with urlopen(url, timeout=5) as response:
        return cast(str, response.read().decode())


async def _query_prometheus(prometheus_url: str, query: str) -> dict[str, Any]:
    params = urlencode({"query": query})
    return await asyncio.to_thread(_get_json, f"{prometheus_url}/api/v1/query?{params}")


async def _wait_for_prometheus_metric(prometheus_url: str, query: str) -> None:
    deadline = asyncio.get_running_loop().time() + 30
    last_response: dict[str, Any] | None = None

    while asyncio.get_running_loop().time() < deadline:
        last_response = await _query_prometheus(prometheus_url, query)
        results = last_response.get("data", {}).get("result", [])
        if results:
            value = float(results[0]["value"][1])
            if value > 0:
                return
        await asyncio.sleep(1)

    raise AssertionError(f"Prometheus did not scrape {query}: {last_response}")


async def test_worker_poll_metrics_are_scraped_by_prometheus(
    helper: CadenceHelper, docker_ip: str, docker_services: Services
):
    prometheus_url = (
        f"http://{docker_ip}:{docker_services.port_for('prometheus', 9090)}"
    )
    docker_services.wait_until_responsive(
        timeout=30,
        pause=1,
        check=lambda: (
            "Prometheus Server is Ready" in _get_text(f"{prometheus_url}/-/ready")
        ),
    )

    metrics = PrometheusMetrics(PrometheusConfig(registry=CollectorRegistry()))
    task_list = helper.test_name

    with metrics_endpoint(metrics):
        async with helper.worker(
            registry,
            metrics_emitter=metrics,
            activity_task_pollers=1,
            decision_task_pollers=1,
        ) as worker:
            execution = await worker.client.start_workflow(
                "WorkflowWithMetrics",
                "hello metrics",
                task_list=worker.task_list,
                execution_start_to_close_timeout=timedelta(seconds=10),
            )

            response: GetWorkflowExecutionHistoryResponse = await worker.client.workflow_stub.GetWorkflowExecutionHistory(
                GetWorkflowExecutionHistoryRequest(
                    domain=DOMAIN_NAME,
                    workflow_execution=execution,
                    wait_for_new_event=True,
                    history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
                    skip_archival=True,
                )
            )

            assert (
                '"hello metrics"'
                == response.history.events[
                    -1
                ].workflow_execution_completed_event_attributes.result.data.decode()
            )

        labels = f'{{Domain="{DOMAIN_NAME}",TaskList="{task_list}"}}'
        await _wait_for_prometheus_metric(
            prometheus_url, f"cadence_worker_start_total{labels}"
        )
        await _wait_for_prometheus_metric(
            prometheus_url, f"cadence_poller_start_total{labels}"
        )
        await _wait_for_prometheus_metric(
            prometheus_url, f"cadence_decision_poll_succeed_total{labels}"
        )
        await _wait_for_prometheus_metric(
            prometheus_url, f"cadence_activity_poll_succeed_total{labels}"
        )
