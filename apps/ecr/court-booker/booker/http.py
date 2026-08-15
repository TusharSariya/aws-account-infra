from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
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
            response = self._reservations.list_my_reservations(start_time=start, end_time=end)
        except ApiException as exc:
            raise UpaceHttpError(int(exc.status or 0), _error_message(exc)) from exc
        data = _get(response, "data")
        rows = _get(data, "reservations") or []
        held: list[HeldReservation] = []
        for row in rows:
            reservation_id = _get(row, "id")
            if reservation_id is None:
                continue
            equipment_id = _get(row, "equipment_id")
            class_id = _get(row, "class_id")
            held.append(
                HeldReservation(
                    id=int(reservation_id),
                    equipment_id=int(equipment_id) if equipment_id is not None else None,
                    class_id=int(class_id) if class_id is not None else None,
                    start_time=str(_get(row, "start_time") or ""),
                )
            )
        return held

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

        held = self._matching(session, request)
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
            return BookingResult(status=CANCELLED, message="cancelled matching reservation", **meta)
        if held is not None:
            return BookingResult(status=ALREADY_HELD, message="already in My Reservations", **meta)

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
            session.reserve(
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
        return BookingResult(status=BOOKED, message="reservation complete", reserve_clicks=1, **meta)

    def _matching(self, session: UpaceSession, request: BookingRequest) -> HeldReservation | None:
        end = request.target_date + timedelta(days=1)
        try:
            rows = session.reservations(request.target_date, end)
        except UpaceHttpError:
            return None
        prefix = f"{request.target_date.isoformat()} {request.hhmm}"
        for row in rows:
            ids = {value for value in (row.equipment_id, row.class_id) if value is not None}
            if request.equipment_id not in ids:
                continue
            if row.start_time.startswith(prefix):
                return row
        return None
