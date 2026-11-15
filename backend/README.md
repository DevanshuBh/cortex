# CORTEX backend

FastAPI API, Celery workers, retrieval, knowledge graph and agents. See the repository README for how to run the
whole stack and `../docs/design.md` for the design.

```bash
uv sync                      # install (Python 3.13)
uv run ruff check . && uv run mypy
uv run pytest -m "not integration and not sandbox"   # unit tests
uv run pytest -m integration                          # needs Docker (Testcontainers)
```
