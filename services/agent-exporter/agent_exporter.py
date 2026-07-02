#!/usr/bin/env python3
"""
agent-exporter — AIAMSBS agent-activity Prometheus exporter (BACKLOG #29).

Reads Hermes Agent state and emits 6 SQLite-derived metrics on /metrics:
  - hermes_session_duration_seconds_bucket{profile,end_reason}  histogram
  - hermes_sessions_active{profile}                              gauge
  - hermes_estimated_cost_usd_total{model,profile}              counter
  - hermes_kanban_runs_in_flight{assignee}                      gauge
  - hermes_kanban_runs_total{assignee,outcome}                  counter
  - hermes_cron_job_last_success_timestamp{job_name}            gauge

Plus 3 self-health metrics:
  - hermes_exporter_up                                            gauge
  - hermes_exporter_scrape_duration_seconds                      histogram
  - hermes_exporter_db_size_bytes{path}                          gauge

Data sources (all read-only, no writes):
  - ~/.hermes/profiles/*/state.db     (sessions, messages)
  - ~/.hermes/kanban.db               (tasks, task_runs)  — global
  - ~/.hermes/profiles/*/kanban.db    (tasks, task_runs)  — per-profile
  - ~/.hermes/cron/jobs.json          (cron job last_status)

Profile discovery is glob-based (~/.hermes/profiles/*); we label with
{profile=<dirname>} and never hardcode profile names. If a customer's
deployment has different profile names this still works.

Missing files are handled gracefully — the VM may not have a kanban.db or
cron/jobs.json on a fresh bootstrap. The exporter stays up; those metrics
just don't appear until the files exist.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Iterable

from prometheus_client import (
    CollectorRegistry,
    Gauge,
    Histogram,
    Counter,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily, HistogramMetricFamily

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LISTEN_PORT = int(os.environ.get("AGENT_EXPORTER_PORT", "9117"))
SCRAPE_INTERVAL_SEC = int(os.environ.get("AGENT_EXPORTER_INTERVAL", "15"))
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))

# SQLite read-only safety: open with mode=ro and PRAGMA query_only=1 to make
# sure we never block a writer. WAL sidecars (-wal, -shm) are honored automatically.
def _open_readonly(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.execute("PRAGMA query_only=1")
    conn.row_factory = sqlite3.Row
    return conn

# Buckets for session duration (seconds) — chat-style, seconds to tens of minutes.
SESSION_DURATION_BUCKETS = (
    1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0, 3600.0, float("inf"),
)

# Buckets for self-scrape duration
SCRAPE_DURATION_BUCKETS = (
    0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, float("inf"),
)

logging.basicConfig(
    level=os.environ.get("AGENT_EXPORTER_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] agent-exporter: %(message)s",
)
log = logging.getLogger("agent-exporter")


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

class HermesCollector:
    """Single-pass collector for all 6 SQLite-derived metrics + self-health.

    Implemented as a custom prometheus_client collector (not the default
    global registry) so we can build the metric families once per scrape
    with the right labels and no cross-process state.
    """

    def __init__(self) -> None:
        # Self-health metrics (regular client metrics are fine for these)
        self._scrape_duration = Histogram(
            "hermes_exporter_scrape_duration_seconds",
            "Time spent collecting agent-exporter metrics",
            buckets=SCRAPE_DURATION_BUCKETS,
        )
        self._up = Gauge(
            "hermes_exporter_up",
            "1 if the most recent scrape succeeded, 0 otherwise",
        )
        self._db_size = Gauge(
            "hermes_exporter_db_size_bytes",
            "Size of each SQLite file the exporter reads",
            ["path"],
        )

    # --- prometheus_client interface ---------------------------------------

    def collect(self):
        start = time.perf_counter()
        errors: list[str] = []
        try:
            yield from self._collect_sessions()
            yield from self._collect_kanban()
            yield from self._collect_cron()
            self._up.set(1)
        except Exception as e:  # never let a scrape crash the server
            errors.append(f"{type(e).__name__}: {e}")
            log.exception("scrape failed")
            self._up.set(0)

        elapsed = time.perf_counter() - start
        self._scrape_duration.observe(elapsed)
        if errors:
            log.warning("scrape completed with %d error(s) in %.3fs", len(errors), elapsed)
        else:
            log.debug("scrape OK in %.3fs", elapsed)

        # Yield the self-health metrics now (they need to be in the response too)
        for m in self._up.collect():
            yield m
        for m in self._scrape_duration.collect():
            yield m
        for m in self._db_size.collect():
            yield m

    # --- readers ------------------------------------------------------------

    def _collect_sessions(self) -> Iterable:
        """Read every ~/.hermes/profiles/*/state.db and emit the 3 session metrics."""
        profiles_root = HERMES_HOME / "profiles"
        if not profiles_root.is_dir():
            log.debug("no profiles dir at %s — skipping sessions", profiles_root)
            return

        # Track per-profile histograms. We bucket in Python and emit a
        # HistogramMetricFamily with a fixed bucket scheme.
        session_durations: dict[tuple[str, str], list[float]] = {}
        active: dict[str, int] = {}
        cost_counter: dict[tuple[str, str], float] = {}

        for profile_dir in sorted(profiles_root.iterdir()):
            if not profile_dir.is_dir():
                continue
            profile = profile_dir.name
            db = profile_dir / "state.db"
            if not db.exists():
                continue
            self._db_size.labels(path=str(db)).set(db.stat().st_size)

            try:
                conn = _open_readonly(db)
            except Exception as e:
                log.warning("cannot open %s: %s", db, e)
                continue

            try:
                rows = conn.execute(
                    """
                    SELECT
                        model,
                        started_at,
                        ended_at,
                        end_reason,
                        estimated_cost_usd
                    FROM sessions
                    WHERE started_at IS NOT NULL
                    """
                ).fetchall()
            except sqlite3.Error as e:
                log.warning("query %s failed: %s", db, e)
                conn.close()
                continue
            conn.close()

            for r in rows:
                end_reason = r["end_reason"] or "unknown"
                if r["ended_at"] is not None and r["started_at"] is not None:
                    dur = max(0.0, float(r["ended_at"]) - float(r["started_at"]))
                    key = (profile, end_reason)
                    session_durations.setdefault(key, []).append(dur)
                else:
                    # Active session (ended_at IS NULL)
                    active[profile] = active.get(profile, 0) + 1

                if r["estimated_cost_usd"] is not None and r["model"]:
                    model = r["model"]
                    cost_counter[(model, profile)] = (
                        cost_counter.get((model, profile), 0.0)
                        + float(r["estimated_cost_usd"])
                    )

        # Emit hermes_sessions_active (gauge)
        if active:
            m = GaugeMetricFamily(
                "hermes_sessions_active",
                "Hermes sessions with ended_at IS NULL (currently running)",
                labels=["profile"],
            )
            for profile, count in active.items():
                m.add_metric([profile], count)
            yield m

        # Emit hermes_estimated_cost_usd_total (counter)
        if cost_counter:
            m = CounterMetricFamily(
                "hermes_estimated_cost_usd_total",
                "Sum of estimated_cost_usd across all sessions (USD)",
                labels=["model", "profile"],
            )
            for (model, profile), total in cost_counter.items():
                m.add_metric([model, profile], total)
            yield m

        # Emit hermes_session_duration_seconds (histogram).
        # HistogramMetricFamily with labels= requires no buckets at construction —
        # the per-label buckets are supplied via add_metric(buckets=...).
        if session_durations:
            m = HistogramMetricFamily(
                "hermes_session_duration_seconds",
                "Hermes session duration (seconds) — ended sessions only",
                labels=["profile", "end_reason"],
            )
            for (profile, end_reason), durations in session_durations.items():
                m.add_metric(
                    [profile, end_reason],
                    buckets=_bucket_counts(durations, SESSION_DURATION_BUCKETS),
                    sum_value=sum(durations),
                )
            yield m

    def _collect_kanban(self) -> Iterable:
        """Read ~/.hermes/kanban.db (global) + ~/.hermes/profiles/*/kanban.db."""
        # Map<db_path, profile_label>  (profile="" for the global orchestrator DB)
        candidates: list[tuple[Path, str]] = []
        global_db = HERMES_HOME / "kanban.db"
        if global_db.exists():
            candidates.append((global_db, ""))
        profiles_root = HERMES_HOME / "profiles"
        if profiles_root.is_dir():
            for profile_dir in sorted(profiles_root.iterdir()):
                if not profile_dir.is_dir():
                    continue
                pdb = profile_dir / "kanban.db"
                if pdb.exists():
                    candidates.append((pdb, profile_dir.name))

        if not candidates:
            log.debug("no kanban.db found — skipping kanban metrics")
            return

        # outcome normalization: kanban stores "done"/"blocked"/"crashed"/"failed"/"timed_out"
        # Map to the spec's {done, blocked, crashed, failed} vocabulary.
        OUTCOME_MAP = {
            "completed": "done",
            "done": "done",
            "blocked": "blocked",
            "crashed": "crashed",
            "timed_out": "failed",
            "failed": "failed",
            "released": "released",  # not surfaced (claim reaper, not a terminal)
            "gave_up": "failed",
        }

        runs_counter: dict[tuple[str, str], int] = {}
        in_flight: dict[str, int] = {}

        for db, profile in candidates:
            self._db_size.labels(path=str(db)).set(db.stat().st_size)
            try:
                conn = _open_readonly(db)
            except Exception as e:
                log.warning("cannot open %s: %s", db, e)
                continue

            try:
                # Per the research, task_runs.outcome values include
                # "completed" | "blocked" | "crashed" | "timed_out" | "spawn_failed" | "gave_up" | "reclaimed"
                # The assignee is on tasks.assignee (we join for the label).
                rows = conn.execute(
                    """
                    SELECT
                        r.outcome,
                        r.status,
                        r.ended_at,
                        t.assignee
                    FROM task_runs r
                    LEFT JOIN tasks t ON t.id = r.task_id
                    """
                ).fetchall()
            except sqlite3.Error as e:
                log.warning("query %s failed: %s", db, e)
                conn.close()
                continue
            conn.close()

            for r in rows:
                assignee = r["assignee"] or "unassigned"
                status = r["status"] or "unknown"
                outcome = r["outcome"] or "unknown"
                normalized = OUTCOME_MAP.get(outcome, "failed")

                # counter: every run with a terminal outcome
                if status in ("done", "blocked", "crashed", "failed", "timed_out"):
                    key = (assignee, normalized)
                    runs_counter[key] = runs_counter.get(key, 0) + 1

                # gauge: runs in flight (status='running')
                if status == "running":
                    key = (assignee)
                    in_flight[key] = in_flight.get(key, 0) + 1

        # Emit hermes_kanban_runs_total
        if runs_counter:
            m = CounterMetricFamily(
                "hermes_kanban_runs_total",
                "Hermes kanban task run outcomes by assignee",
                labels=["assignee", "outcome"],
            )
            for (assignee, outcome), count in sorted(runs_counter.items()):
                m.add_metric([assignee, outcome], count)
            yield m

        # Emit hermes_kanban_runs_in_flight
        if in_flight:
            m = GaugeMetricFamily(
                "hermes_kanban_runs_in_flight",
                "Hermes kanban runs currently in 'running' state by assignee",
                labels=["assignee"],
            )
            for assignee, count in sorted(in_flight.items()):
                m.add_metric([assignee], count)
            yield m

    def _collect_cron(self) -> Iterable:
        """Read ~/.hermes/cron/jobs.json and emit per-job last_success timestamps."""
        jobs_path = HERMES_HOME / "cron" / "jobs.json"
        if not jobs_path.exists():
            log.debug("no cron/jobs.json at %s — skipping cron metrics", jobs_path)
            return

        try:
            with jobs_path.open() as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            log.warning("cannot read %s: %s", jobs_path, e)
            return

        # The schema is {jobs: [...]} or just a list — both are common.
        jobs: list[dict]
        if isinstance(data, dict) and "jobs" in data:
            jobs = data["jobs"]
        elif isinstance(data, list):
            jobs = data
        else:
            log.warning("unexpected cron/jobs.json shape: %r", type(data))
            return

        if not jobs:
            return

        m = GaugeMetricFamily(
            "hermes_cron_job_last_success_timestamp",
            "Unix timestamp of each cron job's most recent successful run (0 if never)",
            labels=["job_name"],
        )
        for job in jobs:
            name = job.get("name") or job.get("id") or "unnamed"
            last_status = job.get("last_status")
            last_run_at = job.get("last_run_at")
            # Only set the gauge on "ok"; failures get value 0 so a fresh
            # 'last_success' query never lies about a failed run.
            if last_status == "ok" and last_run_at:
                # last_run_at is an ISO-8601 string in the current schema.
                # Convert to unix timestamp.
                ts = _parse_iso8601(last_run_at)
                if ts is not None:
                    m.add_metric([name], ts)
                    continue
            # Default: never successfully ran (or status wasn't ok)
            m.add_metric([name], 0.0)
        yield m


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bucket_counts(values: list[float], buckets: tuple[float, ...]) -> list[tuple[str, float]]:
    """Return cumulative bucket counts for a list of observed values.

    Mirrors the standard histogram semantics: each bucket's count is the
    number of values <= its upper bound, and the last bucket (+Inf) is the
    total observation count. Returns a list of (bucket_str, count) tuples
    suitable for HistogramMetricFamily.add_metric(buckets=...).

    bucket_str format: "1.0", "5.0", ..., "+Inf" (matches Prometheus
    exposition format from the Go client).
    """
    sorted_vals = sorted(values)
    out: list[tuple[str, float]] = []
    idx = 0
    for upper in buckets:
        while idx < len(sorted_vals) and sorted_vals[idx] <= upper:
            idx += 1
        if upper == float("inf"):
            bucket_str = "+Inf"
        else:
            # Match Go's formatting: integers as "1", floats with up to N decimals.
            # For our use case, all buckets are seconds (integer or float).
            bucket_str = str(upper) if upper != int(upper) else str(int(upper))
        out.append((bucket_str, float(idx)))
    return out


def _parse_iso8601(s: str) -> float | None:
    """Parse an ISO-8601 timestamp string into a unix epoch float.

    Handles the most common shape we see in cron/jobs.json
    ('2026-07-01T09:01:56.378858-04:00'). Returns None on failure.
    """
    from datetime import datetime
    s = s.strip()
    if not s:
        return None
    # Try full ISO format first (with timezone), fall back to naive.
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.timestamp()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class _MetricsHandler:
    """Minimal HTTP handler for /metrics and /healthz.

    Implemented as a class with the right BaseHTTPRequestHandler hooks so
    we don't pull in a third-party HTTP framework. Stdlib http.server is
    fine for a metrics endpoint that gets scraped every 15s.
    """
    pass  # implemented below with a hand-rolled handler


def _make_handler(collector: HermesCollector):
    from http.server import BaseHTTPRequestHandler

    class MetricsHandler(BaseHTTPRequestHandler):
        # Silence the default per-request stderr log; we log at debug if needed.
        def log_message(self, format, *args):  # noqa: A002
            pass

        def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
            if self.path in ("/", "/healthz", "/health"):
                body = b'{"status":"ok","exporter":"agent-exporter"}\n'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path in ("/metrics", "/metrics/"):
                try:
                    body = generate_latest(collector)
                except Exception:
                    log.exception("failed to render /metrics")
                    self.send_response(500)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"# exporter render failed\n")
                    return
                self.send_response(200)
                self.send_header("Content-Type", CONTENT_TYPE_LATEST)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"not found\n")

    return MetricsHandler


def main() -> int:
    log.info("agent-exporter starting on :%d (interval=%ds, hermes_home=%s)",
             LISTEN_PORT, SCRAPE_INTERVAL_SEC, HERMES_HOME)

    collector = HermesCollector()

    from http.server import HTTPServer
    server = HTTPServer(("0.0.0.0", LISTEN_PORT), _make_handler(collector))
    log.info("agent-exporter listening on http://0.0.0.0:%d/metrics", LISTEN_PORT)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
