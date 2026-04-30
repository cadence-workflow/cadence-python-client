import asyncio
import logging
import signal
import cadence
from cadence.contrib.airflow.cadence_dag import dag_as_workflow, operator_as_activity
from cadence.contrib.airflow.example_dag import dag, extract_task, transform_task

logger = logging.getLogger(__name__)


async def main():

    registry = cadence.Registry()

    registry.register_workflow(dag_as_workflow(dag))
    registry.register_activity(operator_as_activity(extract_task))
    registry.register_activity(operator_as_activity(transform_task))

    # start Cadence worker
    worker = cadence.worker.Worker(
        cadence.Client(
            domain="default",
            target="localhost:7833",
        ),
        "airflow-task-list",
        registry,
    )

    # start BookFlightAgentWorkflow
    async with worker:
        logger.info(
            "Worker started. Go to http://localhost:8088/domains/default/cluster0/workflows to start an agent run."
        )
        shutdown_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, shutdown_event.set)
        logger.info("Press Ctrl+C to stop the worker.")

        await shutdown_event.wait()


if __name__ == "__main__":
    asyncio.run(main())
