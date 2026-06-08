"""Example: full schedule lifecycle using the Cadence Python client.

Demonstrates create, describe, pause/unpause, update, list, backfill, and delete.
A worker is started alongside so that any workflows triggered by the schedule
actually complete rather than time out.

Run against local docker-compose:
    docker-compose -f tests/integration_tests/docker-compose.yml up -d
    uv run python cadence/sample/schedule_example.py

Run against a remote server:
    uv run python cadence/sample/schedule_example.py --target <host>:7833 --domain <domain>
"""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from cadence import Registry, workflow
from cadence.api.v1 import common_pb2, schedule_pb2, tasklist_pb2
from cadence.client import Client
from cadence.worker import Worker

TASK_LIST = "schedule-example-task-list"

reg = Registry()


@reg.workflow()
class ExampleWorkflow:
    """Short-lived workflow used as the schedule action target."""

    @workflow.run
    async def run(self) -> str:
        return "done"


async def main(target: str, domain: str) -> None:
    async with Client(target=target, domain=domain) as client:
        async with Worker(client, TASK_LIST, reg):
            schedule_id = "example-daily-report"

            # action defines which workflow the schedule will start on each fire
            action = schedule_pb2.ScheduleAction(
                start_workflow=schedule_pb2.ScheduleAction.StartWorkflowAction(
                    workflow_type=common_pb2.WorkflowType(name="ExampleWorkflow"),
                    task_list=tasklist_pb2.TaskList(name=TASK_LIST),
                    execution_start_to_close_timeout=timedelta(seconds=30),
                )
            )

            # Create: fires every day at 09:00 UTC
            await client.create_schedule(
                schedule_id,
                spec=schedule_pb2.ScheduleSpec(cron_expression="0 9 * * *"),
                action=action,
            )
            print(f"Created schedule: {schedule_id}")

            # Describe: inspect current configuration and runtime info
            desc = await client.describe_schedule(schedule_id)
            print(f"  cron       : {desc.spec.cron_expression}")
            print(f"  paused     : {desc.state.paused}")
            print(f"  total_runs : {desc.info.total_runs}")

            # Pause: stop new fires without deleting the schedule
            await client.pause_schedule(schedule_id, reason="maintenance window")
            print("Paused schedule")

            # Unpause: resume firing
            await client.unpause_schedule(
                schedule_id,
                reason="maintenance complete",
                catch_up_policy=schedule_pb2.SCHEDULE_CATCH_UP_POLICY_SKIP,
            )
            print("Unpaused schedule")

            # Update: change the cron expression using read-modify-write
            await client.update_schedule(
                schedule_id,
                lambda d: d.spec.CopyFrom(
                    schedule_pb2.ScheduleSpec(cron_expression="0 18 * * *")
                ),
            )
            print("Updated cron to 18:00 UTC")

            # List: iterate over all schedules in the domain
            print("Schedules in domain:")
            async for entry in client.list_schedules():
                print(f"  {entry.schedule_id}  cron={entry.cron_expression}")

            # Backfill: replay fires for a historical window
            now = datetime.now(tz=timezone.utc)
            await client.backfill_schedule(
                schedule_id,
                start_time=now - timedelta(hours=3),
                end_time=now,
                overlap_policy=schedule_pb2.SCHEDULE_OVERLAP_POLICY_CONCURRENT,
            )
            print("Triggered backfill for last 3 hours")

            # Delete: remove the schedule (in-flight workflows are not affected)
            await client.delete_schedule(schedule_id)
            print(f"Deleted schedule: {schedule_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Schedule lifecycle example")
    parser.add_argument(
        "--target", default="localhost:7833", help="Cadence gRPC endpoint"
    )
    parser.add_argument("--domain", default="test-domain", help="Cadence domain")
    args = parser.parse_args()
    asyncio.run(main(args.target, args.domain))
