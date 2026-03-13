from session_zoo.adapters.claude_code import ClaudeCodeAdapter

_ADAPTERS = {
    "claude-code": ClaudeCodeAdapter,
}


def get_adapter(name: str, **kwargs):
    cls = _ADAPTERS.get(name)
    if cls is None:
        raise ValueError(f"Unknown adapter: {name}. Available: {list(_ADAPTERS.keys())}")
    return cls(**kwargs)


def list_adapters() -> list[str]:
    return list(_ADAPTERS.keys())
