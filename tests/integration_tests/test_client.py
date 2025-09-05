import pytest

from cadence.api.v1.service_domain_pb2 import DescribeDomainRequest, DescribeDomainResponse
from cadence.error import EntityNotExistsError
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME


@pytest.mark.usefixtures("helper")
async def test_domain_exists(helper: CadenceHelper):
    async with helper.client() as client:
        response: DescribeDomainResponse = await client.domain_stub.DescribeDomain(DescribeDomainRequest(name=DOMAIN_NAME))
        assert response.domain.name == DOMAIN_NAME

@pytest.mark.usefixtures("helper")
async def test_domain_not_exists(helper: CadenceHelper):
    with pytest.raises(EntityNotExistsError):
        async with helper.client() as client:
            await client.domain_stub.DescribeDomain(DescribeDomainRequest(name="unknown-domain"))
