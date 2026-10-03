"""Local Password Limited bootstrap and fail-closed, leased token rotation.

Only SSM SecureString parameters contain credentials. The snapshot lease coordinates every
exchange, including local bootstrap. An in-flight marker is durable *before*
using a single-use refresh token, so a crash cannot accidentally replay it.
"""

import base64
import hashlib
import json
import time
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

import jwt
from botocore.exceptions import BotoCoreError, ClientError

from .store import Conflict, client

ISSUER = "https://oauth.iracing.com"
JWKS = ISSUER + "/.well-known/jwks.json"
TOKEN = ISSUER + "/oauth2/token"


class AuthError(RuntimeError):
    """Sanitized operational error safe for Lambda logs and CLI output."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url, form=None):
    """Fixed OAuth origins only; never retry an exchange or follow a redirect."""
    if url not in (TOKEN, JWKS):
        raise AuthError("Unapproved authentication endpoint")
    request = Request(
        url,
        data=urlencode(form).encode() if form is not None else None,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise ValueError()
            return json.loads(body)
    except HTTPError as exc:
        # Only fixed protocol codes may escape this boundary. Never include the
        # response description, URL, request, or arbitrary upstream text.
        code = "unrecognized_error"
        try:
            payload = json.loads(exc.read(16384))
            candidate = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(candidate, str) and candidate in {
                "invalid_request",
                "invalid_client",
                "invalid_grant",
                "unauthorized_client",
                "unsupported_grant_type",
                "invalid_scope",
                "access_denied",
                "server_error",
                "temporarily_unavailable",
            }:
                code = candidate
        except ValueError, OSError, HTTPException:
            pass
        finally:
            exc.close()
        raise AuthError(
            f"Authentication HTTP {exc.code}: {code}; no automatic retry"
        ) from None
    except HTTPException, URLError, OSError, ValueError:
        # Exception text, bodies and chained exceptions may contain credentials.
        raise AuthError("Authentication request failed; no automatic retry") from None


def mask(secret, identifier):
    return base64.b64encode(
        hashlib.sha256((secret + identifier.strip().lower()).encode()).digest()
    ).decode()


def verify_access(token, config, clock=time.time, fetch=request_json):
    """Validate signature and the documented operational claims, never log JWTs."""
    try:
        header = jwt.get_unverified_header(token)
        if (
            header.get("jku") != JWKS
            or header.get("alg") != "EdDSA"
            or not header.get("kid")
        ):
            raise ValueError()
        keys = [k for k in fetch(JWKS)["keys"] if k.get("kid") == header["kid"]]
        if (
            len(keys) != 1
            or keys[0].get("kty") != "OKP"
            or keys[0].get("crv") != "Ed25519"
        ):
            raise ValueError()
        claims = jwt.decode(
            token,
            jwt.PyJWK.from_dict(keys[0], algorithm="EdDSA").key,
            algorithms=["EdDSA"],
            issuer=ISSUER,
            audience="data-server",
            options={
                "require": [
                    "exp",
                    "iat",
                    "auth_time",
                    "aud",
                    "scope",
                    "client_id",
                    "iracing_cust_id",
                ],
                "verify_sub": False,
            },
        )
        if (
            not {"data-server", "oauth-api", config["client_id"]}.issubset(
                claims["aud"]
            )
            or claims["client_id"] != config["client_id"]
            or claims["iracing_cust_id"] != config["allowed_cust_id"]
            or claims.get("iracing_env", "members") != "members"
            or "iracing.auth" not in claims["scope"].split()
            or not claims["auth_time"] <= claims["iat"] <= clock() < claims["exp"]
        ):
            raise ValueError()
    except AuthError, jwt.PyJWTError, ValueError, TypeError, KeyError, AttributeError:
        raise AuthError(
            "Access token failed account, audience, scope or signature validation"
        ) from None


class Parameters:
    def __init__(self, client_parameter, token_parameter, api=None):
        if client_parameter == token_parameter or any(
            ":" in name for name in (client_parameter, token_parameter)
        ):
            raise AuthError("Use separate unversioned SSM parameter names")
        self.api = api or client("ssm")
        self.client_parameter = client_parameter
        self.token_parameter = token_parameter

    def read(self, secret):
        try:
            parameter = self.api.get_parameter(Name=secret, WithDecryption=True)[
                "Parameter"
            ]
            value = json.loads(parameter["Value"])
            if parameter["Type"] != "SecureString" or not isinstance(value, dict):
                raise ValueError()
            return value
        except self.api.exceptions.ParameterNotFound:
            return {}
        except BotoCoreError, ClientError, ValueError, KeyError:
            raise AuthError("Unable to read authentication parameter") from None

    def write(self, secret, value):
        try:
            self.api.put_parameter(
                Name=secret,
                Value=self.serialize(value),
                Type="SecureString",
                KeyId="alias/aws/ssm",
                Tier="Standard",
                Overwrite=True,
            )
        except BotoCoreError, ClientError:
            raise AuthError(
                "Unable to persist authentication state; do not retry token exchange"
            ) from None

    @staticmethod
    def serialize(value):
        body = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        if len(body.encode("utf-8")) > 4096:
            raise AuthError("Authentication state exceeds SSM Standard's 4 KB limit")
        return body

    def status(self, now=None):
        now = time.time() if now is None else now
        state = self.read(self.token_parameter)
        return {
            "configured": bool(self.read(self.client_parameter)),
            "reauthentication_required": state.get("state") != "ready"
            or state.get("refresh_expires_at", 0) <= now,
            "access_expires_at": state.get("access_expires_at"),
            "refresh_expires_at": state.get("refresh_expires_at"),
        }


class Auth:
    """Use only within the snapshot lease; never retain tokens in reports."""

    def __init__(
        self,
        secrets,
        store,
        etag,
        owner,
        clock=time.time,
        exchange=request_json,
        verify=verify_access,
    ):
        self.secrets, self.store = secrets, store
        self.etag, self.owner = etag, owner
        self.clock, self.exchange, self.verify = clock, exchange, verify

    def fence(self):
        state, etag = self.store.read()
        # Leave enough time for the bounded HTTP exchange and secret persistence.
        if (
            etag != self.etag
            or state.get("lease") != self.owner
            or state.get("lease_until", 0) < self.clock() + 90
        ):
            raise Conflict("Authentication lease expired or changed")

    def bootstrap(self, config, username, password):
        if username.strip().lower() != config["allowed_username"].strip().lower():
            raise AuthError("Account is not the configured allowed user")
        self.fence()
        self.secrets.write(self.secrets.client_parameter, config)
        return self._exchange(
            config,
            {
                "grant_type": "password_limited",
                "username": username,
                "password": mask(password, username),
                "scope": "iracing.auth",
            },
        )

    def access(self):
        self.fence()
        config = self.secrets.read(self.secrets.client_parameter)
        tokens = self.secrets.read(self.secrets.token_parameter)
        if (
            tokens.get("state") != "ready"
            or tokens.get("refresh_expires_at", 0) <= self.clock() + 60
        ):
            raise AuthError(
                "Local auth bootstrap required; refresh token unavailable or exchange outcome unknown"
            )
        if tokens.get("access_expires_at", 0) > self.clock() + 120:
            self.verify(tokens["access_token"], config)
            return tokens["access_token"]
        return self._exchange(
            config,
            {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]},
        )

    def _exchange(self, config, form):
        self.fence()
        # Replace the latest value before exchange. Never recover a historical
        # parameter version: its single-use refresh token may already be consumed.
        self.secrets.write(self.secrets.token_parameter, {"state": "exchange_pending"})
        self.fence()
        started = self.clock()
        response = self.exchange(
            TOKEN,
            form
            | {
                "client_id": config["client_id"],
                "client_secret": mask(config["client_secret"], config["client_id"]),
            },
        )
        try:
            if (
                response["token_type"] != "Bearer"
                or "iracing.auth" not in response["scope"].split()
                or not response["access_token"]
                or not response["refresh_token"]
                or type(response["expires_in"]) is not int
                or response["expires_in"] <= 0
                or type(response["refresh_token_expires_in"]) is not int
                or response["refresh_token_expires_in"] <= 0
            ):
                raise ValueError()
            tokens = {
                "state": "unverified",
                "access_token": response["access_token"],
                "refresh_token": response["refresh_token"],
                "access_expires_at": started + response["expires_in"],
                "refresh_expires_at": started + response["refresh_token_expires_in"],
            }
        except KeyError, ValueError, TypeError, AttributeError:
            raise AuthError(
                "Invalid token response; local auth bootstrap required"
            ) from None
        self.fence()
        # Persist the issued pair before any follow-up network request.
        self.secrets.write(self.secrets.token_parameter, tokens)
        self.verify(tokens["access_token"], config)
        self.fence()
        self.secrets.write(self.secrets.token_parameter, tokens | {"state": "ready"})
        return tokens["access_token"]
