

ENABLE_INTEGRATION_TESTS = "--integration-tests"

# Need to define the option in the root conftest.py file
def pytest_addoption(parser):
    parser.addoption(ENABLE_INTEGRATION_TESTS, action="store_true",
                     help="enables running integration tests, which rely on docker and docker-compose")