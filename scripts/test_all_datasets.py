#!/usr/bin/env python
"""Smoke-test fetch_data against every dataset in the catalog.

Usage:
    python scripts/test_all_datasets.py                    # all datasets
    python scripts/test_all_datasets.py --observatory ace  # one observatory
    python scripts/test_all_datasets.py --resume           # resume from last report
    python scripts/test_all_datasets.py --workers 4        # parallel workers (default 3)
    python scripts/test_all_datasets.py --report           # print summary from last run
"""

import argparse
import json
import signal
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB — skip huge CDF files
PER_DATASET_TIMEOUT = 120  # seconds


# ── Dataset enumeration ─────────────────────────────────────────────────────

def enumerate_datasets(observatory_filter: str | None = None) -> list[dict]:
    """Build flat list of all datasets from observatory catalog JSONs."""
    from cdawebmcp.catalog import browse_observatories, load_observatory_json

    obs_list = browse_observatories()
    datasets = []
    for obs in obs_list:
        if observatory_filter and obs["id"] != observatory_filter:
            continue
        data = load_observatory_json(obs["id"])
        for inst_name, inst in data.get("instruments", {}).items():
            for ds_id, ds in inst.get("datasets", {}).items():
                datasets.append({
                    "observatory": obs["id"],
                    "dataset_id": ds_id,
                    "start_date": ds.get("start_date", ""),
                    "stop_date": ds.get("stop_date", ""),
                })
    datasets.sort(key=lambda d: (d["observatory"], d["dataset_id"]))
    return datasets


# ── Single dataset test ──────────────────────────────────────────────────────

def test_one_dataset(entry: dict) -> dict:
    """Smoke-test one dataset. Returns result dict."""
    dataset_id = entry["dataset_id"]
    t0 = time.monotonic()

    try:
        from cdawebmcp.metadata import browse_parameters
        meta = browse_parameters(dataset_id)
        if meta.get("status") != "success" or not meta.get("parameters"):
            return _result(entry, "no_params", "No parameters in metadata", t0)

        param_name = meta["parameters"][0]["name"]

        # Compute 1-hour window: start_date + 1 day
        start_str = entry.get("start_date", "")
        if not start_str:
            return _result(entry, "empty", "No start_date in catalog", t0)

        start_dt = _parse_date(start_str) + timedelta(days=1)
        stop_dt = start_dt + timedelta(hours=1)
        start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        stop_iso = stop_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        from cdawebmcp.fetch import fetch_data
        result = fetch_data(
            dataset_id=dataset_id,
            parameters=[param_name],
            start=start_iso,
            stop=stop_iso,
        )

        info = result.get(param_name, {})
        if "error" in info:
            err = info["error"]
            status = _classify_error(err)
            return _result(entry, status, f"{param_name}: {err}", t0)

        df = info.get("data")
        if df is None or len(df) == 0:
            return _result(entry, "empty", f"{param_name}: DataFrame empty", t0)

        rows = len(df)
        return _result(entry, "pass", f"{param_name}: {rows} rows", t0)

    except Exception as e:
        status = _classify_error(str(e))
        return _result(entry, status, str(e)[:300], t0)


def _result(entry: dict, status: str, detail: str, t0: float) -> dict:
    return {
        "dataset_id": entry["dataset_id"],
        "observatory": entry["observatory"],
        "status": status,
        "detail": detail,
        "elapsed_seconds": round(time.monotonic() - t0, 2),
        "timestamp": datetime.now(UTC).isoformat() + "Z",
    }


def _parse_date(s: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.rstrip("Z") if "T" not in s else s.replace("Z", ""), fmt.replace("Z", ""))
        except ValueError:
            continue
    return datetime.strptime(s[:10], "%Y-%m-%d")


def _classify_error(msg: str) -> str:
    msg_lower = msg.lower()
    if "length of values" in msg_lower and "does not match" in msg_lower:
        return "epoch_mismatch"
    if "no cdf files" in msg_lower or "no data" in msg_lower:
        return "empty"
    if "timeout" in msg_lower or "timed out" in msg_lower:
        return "timeout"
    if "404" in msg or "not found" in msg_lower:
        return "download_error"
    if any(x in msg for x in ("500", "502", "503", "HTTPError")):
        return "download_error"
    if "variable" in msg_lower and "not found" in msg_lower:
        return "parse_error"
    if "epoch" in msg_lower:
        return "parse_error"
    return "other"


# ── Report I/O ───────────────────────────────────────────────────────────────

def get_latest_report() -> Path | None:
    if not REPORTS_DIR.exists():
        return None
    reports = sorted(REPORTS_DIR.glob("fetch_test_*.json"))
    return reports[-1] if reports else None


def load_report(path: Path) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def new_report_path() -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return REPORTS_DIR / f"fetch_test_{ts}.json"


def save_report(path: Path, results: list[dict]) -> None:
    with open(path, "w") as f:
        json.dump(results, f, indent=2)


# ── Summary ──────────────────────────────────────────────────────────────────

def print_summary(results: list[dict]) -> None:
    total = len(results)
    if total == 0:
        print("No results.")
        return

    counts = Counter(r["status"] for r in results)
    order = ["pass", "empty", "no_params", "download_error", "parse_error",
             "epoch_mismatch", "timeout", "other"]
    print(f"\n{'─' * 50}")
    print(f"  Results: {total} datasets tested")
    print(f"{'─' * 50}")
    for status in order:
        c = counts.get(status, 0)
        pct = 100 * c / total
        print(f"  {status:20s} {c:5d}  ({pct:5.1f}%)")
    print(f"{'─' * 50}")

    elapsed = [r["elapsed_seconds"] for r in results]
    print(f"  Total time:  {sum(elapsed):.0f}s  (wall clock varies with parallelism)")
    print(f"  Avg per ds:  {sum(elapsed)/len(elapsed):.1f}s")
    print()

    # Top failures by observatory
    failures = [r for r in results if r["status"] not in ("pass", "empty")]
    if failures:
        obs_fails = Counter(r["observatory"] for r in failures)
        print("  Top failing observatories:")
        for obs, c in obs_fails.most_common(10):
            print(f"    {obs:40s} {c}")
        print()


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Smoke-test all CDAWeb datasets")
    parser.add_argument("--observatory", help="Test only this observatory")
    parser.add_argument("--resume", action="store_true", help="Resume from latest report")
    parser.add_argument("--workers", type=int, default=3, help="Parallel workers (default 3)")
    parser.add_argument("--report", action="store_true", help="Print summary of latest report")
    args = parser.parse_args()

    if args.report:
        rpt = get_latest_report()
        if not rpt:
            print("No reports found.")
            return
        print(f"Report: {rpt}")
        print_summary(load_report(rpt))
        return

    datasets = enumerate_datasets(args.observatory)
    print(f"Found {len(datasets)} datasets")

    # Resume support
    results = []
    done_ids = set()
    report_path = None
    if args.resume:
        rpt = get_latest_report()
        if rpt:
            results = load_report(rpt)
            done_ids = {r["dataset_id"] for r in results}
            report_path = rpt
            print(f"Resuming from {rpt} ({len(done_ids)} already done)")

    if report_path is None:
        report_path = new_report_path()

    pending = [d for d in datasets if d["dataset_id"] not in done_ids]
    print(f"Pending: {len(pending)} datasets → {report_path.name}")
    print(f"Workers: {args.workers}")
    print()

    lock = threading.Lock()
    completed = [len(done_ids)]  # mutable counter
    total = len(datasets)

    # Graceful Ctrl+C
    interrupted = threading.Event()

    def signal_handler(sig, frame):
        interrupted.set()
        print("\nInterrupted — saving report...")

    signal.signal(signal.SIGINT, signal_handler)

    def run_and_record(entry):
        if interrupted.is_set():
            return None
        result = test_one_dataset(entry)
        with lock:
            results.append(result)
            completed[0] += 1
            n = completed[0]
            s = result["status"]
            ds = result["dataset_id"]
            t = result["elapsed_seconds"]
            tag = "PASS" if s == "pass" else s.upper()
            print(f"  [{n:4d}/{total}] {ds:45s} {tag:20s} ({t:.1f}s)")
            # Incremental save every 10 datasets
            if n % 10 == 0:
                save_report(report_path, results)
        return result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_and_record, e): e for e in pending}
        for future in as_completed(futures):
            if interrupted.is_set():
                break
            try:
                future.result()
            except Exception as e:
                entry = futures[future]
                print(f"  FATAL: {entry['dataset_id']}: {e}")

    save_report(report_path, results)
    print_summary(results)
    print(f"Report saved: {report_path}")


if __name__ == "__main__":
    main()
