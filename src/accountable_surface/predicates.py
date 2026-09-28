"""Post-condition predicates (S7): pure functions, stdlib only, no I/O.

Each takes the post-condition, the driver's own after-snapshot, and the
independent reader's after-evidence, and returns `(verdict, detail,
independence)`:

- `verified`: the post-condition is settled true and every `forbid` is settled
  absent;
- `drift`: settled false, or a forbidden condition (an alert, an error text) is
  present;
- `unverifiable`: nothing settled it (no readback, an error status, an
  ambiguous name, a kind this build cannot check).

Independence is recorded honestly. `url_is`, `title_is`, and `field_value_is`
read the snapshot of the driver that acted (`same-driver`). `text_present` and
the element kinds read a separate GET (`separate-reader`). Neither escapes a
driver and a server that both lie; only a separate channel would.
"""

from __future__ import annotations

VERSION = "1"
VERDICTS = ("verified", "drift", "unverifiable")


def meet(verdicts) -> str:
    """The step verdict: any drift is drift, else any unverifiable is
    unverifiable, else verified. Empty input settles nothing."""
    verdicts = list(verdicts)
    if not verdicts:
        return "unverifiable"
    if "drift" in verdicts:
        return "drift"
    return "unverifiable" if "unverifiable" in verdicts else "verified"


def _url(post, driver, reader):
    ok = str(driver.get("url", "")).rstrip("/") == str(post.get("value", "")).rstrip("/")
    return ("verified" if ok else "drift"), "url " + ("matches" if ok else "differs"), "same-driver"


def _title(post, driver, reader):
    ok = driver.get("title") == post.get("value")
    return ("verified" if ok else "drift"), "title " + ("matches" if ok else "differs"), "same-driver"


def _field(post, driver, reader):
    name = (post.get("control") or {}).get("name")
    fields = driver.get("fields") or {}
    if name not in fields:
        return "unverifiable", f"field {name!r} is not in the after snapshot", "same-driver"
    ok = str(fields[name]) == str(post.get("value", ""))
    return ("verified" if ok else "drift"), f"field {name!r} " + ("holds" if ok else "does not hold") + " the planned value", "same-driver"


def _settled(reader) -> str | None:
    if reader is None:
        return "no readback was captured"
    if reader.http_status != 200:
        return f"readback status {reader.http_status}"
    return None


def _text(post, driver, reader):
    why = _settled(reader)
    if why:
        return "unverifiable", why, "separate-reader"
    ok = str(post.get("value", "")) in reader.text
    return ("verified" if ok else "drift"), "text " + ("present" if ok else "absent") + " in the readback", "separate-reader"


def _count(reader, control) -> int:
    name, role = (control or {}).get("name"), (control or {}).get("role")
    return sum(1 for c in reader.controls if c.name == name and (not role or c.role == role))


def _appears(post, driver, reader):
    why = _settled(reader)
    if why:
        return "unverifiable", why, "separate-reader"
    n = _count(reader, post.get("control"))
    if n > 1:
        return "unverifiable", "the name is carried by more than one control", "separate-reader"
    return ("verified" if n == 1 else "drift"), f"{n} matching control(s)", "separate-reader"


def _disappears(post, driver, reader):
    why = _settled(reader)
    if why:
        return "unverifiable", why, "separate-reader"
    n = _count(reader, post.get("control"))
    return ("verified" if n == 0 else "drift"), f"{n} matching control(s)", "separate-reader"


PREDICATES = {"url_is": _url, "title_is": _title, "field_value_is": _field, "text_present": _text,
              "element_appears": _appears, "element_disappears": _disappears}


def _forbidden(forbid, reader) -> tuple[str, str] | None:
    if not forbid:
        return None
    if _settled(reader):
        return "unverifiable", "a forbid list needs a settled readback"
    for item in forbid:
        role, text = item.get("role"), item.get("text")
        if role and f"role:{role}" in reader.markers:
            return "drift", f"forbidden role {role!r} present"
        if text and str(text) in reader.text:
            return "drift", "forbidden text present"
    return None


def forbidden_present(post, reader_after) -> bool:
    """A forbidden condition is settled present: it ends a settle wait as drift."""
    blocked = _forbidden((post or {}).get("forbid"), reader_after) if isinstance(post, dict) else None
    return bool(blocked and blocked[0] == "drift")


def check(post, *, driver_after: dict, reader_after, timed_out: bool = False) -> tuple[str, str, str]:
    """The verdict for one post-condition. `timed_out` says a settle_ms wait ran
    out: then anything short of verified is unverifiable, never a settled drift,
    unless a forbidden condition is present, which settles drift on its own."""
    if not isinstance(post, dict) or post.get("kind") not in PREDICATES:
        kind = post.get("kind") if isinstance(post, dict) else None
        return "unverifiable", f"no predicate for {kind!r}", "none"
    verdict, detail, independence = PREDICATES[post["kind"]](post, driver_after or {}, reader_after)
    blocked = _forbidden(post.get("forbid"), reader_after)
    if blocked and verdict != "drift":
        verdict, detail = blocked[0], detail + "; " + blocked[1]
    if timed_out and verdict != "verified" and not forbidden_present(post, reader_after):
        verdict, detail = "unverifiable", detail + f"; not settled within {post.get('settle_ms')} ms"
    return verdict, detail, independence
