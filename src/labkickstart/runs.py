from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Callable

from .sensors import Sample

DATA_DIR = Path("data/runs")


@dataclass
class ActiveTrigger:
    """A trigger configured for the currently active run. Fires when a
    sample on `channel` crosses `threshold` in the configured direction."""
    trigger_id: str
    channel: str
    direction: str        # "below" | "above"
    threshold: float

    def __post_init__(self) -> None:
        if self.direction not in ("below", "above"):
            raise ValueError(
                f"trigger direction must be 'below' or 'above', got {self.direction!r}"
            )

    def matches(self, sample: Sample) -> bool:
        if sample.channel != self.channel:
            return False
        if self.direction == "below":
            return sample.value <= self.threshold
        return sample.value >= self.threshold

    def to_json(self) -> dict:
        return {
            "trigger_id": self.trigger_id,
            "channel": self.channel,
            "direction": self.direction,
            "threshold": self.threshold,
        }


@dataclass
class Run:
    run_id: str
    name: str
    started_at: float
    ended_at: float | None
    csv_path: str
    triggers: list[ActiveTrigger] = field(default_factory=list)
    ended_reason: str | None = None        # e.g. "trigger:auto_stop_below"

    def to_json(self) -> dict:
        d = asdict(self)
        d["duration_s"] = (self.ended_at - self.started_at) if self.ended_at else None
        return d


class RunStore:
    """Owns the active run + CSV writer. Single-run-at-a-time."""

    def __init__(
        self,
        data_dir: Path = DATA_DIR,
        on_state_change: Callable[["Run | None"], None] | None = None,
    ):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._active: Run | None = None
        self._fh = None
        self._writer = None
        # Called whenever the active run starts or stops (including from a
        # trigger). Lets the Hub push a state-change event over the WS.
        self._on_state_change = on_state_change

    def _notify(self) -> None:
        if self._on_state_change is not None:
            try:
                self._on_state_change(self._active)
            except Exception:
                pass

    @property
    def active(self) -> Run | None:
        return self._active

    def start(self, name: str, triggers: list[ActiveTrigger] | None = None) -> Run:
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
            triggers=list(triggers or []),
        )
        self._notify()
        return self._active

    def write(self, sample: Sample) -> None:
        if self._writer is None or self._active is None:
            return
        self._writer.writerow([f"{sample.t:.6f}", sample.device_id, sample.channel, sample.value])
        # After persisting the sample, see if any trigger fires on it. The
        # triggering row is the last entry in the CSV - clean stop point.
        for trig in self._active.triggers:
            if trig.matches(sample):
                self.stop(reason=f"trigger:{trig.trigger_id}")
                return

    def stop(self, reason: str | None = None) -> Run | None:
        if self._active is None:
            return None
        self._active.ended_at = time.time()
        if reason is not None:
            self._active.ended_reason = reason
        if self._fh:
            self._fh.flush()
            self._fh.close()
        self._fh = None
        self._writer = None
        finished = self._active
        self._active = None
        self._notify()
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

    def delete_all(self) -> int:
        """Delete every CSV in data_dir. Refuses if a run is active."""
        if self._active is not None:
            raise RuntimeError("stop the active run before deleting")
        n = 0
        for p in self.data_dir.glob("*.csv"):
            p.unlink()
            n += 1
        return n
