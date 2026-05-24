from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tools.code_executor import SafeCodeExecutor


@dataclass
class TestRunResult:
    __test__ = False
    success: bool
    summary: str
    stdout: str
    stderr: str


class TestRunner:
    __test__ = False

    def __init__(self) -> None:
        self.executor = SafeCodeExecutor()

    def run_playwright(self, project_path: str | Path) -> TestRunResult:
        result = self.executor.run(["npx", "playwright", "test", "--reporter=list"], cwd=project_path, timeout=120)
        summary = "Playwright tests passed" if result.success else "Playwright tests failed or could not run"
        return TestRunResult(result.success, summary, result.stdout, result.stderr)

    def run_pytest(self, project_path: str | Path) -> TestRunResult:
        result = self.executor.run(["python", "-m", "pytest", "-q"], cwd=project_path, timeout=120)
        summary = "Pytest passed" if result.success else "Pytest failed or could not run"
        return TestRunResult(result.success, summary, result.stdout, result.stderr)
