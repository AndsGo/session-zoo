# Contributing to session-zoo

Thanks for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/AndsGo/session-zoo.git
cd session-zoo
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest
```

## Code Style

- Python 3.12+ with type hints
- Keep functions focused and small
- Follow existing patterns in the codebase

## Adding a New Adapter

To support a new AI tool (e.g., Cursor, Copilot), create a new adapter:

1. Create `src/session_zoo/adapters/your_tool.py`
2. Implement the adapter class with `discover()`, `parse()`, `get_restore_path()` methods
3. Register it in `src/session_zoo/adapters/__init__.py`
4. Add tests in `tests/test_your_tool_adapter.py`

See `adapters/claude_code.py` for reference.

## Pull Request Process

1. Fork the repo and create a branch from `main`
2. Add tests for any new functionality
3. Ensure all tests pass (`pytest`)
4. Submit a PR with a clear description of the changes
