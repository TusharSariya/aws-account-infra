import sys
from pathlib import Path
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'apps/platform/lifecycle'), str(ROOT / 'apps/platform/storage')]
from capacity import Decision
from state import Observation, Rejected, begin, command, finish, heartbeat, initial

GOOD = Decision(True, False, False, ())
BAD = Decision(False, True, True, ('missing measurement',))


class StateTests(unittest.TestCase):
    def start(self):
        return command(initial(), 'start', str(uuid.uuid4()), 0, GOOD)[0]

    def test_durable_commands_supersede_pending_start_and_reject_stale_revision(self):
        identity = str(uuid.uuid4())
        on, revision = command(initial(), 'start', identity, 0, GOOD)
        off, _ = command(on, 'stop', str(uuid.uuid4()), revision, GOOD)
        repeated, acknowledged = command(off, 'start', identity, 0, GOOD)
        self.assertEqual(repeated['desired'], 'off')
        self.assertEqual(acknowledged, 1)
        with self.assertRaises(Rejected):
            command(off, 'start', str(uuid.uuid4()), 1, GOOD)
        with self.assertRaises(Rejected):
            command(off, 'start', str(uuid.uuid4()), 2, BAD)
        for action in ('stop', 'force-stop'):
            self.assertEqual(command(off, action, str(uuid.uuid4()), 2, BAD)[0]['desired'], 'off')

    def test_admitted_work_can_extend_drain_but_new_work_cannot(self):
        state = begin(self.start(), 'odysseus', 'instance', 'a' * 32, None, GOOD, True)
        state, _ = command(state, 'stop', str(uuid.uuid4()), 1, GOOD)
        with self.assertRaises(Rejected):
            begin(state, 'ollama', 'instance', 'b' * 32, None, GOOD, True)
        state = begin(state, 'ollama', 'instance', 'b' * 32, 'a' * 32, BAD, False)
        state = finish(state, 'odysseus', 'instance', 'a' * 32)
        self.assertEqual(len(state['tickets']), 1)
        with self.assertRaises(Rejected):
            finish(state, 'odysseus', 'instance', 'b' * 32)
        state, _ = command(state, 'force-stop', str(uuid.uuid4()), 2, GOOD)
        with self.assertRaises(Rejected):
            begin(state, 'ollama', 'instance', 'c' * 32, 'b' * 32, GOOD, True)

    def observe(self, observer, state, now, known=True, **kwargs):
        for source in ('odysseus', 'ollama'):
            tickets = [ticket for ticket, value in state['tickets'].items() if value['source'] == source]
            state = heartbeat(state, source, source, tickets, known, now)
        return observer.reconcile(state, now=now, capacity=kwargs.get('capacity', GOOD),
            pods_present=kwargs.get('pods_present', True), ready=kwargs.get('ready', True),
            instances={'odysseus': 'odysseus', 'ollama': 'ollama'})

    def test_exact_idle_interval_excludes_heartbeat_and_resets_on_unknown_or_recovery(self):
        observer, state = Observation(), self.start()
        for now in range(0, 1800, 5):
            state, replicas, status = self.observe(observer, state, now)
            self.assertEqual(replicas, 1)
        state, replicas, status = self.observe(observer, state, 1800)
        self.assertEqual((state['desired'], replicas), ('off', 0))
        observer, state = Observation(), self.start()
        for now in range(0, 1795, 5):
            state, _, _ = self.observe(observer, state, now)
        state, _, status = self.observe(observer, state, 1795, known=False)
        self.assertFalse(status['admission'])
        state, replicas, _ = self.observe(observer, state, 1800)
        self.assertEqual(replicas, 1)
        self.assertEqual(observer.idle_since, 1800)
        recovered = Observation()
        state, replicas, _ = self.observe(recovered, state, 3600)
        self.assertEqual((replicas, recovered.idle_since), (1, 3600))

    def test_stop_never_forces_unknown_work_and_force_waits_for_observed_termination(self):
        state, _ = command(self.start(), 'stop', str(uuid.uuid4()), 1, GOOD)
        state, replicas, status = self.observe(Observation(), state, 0, known=False)
        self.assertEqual((replicas, status['observed']), (1, 'Draining'))
        state, _ = command(state, 'force-stop', str(uuid.uuid4()), 2, GOOD)
        state, replicas, status = self.observe(Observation(), state, 5, known=False)
        self.assertEqual((replicas, status['observed']), (0, 'Stopping'))
        state, replicas, status = self.observe(Observation(), state, 10, pods_present=False, ready=False)
        self.assertEqual((replicas, status['observed']), (0, 'Off'))

    def test_pressure_latches_desired_off_without_force_or_automatic_restart(self):
        state = begin(self.start(), 'odysseus', 'odysseus', 'a' * 32, None, GOOD, True)
        state, replicas, _ = self.observe(Observation(), state, 0, capacity=BAD)
        self.assertEqual((state['desired'], state['force'], replicas), ('off', False, 1))
        state = finish(state, 'odysseus', 'odysseus', 'a' * 32)
        state, replicas, _ = self.observe(Observation(), state, 5)
        self.assertEqual((state['desired'], replicas), ('off', 0))

    def test_stop_cancels_verified_unstarted_pending_pod(self):
        state, _ = command(self.start(), 'stop', str(uuid.uuid4()), 1, GOOD)
        state, replicas, status = Observation().reconcile(state, now=0, capacity=GOOD,
            pods_present=True, ready=False, instances={}, unstarted=True)
        self.assertEqual((replicas, status['observed']), (0, 'Stopping'))

    def test_delayed_admission_cannot_resurrect_finished_work(self):
        state = self.start()
        state = finish(state, 'ollama', 'ollama', 'a' * 32, now=5)
        with self.assertRaises(Rejected):
            begin(state, 'ollama', 'ollama', 'a' * 32, None, GOOD, True, now=6, deadline=30)
        with self.assertRaises(Rejected):
            begin(state, 'ollama', 'ollama', 'a' * 32, None, GOOD, True, now=70, deadline=30)
        with self.assertRaises(Rejected):
            begin(state, 'ollama', 'ollama', 'b' * 32, None, GOOD, True, now=5, deadline=99999)


class InterruptionTests(unittest.TestCase):
    def test_force_stop_retains_interruption_record_after_observed_termination(self):
        state = initial()
        state, _ = command(state, 'start', str(uuid.uuid4()), 0, GOOD)
        state = begin(state, 'odysseus', 'instance', 'a' * 32, None, GOOD, True)
        state, revision = command(state, 'force-stop', str(uuid.uuid4()), 1, GOOD)
        state, replicas, status = Observation().reconcile(state, now=0, capacity=GOOD,
            pods_present=False, ready=False, instances={})
        self.assertEqual((replicas, status['observed'], status['active_work']), (0, 'Off', 0))
        self.assertEqual(status['last_interruption'], {'revision': revision, 'tickets': {'a' * 32: 'odysseus'}})
