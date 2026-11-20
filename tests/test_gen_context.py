import re

import gen_context as g


def test_same_seed_same_text():
    assert g.generate(2000, seed=7) == g.generate(2000, seed=7)


def test_different_seeds_differ_in_the_first_chars():
    # The cache is a PREFIX match: two sessions must differ at the very start, or they would share a cached document.
    a, b = g.generate(2000, seed=1), g.generate(2000, seed=2)
    assert a[:60] != b[:60]


def test_length_follows_tokens_times_chars_per_token():
    text = g.generate(1500, seed=3, cpt=4.0)
    assert len(text) == 6000
    assert len(g.generate(1500, seed=3, cpt=3.0)) == 4500


def test_text_is_plain_ascii_without_personal_markers():
    text = g.generate(3000, seed=5)
    text.encode("ascii")
    assert not re.search(r"/Users/|@|http", text)


def test_seed_for_label_is_stable_and_distinct():
    assert g.seed_for("gap-small-1") == g.seed_for("gap-small-1")
    assert g.seed_for("gap-small-1") != g.seed_for("gap-small-2")
    assert g.seed_for("gap-small-1") != g.seed_for("gap-large-1")


def test_minimum_size_is_enforced():
    import pytest
    with pytest.raises(ValueError):
        g.generate(10, seed=1)
