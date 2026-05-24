from __future__ import annotations

from typing import Iterable


def prompt_user_choice(prompt: str, choices: Iterable[str], default: str | None = None) -> str:
    choices = list(choices)
    choice_hint = "/".join(choices)
    while True:
        suffix = f" [{choice_hint}]"
        if default:
            suffix += f" default={default}"
        value = input(f"{prompt}{suffix}: ").strip().lower()
        if not value and default:
            return default
        if value in choices:
            return value
        print(f"Please choose one of: {choice_hint}")


def prompt_user_text(prompt: str, default: str = "") -> str:
    value = input(f"{prompt}: ").strip()
    return value or default


def prompt_user_confirm(prompt: str, default: bool = False) -> bool:
    default_text = "Y/n" if default else "y/N"
    value = input(f"{prompt} [{default_text}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "true", "1"}
