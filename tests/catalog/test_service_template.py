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


def test_analysis_wrapper_checks_worktree_cleanliness():
    wrapper = (TEMPLATE / "scripts/run-analysis-clean.sh").read_text()
    assert wrapper.count("git status --porcelain") == 2


def test_template_actions_are_pinned_by_full_commit_sha():
    workflow = (TEMPLATE / ".github/workflows/test.yml").read_text()
    action_lines = [line.strip() for line in workflow.splitlines() if "uses:" in line]
    assert action_lines
    for line in action_lines:
        revision = line.split("@", 1)[1].split()[0]
        assert len(revision) == 40
        assert all(character in "0123456789abcdef" for character in revision)
