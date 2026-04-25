from __future__ import annotations

import csv
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .sensors import Sample

DATA_DIR = Path("data/runs")


@dataclass
class Run:
    run_id: str
    name: str
    started_at: float
    ended_at: float | None
    csv_path: str

    def to_json(self) -> dict:
        d = asdict(self)
        d["duration_s"] = (self.ended_at - self.started_at) if self.ended_at else None
        return d


class RunStore:
    """Owns the active run + CSV writer. Single-run-at-a-time."""

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._active: Run | None = None
        self._fh = None
        self._writer = None

    @property
    def active(self) -> Run | None:
        return self._active

    def start(self, name: str) -> Run:
        if self._active is not None:
            raise RuntimeError("a run is already active")
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name) or "run"
        csv_path = self.data_dir / f"{run_id}_{safe}.csv"
        self._fh = csv_path.open("w", newline="")
        self._writer = csv.writer(self._fh)
        self._writer.writerow(["t", "device_id", "channel", "value"])
        self._active = Run(
            run_id=run_id,
            name=name,
            started_at=time.time(),
            ended_at=None,
            csv_path=str(csv_path),
        )
        return self._active

    def write(self, sample: Sample) -> None:
        if self._writer is None:
            return
        self._writer.writerow([f"{sample.t:.6f}", sample.device_id, sample.channel, sample.value])

    def stop(self) -> Run | None:
        if self._active is None:
            return None
        self._active.ended_at = time.time()
        if self._fh:
            self._fh.flush()
            self._fh.close()
        self._fh = None
        self._writer = None
        finished = self._active
        self._active = None
        return finished

    def list(self) -> list[dict]:
        out: list[dict] = []
        for p in sorted(self.data_dir.glob("*.csv"), reverse=True):
            stat = p.stat()
            run_id = p.stem.split("_", 1)[0]
            name = p.stem.split("_", 1)[1] if "_" in p.stem else ""
            out.append({
                "run_id": run_id,
                "name": name,
                "csv_path": str(p),
                "size_bytes": stat.st_size,
                "modified": stat.st_mtime,
            })
        return out

    def path_for(self, run_id: str) -> Path | None:
        for p in self.data_dir.glob(f"{run_id}_*.csv"):
            return p
        return None
