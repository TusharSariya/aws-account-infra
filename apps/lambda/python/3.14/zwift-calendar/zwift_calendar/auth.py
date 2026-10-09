"""Serialize authentication, persist issued tokens, and never log credentials."""

import os
import time

from .errors import AuthenticationError, ContractError
from .transport import TOKEN_URL

CREDENTIALS = "/staging/zwift-calendar/credentials"
TOKENS = "/staging/zwift-calendar/tokens"


class Auth:
    def __init__(self, transport, parameters, store, clock=time.time):
        self.http, self.parameters, self.store, self.clock = (
            transport,
            parameters,
            store,
            clock,
        )
        self.credentials_name = os.environ.get(
            "ZWIFT_CREDENTIALS_PARAMETER", CREDENTIALS
        )
        self.tokens_name = os.environ.get("ZWIFT_TOKENS_PARAMETER", TOKENS)

    def access(self):
        self.store.fence()
        saved = self.parameters.read(self.tokens_name, missing=True)
        if saved.get("expires_at", 0) > self.clock() + 120 and saved.get(
            "access_token"
        ):
            return saved["access_token"]
        if (
            saved.get("refresh_token")
            and saved.get("refresh_expires_at", 0) > self.clock() + 120
        ):
            try:
                return self.exchange(
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": saved["refresh_token"],
                    }
                )
            except AuthenticationError:
                # A rejected refresh can reauthenticate, but transport uncertainty
                # is not retried within this invocation.
                pass
        credentials = self.parameters.read(self.credentials_name)
        if not all(
            isinstance(credentials.get(k), str) and credentials[k]
            for k in ("username", "password")
        ):
            raise AuthenticationError("Zwift credentials are not configured")
        return self.exchange(
            {
                "grant_type": "password",
                **{k: credentials[k] for k in ("username", "password")},
            }
        )

    def exchange(self, form):
        self.store.fence()
        self.parameters.write(self.tokens_name, {"state": "exchange_pending"})
        started = self.clock()
        value = self.http.request(
            TOKEN_URL, form={"client_id": "Zwift_Mobile_Link", **form}
        )
        if not isinstance(value, dict) or any(
            not isinstance(value.get(k), str) or not value[k]
            for k in ("access_token", "refresh_token")
        ):
            raise ContractError("Invalid Zwift token response")
        if any(
            type(value.get(k)) is not int or value[k] <= 0
            for k in ("expires_in", "refresh_expires_in")
        ):
            raise ContractError("Invalid Zwift token expiration")
        self.store.fence()
        self.parameters.write(
            self.tokens_name,
            {
                "access_token": value["access_token"],
                "refresh_token": value["refresh_token"],
                "expires_at": started + value["expires_in"],
                "refresh_expires_at": started + value["refresh_expires_in"],
            },
        )
        return value["access_token"]
