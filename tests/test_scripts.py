"""Script-level smoke tests. The scripts are driven with tests/fake_claude.sh. NO model calls, no plan usage.

Safety net: NO_MODEL_CALLS=1 makes the scripts refuse to run any CLAUDE_BIN that is not fake_claude.sh.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import EVAL, ROOT

FAKE = str(ROOT / "tests" / "fake_claude.sh")
SCRIPTS = ["gap_eval.sh", "chain_eval.sh", "lib.sh", "scrub.sh"]


def env_for(tmp_path, **extra):
    e = dict(os.environ)
    e.update({
        "RESULTS_DIR": str(tmp_path / "results"), "CLAUDE_BIN": FAKE, "NO_MODEL_CALLS": "1",
        "SLEEP_SCALE": "0", "STAGGER_S": "0", "IDLE_CAFFEINATED": "1", "CUM_COST_CAP_USD": "5",
        "FAKE_LOG": str(tmp_path / "fake.log"), "ANTHROPIC_API_KEY": "sk-fixture-must-be-unset",
    })
    e.update({k: str(v) for k, v in extra.items()})
    return e


def run(script, args, env, check=False):
    return subprocess.run(["bash", str(EVAL / script), *args], env=env, capture_output=True, text=True, timeout=120)


def lines(p):
    return Path(p).read_text().splitlines() if Path(p).exists() else []


@pytest.mark.parametrize("name", SCRIPTS)
def test_scripts_parse(name):
    assert subprocess.run(["bash", "-n", str(EVAL / name)]).returncode == 0


def test_scripts_never_use_bare_or_set_an_api_key():
    for name in SCRIPTS:
        text = (EVAL / name).read_text()
        assert "--bare" not in text, name
        assert not re.search(r"ANTHROPIC_API_KEY=", text), name
    assert "unset ANTHROPIC_API_KEY" in (EVAL / "lib.sh").read_text()


def test_refuses_the_real_cli_when_no_model_calls_is_set(tmp_path):
    r = run("gap_eval.sh", ["pilot"], env_for(tmp_path, CLAUDE_BIN="claude"))
    assert r.returncode == 3
    assert not (tmp_path / "results").exists() or not list((tmp_path / "results").glob("*.json"))


def test_requires_a_cost_cap(tmp_path):
    e = env_for(tmp_path)
    del e["CUM_COST_CAP_USD"]
    r = run("gap_eval.sh", ["pilot"], e)
    assert r.returncode != 0 and "CUM_COST_CAP_USD" in r.stderr


def test_pilot_runs_floor_then_four_sessions(tmp_path):
    e = env_for(tmp_path)
    r = run("gap_eval.sh", ["pilot"], e)
    assert r.returncode == 0, r.stderr
    res = tmp_path / "results"
    assert (res / "floor.json").exists()
    sessions = sorted(p.name for p in res.glob("gap-*") if p.is_dir())
    assert sessions == ["gap-large-g3900-rep1", "gap-small-g0-rep1", "gap-small-g360-rep1", "gap-small-g3900-rep1"]
    meta = json.loads((res / "gap-small-g360-rep1" / "meta.json").read_text())
    for key in ("cell", "rep", "size_label", "gap_planned_s", "gap_actual_s", "claude_version", "started_at_utc",
                "setup_wall_s", "resume_wall_s", "session_id", "doc_chars"):
        assert key in meta, key
    assert meta["gap_planned_s"] == 360 and meta["claude_version"].startswith("0.0.0-fake")


def test_calls_use_plan_login_flags_and_the_same_session_id(tmp_path):
    e = env_for(tmp_path)
    run("gap_eval.sh", ["pilot"], e)
    log = lines(tmp_path / "fake.log")
    assert log and all("keyset=yes" not in l for l in log), "ANTHROPIC_API_KEY leaked to claude"
    setups = [l for l in log if l.startswith("mode=setup")]
    resumes = [l for l in log if l.startswith("mode=resume")]
    assert len(setups) == 4 and len(resumes) == 4
    for l in setups + resumes:
        assert "--model sonnet" in l and "--effort medium" in l and "--output-format json" in l
        assert "--max-budget-usd" in l and "--no-session-persistence" not in l and "--bare" not in l
    ids_setup = {re.search(r"--session-id (\S+)", l).group(1) for l in setups}
    ids_resume = {re.search(r"--resume (\S+)", l).group(1) for l in resumes}
    assert ids_setup == ids_resume and len(ids_setup) == 4


def test_fails_fast_when_a_target_is_not_above_the_floor(tmp_path):
    # Found in the real pilot: floor 15,583 tokens vs TARGET_SMALL 15,000 made every small session fail silently.
    e = env_for(tmp_path, FAKE_FLOOR_TOKENS=16000)
    r = run("gap_eval.sh", ["pilot"], e)
    assert r.returncode != 0 and "TARGET_SMALL" in r.stderr
    log = lines(tmp_path / "fake.log")
    assert not [l for l in log if l.startswith("mode=setup")], "no session may start with an impossible target"


def test_only_runs_the_listed_sessions(tmp_path):
    e = env_for(tmp_path, ONLY="small 0 1;small 6 1")
    r = run("gap_eval.sh", ["pilot"], e)
    assert r.returncode == 0, r.stderr
    sessions = sorted(p.name for p in (tmp_path / "results").glob("gap-*") if p.is_dir())
    assert sessions == ["gap-small-g0-rep1", "gap-small-g360-rep1"]


def test_calibrated_chars_per_token_is_used_for_sizing(tmp_path):
    res = tmp_path / "results"
    res.mkdir()
    (res / "sizes.env").write_text("CPT=2.0\n")
    e = env_for(tmp_path, ONLY="small 0 1", TARGET_SMALL=5000)
    run("gap_eval.sh", ["pilot"], e)
    meta = json.loads((res / "gap-small-g0-rep1" / "meta.json").read_text())
    assert meta["doc_chars"] == int((5000 - 3006) * 2.0)  # the stub floor is 3,006 input tokens (3,000 written + 6 plain)


def test_cost_cap_counts_each_session_once_because_resume_totals_are_cumulative(tmp_path):
    res = tmp_path / "results"
    (res / "s1").mkdir(parents=True)
    (res / "chain").mkdir()
    def put(path, cost):
        path.write_text(json.dumps({"total_cost_usd": cost}))
    put(res / "floor.json", 0.01)
    put(res / "s1" / "setup.json", 0.01); put(res / "s1" / "resume.json", 0.02)      # session total is 0.02
    for i, c in enumerate((0.01, 0.02, 0.03), 1):                                      # chain turns are cumulative too
        put(res / "chain" / f"turn-{i:02d}.json", c)
    (res / "s1" / "meta.json").write_text(json.dumps({"total_cost_usd": 99}))         # meta is never counted
    out = subprocess.run(["bash", "-c", f'RESULTS_DIR="{res}" . "{EVAL}/lib.sh"; total_cost'], capture_output=True, text=True)
    assert abs(float(out.stdout.strip()) - 0.06) < 1e-9, out.stdout + out.stderr


def test_rerun_skips_finished_sessions(tmp_path):
    e = env_for(tmp_path)
    run("gap_eval.sh", ["pilot"], e)
    n = len(lines(tmp_path / "fake.log"))
    run("gap_eval.sh", ["pilot"], e)
    # floor and all four sessions already exist: no further calls
    assert len(lines(tmp_path / "fake.log")) == n


def test_any_error_writes_a_stop_file_and_blocks_the_resume(tmp_path):
    r = run("gap_eval.sh", ["pilot"], env_for(tmp_path, FAKE_FAIL=1))
    res = tmp_path / "results"
    assert (res / "STOP").exists()
    assert not list(res.glob("gap-*/resume.json"))
    assert r.returncode != 0


def test_resume_error_also_stops(tmp_path):
    run("gap_eval.sh", ["pilot"], env_for(tmp_path, FAKE_FAIL_ON="resume"))
    assert (tmp_path / "results" / "STOP").exists()


def test_cost_cap_stops_the_run(tmp_path):
    r = run("gap_eval.sh", ["pilot"], env_for(tmp_path, FAKE_COST=3, CUM_COST_CAP_USD=1))
    stop = tmp_path / "results" / "STOP"
    assert stop.exists() and "cost" in stop.read_text().lower()
    assert r.returncode != 0


def test_full_needs_a_floor_first_then_runs_eight_cells_times_n(tmp_path):
    e = env_for(tmp_path)
    r = run("gap_eval.sh", ["full", "1"], e)
    assert r.returncode != 0 and "floor" in r.stderr.lower()
    run("gap_eval.sh", ["pilot"], e)
    r = run("gap_eval.sh", ["full", "1"], e)
    assert r.returncode == 0, r.stderr
    dirs = [p for p in (tmp_path / "results").glob("gap-*") if p.is_dir()]
    assert len(dirs) == 8  # 4 gaps x 2 sizes x n=1 (the 4 pilot sessions are among them)


def test_chain_makes_one_session_with_n_turns(tmp_path):
    e = env_for(tmp_path)
    run("gap_eval.sh", ["pilot"], e)
    r = run("chain_eval.sh", ["4"], e)
    assert r.returncode == 0, r.stderr
    turns = sorted((tmp_path / "results" / "chain").glob("turn-*.json"))
    assert [t.name for t in turns] == ["turn-01.json", "turn-02.json", "turn-03.json", "turn-04.json"]
    ids = {json.loads(t.read_text())["session_id"] for t in turns}
    assert len(ids) == 1


def test_analyze_reads_what_the_scripts_wrote(tmp_path):
    e = env_for(tmp_path, FAKE_RESUME="miss")
    run("gap_eval.sh", ["pilot"], e)
    out = subprocess.run([sys.executable, "-I", str(EVAL / "analyze.py"), str(tmp_path / "results")],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "miss" in out.stdout and "synthetic" not in out.stdout.lower()


def test_scrub_script_removes_session_ids(tmp_path):
    e = env_for(tmp_path)
    run("gap_eval.sh", ["pilot"], e)
    pub = tmp_path / "public"
    r = subprocess.run(["bash", str(EVAL / "scrub.sh"), str(tmp_path / "results"), str(pub)], env=e,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    text = "".join(p.read_text() for p in pub.rglob("*.json"))
    assert "00000000-0000-4000" not in text and "sess-" in text
