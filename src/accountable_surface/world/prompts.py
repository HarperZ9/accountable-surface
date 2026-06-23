"""Prompts + world-state rendering for the pilots — the words handed to a model.

Kept separate from pilot.py so the prompt surface (system instructions, how the witnessed world
is rendered into the prompt, how a chat turn is assembled) is one readable unit, and the pilots +
the autopilot loop stay focused on driving the body. The pilots import these back.
"""
from __future__ import annotations

from .sight import describe_sight  # noqa: F401  (re-exported convenience for prompt builders)


_SYSTEM = (
    "You operate a body in a shared, accountable world. You are shown the WITNESSED state (real "
    "files, real content, real digests, the journal) — trust it over any memory of yours. Propose "
    "exactly ONE next action toward the goal as a single JSON object and nothing else, for example: "
    '{"reasoning": "the world has an image; I will describe what I see", "kind": "fs.write", '
    '"target": "notes.md", "content": "the full file content here", "justification": "record what I see"}. '
    "Use a real, NEW filename ending in .md for your notes; never overwrite an existing file or an "
    "image. The only action is fs.write — to extend a note, write its FULL new content (there is no "
    'append). When the goal is met, return {"done": true, "reasoning": "..."}. Every action is gated '
    "by an operator grant and verified by the body; propose only what is within the sandbox. If a "
    "write was refused or failed, read the witnessed result and adjust rather than repeating it. "
    "If the world shows you WHAT YOU SEE (a witnessed image — its SHAPE as a glyph grid and its "
    "COLOUR map), use both together to say plainly what it shows before you act. Make REAL progress each step: build on the files "
    "you have already written (shown in FILES and their content) toward the goal — first record what "
    "you observe, then in later steps extend or refine your own notes; never rewrite a file you just "
    "wrote unchanged. Return done only when the goal is genuinely met."
)


def _format_sight(s) -> str:
    """Present a witnessed image to the model: the SHAPE (glyph grid) and the COLOUR map together,
    so it can work out what the image actually shows — not just light and dark."""
    out = (f"\n{s.get('name', 'image')} ({s.get('width')}x{s.get('height')}, phash {s.get('phash')})"
           " — witnessed SHAPE (glyph grid, brighter = denser glyph):\n" + "\n".join(s.get("ascii", [])))
    col = s.get("color") or {}
    if col.get("map"):
        legend = ", ".join(f"{k}={v}" for k, v in col.get("legend", {}).items())
        out += ("\nwitnessed COLOUR — one letter per cell, where each colour sits (legend: " + legend + "):\n"
                + "\n".join(col["map"])
                + "\ndominant colours: " + ", ".join(f"{p['name']} {p['pct']}%" for p in col.get("palette", [])))
    return out + "\n"


def _world_brief(world_state, goal) -> str:
    """Render the witnessed world state into the prompt — the ground truth the mind reasons over."""
    files = ", ".join(f'{f["name"]} ({f["size"]}B)' for f in world_state.get("files", [])) or "(empty)"
    focus = world_state.get("focus") or {}
    journal = world_state.get("journal", [])
    recent = "; ".join(f'{e.get("kind")}: {e.get("summary", "")}' for e in journal[-4:]) or "(none yet)"
    grant = world_state.get("grant", {}).get("allowed_actions", [])
    sight = "".join(_format_sight(s) for s in world_state.get("sights", []))
    note_block = ""
    for name, content in (world_state.get("notes") or {}).items():
        note_block += f"\n--- your note {name} ---\n{content}\n"
    reel = world_state.get("reel")
    reel_block = ""
    if reel:
        reel_block = (f"\nMOVING MATERIAL: a {reel['count']}-frame reel is playing ({reel['fps']} fps). "
                      "One sampled frame (witnessed glyph grid):\n"
                      + "\n".join((reel.get("sample") or {}).get("ascii", [])) + "\n")
    return (f"GOAL: {goal}\nWORLD ROOT: {world_state.get('root', '')}\nFILES: {files}\n"
            f"FOCUS: {focus.get('name', '(none)')}{sight}{reel_block}\n"
            f"YOUR NOTES SO FAR:{note_block or ' (none yet)'}\n"
            f"RECENT WITNESSED JOURNAL: {recent}\nGRANTED ACTIONS: {grant}\n"
            "Propose the next action as one JSON object.")


_CHAT_SYSTEM = (
    "You and the operator share a world and are looking at the SAME thing — a witnessed view of "
    "their image: its SHAPE (a glyph grid) and its COLOUR (a map of where each colour sits, with a "
    "legend). Use BOTH together to work out what the image actually shows and to judge its quality. "
    "Talk with them about it: answer their messages, grounded in the witnessed view. Be brief, "
    "natural, and honest — say what you can and can't make out at this fidelity. You are not taking "
    "actions here, just discussing what you both see."
)


def _chat_brief(world_state) -> str:
    """What you both see, for the conversation — the witnessed grid(s), no action instructions."""
    parts = ["You and the operator are looking at this together:"]
    for s in world_state.get("sights", []) or []:
        parts.append(_format_sight(s))
    reel = world_state.get("reel")
    if reel:
        parts.append(f"\nA {reel['count']}-frame reel is also playing; one frame:\n"
                     + "\n".join((reel.get("sample") or {}).get("ascii", [])))
    if len(parts) == 1:
        parts.append(" (nothing is in view yet.)")
    return "".join(parts)


def _chat_messages(world_state, history, message):
    """The shared-view brief, then the recent conversation, then the operator's message."""
    msgs = [{"role": "user", "content": _chat_brief(world_state)}]
    for h in (history or [])[-8:]:
        msgs.append({"role": "assistant" if h.get("role") == "assistant" else "user",
                     "content": h.get("text", "")})
    msgs.append({"role": "user", "content": message})
    return msgs
