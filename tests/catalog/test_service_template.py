import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates/service-stack"


def test_service_template_contract_is_self_validating():
    result = subprocess.run(
        ["python3", "scripts/check_repo_contract.py"],
        cwd=TEMPLATE,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "valid" in result.stdout


def test_template_has_one_canonical_agent_policy():
    assert (TEMPLATE / "AGENTS.md").is_file()
    for wrapper in ("CLAUDE.md", "GEMINI.md"):
        assert "AGENTS.md" in (TEMPLATE / wrapper).read_text()


def test_repository_intelligence_commands_have_explicit_write_boundaries():
    wrapper = (TEMPLATE / "scripts/repository-intelligence.sh").read_text()
    assert "repowise-init" in wrapper
    assert "repowise-update" in wrapper
    assert "graphify-generate" in wrapper
    assert "run_query" in wrapper
    assert "REPOWISE_SKIP_EDITOR_SETUP=1" in wrapper
    assert "run-analysis-clean" not in wrapper


def test_template_is_pinned_spec_kit_ready():
    manifest = (TEMPLATE / ".specify/integration.json").read_text()
    assert '"version": "0.16.4"' in manifest
    assert '"integration": "codex"' in manifest
    constitution = (TEMPLATE / ".specify/memory/constitution.md").read_text()
    assert "[PRINCIPLE_" not in constitution
    for command in ("specify", "plan", "tasks", "analyze", "converge"):
        assert (TEMPLATE / f".agents/skills/speckit-{command}/SKILL.md").is_file()


def test_template_actions_are_pinned_by_full_commit_sha():
    workflow = (TEMPLATE / ".github/workflows/test.yml").read_text()
    action_lines = [line.strip() for line in workflow.splitlines() if "uses:" in line]
    assert action_lines
    for line in action_lines:
        revision = line.split("@", 1)[1].split()[0]
        assert len(revision) == 40
        assert all(character in "0123456789abcdef" for character in revision)
