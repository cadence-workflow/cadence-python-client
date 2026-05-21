import asyncio
import logging
import os
from datetime import timedelta

import pytest

from google.protobuf.duration import from_timedelta
from pytest_docker import Services

from cadence.api.v1.service_domain_pb2 import RegisterDomainRequest
from cadence.client import ClientOptions
from cadence.error import DomainAlreadyExistsError
from tests.conftest import ENABLE_INTEGRATION_TESTS, KEEP_CADENCE_ALIVE
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME


logger = logging.getLogger(__name__)


# Run tests in this directory and lower only if integration tests are enabled
def pytest_runtest_setup(item):
    if not item.config.getoption(ENABLE_INTEGRATION_TESTS):
        pytest.skip(f"{ENABLE_INTEGRATION_TESTS} not enabled")


@pytest.fixture(scope="session")
def docker_compose_file(pytestconfig):
    return os.path.join(
        str(pytestconfig.rootdir), "tests", "integration_tests", "docker-compose.yml"
    )


# Use a consistent project name so it can be reused or replaced by a manually created one
@pytest.fixture(scope="session")
def docker_compose_project_name() -> str:
    return "pytest-cadence"


@pytest.fixture(scope="session")
def docker_cleanup(pytestconfig):
    if pytestconfig.getoption(KEEP_CADENCE_ALIVE):
        return False
    else:
        return ["down -v"]


@pytest.fixture(scope="session")
def client_options(docker_ip: str, docker_services: Services) -> ClientOptions:
    return ClientOptions(
        domain=DOMAIN_NAME,
        target=f"{docker_ip}:{docker_services.port_for('cadence', 7833)}",
    )


@pytest.fixture(scope="session", autouse=True)
async def create_test_domain(client_options: ClientOptions) -> None:
    helper = CadenceHelper(client_options, "create_test_domain", "")
    async with helper.client() as client:
        logging.info("Connecting to service...")
        # It takes around a minute for the Cadence server to start up with Cassandra
        async with asyncio.timeout(120):
            await client.ready()

        try:
            logging.info("Creating domain %s...", DOMAIN_NAME)
            await client.domain_stub.RegisterDomain(
                RegisterDomainRequest(
                    name=DOMAIN_NAME,
                    workflow_execution_retention_period=from_timedelta(
                        timedelta(days=1)
                    ),
                )
            )
            logging.info("Done creating domain %s", DOMAIN_NAME)
        except DomainAlreadyExistsError:
            logging.info("Domain %s already exists", DOMAIN_NAME)
    return None


# We can't pass around Client objects between tests/fixtures without changing our pytest-asyncio version
# to ensure that they use the same event loop.
# Instead, we can wait for the server to be ready, create the common domain, and then provide a helper capable
# of creating additional clients within each test as needed
@pytest.fixture
async def helper(
    client_options: ClientOptions, request: pytest.FixtureRequest
) -> CadenceHelper:
    return CadenceHelper(client_options, request.node.name, request.node.fspath)
