from cadence.client import ClientOptions, Client

DOMAIN_NAME = "test-domain"


class CadenceHelper:
    def __init__(self, options: ClientOptions):
        self.options = options

    def client(self):
        return Client(**self.options)