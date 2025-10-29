import asyncio
import os
from datetime import timedelta

import pytest

from google.protobuf.duration import from_timedelta
from pytest_docker import Services

from cadence.api.v1.service_domain_pb2 import RegisterDomainRequest
from cadence.client import ClientOptions
from tests.conftest import ENABLE_INTEGRATION_TESTS
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME


# Run tests in this directory and lower only if integration tests are enabled
def pytest_runtest_setup(item):
    if not item.config.getoption(ENABLE_INTEGRATION_TESTS):
        pytest.skip(f"{ENABLE_INTEGRATION_TESTS} not enabled")


@pytest.fixture(scope="session")
def docker_compose_file(pytestconfig):
    return os.path.join(
        str(pytestconfig.rootdir), "tests", "integration_tests", "docker-compose.yml"
    )


@pytest.fixture(scope="session")
def client_options(docker_ip: str, docker_services: Services) -> ClientOptions:
    return ClientOptions(
        domain=DOMAIN_NAME,
        target=f"{docker_ip}:{docker_services.port_for('cadence', 7833)}",
    )


# We can't pass around Client objects between tests/fixtures without changing our pytest-asyncio version
# to ensure that they use the same event loop.
# Instead, we can wait for the server to be ready, create the common domain, and then provide a helper capable
# of creating additional clients within each test as needed
@pytest.fixture(scope="session")
async def helper(client_options: ClientOptions) -> CadenceHelper:
    helper = CadenceHelper(client_options)
    async with helper.client() as client:
        # It takes around a minute for the Cadence server to start up with Cassandra
        async with asyncio.timeout(120):
            await client.ready()

        await client.domain_stub.RegisterDomain(
            RegisterDomainRequest(
                name=DOMAIN_NAME,
                workflow_execution_retention_period=from_timedelta(timedelta(days=1)),
            )
        )
    return CadenceHelper(client_options)
