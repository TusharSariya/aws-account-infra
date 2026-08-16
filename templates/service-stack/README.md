# Service stack

This repository was created by the platform service catalog. Start with a specification
under `specs/`, keep database changes in ordered migrations, and keep environment
credentials outside Git.

## Validate

```bash
python3 scripts/check_repo_contract.py
```

RepoWise and Graphify are optional local analysis tools. Run them through
`scripts/run-analysis-clean.sh -- <command>` so any repository mutation fails the run.
