"""Detectors the policy check runs over page and window evidence.

Each module is lexical or structural, pure (no I/O, no clock), and exposes a
`lexicon()` whose digest lands in every receipt, so a reader can name the exact
marker set that decided a step.
"""
