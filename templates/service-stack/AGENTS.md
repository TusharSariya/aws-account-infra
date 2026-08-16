# Agent instructions

This repository is a vended service repository.

- Treat `specs/` as the product specification authority.
- Keep infrastructure declarative and reviewable. Do not make live cloud changes from pull requests.
- Never print, commit, or pass credentials in command arguments. Resolve secrets only at runtime.
- Agents have no database row access by default. Any exception must be explicit in the service catalog.
- Run `python3 scripts/check_repo_contract.py` before opening a pull request.
