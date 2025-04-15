default:
    just --list
pre-push: lint fmt-config fmt-check test
  @echo "All checks passed"
build:
  uv run scripts/file_copy.py copy
  uv build
  uv run scripts/file_copy.py clean
fix:
  uv run ruff check --fix .
fix-unsafe:
  uv run ruff check --fix --unsafe-fixes .
fmt-config:
  uv run scripts/atlas_init_sort.py
fmt-check:
  uv run ruff format --check .
fmt:
  uv run ruff format .
lint:
  uv run ruff check .
cli-help:
  uv run atlas-init
sec-test:
  uv run bandit -c pyproject.toml -r atlas_init
test:
  uv run pytest
test-file filename:
  uv run pytest {{filename}}
type-check:
  uv run pyright
