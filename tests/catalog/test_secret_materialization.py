from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_harvester_secrets_never_use_command_line_literals():
    tasks = (ROOT / "ansible/roles/cluster_harvester/tasks/main.yml").read_text()
    assert "--from-literal" not in tasks
    assert "vault_harvester_service_key }}" not in tasks
    assert "vault_harvester_keda_dsn }}" not in tasks
    assert "lookup('ansible.builtin.template'" in tasks


def test_harvester_secret_tasks_suppress_output_and_diffs():
    tasks = (ROOT / "ansible/roles/cluster_harvester/tasks/main.yml").read_text()
    worker = tasks.split("- name: Apply the harvester worker secret from Vault", 1)[1]
    worker = worker.split("- name:", 1)[0]
    keda = tasks.split("- name: Apply the KEDA postgresql scaler secret", 1)[1]
    keda = keda.split("- name:", 1)[0]
    assert "no_log: true" in worker
    assert "no_log: true" in keda


def test_no_ansible_role_passes_secret_literals_on_process_argv():
    offenders = []
    for path in (ROOT / "ansible/roles").glob("*/tasks/*.yml"):
        active_lines = [
            line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
        ]
        if any("--from-literal" in line for line in active_lines):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []
