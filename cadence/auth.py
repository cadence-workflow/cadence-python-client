from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Union

CADENCE_AUTHORIZATION_HEADER = "cadence-authorization"

AuthToken = Union[str, bytes]
AuthTokenResult = Union[AuthToken, Awaitable[AuthToken]]


class AuthorizationProvider(ABC):
    """Abstract base class for Cadence authorization token providers.

    Implementations provide OAuth or JWT authorization tokens to be sent
    in the `cadence-authorization` header on every request to the Cadence server.
    """

    @abstractmethod
    def get_auth_token(self) -> AuthTokenResult:
        """Provide the authorization token.

        Called before requests to the Cadence server. Can return a string,
        bytes, or an awaitable returning a string or bytes.
        """
        pass


class StaticAuthorizationProvider(AuthorizationProvider):
    """Authorization provider that supplies a static token."""

    def __init__(self, token: AuthToken) -> None:
        if not token:
            raise ValueError("Token must not be empty")
        self._token = token

    def get_auth_token(self) -> AuthToken:
        return self._token


class CallableAuthorizationProvider(AuthorizationProvider):
    """Authorization provider that dynamically invokes a callback.

    The callback may be a synchronous function returning `str` or `bytes`,
    or an asynchronous coroutine function.
    """

    def __init__(self, fn: Callable[[], AuthTokenResult]) -> None:
        if not callable(fn):
            raise TypeError("Authorization provider callback must be callable")
        self._fn = fn

    def get_auth_token(self) -> AuthTokenResult:
        return self._fn()
