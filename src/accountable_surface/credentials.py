"""The one door a credential enters through.

Secrets live only in the environment, named by variable. They never appear in
source, in a Plan, in an Observation, in the journal, or in an error message: a
raise names the variable that is missing and never a value. An effector that needs
auth calls `require_secret` at the moment of the call and puts the result in a
request header, so the secret never reaches a URL, which is the part the surface
witnesses.

The semantics here match gather's `credentials.py`, which is the worked example of
the pattern in this ecosystem. The two repositories share no code, so this is a
deliberate re-statement rather than an import.
"""

from __future__ import annotations

import os


class MissingCredential(RuntimeError):
    """A required credential was not present in the environment."""


def require_secret(name: str) -> str:
    """The named environment variable's value, or raise `MissingCredential`.

    Rejects a value carrying CR or LF: a stray newline (from `export TOKEN=$(cat
    file)`, say) would split or inject a request header.
    """
    value = os.environ.get(name)
    if not value or not value.strip():
        raise MissingCredential(f"missing required credential in environment: {name}")
    if "\r" in value or "\n" in value:
        raise MissingCredential(f"credential in environment variable {name} contains a newline")
    return value


def has_secret(name: str) -> bool:
    """Whether the named credential is present, without revealing it.

    Presence only. This is what a status surface is allowed to report; the value is
    not available to anything but the effector making the call.
    """
    return bool(os.environ.get(name))
