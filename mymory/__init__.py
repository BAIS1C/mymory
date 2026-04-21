"""MyMory: governed memory vault substrate.

Wings, corridors, scheduled hygiene. Agentic plus offline. MyMories plus
MemPalace plus Graphify hybrid.
"""

__version__ = "0.1.0"

from mymory.core.manifest import Manifest, load_manifest
from mymory.core.note import Note, parse_note, serialize_note
from mymory.core.vault import Vault

__all__ = [
    "__version__",
    "Manifest",
    "load_manifest",
    "Note",
    "parse_note",
    "serialize_note",
    "Vault",
]
