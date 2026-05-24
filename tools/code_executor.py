from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class CommandResult:
    success: bool
    command: List[str]
    stdout: str
    stderr: str
    returncode: int


class SafeCodeExecutor:
    """Safe allowlisted command executor.

    This is intentionally narrow. Do not add broad prefixes such as
    ["npm", "run"] unless the project is fully trusted.
    """

    ALLOWED_COMMANDS = [
        ["npm", "test"],
        ["npm", "run", "test"],
        ["npm", "run", "test:ui"],
        ["npm", "run", "test:api"],
        ["npm", "run", "test:a11y"],
        ["npm", "run", "report"],
        ["npx", "playwright", "test", "--reporter=list"],
        ["npx", "playwright", "install"],
        ["npx", "playwright", "install", "--with-deps"],
        ["npx", "tsc", "--noEmit"],
        ["k6", "run", "k6-smoke.js"],
        ["python", "-m", "pytest", "-q"],
    ]

    def run(self, command: List[str], cwd: str | Path, timeout: int = 90) -> CommandResult:
        if not self._is_allowed(command):
            return CommandResult(False, command, "", "Command is not allowlisted", 126)
        try:
            result = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
            return CommandResult(result.returncode == 0, command, result.stdout, result.stderr, result.returncode)
        except Exception as exc:
            return CommandResult(False, command, "", str(exc), 1)

    def _is_allowed(self, command: List[str]) -> bool:
        return command in self.ALLOWED_COMMANDS
