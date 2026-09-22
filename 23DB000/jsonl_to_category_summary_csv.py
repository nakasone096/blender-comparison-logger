import json
import csv
import sys
from pathlib import Path

CATEGORY_LABELS = {
    1: "基本操作（移動・回転・拡大縮小）",
    2: "ビュー操作（回転・ズーム）",
    3: "モデリング（編集モード＋ループカット/押し出し）",
    4: "モディファイア追加",
    5: "スカルプト変形",
    6: "マテリアル作成（Roughness調整）",
}

def main(jsonl_path: str):
    p = Path(jsonl_path)
    if not p.exists():
        raise FileNotFoundError(p)

    rows = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # 末尾が壊れている（クラッシュ等）場合でも復旧できるように無視
                continue

    by_category = {
        i: {"category": i, "label": CATEGORY_LABELS[i],
            "detected": False, "elapsed_s": None, "undo_count_so_far": None}
        for i in range(1, 7)
    }
    total_elapsed = None
    total_undo = None
    participant_id = None
    group = None

    for ev in rows:
        if participant_id is None and ev.get("participant_id"):
            participant_id = ev.get("participant_id")
        if group is None and ev.get("group"):
            group = ev.get("group")

        if ev.get("event") == "category_detected":
            cat = ev.get("category")
            if cat in by_category:
                by_category[cat]["detected"] = True
                by_category[cat]["elapsed_s"] = ev.get("elapsed_s")
                by_category[cat]["undo_count_so_far"] = ev.get("undo_count_so_far")

        if ev.get("event") == "measurement_end":
            total_elapsed = ev.get("total_elapsed_s")
            total_undo = ev.get("undo_count_total")

    out_csv = p.with_suffix(".category_summary.csv")

    with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["participant_log_file", p.name])
        w.writerow(["participant_id", participant_id or ""])
        w.writerow(["group", group or ""])
        w.writerow(["total_elapsed_s", "" if total_elapsed is None else f"{total_elapsed:.3f}"])
        w.writerow(["undo_count_total", "" if total_undo is None else total_undo])
        w.writerow([])
        w.writerow(["category", "label", "detected", "elapsed_s", "undo_count_so_far"])
        for i in range(1, 7):
            r = by_category[i]
            elapsed = r["elapsed_s"]
            w.writerow([
                r["category"],
                r["label"],
                r["detected"],
                "" if elapsed is None else f"{float(elapsed):.3f}",
                "" if r["undo_count_so_far"] is None else r["undo_count_so_far"],
            ])

    print(f"written: {out_csv}")


def main_batch(jsonl_dir: str):
    """フォルダ内の全参加者ログをまとめて1つの横並びCSVに集計する（被験者間比較用）"""
    d = Path(jsonl_dir)
    jsonl_files = sorted(d.glob("*.jsonl"))
    if not jsonl_files:
        print(f"no .jsonl files found in: {d}")
        return

    out_csv = d / "all_participants_category_summary.csv"
    header = ["participant_id", "group", "total_elapsed_s", "undo_count_total"]
    for i in range(1, 7):
        header += [f"cat{i}_detected", f"cat{i}_elapsed_s"]

    with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for jf in jsonl_files:
            rows = []
            with jf.open("r", encoding="utf-8") as fin:
                for line in fin:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

            by_category = {i: {"detected": False, "elapsed_s": None} for i in range(1, 7)}
            total_elapsed = None
            total_undo = None
            participant_id = None
            group = None
            for ev in rows:
                if participant_id is None and ev.get("participant_id"):
                    participant_id = ev.get("participant_id")
                if group is None and ev.get("group"):
                    group = ev.get("group")
                if ev.get("event") == "category_detected":
                    cat = ev.get("category")
                    if cat in by_category:
                        by_category[cat]["detected"] = True
                        by_category[cat]["elapsed_s"] = ev.get("elapsed_s")
                if ev.get("event") == "measurement_end":
                    total_elapsed = ev.get("total_elapsed_s")
                    total_undo = ev.get("undo_count_total")

            row = [
                participant_id or jf.stem,
                group or "",
                "" if total_elapsed is None else f"{total_elapsed:.3f}",
                "" if total_undo is None else total_undo,
            ]
            for i in range(1, 7):
                r = by_category[i]
                elapsed = r["elapsed_s"]
                row += [r["detected"], "" if elapsed is None else f"{float(elapsed):.3f}"]
            w.writerow(row)

    print(f"written: {out_csv}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage:")
        print("  1人分の集計:     python jsonl_to_category_summary_csv.py <participant_log.jsonl>")
        print("  複数人まとめて:   python jsonl_to_category_summary_csv.py <jsonlが入っているフォルダ>")
        raise SystemExit(2)

    target = Path(sys.argv[1])
    if target.is_dir():
        main_batch(sys.argv[1])
    else:
        main(sys.argv[1])
