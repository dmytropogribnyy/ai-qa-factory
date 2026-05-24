from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class StructuredLogger:
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)

    def log(self, project_id: str, event: str, **fields: Any) -> None:
        log_dir = self.output_dir / project_id / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        record: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "project_id": project_id,
            **fields,
        }
        with (log_dir / "factory.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
