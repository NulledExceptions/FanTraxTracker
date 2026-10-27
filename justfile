set dotenv-load

default:
    @just --list

setup:
    uv venv
    uv pip install -e ".[dev]"

discover *ARGS:
    uv run fantrax discover {{ARGS}}

sync *ARGS:
    uv run fantrax sync {{ARGS}}

report *ARGS:
    uv run fantrax report {{ARGS}}

test:
    uv run pytest

lint:
    uv run ruff check src tests
    uv run ruff format --check src tests
    uv run mypy

fmt:
    uv run ruff format src tests
    uv run ruff check --fix src tests
