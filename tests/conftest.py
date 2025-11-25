ENABLE_INTEGRATION_TESTS = "--integration-tests"
KEEP_CADENCE_ALIVE = "--keep-cadence-alive"


# Need to define the option in the root conftest.py file
def pytest_addoption(parser):
    parser.addoption(
        ENABLE_INTEGRATION_TESTS,
        action="store_true",
        help="enables running integration tests, which rely on docker and docker-compose",
    )
    parser.addoption(
        KEEP_CADENCE_ALIVE,
        action="store_true",
        help="skips tearing down the docker-compose project used by the integration tests so it can be reused to quickly iterate on tests",
    )
