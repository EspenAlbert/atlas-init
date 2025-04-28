set dotenv-load

default:
    just --list
pre-push: lint fmt-check build test
  @echo "All checks passed"
quick: fmt fix lint
  @echo "All quick checks passed"
build:
  uv run scripts/file_utils.py check
  uv run scripts/file_utils.py copy
  uv run scripts/file_utils.py generate
  uv build
  uv run scripts/file_utils.py clean
clean:
  uv run scripts/file_utils.py clean
file-check:
  uv run scripts/file_utils.py check
file-generate:
  uv run scripts/file_utils.py generate
fix:
  uv run ruff check --fix .
fix-unsafe:
  uv run ruff check --fix --unsafe-fixes .
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
test-cov reportFormat="xml":
  uv run pytest --cov --cov-report={{reportFormat}}
test:
  uv run pytest
test-file filename:
  uv run pytest {{filename}}
type-check:
  uv run pyright
version:
  hatch version
bump bump-type='patch':
  hatch version {{bump-type}}

[positional-arguments]
run *args:
  uv run atlas-init {{args}}
