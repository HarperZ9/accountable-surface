"""The content-addressed evidence store and the helpers that fill it.

A blob's name is the sha256 of its bytes, so a missing blob reads UNVERIFIABLE
and an edited one DRIFT on re-hash. A ref that is not a well-formed sha256 name
never reaches the filesystem. Driver snapshots are redacted before storage:
secret shapes in any field value, and the whole value of a field whose name
marks it secret.
"""

from __future__ import annotations

import hashlib

import pytest

from accountable_surface import evidence
from accountable_surface.page_evidence import parse_page

CARD = "4111 1111 1111 1111"


def test_put_names_the_blob_by_its_sha256_and_is_idempotent(tmp_path):
    store = evidence.EvidenceStore(tmp_path / "ev")
    ref = store.put({"b": 2, "a": 1})
    raw = b'{"a":1,"b":2}'
    assert ref == "sha256:" + hashlib.sha256(raw).hexdigest()
    hexd = ref.split(":", 1)[1]
    assert (tmp_path / "ev" / "sha256" / hexd[:2] / hexd).read_bytes() == raw
    assert store.put({"a": 1, "b": 2}) == ref
    assert store.load(ref) == {"a": 1, "b": 2}


def test_check_reads_missing_as_unverifiable_and_edited_as_drift(tmp_path):
    store = evidence.EvidenceStore(tmp_path / "ev")
    ref = store.put({"page": "notes"})
    assert store.check(ref) == "MATCH"
    store.path_for(ref).write_bytes(b'{"page":"orders"}')
    assert store.check(ref) == "DRIFT" and store.load(ref) is None
    store.path_for(ref).unlink()
    assert store.check(ref) == "UNVERIFIABLE" and store.load(ref) is None


@pytest.mark.parametrize("ref", ["sha256:../../etc/passwd", "sha256:" + "g" * 64, "md5:" + "a" * 32, "", None, 7])
def test_a_malformed_ref_never_reaches_the_filesystem(tmp_path, ref):
    store = evidence.EvidenceStore(tmp_path / "ev")
    assert store.check(ref) == "UNVERIFIABLE" and store.load(ref) is None
    with pytest.raises(ValueError):
        store.path_for(ref)


def test_page_evidence_round_trips_through_its_dict():
    page = parse_page("http://127.0.0.1:9/order", "<title>Order</title><form action='/o'>"
                      "<label for='q'>Quantity</label><input id='q' name='quantity'>"
                      "<button type='submit'>Submit order</button></form><iframe src='x' title='t'></iframe>",
                      http_status=403, response_headers={"cf-mitigated": "challenge"})
    again = evidence.page_from_dict(page.to_dict())
    assert again == page and again.digest == page.digest
    assert evidence.page_from_dict(None) is None


def test_before_evidence_is_stored_under_its_own_digest(tmp_path):
    store = evidence.EvidenceStore(tmp_path / "ev")
    page = parse_page("http://127.0.0.1:9/notes", "<title>Notes</title><p>hello</p>")
    assert store.put(page.to_dict()) == page.digest


def test_snapshot_redaction_drops_secret_shapes_and_secret_field_values():
    snap = {"url": "http://127.0.0.1:9/x", "title": "Checkout",
            "fields": {"Notes": f"call me, card {CARD}", "Password": "hunter2-horse", "Title": "weekly notes"}}
    out, count = evidence.redact_snapshot(snap)
    assert CARD not in out["fields"]["Notes"] and "[redacted:" in out["fields"]["Notes"]
    assert out["fields"]["Password"] == "[redacted:secret-field]"
    assert out["fields"]["Title"] == "weekly notes" and out["title"] == "Checkout"
    assert count == 2 and snap["fields"]["Password"] == "hunter2-horse"  # the input is not changed
