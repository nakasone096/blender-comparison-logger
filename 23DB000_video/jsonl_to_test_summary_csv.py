import csv
import json
import sys
from pathlib import Path

TASK_KEYS = ["practice", "move", "rot_scale", "view", "pillar", "cuts", "round", "combo"]
COMBO_SUBS = ["scaled", "pillar", "cut", "material"]


def read_events(path: Path):
    events = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def summarize(path: Path):
    events = read_events(path)
    row = {"file": path.name, "participant_id": "", "group": "",
           "total_elapsed_s": "", "completed": ""}
    tasks = {}
    for ev in events:
        if not row["participant_id"] and ev.get("participant_id"):
            row["participant_id"] = ev["participant_id"]
        if not row["group"] and ev.get("group"):
            row["group"] = ev["group"]
        kind = ev.get("event")
        if kind == "test_task_end":
            tasks[ev.get("key")] = ev
        elif kind == "test_end":
            row["total_elapsed_s"] = ev.get("total_elapsed_s", "")
            row["completed"] = ev.get("completed", "")
    for key in TASK_KEYS:
        ev = tasks.get(key)
        row[f"{key}_result"] = ev.get("result", "") if ev else ""
        row[f"{key}_elapsed_s"] = ev.get("elapsed_s", "") if ev else ""
        row[f"{key}_undo"] = ev.get("undo_count", "") if ev else ""
        row[f"{key}_reset"] = ev.get("reset_count", "") if ev else ""
    combo = tasks.get("combo")
    sub = (combo or {}).get("sub") or {}
    for s in COMBO_SUBS:
        row[f"combo_{s}"] = sub.get(s, "")
    row["combo_score"] = sum(1 for s in COMBO_SUBS if sub.get(s) is True) if combo else ""
    return row


def columns():
    cols = ["file", "participant_id", "group", "total_elapsed_s", "completed"]
    for key in TASK_KEYS:
        cols += [f"{key}_result", f"{key}_elapsed_s", f"{key}_undo", f"{key}_reset"]
    cols += [f"combo_{s}" for s in COMBO_SUBS] + ["combo_score"]
    return cols


def main(target: str):
    p = Path(target)
    files = sorted(p.glob("*_test_*.jsonl")) if p.is_dir() else [p]
    if not files:
        print(f"no *_test_*.jsonl files found in: {p}")
        return
    out = (p / "all_participants_test_summary.csv") if p.is_dir() else p.with_suffix(".test_summary.csv")
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns())
        w.writeheader()
        for fp in files:
            w.writerow(summarize(fp))
    print(f"written: {out}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage:")
        print("  1人分:     python jsonl_to_test_summary_csv.py <xxx_test_xxx.jsonl>")
        print("  複数人まとめて: python jsonl_to_test_summary_csv.py <jsonlが入っているフォルダ>")
        raise SystemExit(2)
    main(sys.argv[1])
