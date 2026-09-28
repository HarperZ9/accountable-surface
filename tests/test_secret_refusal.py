"""Secret refusal, detector half: field markers and value shapes.

The tool refuses to type a password, key, token, card or bank number, or
government ID into any field. A field is recognised by its markers (type,
autocomplete, name, label); a value is recognised by its shape, so a card
number typed into a field labelled "Notes" is still refused. Refusals name the
rule and the field, never the value. The pipeline half (no fill reaches the
driver, nothing persists) is in test_actuation_pipeline.py.

Key-like strings are assembled at run time so this file carries no string a
secret scanner would read as a real credential.
"""

from __future__ import annotations

import pytest

from accountable_surface.detectors import secrets
from accountable_surface.page_evidence import parse_page

MARKED_FIELDS = [
    "<input type='password' name='p'>",
    "<input autocomplete='current-password' name='x'>",
    "<input autocomplete='new-password' name='x'>",
    "<input autocomplete='one-time-code' name='x'>",
    "<input autocomplete='cc-number' name='x'>",
    "<input autocomplete='cc-csc' name='x'>",
    "<input autocomplete='cc-exp' name='x'>",
    "<input name='password'>", "<input name='passwd'>", "<input name='pwd'>",
    "<input name='otp'>", "<input name='mfa_code'>", "<input name='2fa'>",
    "<input name='cvv'>", "<input name='cvc'>", "<input name='cardNumber'>",
    "<input name='card-number'>", "<input name='ssn'>", "<input name='client_secret'>",
    "<input name='access_token'>", "<input name='apiKey'>", "<input name='api_key'>",
    "<input name='private_key'>", "<input name='seed_phrase'>", "<input name='passphrase'>",
    "<input name='pin'>", "<input name='security-code'>", "<input name='iban'>",
    "<input name='routing_number'>", "<input name='account_number'>", "<input name='sort_code'>",
    "<input name='swift'>", "<input name='bic'>", "<input name='passport_no'>",
    "<input name='tax_id'>", "<input name='tin'>", "<input name='national_id'>",
    "<input name='drivers_license'>", "<input name='recovery_code'>", "<input name='mnemonic'>",
    "<label for='a'>Card number</label><input id='a'>",
    "<input placeholder='Your PIN'>", "<input aria-label='Social Security Number'>",
]


def _key(prefix, n, ch="Q7"):
    return prefix + (ch * n)[:n]


PLANTED_VALUES = [
    "4111111111111111", "4111 1111 1111 1111", "4111-1111-1111-1111", "5555555555554444",
    "378282246310005", "6011111111111117", "3566002020360505", "2223003122003222",
    "my card is 5105 1051 0510 5100 thanks",
    "GB82WEST12345698765432", "DE89 3704 0044 0532 0130 00", "NL91ABNA0417164300",
    "123-45-6789", "078-05-1120",
    "021000021", "011000015", "121000358",
    _key("sk-", 40), _key("sk_live_", 24), _key("rk_live_", 24), _key("ghp_", 36),
    _key("gho_", 36), _key("github_pat_", 60), _key("glpat-", 20), _key("xoxb-", 30),
    _key("xoxp-", 30), "AKIA" + "IOSFODNN7EXAMPLE", "ASIA" + "IOSFODNN7EXAMPLE",
    _key("AIza", 35, "Sy9"), "eyJ" + "hbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----",
    "q8Zr2Lk9Vb7Xn4Pw1Ty6Hs3Jd0Mf5Gc8Ra2Qe7Ui",
]

BENIGN_VALUES = [
    "weekly notes", "Ada Lovelace", "ada@example.test", "12 Main Street", "Seattle", "98101",
    "+1 206 555 0100", "(206) 555-0199", "2026-09-27", "09/27/2026", "3", "19.99", "$19.99",
    "ORD-2026-0042", "Please leave the parcel at the door.", "Blue", "Large", "No preference",
    "1727467200000", "9780306406157", "1Z999AA10123456784", "1.9.1", "v0.3.1",
    "3f2a9c1e5b7d4f6a8c0e2b4d6f8a0c2e4b6d8f0a", "5b73a1b", "d5a7c10",
    "550e8400-e29b-41d4-a716-446655440000", "123e4567-e89b-12d3-a456-426614174000",
    "https://example.test/articles/2026/09/27/accountable-actuation?ref=home",
    "C:/dev/projects/notes/readme.md", "/home/ada/projects/notes/README.md",
    "The quick brown fox jumps over the lazy dog.", "Meeting moved to Thursday at 3pm.",
    "Order 1234 arrived damaged, requesting a replacement.", "Room 204", "Flight AS 1234",
    "Invoice #000123", "Qty 12", "SKU-4411-BLUE", "4 x 2 x 1 in", "42", "0", "-7", "3.14159",
    "hello world", "HELLO", "Thanks!", "N/A", "none", "yes", "no", "maybe later",
    "Supercalifragilisticexpialidocious", "antidisestablishmentarianism",
    "pneumonoultramicroscopicsilicovolcanoconiosis", "tokenizer settings", "password reset flow docs",
    "My PIN code lesson plan", "cardboard boxes", "apiary notes", "Seed catalog 2026",
    "shipping to Portland", "routing the cables behind the desk", "a secret garden",
    "The token economy chapter", "banking holiday on Monday", "Card games night",
    "SGVsbG8gd29ybGQ=", "base64 is an encoding, not encryption", "rgb(12, 34, 56)", "#1a2b3c",
    "lorem ipsum dolor sit amet consectetur adipiscing elit", "user_42", "ada.lovelace",
    "Ada_Lovelace_1815", "q=accountable+surface", "utm_source=newsletter",
    "10 Downing Street, London SW1A 2AA", "221B Baker Street", "Apartment 5C",
    "WA", "US", "en-US", "America/Los_Angeles", "UTC+02:00", "14:30", "2:30 PM",
    "https://github.com/HarperZ9/accountable-surface/pull/24",
    "ISBN 978-0-306-40615-7", "phone 425 555 0142", "zip 98052-6399", "ext. 204",
    "Order history", "gift message: happy birthday!", "leave at back gate",
    "call before delivery", "fragile", "12 oz", "2 lbs", "1,000", "1,234,567", "99%",
    "The build finished in 12.3 seconds.", "Deploy notes for release 1.9.1",
    "Contact me via the form", "LinkedIn profile link", "see attached PDF",
    "Chapter 7: Accountability", "A-12", "B-7", "Gate 42",
]


def _control(html):
    ev = parse_page("http://127.0.0.1:1/f", f"<form>{html}</form>")
    return next(c for c in ev.controls if c.role == "textbox")


def test_corpora_are_the_size_the_design_names():
    assert len(MARKED_FIELDS) + len(PLANTED_VALUES) >= 60
    assert len(BENIGN_VALUES) >= 100


@pytest.mark.parametrize("html", MARKED_FIELDS)
def test_every_marked_field_is_recognised(html):
    assert secrets.field_markers(_control(html)), html


@pytest.mark.parametrize("value", PLANTED_VALUES, ids=range(len(PLANTED_VALUES)))
def test_every_planted_value_shape_is_recognised(value):
    assert secrets.value_shape(value) is not None


def test_benign_values_false_refusals_at_most_2_percent():
    refused = [v for v in BENIGN_VALUES if secrets.value_shape(v) is not None]
    assert len(refused) / len(BENIGN_VALUES) <= 0.02, refused


def test_innocent_fields_carry_no_marker():
    for html in ("<input name='title'>", "<label for='n'>Notes</label><textarea id='n'></textarea>",
                 "<input name='shipping_address'>", "<input name='email' type='email'>",
                 "<input name='settings'>", "<input name='author'>", "<input name='keyboard_layout'>"):
        assert secrets.field_markers(_control(html)) == [], html


def test_secret_in_an_innocent_field_is_refused_by_value_shape():
    notes = _control("<label for='n'>Notes</label><textarea id='n'></textarea>")
    assert secrets.field_markers(notes) == []
    assert secrets.value_shape("4111 1111 1111 1111") == "luhn"


def test_refusal_reasons_never_carry_the_value():
    control = _control("<label for='a'>Card number</label><input id='a' autocomplete='cc-number'>")
    reasons = secrets.field_markers(control)
    assert reasons and all("4111" not in r for r in reasons)
    assert "Card number" in " ".join(reasons)


def test_key_file_upload_is_refused():
    for name in ("id_rsa", "id_ed25519", "server.pem", "cert.p12", "store.pfx", ".env", ".env.local", "prod.key"):
        assert secrets.upload_refusal(name, b"") is not None, name
    assert secrets.upload_refusal("id_rsa.pub", b"ssh-ed25519 AAAA") is None
    assert secrets.upload_refusal("notes.txt", b"hello") is None
    assert secrets.upload_refusal("notes.txt", _key("ghp_", 36).encode()) == "content:key-prefix"


def test_redact_replaces_shapes_and_counts_them():
    text = f"card 4111 1111 1111 1111 and key {_key('ghp_', 36)} and ssn 123-45-6789 ok"
    red, count = secrets.redact(text)
    assert count == 3
    assert "4111" not in red and "ghp_" not in red and "6789" not in red
    assert "[redacted:luhn]" in red and red.endswith("ok")


def test_lexicon_is_stable_and_versioned():
    lex = secrets.lexicon()
    assert lex["version"] and "password" in lex["field_words"] and "cc-number" in lex["autocomplete"]
