from __future__ import annotations

import json
import argparse
import os
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path


PROMETHEUS = os.environ.get("PROMETHEUS_URL", "http://127.0.0.1:9090")
OUTPUT = Path("web_cockpit/live_data.js")

QUERIES = {
    "connections": 'pg_stat_activity_cockpit_connections{datname="cockpit"}',
    "active_connections": 'pg_stat_activity_cockpit_active_connections{datname="cockpit"}',
    "waiting_connections": 'pg_stat_activity_cockpit_waiting_connections{datname="cockpit"}',
    "xact_rate": 'rate(pg_stat_database_xact_commit{datname="cockpit"}[1m]) + rate(pg_stat_database_xact_rollback{datname="cockpit"}[1m])',
    "read_blocks_rate": 'rate(pg_database_io_cockpit_blks_read{datname="cockpit"}[1m])',
    "cache_hit_rate": 'rate(pg_database_io_cockpit_blks_hit{datname="cockpit"}[1m])',
    "blk_read_time_ms_rate": 'rate(pg_database_io_cockpit_blk_read_time_ms{datname="cockpit"}[1m])',
}


def query_prometheus(expr: str) -> float:
    url = PROMETHEUS + "/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            if attempt == 1:
                return 0.0
            time.sleep(0.2)
    result = payload.get("data", {}).get("result", [])
    if not result:
        return 0.0
    return float(result[0]["value"][1])


def classify(point: dict[str, float]) -> list[dict[str, object]]:
    detections: list[dict[str, object]] = []
    if point["waiting_connections"] >= 2:
        detections.append(
            {
                "type": "wait_contention",
                "severity": "warning",
                "metric": "waiting_connections",
                "value": point["waiting_connections"],
                "summary": "Postgres sessions are waiting; inspect locks, IO, and concurrent workload.",
            }
        )
    if point["active_connections"] >= 24:
        detections.append(
            {
                "type": "high_concurrency",
                "severity": "warning",
                "metric": "active_connections",
                "value": point["active_connections"],
                "summary": "Active database concurrency is elevated.",
            }
        )
    if point["blk_read_time_ms_rate"] >= 50:
        detections.append(
            {
                "type": "read_io_pressure",
                "severity": "critical",
                "metric": "blk_read_time_ms_rate",
                "value": point["blk_read_time_ms_rate"],
                "summary": "Block read time is rising; possible storage pressure.",
            }
        )
    return detections


def write_payload(points: list[dict[str, float]], detections: list[dict[str, object]]) -> None:
    payload = {
        "source": "prometheus-postgres",
        "generated_at": int(time.time()),
        "stream": points[-720:],
        "detections": detections[-100:],
    }
    OUTPUT.write_text("window.COCKPIT_LIVE_DATA = " + json.dumps(payload, indent=2) + ";\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--samples", type=int, default=0, help="0 means run until Ctrl+C")
    args = parser.parse_args()
    points: list[dict[str, float]] = []
    detections: list[dict[str, object]] = []
    print("Polling Prometheus. Press Ctrl+C to stop.")
    count = 0
    while True:
        now = int(time.time())
        point = {"t": float(now)}
        for name, expr in QUERIES.items():
            point[name] = round(query_prometheus(expr), 3)
        points.append(point)
        for detection in classify(point):
            detection = {"t": now, **detection}
            if not detections or detections[-1].get("type") != detection["type"]:
                detections.append(detection)
                print(f"{time.strftime('%H:%M:%S')} detection={detection['type']} value={detection['value']}")
        write_payload(points, detections)
        count += 1
        if args.samples and count >= args.samples:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
