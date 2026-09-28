"""Secret refusal: passwords, keys, tokens, card and bank numbers, government IDs.

The tool never types one of these into a field, even when a person asks; the
person types it. Two independent checks run on every text-carrying step:

- field markers, read from the target control in the page evidence, never from
  the caller's description of it: `type=password`, an autocomplete hint for a
  password, one-time code, or card field, or a name, id, label, placeholder, or
  aria-label word from the secret vocabulary;
- value shapes, read from the value itself, so a secret typed into an innocent
  field is refused too: a Luhn-valid card number, an IBAN passing mod-97, a US
  SSN, a US ABA routing number, a known key or token prefix, a JWT, a PEM
  private key block, or a long mixed-class token with high character entropy.

Output discipline: a reason names the rule and the field label, never the value.
Nothing here stores, hashes, or returns the value, because a digest of a short
secret can be reversed by guessing.

Limit: lexical and structural. A secret in a shape this module does not know, in
a field with no marker, passes it.
"""

from __future__ import annotations

import math
import re
from collections import Counter

VERSION = "1"
AUTOCOMPLETE = frozenset({
    "current-password", "new-password", "one-time-code", "cc-number", "cc-csc",
    "cc-exp", "cc-exp-month", "cc-exp-year",
})
FIELD_WORDS = frozenset({
    "password", "passwd", "pwd", "passcode", "passphrase", "otp", "totp", "mfa", "2fa",
    "cvv", "cvv2", "cvc", "csc", "card", "ssn", "secret", "token", "pin", "iban", "routing",
    "swift", "bic", "passport", "tin", "recovery", "mnemonic", "apikey",
})
FIELD_COMPOUNDS = (
    "password", "passwd", "cardnumber", "creditcard", "apikey", "privatekey", "seedphrase",
    "securitycode", "accountnumber", "sortcode", "taxid", "nationalid", "driverslicense",
    "socialsecurity", "onetimecode", "accesstoken", "authtoken", "clientsecret", "bankaccount",
)
KEY_PATTERN = re.compile(
    r"(?<![\w-])(sk-[A-Za-z0-9_-]{16,}|sk_live_\w{8,}|rk_live_\w{8,}|gh[pousr]_\w{20,}"
    r"|github_pat_\w{20,}|glpat-[\w-]{16,}|xox[abprs]-[\w-]{10,}|A[KS]IA[0-9A-Z]{16}"
    r"|AIza[\w-]{30,})")
JWT_PATTERN = re.compile(r"(?<![\w-])eyJ[\w-]{4,}\.[\w-]{4,}\.[\w-]{4,}")
PEM_PATTERN = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
IBAN_PATTERN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b")
SSN_PATTERN = re.compile(r"(?<!\d)(\d{3})-(\d{2})-(\d{4})(?!\d)")
KEY_FILE_NAMES = frozenset({
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".env", ".npmrc", ".pypirc", ".netrc",
    "credentials", "credentials.json",
})
KEY_FILE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx", ".ppk")
ENTROPY_MIN_LEN = 32
ENTROPY_BITS = 4.3


def _words(text: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return [w for w in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if w]


def _label_hits(label: str) -> list[str]:
    words = _words(label)
    joined = "".join(words)
    hits = sorted({w for w in words if w in FIELD_WORDS})
    hits += sorted({c for c in FIELD_COMPOUNDS if c in joined and c not in hits})
    return hits


def field_markers(control) -> list[str]:
    """Why this control is a secret field, as reasons naming the field. Empty
    when no marker is present."""
    if control is None:
        return []
    label = control.name or control.attr("name") or control.ref
    reasons = []
    if control.input_type == "password":
        reasons.append(f"field {label!r} is marked type=password")
    hint = control.attr("autocomplete").lower().split()
    reasons += [f"field {label!r} has autocomplete={h}" for h in hint if h in AUTOCOMPLETE]
    sources = [control.name] + [control.attr(k) for k in ("id", "name", "placeholder", "aria-label")]
    words = sorted({w for s in sources if s for w in _label_hits(s)})
    if words:
        reasons.append(f"field {label!r} is named with {', '.join(words)}")
    return reasons


def _luhn(digits: str) -> bool:
    total = 0
    for index, ch in enumerate(reversed(digits)):
        d = int(ch)
        if index % 2:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return total % 10 == 0


def _card(text: str) -> bool:
    for match in CARD_PATTERN.finditer(text):
        digits = re.sub(r"[ -]", "", match.group())
        if 13 <= len(digits) <= 19 and digits[0] in "23456" and _luhn(digits):
            return True
    return False


def _iban(text: str) -> bool:
    for match in IBAN_PATTERN.finditer(text):
        raw = match.group().replace(" ", "")
        moved = raw[4:] + raw[:4]
        numeric = "".join(str(int(ch, 36)) for ch in moved)
        if 15 <= len(raw) <= 34 and int(numeric) % 97 == 1:
            return True
    return False


def _ssn(text: str) -> bool:
    for area, group, serial in SSN_PATTERN.findall(text):
        if area not in ("000", "666") and not area.startswith("9") and group != "00" and serial != "0000":
            return True
    return False


def _aba(value: str) -> bool:
    digits = value.strip()
    if not re.fullmatch(r"\d{9}", digits):
        return False
    prefix = int(digits[:2])
    if not (prefix <= 12 or 21 <= prefix <= 32 or 61 <= prefix <= 72 or prefix == 80):
        return False
    d = [int(c) for c in digits]
    return (3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])) % 10 == 0


def _entropy(token: str) -> float:
    counts = Counter(token)
    return -sum(n / len(token) * math.log2(n / len(token)) for n in counts.values())


def _high_entropy(text: str) -> bool:
    for token in text.split():
        if len(token) < ENTROPY_MIN_LEN or "://" in token:
            continue
        classes = sum(bool(re.search(p, token)) for p in (r"[a-z]", r"[A-Z]", r"\d"))
        if classes == 3 and _entropy(token) >= ENTROPY_BITS:
            return True
    return False


def value_shape(value: str) -> str | None:
    """The name of the secret shape the value carries, or None. Never the value."""
    if not isinstance(value, str) or not value:
        return None
    checks = (("pem-private-key", PEM_PATTERN.search), ("jwt", JWT_PATTERN.search),
              ("key-prefix", KEY_PATTERN.search), ("luhn", _card), ("iban", _iban),
              ("ssn", _ssn), ("aba-routing", _aba), ("high-entropy", _high_entropy))
    for name, check in checks:
        if check(value):
            return name
    return None


def upload_refusal(filename: str, content: bytes | None) -> str | None:
    """Why an upload is refused: a key or env file by name, or key and token
    shapes in its content. None when neither holds."""
    base = filename.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if base in KEY_FILE_NAMES or base.startswith(".env.") or base.endswith(KEY_FILE_SUFFIXES):
        return "name:key-or-env-file"
    text = (content or b"").decode("utf-8", errors="ignore")
    for name, pattern in (("pem-private-key", PEM_PATTERN), ("jwt", JWT_PATTERN), ("key-prefix", KEY_PATTERN)):
        if pattern.search(text):
            return f"content:{name}"
    return None


def redact(text: str) -> tuple[str, int]:
    """Replace every recognised secret span with `[redacted:<shape>]` before the
    text is stored anywhere. Returns the text and the number of spans replaced."""
    count = 0

    def sub(pattern, shape, keep=lambda s: True):
        nonlocal text, count

        def repl(match):
            nonlocal count
            if not keep(match.group()):
                return match.group()
            count += 1
            return f"[redacted:{shape}]"
        text = pattern.sub(repl, text)

    sub(re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(-----END [A-Z0-9 ]*PRIVATE KEY-----|$)", re.S),
        "pem-private-key")
    sub(JWT_PATTERN, "jwt")
    sub(KEY_PATTERN, "key-prefix")
    sub(CARD_PATTERN, "luhn", _card)
    sub(IBAN_PATTERN, "iban", _iban)
    sub(SSN_PATTERN, "ssn", _ssn)
    return text, count


SCRIPT_VALUE_ACCESS = re.compile(
    r"\.value\b|setattribute\(\s*['\"]value|\.fill\(|\.type\(|\.press\(|sendkeys|inserttext"
    r"|\.presssequentially\(", re.I)
_REDACTED = re.compile(r"\[redacted:([a-z-]+)\]")


def script_refusal(script: str) -> str | None:
    """Why a script is refused under R4, or None. A fill into a secret field is
    refused, so a script is too when it reads or writes a value and names a
    secret field, or when it carries a secret-shaped literal. The reason names
    the field words or the shape, never the value."""
    if not isinstance(script, str) or not script:
        return None
    shapes = sorted(set(_REDACTED.findall(redact(script)[0])))
    if shapes:
        return f"the script carries a value shaped like a {', '.join(shapes)}"
    words = _label_hits(script)
    if words and SCRIPT_VALUE_ACCESS.search(script):
        return f"the script reads or writes the value of a secret field ({', '.join(words)})"
    return None


def lexicon() -> dict:
    return {"version": VERSION, "autocomplete": sorted(AUTOCOMPLETE), "field_words": sorted(FIELD_WORDS),
            "field_compounds": list(FIELD_COMPOUNDS), "key_pattern": KEY_PATTERN.pattern,
            "entropy": [ENTROPY_MIN_LEN, ENTROPY_BITS], "key_files": sorted(KEY_FILE_NAMES),
            "key_suffixes": list(KEY_FILE_SUFFIXES),
            "script": {"write_markers": SCRIPT_VALUE_ACCESS.pattern}}
