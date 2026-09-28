"""accountable-surface-replay: verify, explain, and export, without acting.

`verify` prints the level report as JSON and exits 0 MATCH, 1 DRIFT, 2
UNVERIFIABLE. `explain` shows one event: the step as a person may see it, every
rule hit with its reason, the evidence refs, and the verdict detail, and never
a field value. `export --mode chain` hands over the receipts alone; `--mode
full` adds the salt, every blob the receipts name, and the pinned sources, and
the bundle re-derives in a fresh place.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from actuation_site import Site
from actuation_world import PASSWORD, World, mixed_session, reseal

from accountable_surface import replay_cli


@pytest.fixture
def site():
    s = Site().start()
    yield s
    s.stop()


@pytest.fixture
def world(tmp_path, site):
    w = World(tmp_path / "session", site)
    mixed_session(w)
    return w


def cli(capsys, *argv):
    code = replay_cli.main([str(a) for a in argv])
    return code, capsys.readouterr().out


def test_verify_prints_the_report_and_exits_by_verdict(world, capsys):
    code, out = cli(capsys, "verify", world.receipts.path, "--evidence", world.evidence.root)
    assert code == 0 and json.loads(out)["verdict"] == "MATCH"

    def launder(records):
        records[-1]["policy"]["outcome"] = "pass"
    reseal(world.receipts.path, launder)
    code, out = cli(capsys, "verify", world.receipts.path, "--evidence", world.evidence.root)
    assert code == 1 and json.loads(out)["levels"]["policy"]["verdict"] == "DRIFT"


def test_verify_a_missing_file_or_store_is_unverifiable(world, tmp_path, capsys):
    code, _ = cli(capsys, "verify", tmp_path / "nope.jsonl", "--level", "chain")
    assert code == 2
    code, out = cli(capsys, "verify", world.receipts.path, "--evidence", tmp_path / "empty-store")
    assert code == 2 and json.loads(out)["verdict"] == "UNVERIFIABLE"


def test_verify_at_the_chain_level_needs_no_evidence(world, capsys):
    code, out = cli(capsys, "verify", world.receipts.path, "--level", "chain")
    assert code == 0 and list(json.loads(out)["levels"]) == ["chain"]


def test_verify_past_the_chain_level_without_a_store_is_refused(world, capsys):
    code, out = cli(capsys, "verify", world.receipts.path, "--level", "policy")
    assert code == 2 and "--evidence" in out


def test_explain_names_every_rule_hit_and_the_evidence(world, capsys):
    code, out = cli(capsys, "explain", world.receipts.path, "--event", "6", "--evidence", world.evidence.root)
    shown = json.loads(out)
    assert code == 0 and shown["step"]["step_id"] == "submit" and shown["status"] == "needs-human"
    assert {"R7.irreversible"} <= {h["rule"] for h in shown["rule_hits"]}
    assert all(h["reason"] for h in shown["rule_hits"])
    assert shown["evidence"]["inputs"].startswith("sha256:") and shown["rederived"]["policy"] == "MATCH"
    assert "value" not in shown["step"].get("args", {})


def test_explain_never_shows_a_value(world, capsys):
    code, out = cli(capsys, "explain", world.receipts.path, "--event", "2", "--evidence", world.evidence.root)
    assert code == 0 and "weekly notes" not in out
    code, out = cli(capsys, "explain", world.receipts.path, "--event", "4", "--evidence", world.evidence.root)
    assert code == 0 and PASSWORD not in out and "R4.secret-field" in out


def test_explain_an_unknown_event_exits_2(world, capsys):
    code, _ = cli(capsys, "explain", world.receipts.path, "--event", "99")
    assert code == 2


def test_export_chain_carries_only_the_receipts(world, tmp_path, capsys):
    out_dir = tmp_path / "bundle-chain"
    code, _ = cli(capsys, "export", world.receipts.path, "--evidence", world.evidence.root,
                  "--mode", "chain", "--out", out_dir)
    assert code == 0
    files = sorted(p.relative_to(out_dir).as_posix() for p in out_dir.rglob("*") if p.is_file())
    assert files == ["MANIFEST.json", "receipts.jsonl"]
    salt = world.receipts.salt_path.read_bytes()
    assert all(salt not in (out_dir / f).read_bytes() for f in files)
    assert b"weekly notes" not in b"".join((out_dir / f).read_bytes() for f in files)


def test_export_full_re_derives_in_a_fresh_place(world, tmp_path, capsys):
    out_dir = tmp_path / "bundle-full"
    code, _ = cli(capsys, "export", world.receipts.path, "--evidence", world.evidence.root,
                  "--mode", "full", "--out", out_dir)
    assert code == 0 and (out_dir / "receipts.jsonl.salt").read_bytes() == world.receipts.salt_path.read_bytes()
    code, out = cli(capsys, "verify", out_dir / "receipts.jsonl", "--evidence", out_dir / "evidence")
    assert code == 0 and json.loads(out)["verdict"] == "MATCH"
    genesis = json.loads((out_dir / "receipts.jsonl").read_text(encoding="utf-8").splitlines()[0])
    for name, pinned in genesis["sources"].items():
        data = (out_dir / "sources" / name).read_bytes()
        assert "sha256:" + hashlib.sha256(data).hexdigest() == pinned, name
    manifest = json.loads((out_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "full" and all(f["sha256"].startswith("sha256:") for f in manifest["files"])


def test_export_refuses_to_write_into_a_non_empty_folder(world, tmp_path, capsys):
    out_dir = tmp_path / "busy"
    out_dir.mkdir()
    (out_dir / "keep.txt").write_text("keep", encoding="utf-8")
    code, _ = cli(capsys, "export", world.receipts.path, "--mode", "chain", "--out", out_dir)
    assert code == 2 and (out_dir / "keep.txt").read_text(encoding="utf-8") == "keep"
