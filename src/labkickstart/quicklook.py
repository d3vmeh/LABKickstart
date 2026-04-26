"""Per-run summary statistics.

Reads a finished run's CSV and computes count, mean, median, 5th/95th
percentile, sample standard deviation, and standard error of the mean
per channel (across all devices).
"""
from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path


class RunNotFoundError(Exception):
    """Mapped to HTTP 404 by the route layer."""


def _percentile(sorted_vals: list[float], p: float) -> float:
    """Linear-interpolation percentile (numpy's default). p in [0, 100]."""
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (p / 100.0) * (len(sorted_vals) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return sorted_vals[lo]
    frac = rank - lo
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])


def compute_stats(csv_path: Path) -> dict[str, dict]:
    """Group all numeric values by channel and return summary stats per
    channel. Empty file -> empty dict."""
    if not csv_path.exists():
        raise RunNotFoundError(f"no CSV at {csv_path}")
    by_channel: dict[str, list[float]] = {}
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                v = float(row["value"])
            except (TypeError, ValueError, KeyError):
                continue
            ch = row.get("channel") or ""
            if not ch:
                continue
            by_channel.setdefault(ch, []).append(v)
    out: dict[str, dict] = {}
    for ch, vals in by_channel.items():
        n = len(vals)
        if n == 0:
            continue
        s = sorted(vals)
        mean = statistics.fmean(vals)
        std = statistics.stdev(vals) if n >= 2 else 0.0
        sem = (std / math.sqrt(n)) if n >= 2 else 0.0
        out[ch] = {
            "count": n,
            "mean": mean,
            "median": _percentile(s, 50.0),
            "p5": _percentile(s, 5.0),
            "p95": _percentile(s, 95.0),
            "std": std,
            "sem": sem,
        }
    return out
