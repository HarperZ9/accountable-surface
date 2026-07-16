"""The journal must be tamper-EVIDENT, not merely corruption-evident. An edited-but-
valid entry, a deleted middle entry, or a reordered entry all still PARSE, so the
replay_errors check misses them. A hash chain catches them on reload, and
verify_journal reports the verdict."""
from __future__ import annotations

import json

from accountable_surface.surface import AccountableSurface

_PAGES = [
    b"<!doctype html><html><head><title>one</title></head><body><p>1</p></body></html>",
    b"<!doctype html><html><head><title>two</title></head><body><p>2</p></body></html>",
    b"<!doctype html><html><head><title>three</title></head><body><p>3</p></body></html>",
]


def _seed(path):
    s = AccountableSurface(journal_path=path)
    for page in _PAGES:
        s.perceive(page)
    return s


def _lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_an_intact_journal_verifies(tmp_path):
    path = tmp_path / "j.jsonl"
    _seed(path)
    reloaded = AccountableSurface(journal_path=path)
    assert reloaded.journal_tamper == 0 and len(reloaded.journal) == 3
    v = reloaded.verify_journal()
    assert v["chain_ok"] is True and v["tamper_count"] == 0


def test_editing_a_valid_entry_is_caught_though_it_still_parses(tmp_path):
    path = tmp_path / "j.jsonl"
    _seed(path)
    lines = _lines(path)
    rec = json.loads(lines[1])
    rec["detail"]["title"] = "TAMPERED"          # a valid JSON edit, no rehash
    lines[1] = json.dumps(rec, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    reloaded = AccountableSurface(journal_path=path)
    assert reloaded.replay_errors == 0            # the corruption check misses it (it parses)
    assert reloaded.journal_tamper >= 1           # the chain does not
    assert reloaded.verify_journal()["chain_ok"] is False


def test_deleting_a_middle_entry_is_caught(tmp_path):
    path = tmp_path / "j.jsonl"
    _seed(path)
    lines = _lines(path)
    del lines[1]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    reloaded = AccountableSurface(journal_path=path)
    assert reloaded.journal_tamper >= 1 and reloaded.verify_journal()["chain_ok"] is False


def test_reordering_entries_is_caught(tmp_path):
    path = tmp_path / "j.jsonl"
    _seed(path)
    lines = _lines(path)
    lines[0], lines[1] = lines[1], lines[0]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    reloaded = AccountableSurface(journal_path=path)
    assert reloaded.journal_tamper >= 1


def test_verify_journal_is_true_for_an_in_memory_surface(tmp_path):
    s = AccountableSurface()          # no path: nothing persisted to tamper
    s.perceive(_PAGES[0])
    assert s.verify_journal()["chain_ok"] is True
