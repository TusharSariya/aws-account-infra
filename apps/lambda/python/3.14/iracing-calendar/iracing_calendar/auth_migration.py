"""Leased, resumable transfer to SSM without two active refresh-token stores."""

import json
import time
import uuid

from botocore.exceptions import BotoCoreError, ClientError

from .auth import Auth, AuthError
from .store import client


def migrate_auth(parameters, store, client_secret, token_secret, legacy=None):
    previous, etag, owner = store.claim()
    service = Auth(parameters, store, etag, owner)
    destination = {
        "client": parameters.client_parameter,
        "tokens": parameters.token_parameter,
    }
    try:
        if previous.get("auth_storage") == destination:
            status = parameters.status()
            if not status["configured"] or status["reauthentication_required"]:
                raise AuthError("SSM authentication needs local auth bootstrap")
            return {"status": "already_migrated"}
        legacy = legacy or client("secretsmanager")
        service.fence()
        config = json.loads(
            legacy.get_secret_value(SecretId=client_secret)["SecretString"]
        )
        source = json.loads(
            legacy.get_secret_value(SecretId=token_secret)["SecretString"]
        )
        current_config = parameters.read(parameters.client_parameter)
        current_tokens = parameters.read(parameters.token_parameter)
        if current_config and current_config != config:
            raise AuthError("SSM client configuration differs; migration stopped")
        if source.get("state") == "ready":
            if current_tokens and current_tokens.get("state") != "migration_pending":
                raise AuthError(
                    "SSM token parameter is already in use; migration stopped"
                )
            if source.get("refresh_expires_at", 0) <= time.time() + 60:
                raise AuthError(
                    "Legacy refresh token expired; recover authentication before migration"
                )
            migration_id = uuid.uuid4().hex
            staged = source | {
                "state": "migration_pending",
                "migration_id": migration_id,
            }
            # Preflight BOTH sizes before changing either store. No paid-tier upgrade.
            parameters.serialize(config)
            parameters.serialize(staged)
            service.fence()
            parameters.write(parameters.client_parameter, config)
            parameters.write(parameters.token_parameter, staged)
            if parameters.read(parameters.token_parameter) != staged:
                raise AuthError("SSM migration staging could not be verified")
            service.fence()
            # Old code rejects this state. On an uncertain write, retrying this
            # command reads AWSCURRENT, never an old version or cached token.
            legacy.put_secret_value(
                SecretId=token_secret,
                SecretString=json.dumps(
                    {
                        "state": "migrated_to_ssm",
                        "migration_id": migration_id,
                        "destination": destination,
                    }
                ),
                ClientRequestToken=str(uuid.uuid4()),
            )
        elif (
            source.get("state") == "migrated_to_ssm"
            and source.get("destination") == destination
            and source.get("migration_id")
            and source["migration_id"] == current_tokens.get("migration_id")
            and current_tokens.get("state") in {"migration_pending", "ready"}
        ):
            staged = current_tokens
        else:
            raise AuthError(
                "Legacy authentication is not safely transferable; migration stopped"
            )
        service.fence()
        ready = staged | {"state": "ready"}
        if ready.get("refresh_expires_at", 0) <= time.time() + 60:
            raise AuthError(
                "Transferred refresh token expired; run local SSM auth bootstrap"
            )
        parameters.write(parameters.token_parameter, ready)
        if parameters.read(parameters.token_parameter) != ready:
            raise AuthError("SSM migration activation could not be verified")
        service.fence()
        store.publish(previous | {"auth_storage": destination}, etag, owner)
        return {"status": "migrated"}
    except BotoCoreError, ClientError, ValueError, KeyError, TypeError:
        raise AuthError(
            "Authentication migration failed; retry migration, never restore old tokens"
        ) from None
    finally:
        store.release(etag, owner)
