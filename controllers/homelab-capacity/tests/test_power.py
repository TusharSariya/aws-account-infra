import json
from pathlib import Path
import pytest
from homelab_capacity.imm2 import PowerController, PowerError, parse_power, parse_ack


@pytest.mark.parametrize('output,expected', [
    ('system> power off\r\nsystem> ', 'off'),
    ('system> power on\nState:System on/starting UEFI\nsystem> ', 'on'),
    ('system> power on\nState:Booting OS or in unsupported OS\nsystem> ', 'on'),
    ('system> power state\nsystem> power on\nsystem> ', 'on'),
])
def test_observed_power(output, expected):
    assert parse_power(output).power == expected


@pytest.mark.parametrize('output', [
    '', 'system> power state\nsystem>', 'system> ok',
    'power off\npower on', 'power off\nerror: permission denied',
    'system> ssh key mgr error - The public key format is unexpected!',
    'power off\nunrecognized state', 'Power: unknown',
])
def test_unknown_and_error_never_mean_off(output):
    with pytest.raises(PowerError):
        parse_power(output)


@pytest.mark.parametrize('output', ['system> error\nsystem> ok', 'power on', '', 'ok\nunknown'])
def test_exit_zero_is_not_acknowledgement(output):
    with pytest.raises(PowerError):
        parse_ack(output)


class Replies:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.commands = []

    def get_power(self):
        return parse_power(self.run("power state"))

    def request_on(self):
        parse_ack(self.run("power on"))

    def run(self, command):
        self.commands.append(command)
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


def controller(tmp_path, responses):
    config = tmp_path / 'hosts.json'
    config.write_text(json.dumps({'hosts': {'secondary': {}}, 'lock_dir': str(tmp_path/'locks')}))
    transport = Replies(responses)
    return PowerController(config, 'secondary', transport), transport


def test_on_does_not_send_power_command(tmp_path):
    c, t = controller(tmp_path, ['power on'])
    assert c.ensure_on()['changed'] is False
    assert t.commands == ['power state']


def test_wake_observes_before_and_after(tmp_path):
    c, t = controller(tmp_path, ['power off', 'system> ok\nsystem>', 'power on\nState:System running in UEFI'])
    assert c.ensure_on()['power'] == 'on'
    assert t.commands == ['power state', 'power on', 'power state']


def test_failed_observation_never_wakes(tmp_path):
    c, t = controller(tmp_path, [PowerError('unreachable')])
    with pytest.raises(PowerError):
        c.ensure_on()
    assert t.commands == ['power state']


def test_timed_out_write_not_replayed(tmp_path):
    c, t = controller(tmp_path, ['power off', PowerError('timeout'), 'power on'])
    with pytest.raises(PowerError):
        c.ensure_on()
    assert c.ensure_on()['changed'] is False
    assert t.commands == ['power state', 'power on', 'power state']


def test_per_host_lock_blocks_second_writer(tmp_path):
    c, t = controller(tmp_path, [])
    with c.locked(), pytest.raises(PowerError, match='already in progress'):
        c.ensure_on()
    assert t.commands == []

@pytest.mark.parametrize('response', [{}, {'powerstate':'unknown'}, {'powerstate':'off','error':'unreachable'}])
def test_ipmi_unknown_is_not_off(monkeypatch, response):
    from homelab_capacity.imm2 import IPMITransport
    t=IPMITransport(Path('/unused'), 'secondary')
    monkeypatch.setattr(t, 'operation', lambda _: response)
    with pytest.raises(PowerError):
        t.get_power()

@pytest.mark.parametrize('response', [{'pendingpowerstate':'reset'}, {'powerstate':'off'}, {'error':'denied'}])
def test_ipmi_wrong_ack_is_rejected(monkeypatch, response):
    from homelab_capacity.imm2 import IPMITransport
    t=IPMITransport(Path('/unused'), 'secondary')
    monkeypatch.setattr(t, 'operation', lambda _: response)
    with pytest.raises(PowerError):
        t.request_on()
