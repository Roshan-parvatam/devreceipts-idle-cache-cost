"""Shared helpers for the smoke tests. NO model calls anywhere in this folder.

Every number built here is a SYNTHETIC FIXTURE to exercise the code. None of it is a measurement
and none of it may be quoted in the video or in METRICS.md.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"
sys.path.insert(0, str(EVAL))


def make_call(inp=6, cc=0, cr=0, out=5, cc_5m=0, cc_1h=None, cost=0.001, is_error=False,
              result="OK", session_id="00000000-0000-4000-8000-000000000000", subtype="success"):
    """A fake `claude -p --output-format json` result, same key shape as a real one (see eval/results of Video #1)."""
    if cc_1h is None:
        cc_1h = cc  # default: everything written went to the 1h field, as in the Video #1 files
    return {
        "type": "result",
        "subtype": subtype,
        "is_error": is_error,
        "api_error_status": None,
        "result": result,
        "session_id": session_id,
        "total_cost_usd": cost,
        "duration_ms": 1000,
        "num_turns": 1,
        "usage": {
            "input_tokens": inp,
            "cache_creation_input_tokens": cc,
            "cache_read_input_tokens": cr,
            "output_tokens": out,
            "cache_creation": {"ephemeral_5m_input_tokens": cc_5m, "ephemeral_1h_input_tokens": cc_1h},
        },
        "_fixture": "synthetic, not a measurement",
    }


def write_session(dirpath: Path, setup, resume, **meta):
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "setup.json").write_text(json.dumps(setup))
    if resume is not None:
        (dirpath / "resume.json").write_text(json.dumps(resume))
    m = {"cell": "gap", "rep": 1, "size_label": "small", "gap_planned_s": 360, "gap_actual_s": 361.2,
         "claude_version": "0.0.0-fixture", "started_at_utc": "2000-01-01T00:00:00Z",
         "setup_wall_s": 2.0, "resume_wall_s": 1.5, "doc_chars": 40000, "session_id": setup["session_id"]}
    m.update(meta)
    (dirpath / "meta.json").write_text(json.dumps(m))
    return dirpath
