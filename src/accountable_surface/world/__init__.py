"""The shared world -- a live, embodied, accountable operating surface.

The body (AccountableSurface) alive in a world the operator co-inhabits: the model proposes an
action, the gate decides, the native hands act on real material, and the receipt witnesses it --
streamed live. Compose-only; this subsystem reinvents none of the body's organs.
"""
from .session import WorldSession, WorldStep

__all__ = ["WorldSession", "WorldStep"]
