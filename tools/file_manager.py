from __future__ import annotations

from pathlib import Path
from typing import Dict


class FileManager:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_many(self, project_id: str, files: Dict[str, str]) -> Path:
        project_dir = (self.output_dir / project_id).resolve()
        project_dir.mkdir(parents=True, exist_ok=True)

        for relative_path, content in files.items():
            file_path = (project_dir / relative_path).resolve()
            if not self._is_relative_to(file_path, project_dir):
                raise ValueError(f"Blocked path traversal attempt: {relative_path}")
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        index = "# Output Index\n\n" + "\n".join(f"- `{path}`" for path in sorted(files.keys())) + "\n"
        (project_dir / "output_index.md").write_text(index, encoding="utf-8")
        return project_dir

    @staticmethod
    def _is_relative_to(path: Path, base: Path) -> bool:
        try:
            path.relative_to(base)
            return True
        except ValueError:
            return False
