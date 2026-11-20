#!/usr/bin/env python3
"""Read raw results (JSON from `claude -p --output-format json`) and report TOKENS per cell.

    analyze.py RESULTS_DIR                  table per (gap, size) cell + the JSONL run log on request
    analyze.py RESULTS_DIR --jsonl out.jsonl
    analyze.py RESULTS_DIR --sizes          calibrate chars-per-token and write RESULTS_DIR/sizes.env
    analyze.py scrub SRC DST                copy results with session ids replaced (for publishing)

Nothing here estimates or invents a number: an empty cell prints `TODO: measure`.

Scoring. Let T = setup total input tokens (input + cache_creation + cache_read), F = total input tokens of the
empty-project hello call (0 if unknown) and C = the median resume cache_read of the gap-0 sessions of the same size.
  hit     : resume cache_read     >= 0.9 * C           (REVISED after the pilot, see PLAN.md; with no control C the
                                                         original rule applies: cache_read >= 0.9 * T)
  miss    : resume cache_creation >= 0.9 * (T - F)     (the document part was written again)
  partial : anything else
Why revised: every resume re-writes a few thousand tokens even with no gap, so "read >= 90% of T" can never pass;
a hit is now "reads as much as a back-to-back message of the same size does".
  error / incomplete / invalid : the run itself failed, has no resume yet, or T is not usable
"""
import argparse
import hashlib
import json
import re
import shutil
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HIT_FRAC = 0.90
MISS_FRAC = 0.90


# ---------- one call ----------
def usage_of(call: dict) -> dict:
    u = call.get("usage") or {}
    cc = u.get("cache_creation") or {}
    inp = u.get("input_tokens") or 0
    cw = u.get("cache_creation_input_tokens") or 0
    cr = u.get("cache_read_input_tokens") or 0
    return {
        "input": inp, "output": u.get("output_tokens") or 0, "cache_creation": cw, "cache_read": cr,
        "cc_5m": cc.get("ephemeral_5m_input_tokens"), "cc_1h": cc.get("ephemeral_1h_input_tokens"),
        "total_in": inp + cw + cr,
        "cost_usd": call.get("total_cost_usd"),
        "is_error": bool(call.get("is_error")), "subtype": call.get("subtype"),
        "result": call.get("result"),
    }


def classify(setup_total: int, resume: dict, floor_total: int = 0, control_read=None) -> str:
    if resume.get("is_error"):
        return "error"
    if not setup_total or setup_total <= 0:
        return "invalid"
    ref = control_read if control_read else setup_total
    if resume["cache_read"] >= HIT_FRAC * ref:
        return "hit"
    doc_part = max(setup_total - (floor_total or 0), 1)
    if resume["cache_creation"] >= MISS_FRAC * doc_part:
        return "miss"
    return "partial"


def calibrate_cpt(chars: int, setup_total: int, floor_total: int):
    """Real chars-per-token for the filler text: chars / (setup total minus shared prefix). None if unusable."""
    doc_tokens = setup_total - floor_total
    return round(chars / doc_tokens, 3) if doc_tokens > 0 else None


# ---------- one session ----------
def _load(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


def load_session(d: Path, floor_total: int = 0, control_read=None) -> dict:
    d = Path(d)
    meta = _load(d / "meta.json") or {}
    setup_raw, resume_raw = _load(d / "setup.json"), _load(d / "resume.json")
    setup = usage_of(setup_raw) if setup_raw else None
    resume = usage_of(resume_raw) if resume_raw else None
    if setup and resume and setup["cost_usd"] is not None and resume["cost_usd"] is not None:
        # total_cost_usd of a resumed call is cumulative for the session: its own cost is the difference
        resume["cost_own_usd"] = round(resume["cost_usd"] - setup["cost_usd"], 6)
    if setup is None or resume is None:
        cls = "incomplete"
    elif setup["is_error"]:
        cls = "error"
    else:
        cls = classify(setup["total_in"], resume, floor_total, control_read)
    return {
        "session": d.name,
        "cell": meta.get("cell"), "rep": meta.get("rep"), "size_label": meta.get("size_label"),
        "gap_planned_s": meta.get("gap_planned_s"), "gap_actual_s": meta.get("gap_actual_s"),
        "claude_version": meta.get("claude_version"), "started_at_utc": meta.get("started_at_utc"),
        "wall_s": meta.get("resume_wall_s"), "setup_wall_s": meta.get("setup_wall_s"),
        "is_error": bool((setup and setup["is_error"]) or (resume and resume["is_error"])),
        "subtype": resume["subtype"] if resume else (setup["subtype"] if setup else None),
        "reply_ok": bool(resume and (resume["result"] or "").strip() == "OK"),
        "setup": setup, "resume": resume, "class": cls,
        "session_id": meta.get("session_id"),
    }


def controls_from(records: list) -> dict:
    """Median resume cache_read of the gap-0 sessions, per size label."""
    reads = defaultdict(list)
    for r in records:
        if r["gap_planned_s"] == 0 and r["resume"] is not None and not r["is_error"]:
            reads[r["size_label"]].append(r["resume"]["cache_read"])
    return {k: statistics.median(v) for k, v in reads.items()}


def load_all(results: Path, floor_total: int = 0) -> list:
    dirs = [p for p in sorted(Path(results).glob("gap-*")) if p.is_dir()]
    controls = controls_from([load_session(p, floor_total) for p in dirs])
    out = []
    for p in dirs:
        meta = _load(p / "meta.json") or {}
        out.append(load_session(p, floor_total, controls.get(meta.get("size_label"))))
    return out


def floor_read_of(results: Path) -> int:
    f = _load(Path(results) / "floor.json")
    return usage_of(f)["cache_read"] if f else 0


def floor_total_of(results: Path) -> int:
    f = _load(Path(results) / "floor.json")
    return usage_of(f)["total_in"] if f else 0


# ---------- many sessions ----------
def _stats(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {"median": statistics.median(values), "min": min(values), "max": max(values)}


def summarize(records: list) -> dict:
    groups = defaultdict(list)
    for r in records:
        groups[(r["gap_planned_s"], r["size_label"])].append(r)
    cells = {}
    for key, rs in groups.items():
        done = [r for r in rs if r["resume"] is not None]
        cells[key] = {
            "n": len(rs),
            "classes": dict(Counter(r["class"] for r in rs)),
            "setup_total": _stats([r["setup"]["total_in"] for r in done]),
            "resume_cache_read": _stats([r["resume"]["cache_read"] for r in done]),
            "resume_cache_creation": _stats([r["resume"]["cache_creation"] for r in done]),
            "resume_cost_own_usd": _stats([r["resume"].get("cost_own_usd") for r in done]),
            "gap_actual_s": _stats([r["gap_actual_s"] for r in rs]),
        }
    return cells


def gap0_ok(records: list, floor_total: int, floor_read: int):
    """Instrument sanity (stop rule 4, revised): at gap 0 the document must come from the cache. Each gap-0 resume must read at
    least floor_read + 0.9 * (setup total - floor_total). None when there is no finished gap-0 session."""
    zero = [r for r in records if r["gap_planned_s"] == 0 and r["resume"] is not None and r["setup"] is not None]
    if not zero:
        return None
    return all(r["resume"]["cache_read"] >= floor_read + HIT_FRAC * max(r["setup"]["total_in"] - floor_total, 0) for r in zero)


def _fmt(s, key="median"):
    return "TODO: measure" if not s else f"{s[key]:,.0f} ({s['min']:,.0f}-{s['max']:,.0f})"


def to_markdown(cells: dict, gaps, sizes) -> str:
    rows = ["| Gap (min) | Size | n | Classes | Setup total tokens | Resume cache_read (median, range) | Resume cache_creation (median, range) |",
            "|---|---|---|---|---|---|---|"]
    for gap in gaps:
        for size in sizes:
            c = cells.get((gap * 60, size)) or cells.get((gap, size))
            if not c:
                rows.append(f"| {gap} | {size} | 0 | TODO: measure | TODO: measure | TODO: measure | TODO: measure |")
                continue
            cls = ", ".join(f"{k} {v}" for k, v in sorted(c["classes"].items()))
            rows.append(f"| {gap} | {size} | {c['n']} | {cls} | {_fmt(c['setup_total'])} | "
                        f"{_fmt(c['resume_cache_read'])} | {_fmt(c['resume_cache_creation'])} |")
    return "\n".join(rows)


# ---------- publishing ----------
def scrub(src: Path, dst: Path) -> None:
    """Copy every result file, replacing each session id with a short hash. Raw .err files are not copied."""
    src, dst = Path(src), Path(dst)
    uuid = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
    for p in src.rglob("*"):
        if not p.is_file() or p.suffix in (".err",) or p.name in ("STOP", "workdir"):
            continue
        out = dst / p.relative_to(src)
        out.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix == ".json":
            text = uuid.sub(lambda m: "sess-" + hashlib.sha256(m.group(0).encode()).hexdigest()[:8], p.read_text())
            out.write_text(text)
        else:
            shutil.copy2(p, out)


# ---------- CLI ----------
def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "scrub":
        scrub(Path(argv[1]), Path(argv[2]))
        return 0
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("results")
    ap.add_argument("--jsonl")
    ap.add_argument("--sizes", action="store_true", help="calibrate chars-per-token and write sizes.env")
    a = ap.parse_args(argv)
    res = Path(a.results)
    floor = floor_total_of(res)
    records = load_all(res, floor)
    if not records and not floor:
        print("no results found in", res)
        return 0
    if a.jsonl:
        with open(a.jsonl, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
    if a.sizes:
        cpts = [calibrate_cpt(r["doc_chars"], r["setup"]["total_in"], floor)
                for r in (_meta_with_chars(res, x) for x in records) if r.get("doc_chars") and r["setup"]]
        cpts = [c for c in cpts if c]
        if not (floor and cpts):
            print("cannot calibrate: need floor.json and at least one finished setup")
            return 1
        cpt = statistics.median(cpts)
        (res / "sizes.env").write_text(f"FLOOR_TOTAL={floor}\nCPT={cpt}\n")
        print(f"FLOOR_TOTAL={floor} CPT={cpt} written to {res / 'sizes.env'}")
        return 0
    print(f"shared prefix F (hello call, total input tokens): {floor if floor else 'TODO: measure'}")
    gaps = sorted({r["gap_planned_s"] // 60 for r in records if r["gap_planned_s"] is not None})
    sizes = sorted({r["size_label"] for r in records if r["size_label"]})
    cells = summarize(records)
    print(to_markdown(cells, gaps, sizes))
    ok = gap0_ok(records, floor, floor_read_of(res))
    print("gap-0 sanity (stop rule 4): " + ("TODO: measure" if ok is None else ("ok" if ok else "FAILED: the gap-0 resume did not read its document from the cache")))
    ctl = controls_from(records)
    if ctl:
        print("gap-0 control (median resume cache_read per size): " + ", ".join(f"{k} {v:,.0f}" for k, v in sorted(ctl.items())))
    errs = [r["session"] for r in records if r["is_error"]]
    if errs:
        print("sessions with errors:", ", ".join(errs))
    return 0


def _meta_with_chars(res: Path, rec: dict) -> dict:
    meta = _load(Path(res) / rec["session"] / "meta.json") or {}
    return {**rec, "doc_chars": meta.get("doc_chars")}


if __name__ == "__main__":
    sys.exit(main())
