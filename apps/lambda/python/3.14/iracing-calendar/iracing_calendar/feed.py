"""Read-only feed delivery. Never fetches or invokes a refresh."""

from .store import Store


def lambda_handler(event, context):
    store = Store()
    if event.get("health") is True:
        from datetime import UTC, datetime

        from .sync import health

        return health(store, datetime.now(UTC))
    data, _ = store.read()
    if "ics" not in data:
        return {
            "statusCode": 503,
            "headers": {"Retry-After": "300"},
            "body": "Calendar has not been initialized.",
        }
    headers = {
        "Content-Type": "text/calendar; charset=utf-8",
        "ETag": data["etag"],
        "Cache-Control": "public, max-age=300",
        "Content-Disposition": 'inline; filename="iracing.ics"',
    }
    request = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    tags = [
        value.strip().removeprefix("W/")
        for value in request.get("if-none-match", "").split(",")
    ]
    if data["etag"] in tags or "*" in tags:
        return {"statusCode": 304, "headers": headers, "body": ""}
    return {"statusCode": 200, "headers": headers, "body": data["ics"]}
