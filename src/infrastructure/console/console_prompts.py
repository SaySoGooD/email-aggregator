from __future__ import annotations


def prompt(text: str, default: str | None = None) -> str:
    """Read a string; return *default* if the user just hits enter."""
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{text}{suffix}: ").strip()
    return value or (default or "")


def prompt_int(text: str, default: int) -> int:
    raw = input(f"{text} [{default}]: ").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def prompt_list(text: str) -> list[str]:
    """Read a comma-separated list of addresses."""
    raw = input(f"{text}: ").strip()
    return [item.strip() for item in raw.split(",") if item.strip()]
