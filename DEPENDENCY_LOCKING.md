# Dependency Locking Strategy

Runtime dependencies are declared in `requirements.txt`.
Developer and QA tooling dependencies are declared in `requirements-dev.txt`.

For reproducible builds, generate lock files with `pip-tools`:

```bash
pip install pip-tools
pip-compile --output-file requirements-lock.txt requirements.txt
pip-compile --output-file requirements-dev-lock.txt requirements-dev.txt
```

Install using lock files in CI/production when strict reproducibility is required:

```bash
pip install -r requirements-dev-lock.txt
```
