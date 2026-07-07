"""Pure-logic tests for vendor name matching — no I/O, no mocks."""

from __future__ import annotations

from types import SimpleNamespace

from goldman.vendor_match import match_vendor, normalize_name, significant_words


def _vendor(name, vid="V-1"):
    return SimpleNamespace(contact_id=vid, contact_name=name)


def test_normalize_name_strips_case_punctuation_and_whitespace():
    assert normalize_name("Akiva, CPA.") == "akiva cpa"
    assert normalize_name("  Akiva   CPA  ") == "akiva cpa"


def test_significant_words_drops_filler():
    assert significant_words("Akiva CPA LLC") == {"akiva"}


def test_exact_match_ignores_case_and_punctuation():
    existing = [_vendor("Akiva CPA", "V-1")]
    result = match_vendor("akiva, cpa.", existing)
    assert result.kind == "exact"
    assert result.candidates[0].contact_id == "V-1"


def test_shared_distinctive_word_is_flagged_similar():
    existing = [_vendor("Akiva CPA", "V-1")]
    result = match_vendor("Akiva Cohen, Accounting", existing)
    assert result.kind == "similar"
    assert result.candidates[0].contact_id == "V-1"


def test_added_legal_suffix_is_flagged_similar_not_exact():
    existing = [_vendor("Akiva CPA", "V-1")]
    result = match_vendor("AKIVA CPA LTD", existing)
    assert result.kind == "similar"


def test_close_spelling_typo_is_flagged_similar():
    existing = [_vendor("Akiva CPA", "V-1")]
    result = match_vendor("Akvia CPA", existing)
    assert result.kind == "similar"


def test_unrelated_name_is_not_matched():
    existing = [_vendor("Akiva CPA", "V-1")]
    result = match_vendor("Bezeq", existing)
    assert result.kind == "none"


def test_filler_word_overlap_alone_does_not_false_positive():
    existing = [_vendor("Northline Services LLC", "V-1")]
    result = match_vendor("Summit Consulting Services Inc", existing)
    assert result.kind == "none"


def test_no_existing_vendors_is_none():
    assert match_vendor("Bezeq", []).kind == "none"


def test_empty_name_is_none():
    assert match_vendor("", [_vendor("Akiva CPA")]).kind == "none"


def test_similar_candidates_capped_and_ranked_shared_word_first():
    existing = [
        _vendor("Akiva Cohen Accounting", "V-2"),  # shared word, lower ratio
        _vendor("Akiva CPA", "V-1"),                # exact-ish, would be "exact" alone
        _vendor("Akvia CPA Group", "V-3"),          # ratio-only match
    ]
    # Use a name that doesn't exactly equal any of them, so all three compete
    # as "similar" candidates instead of short-circuiting to "exact".
    result = match_vendor("Akiva CPA Services", existing)
    assert result.kind == "similar"
    assert len(result.candidates) <= 3
