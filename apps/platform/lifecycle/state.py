"""Durable AI command and activity policy, persisted with Deployment replicas by CAS."""
from copy import deepcopy
import math
import re
import uuid

SOURCES = {'odysseus', 'ollama'}
IDLE_SECONDS = 1800
HEARTBEAT_SECONDS = 15
MAX_TICKETS = 128


class Rejected(ValueError):
    pass


def initial():
    return {'desired': 'off', 'revision': 0, 'force': False, 'reason': 'initially off',
            'commands': {}, 'tickets': {}, 'finished': {}, 'sources': {}, 'owner': '', 'interruption': None}


def command(state, action, command_id, expected_revision, capacity):
    if action not in ('start', 'stop', 'force-stop') or not isinstance(command_id, str):
        raise Rejected('Expected an approved operation and UUID command ID')
    try:
        if str(uuid.UUID(command_id)) != command_id:
            raise ValueError()
    except (ValueError, AttributeError):
        raise Rejected('Expected a canonical UUID command ID') from None
    prior = state['commands'].get(command_id)
    if prior:
        if prior['action'] != action:
            raise Rejected('Command ID already belongs to a different operation')
        return deepcopy(state), prior['revision']
    if type(expected_revision) is not int or expected_revision != state['revision']:
        raise Rejected('Command revision changed; refresh Status before issuing a new command')
    if action == 'start' and not capacity.admission:
        raise Rejected('Startup blocked by storage: ' + '; '.join(capacity.reasons))
    result = deepcopy(state)
    result['revision'] += 1
    result.update(desired='on' if action == 'start' else 'off', force=action == 'force-stop', reason=action)
    if action == 'force-stop':
        result['interruption'] = {'revision': result['revision'],
            'tickets': {key: value['source'] for key, value in result['tickets'].items()}}
    # Commands are bounded, but revision remains durable and strictly increasing.
    if len(result['commands']) >= 64:
        del result['commands'][next(iter(result['commands']))]
    result['commands'][command_id] = {'action': action, 'revision': result['revision']}
    return result, result['revision']


def begin(state, source, instance, ticket, parent, capacity, ready, *, now=0, deadline=30):
    if source not in SOURCES or not isinstance(ticket, str) or not re.fullmatch('[a-f0-9]{32}', ticket):
        raise Rejected('Invalid activity source or ticket')
    if parent is not None and (not isinstance(parent, str) or not re.fullmatch('[a-f0-9]{32}', parent)):
        raise Rejected('Invalid parent activity ticket')
    result = deepcopy(state)
    result['finished'] = {key: value for key, value in result['finished'].items() if value['until'] >= now}
    if ticket in result['finished']:
        raise Rejected('Activity already finished')
    previous = result['tickets'].get(ticket)
    value = {'source': source, 'instance': instance, 'parent': parent}
    if previous:
        if previous != value:
            raise Rejected('Ticket identity conflict')
        return result
    if type(deadline) not in (int, float) or not 0 <= deadline - now <= 30:
        raise Rejected('Activity admission deadline expired or invalid')
    if len(result['finished']) + len(result['tickets']) >= 512:
        raise Rejected('Activity admission history is full')
    if result['force']:
        raise Rejected('Forced termination requested')
    # Only an existing admitted tree can continue while normal Stop drains.
    inherited = parent and parent in result['tickets']
    if not inherited and (result['desired'] != 'on' or not ready or not capacity.admission):
        raise Rejected('New work admission is closed')
    if len(result['tickets']) >= MAX_TICKETS:
        raise Rejected('Activity tracking is full')
    result['tickets'][ticket] = value
    return result


def finish(state, source, instance, ticket, *, now=0):
    if source not in SOURCES or not isinstance(ticket, str) or not re.fullmatch('[a-f0-9]{32}', ticket):
        raise Rejected('Invalid activity identity')
    result = deepcopy(state)
    result['finished'] = {key: value for key, value in result['finished'].items() if value['until'] >= now}
    existing = result['tickets'].get(ticket)
    if existing and (existing['source'] != source or existing['instance'] != instance):
        raise Rejected('Cannot finish another activity source')
    if not existing and len(result['finished']) >= 512:
        raise Rejected('Activity completion history is full')
    result['tickets'].pop(ticket, None)
    result['finished'][ticket] = {'source': source, 'instance': instance, 'until': now + 60}
    return result


def heartbeat(state, source, instance, tickets, known, now):
    if (source not in SOURCES or type(known) is not bool or not math.isfinite(now)
            or not isinstance(tickets, list) or len(tickets) > MAX_TICKETS
            or any(not isinstance(ticket, str) or not re.fullmatch('[a-f0-9]{32}', ticket) for ticket in tickets)
            or len(set(tickets)) != len(tickets)):
        raise Rejected('Invalid activity report')
    expected = {key for key, value in state['tickets'].items()
                if value['source'] == source and value['instance'] == instance}
    result = deepcopy(state)
    result['sources'][source] = {'instance': instance, 'at': now,
                                 'known': known and set(tickets) == expected}
    return result


class Observation:
    """Only verified continuously idle observations can cause automatic Stop.

    Recreate this object on leadership acquisition; no persisted wall timestamp
    can establish inactivity through controller downtime.
    """
    def __init__(self):
        self.idle_since = None
        self.last_tick = None

    def reconcile(self, state, *, now, capacity, pods_present, ready, instances, unstarted=False, wall_time=None):
        result = deepcopy(state)
        measured_now = now if wall_time is None else wall_time
        if capacity.drain and result['desired'] == 'on':
            result.update(desired='off', revision=result['revision'] + 1, reason='storage pressure', force=False)
        unknown = []
        verification = {}
        if pods_present and not unstarted:
            for source in sorted(SOURCES):
                report = result['sources'].get(source, {})
                stamp = report.get('at')
                age = measured_now - stamp if type(stamp) in (int, float) and math.isfinite(stamp) else None
                identity = bool(instances.get(source)) and report.get('instance') == instances[source]
                reason = ('identity unverified' if not identity else
                          'work accounting unknown' if report.get('known') is not True else
                          'heartbeat stale or invalid' if age is None or not 0 <= age <= HEARTBEAT_SECONDS else
                          'verified')
                verification[source] = {'identity_verified': identity, 'known': report.get('known') is True,
                    'heartbeat_age_seconds': None if age is None else round(age, 3), 'reason': reason}
                if reason != 'verified':
                    unknown.append(source + ': activity unverified')
        elif not pods_present:
            # The caller must observe all previous containers terminated before
            # saying no Pods remain; API absence during an error is not evidence.
            result['tickets'] = {}
            result['finished'] = {}
            result['sources'] = {}
        gap = self.last_tick is None or not 0 <= now - self.last_tick <= HEARTBEAT_SECONDS
        self.last_tick = now
        idle = (result['desired'] == 'on' and ready and pods_present and not unknown
                and not result['tickets'] and capacity.admission)
        if gap or not idle:
            self.idle_since = None
        if idle and self.idle_since is None:
            self.idle_since = now
        if idle and now - self.idle_since >= IDLE_SECONDS:
            result.update(desired='off', revision=result['revision'] + 1, reason='verified idle', force=False)
            self.idle_since = None
        draining = bool(unknown or result['tickets'])
        replicas = 1 if result['desired'] == 'on' else int(pods_present and draining and not result['force'])
        if not pods_present and result['desired'] == 'off':
            observed = 'Off'
        elif result['desired'] == 'off':
            observed = 'Stopping' if replicas == 0 else 'Draining'
        elif ready:
            observed = 'On'
        else:
            observed = 'Starting/Pending'
        return result, replicas, {'desired': result['desired'], 'observed': observed,
            'revision': result['revision'], 'last_interruption': deepcopy(result.get('interruption')), 'storage_warning': capacity.warning, 'active_work': len(result['tickets']),
            'blocking_reasons': [*capacity.reasons, *unknown], 'reason': result['reason'],
            'activity_verification': verification,
            'idle_seconds': 0 if self.idle_since is None else round(max(0, now - self.idle_since), 3),
            'admission': result['desired'] == 'on' and ready and capacity.admission and not result['force'] and not unknown}
