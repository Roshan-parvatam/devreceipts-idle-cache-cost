import json

import analyze as a
from conftest import make_call, write_session


def test_usage_of_sums_the_three_input_kinds():
    u = a.usage_of(make_call(inp=6, cc=100, cr=900, out=7, cost=0.5))
    assert (u["input"], u["cache_creation"], u["cache_read"], u["output"]) == (6, 100, 900, 7)
    assert u["total_in"] == 1006
    assert u["cost_usd"] == 0.5


def test_usage_of_keeps_ephemeral_fields_and_marks_missing_as_none():
    u = a.usage_of(make_call(cc=50, cc_5m=10, cc_1h=40))
    assert (u["cc_5m"], u["cc_1h"]) == (10, 40)
    raw = make_call()
    del raw["usage"]["cache_creation"]
    u2 = a.usage_of(raw)
    assert u2["cc_5m"] is None and u2["cc_1h"] is None  # unknown stays unknown, never 0


def test_classify_hit_miss_partial_with_no_floor():
    total = 10_000
    assert a.classify(total, a.usage_of(make_call(cr=9_500, cc=400))) == "hit"
    assert a.classify(total, a.usage_of(make_call(cr=500, cc=9_400))) == "miss"
    assert a.classify(total, a.usage_of(make_call(cr=5_000, cc=5_000))) == "partial"


def test_classify_thresholds_are_inclusive_at_90_percent():
    assert a.classify(1000, a.usage_of(make_call(cr=900, cc=100))) == "hit"
    assert a.classify(1000, a.usage_of(make_call(cr=899, cc=101))) == "partial"
    assert a.classify(1000, a.usage_of(make_call(cr=100, cc=900))) == "miss"


def test_classify_miss_is_measured_against_the_document_part_when_the_floor_is_known():
    # total 10,000 with a 3,000 shared prefix: a rewritten document is 7,000 tokens, prefix still read from cache.
    u = a.usage_of(make_call(cr=3_000, cc=7_000))
    assert a.classify(10_000, u) == "partial"              # no floor given: the plain handoff rule says partial
    assert a.classify(10_000, u, floor_total=3_000) == "miss"
    # a full hit stays a hit with a floor
    assert a.classify(10_000, a.usage_of(make_call(cr=9_900, cc=100)), floor_total=3_000) == "hit"


def test_classify_error_and_bad_setup():
    assert a.classify(1000, a.usage_of(make_call(is_error=True, subtype="error_during_execution"))) == "error"
    assert a.classify(0, a.usage_of(make_call(cr=5))) == "invalid"


def test_load_session_builds_the_logged_record(tmp_path):
    d = write_session(tmp_path / "s1", make_call(cc=9_000, cr=0), make_call(cr=8_900, cc=100, result=" OK\n"),
                      gap_planned_s=360)
    r = a.load_session(d)
    for key in ("cell", "rep", "size_label", "gap_planned_s", "gap_actual_s", "claude_version", "started_at_utc",
                "wall_s", "is_error", "subtype", "reply_ok", "setup", "resume", "class"):
        assert key in r, key
    assert r["reply_ok"] is True
    assert r["setup"]["total_in"] == 9_006
    assert r["class"] == "hit"


def test_reply_ok_false_when_the_model_said_something_else(tmp_path):
    d = write_session(tmp_path / "s", make_call(cc=100), make_call(cr=100, result="Sure, OK!"))
    assert a.load_session(d)["reply_ok"] is False


def test_load_session_without_a_resume_is_incomplete_not_a_crash(tmp_path):
    d = write_session(tmp_path / "s", make_call(cc=100), None)
    r = a.load_session(d)
    assert r["class"] == "incomplete" and r["resume"] is None


def test_summarize_groups_cells_and_reports_median_and_range(tmp_path):
    recs = []
    for i, cr in enumerate([9_900, 9_800, 9_950], start=1):
        recs.append(a.load_session(write_session(tmp_path / f"a{i}", make_call(cc=10_000), make_call(cr=cr, cc=10_000 - cr),
                                                 rep=i, gap_planned_s=0, size_label="small")))
    recs.append(a.load_session(write_session(tmp_path / "b1", make_call(cc=10_000), make_call(cr=0, cc=10_000),
                                             rep=1, gap_planned_s=3900, size_label="small")))
    cells = a.summarize(recs)
    c0 = cells[(0, "small")]
    assert c0["n"] == 3 and c0["classes"] == {"hit": 3}
    assert c0["resume_cache_read"]["median"] == 9_900
    assert (c0["resume_cache_read"]["min"], c0["resume_cache_read"]["max"]) == (9_800, 9_950)
    assert cells[(3900, "small")]["classes"] == {"miss": 1}


def test_markdown_table_prints_todo_for_cells_without_data(tmp_path):
    md = a.to_markdown(a.summarize([]), gaps=[0, 240], sizes=["small"])
    assert md.count("TODO: measure") >= 2


def _rec(tmp_path, name, setup, resume, gap, size="small", rep=1):
    return a.load_session(write_session(tmp_path / name, setup, resume, gap_planned_s=gap, size_label=size, rep=rep))


def test_gap0_sanity_needs_the_document_read_from_cache(tmp_path):
    # shared prefix F=15,583 of which 9,064 is read from cache even for a brand-new session; document = setup total - F
    good = _rec(tmp_path, "g", make_call(cc=17_797, cr=9_064), make_call(cc=6_449, cr=20_846), 0)
    assert a.gap0_ok([good], floor_total=15_583, floor_read=9_064) is True
    bad = _rec(tmp_path, "b", make_call(cc=17_797, cr=9_064), make_call(cc=26_000, cr=9_064), 0)
    assert a.gap0_ok([bad], floor_total=15_583, floor_read=9_064) is False
    assert a.gap0_ok([], floor_total=15_583, floor_read=9_064) is None  # nothing measured yet


def test_gap0_sanity_ignores_other_gaps(tmp_path):
    other = _rec(tmp_path, "o", make_call(cc=17_797, cr=9_064), make_call(cc=26_000, cr=9_064), 3900)
    assert a.gap0_ok([other], floor_total=15_583, floor_read=9_064) is None


def test_classify_against_a_gap0_control():
    # a resume always re-writes a few thousand tokens, so 'read >= 90% of the setup total' can never pass.
    # With a control (median cache_read of gap-0 resumes at the same size) a hit is 'reads at least 90% of the control'.
    u = a.usage_of(make_call(cr=20_780, cc=4_140))
    assert a.classify(24_889, u) == "partial"                              # legacy rule, no control
    assert a.classify(24_889, u, floor_total=15_583, control_read=20_846) == "hit"
    miss = a.usage_of(make_call(cr=9_064, cc=60_322))
    assert a.classify(69_355, miss, floor_total=15_583, control_read=62_000) == "miss"
    mid = a.usage_of(make_call(cr=14_000, cc=10_000))
    assert a.classify(26_863, mid, floor_total=15_583, control_read=20_846) == "partial"


def test_controls_are_the_median_gap0_read_per_size(tmp_path):
    recs = [_rec(tmp_path, f"c{i}", make_call(cc=10_000), make_call(cr=cr, cc=500), 0, "small", i)
            for i, cr in enumerate((20_000, 21_000, 25_000), 1)]
    recs.append(_rec(tmp_path, "l", make_call(cc=50_000), make_call(cr=60_000, cc=500), 0, "large"))
    recs.append(_rec(tmp_path, "x", make_call(cc=10_000), make_call(cr=1, cc=10_000), 3900, "small"))
    assert a.controls_from(recs) == {"small": 21_000, "large": 60_000}


def test_resume_cost_is_the_session_total_minus_the_setup(tmp_path):
    # total_cost_usd in a resumed call is cumulative for the session (it includes the setup call)
    r = _rec(tmp_path, "s", make_call(cc=100, cost=0.0721), make_call(cr=100, cost=0.1001), 0)
    assert abs(r["resume"]["cost_own_usd"] - 0.0280) < 1e-9


def test_calibrate_chars_per_token():
    assert a.calibrate_cpt(chars=60_000, setup_total=25_000, floor_total=10_000) == 4.0
    assert a.calibrate_cpt(chars=60_000, setup_total=9_000, floor_total=10_000) is None


def test_scrub_replaces_session_ids_everywhere(tmp_path):
    sid = "11111111-2222-4333-8444-555555555555"
    d = write_session(tmp_path / "src" / "s1", make_call(cc=10, session_id=sid), make_call(cr=10, session_id=sid))
    out = tmp_path / "pub"
    a.scrub(tmp_path / "src", out)
    text = "".join(p.read_text() for p in out.rglob("*.json"))
    assert sid not in text
    assert "sess-" in text
    assert d.name in {p.name for p in out.iterdir()}


def test_cli_prints_no_results_message_for_an_empty_folder(tmp_path, capsys):
    assert a.main([str(tmp_path)]) == 0
    assert "no results" in capsys.readouterr().out.lower()
