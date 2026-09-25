from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from booker.calendar_contract import normalize_reservation
from typing import Any, Callable, Protocol

from booker.results import (
    ALREADY_HELD,
    AUTH_FAIL,
    BOOKED,
    CANCELLED,
    CLOSED,
    DRY_RUN,
    FULL,
    MEMBERSHIP,
    UNEXPECTED_UI,
    BookingResult,
)
from booker.secrets import Credentials
from booker.stub import BookingRequest
from booker.timing import Stopwatch

ORIGIN = "https://embed.upace.app"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class UpaceHttpError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(f"{status}: {message}")


@dataclass(frozen=True)
class HeldReservation:
    id: int
    equipment_id: int | None
    class_id: int | None
    start_time: str
    end_time: str = ""
    cancelled: bool = False


class UpaceSession(Protocol):
    def login(self, username: str, password: str) -> None: ...
    def available_duration_values(self, equipment_id: int, target_date: date, hhmm: str) -> list[int]: ...
    def reservations(self, start: date, end: date) -> list[HeldReservation]: ...
    def reserve(
        self,
        *,
        equipment_id: int,
        target_date: date,
        hhmm: str,
        duration_min: int,
        people: int,
    ) -> int: ...
    def cancel(self, reservation_id: int) -> None: ...


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _json_body(response: Any) -> Any:
    raw = response.read() if hasattr(response, "read") else response
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not raw:
        return {}
    if isinstance(raw, (dict, list)):
        return raw
    return json.loads(raw)


def _reservation_id(payload: Any) -> int | None:
    value = _get(payload, "id") or _get(_get(payload, "data"), "reservation_id")
    if value is None:
        return None
    return int(value)


def _error_message(exc: BaseException) -> str:
    body = getattr(exc, "body", None) or getattr(exc, "data", None)
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    if isinstance(body, str) and body.strip():
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return body.strip()
        if isinstance(parsed, dict):
            return str(parsed.get("message") or body.strip())
        return body.strip()
    data = getattr(exc, "data", None)
    message = _get(data, "message")
    if message:
        return str(message)
    return str(exc)


def _classify_bad_request(message: str) -> str:
    lower = message.lower()
    if "membership" in lower:
        return MEMBERSHIP
    if "not open" in lower or "closed" in lower:
        return CLOSED
    if "spot" in lower or "full" in lower or "capacity" in lower:
        return FULL
    return CLOSED


def _validated_reservations(response: Any) -> list[HeldReservation]:
    """Only the complete, successful endpoint shape can represent an empty calendar."""
    data = _get(response, "data")
    rows = _get(data, "reservations")
    if _get(response, "success") is not True or not isinstance(rows, list):
        raise UpaceHttpError(502, "invalid reservations response")
    # The verified endpoint is unpaginated. Fail closed if that contract changes.
    for container in (response, data):
        for key in ("next", "next_page", "next_cursor", "has_more", "pagination", "links"):
            if _get(container, key):
                raise UpaceHttpError(502, "incomplete reservations response")
        total = _get(container, "total")
        if total is not None and total != len(rows):
            raise UpaceHttpError(502, "incomplete reservations response")
    result = []
    seen = set()
    try:
        for row in rows:
            reservation_id = _strict_id(_get(row, "id"))
            equipment_id = _get(row, "equipment_id")
            class_id = _get(row, "class_id")
            equipment_id = _strict_id(equipment_id) if equipment_id is not None else None
            class_id = _strict_id(class_id) if class_id is not None else None
            if reservation_id in seen or (equipment_id is None and class_id is None):
                raise ValueError("missing identity or duplicate reservation")
            seen.add(reservation_id)
            start, end = _get(row, "start_time"), _get(row, "end_time")
            if not isinstance(start, str) or not isinstance(end, str):
                raise ValueError("missing reservation times")
            if datetime.fromisoformat(end) <= datetime.fromisoformat(start):
                raise ValueError("invalid reservation interval")
            active, deleted = _get(row, "active"), _get(row, "deleted")
            if type(active) is not int or active not in (0, 1):
                raise ValueError("invalid reservation active state")
            if type(deleted) is not int or deleted not in (0, 1):
                raise ValueError("invalid reservation deleted state")
            cancelled_on = _get(row, "cancelled_on")
            if cancelled_on is not None:
                datetime.fromisoformat(cancelled_on)
            result.append(HeldReservation(
                id=reservation_id, equipment_id=equipment_id, class_id=class_id,
                start_time=start, end_time=end,
                cancelled=not active or bool(deleted) or cancelled_on is not None,
            ))
    except (TypeError, ValueError, OverflowError) as exc:
        raise UpaceHttpError(502, "malformed reservation data") from exc
    return result


def _strict_id(value: Any) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("invalid reservation identifier")
    return value


def _held_calendar(held: HeldReservation, request: BookingRequest, *, status="confirmed"):
    if not held.end_time:
        return None
    return normalize_reservation(
        reservation_id=held.id, equipment_id=request.equipment_id,
        start=held.start_time, end=held.end_time, court=request.activity_label,
        status=status, timezone=request.timezone,
        visibility=request.visibility, title=request.title,
    )


class GeneratedUpaceSession:
    """Thin adapter over the generated `upace` package. Lazy-imported so unit
    tests can inject a fake without CodeArtifact.
    """

    def __init__(self) -> None:
        from upace import (
            ApiClient,
            AuthApi,
            Configuration,
            EquipmentApi,
            ReservationsApi,
        )

        configuration = Configuration(host="https://upace.app/api")
        configuration.access_token = None
        self._configuration = configuration
        self._client = ApiClient(configuration)
        self._client.user_agent = USER_AGENT
        self._client.set_default_header("Origin", ORIGIN)
        self._auth = AuthApi(self._client)
        self._equipment = EquipmentApi(self._client)
        self._reservations = ReservationsApi(self._client)

    def login(self, username: str, password: str) -> None:
        from upace import ApiException, LoginLegacyRequest

        try:
            response = self._auth.login_legacy(
                login_legacy_request=LoginLegacyRequest(email=username, password=password),
                origin=ORIGIN,
                _request_timeout=(5, 20),
            )
        except ApiException as exc:
            raise UpaceHttpError(int(exc.status or 0), _error_message(exc)) from exc
        token = _get(response, "token")
        if not token or _get(response, "success") is False:
            raise UpaceHttpError(401, str(_get(response, "message") or "login failed"))
        self._configuration.access_token = str(token)

    def available_duration_values(self, equipment_id: int, target_date: date, hhmm: str) -> list[int]:
        from upace import ApiException

        try:
            response = self._equipment.list_available_durations(
                equipment_id,
                var_date=target_date,
                start_time=hhmm,
                _request_timeout=(5, 20),
            )
        except ApiException as exc:
            raise UpaceHttpError(int(exc.status or 0), _error_message(exc)) from exc
        values: list[int] = []
        for item in _get(response, "data") or []:
            value = _get(item, "value")
            if value is not None:
                values.append(int(value))
        return values

    def reservations(self, start: date, end: date) -> list[HeldReservation]:
        from upace import ApiException

        try:
            response = self._reservations.list_my_reservations_without_preload_content(
                start_time=start, end_time=end, _request_timeout=(5, 20),
            )
        except ApiException as exc:
            raise UpaceHttpError(int(exc.status or 0), _error_message(exc)) from exc
        if int(getattr(response, "status", 0) or 0) != 200:
            raise UpaceHttpError(502, "unsuccessful reservations response")
        try:
            payload = _json_body(response)
        except (ValueError, TypeError, UnicodeError) as exc:
            raise UpaceHttpError(502, "invalid reservations JSON") from exc
        return _validated_reservations(payload)

    def reserve(
        self,
        *,
        equipment_id: int,
        target_date: date,
        hhmm: str,
        duration_min: int,
        people: int,
    ) -> int:
        from upace import ApiException, ReserveRequest

        try:
            # Parse JSON ourselves. The generated ReserveSuccess model treats
            # OpenAPI `const: true` as the string enum `'true'`, so typed
            # deserialize rejects a real boolean `true` after a 200.
            response = self._reservations.reserve_without_preload_content(
                reserve_request=ReserveRequest(
                    var_date=target_date,
                    equipment_id=equipment_id,
                    type="equipment",
                    time=hhmm,
                    duration=duration_min,
                    attending_persons=people,
                )
            )
        except ApiException as exc:
            raise UpaceHttpError(int(exc.status or 0), _error_message(exc)) from exc
        status = int(getattr(response, "status", 0) or 0)
        payload = _json_body(response)
        if status >= 400:
            raise UpaceHttpError(status, str(_get(payload, "message") or payload or f"HTTP {status}"))
        reservation_id = _reservation_id(payload)
        if reservation_id is None:
            raise UpaceHttpError(status or 200, str(_get(payload, "message") or "reserve returned no id"))
        return reservation_id

    def cancel(self, reservation_id: int) -> None:
        from upace import ApiException, CancelRequest

        try:
            self._reservations.cancel_reservation(
                cancel_request=CancelRequest(reservation_id=reservation_id)
            )
        except ApiException as exc:
            raise UpaceHttpError(int(exc.status or 0), _error_message(exc)) from exc


class UpaceHttpBooker:
    """Book via POST /api rather than driving the embed calendar in Chromium."""

    def __init__(self, *, session_factory: Callable[[], UpaceSession] | None = None) -> None:
        self._session_factory = session_factory or GeneratedUpaceSession

    def book(self, request: BookingRequest, creds: Credentials) -> BookingResult:
        return self._run(request, creds, cancel=False)

    def cancel(self, request: BookingRequest, creds: Credentials) -> BookingResult:
        return self._run(request, creds, cancel=True)

    def _run(self, request: BookingRequest, creds: Credentials, *, cancel: bool) -> BookingResult:
        meta = dict(
            target_date=request.target_date.isoformat(),
            activity=request.activity_key,
            time=request.hhmm,
        )
        clock = Stopwatch("upace_http", activity=request.activity_key, time=request.hhmm)
        if request.equipment_id is None:
            return BookingResult(status=UNEXPECTED_UI, message="missing equipment_id", **meta)
        session = self._session_factory()
        clock.mark("session")
        try:
            session.login(creds.username, creds.password)
        except UpaceHttpError as exc:
            clock.mark("login", error=True)
            if exc.status in {0, 401, 403}:
                return BookingResult(status=AUTH_FAIL, message=exc.message, **meta)
            return BookingResult(status=UNEXPECTED_UI, message=exc.message, **meta)
        clock.mark("login")

        try:
            held = self._matching(session, request)
        except UpaceHttpError:
            return BookingResult(status=UNEXPECTED_UI, message="could not validate existing reservations", **meta)
        clock.mark("list_reservations", held=held is not None)
        if cancel:
            if held is None:
                return BookingResult(status=UNEXPECTED_UI, message="matching reservation not found", **meta)
            if request.dry_run:
                return BookingResult(status=DRY_RUN, message="cancel skipped", **meta)
            try:
                session.cancel(held.id)
            except UpaceHttpError as exc:
                clock.mark("cancel", error=True)
                return BookingResult(status=UNEXPECTED_UI, message=exc.message, **meta)
            clock.mark("cancel")
            return BookingResult(
                status=CANCELLED, message="cancelled matching reservation",
                reservation_id=str(held.id),
                calendar_reservation=_held_calendar(held, request, status="cancelled"), **meta,
            )
        if held is not None:
            return BookingResult(
                status=DRY_RUN if request.dry_run else ALREADY_HELD,
                message="already in My Reservations",
                reservation_id=str(held.id),
                calendar_reservation=None if request.dry_run else _held_calendar(held, request),
                **meta,
            )

        try:
            durations = session.available_duration_values(
                request.equipment_id, request.target_date, request.hhmm
            )
        except UpaceHttpError as exc:
            clock.mark("list_durations", error=True)
            return BookingResult(status=_classify_bad_request(exc.message), message=exc.message, **meta)
        clock.mark("list_durations", durations=len(durations))
        if not durations:
            return BookingResult(status=CLOSED, message=f"no start time {request.hhmm}", **meta)
        if request.duration_min not in durations:
            return BookingResult(
                status=FULL,
                message=f"{request.hhmm} has no {request.duration_min} min duration",
                **meta,
            )
        if request.dry_run:
            return BookingResult(status=DRY_RUN, message="slot available, reserve skipped", **meta)
        try:
            reservation_id = session.reserve(
                equipment_id=request.equipment_id,
                target_date=request.target_date,
                hhmm=request.hhmm,
                duration_min=request.duration_min,
                people=request.people,
            )
        except UpaceHttpError as exc:
            clock.mark("reserve", error=True)
            return BookingResult(status=_classify_bad_request(exc.message), message=exc.message, **meta)
        except Exception as exc:
            clock.mark("reserve", error=True)
            return BookingResult(status=UNEXPECTED_UI, message=str(exc), **meta)
        clock.mark("reserve")
        start = datetime.fromisoformat(f"{request.target_date.isoformat()}T{request.hhmm}")
        return BookingResult(
            status=BOOKED, message="reservation complete", reserve_clicks=1,
            reservation_id=str(reservation_id),
            calendar_reservation=normalize_reservation(
                reservation_id=reservation_id, equipment_id=request.equipment_id,
                start=start.isoformat(), end=(start + timedelta(minutes=request.duration_min)).isoformat(),
                court=request.activity_label, timezone=request.timezone,
                visibility=request.visibility, title=request.title,
            ), **meta,
        )

    def _matching(self, session: UpaceSession, request: BookingRequest) -> HeldReservation | None:
        end = request.target_date + timedelta(days=1)
        rows = session.reservations(request.target_date, end)
        target = datetime.fromisoformat(f"{request.target_date.isoformat()}T{request.hhmm}")
        for row in rows:
            ids = {value for value in (row.equipment_id, row.class_id) if value is not None}
            if request.equipment_id not in ids:
                continue
            if row.cancelled:
                continue
            row_start = datetime.fromisoformat(row.start_time)
            if row_start.tzinfo is not None:
                row_start = row_start.astimezone(ZoneInfo(request.timezone)).replace(tzinfo=None)
            if row_start == target:
                return row
        return None
