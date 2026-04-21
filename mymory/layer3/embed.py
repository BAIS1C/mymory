"""Semantic retrieval via sentence-transformers.

Pickle store by default (one dict: note_path -> vector). LanceDB optional.
Re-embeds on mtime drift. Cosine similarity for ranking.
"""

from __future__ import annotations

import os
import pickle
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from mymory.core.note import Note
from mymory.core.vault import Vault


DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@dataclass
class EmbedStore:
    vectors: dict[str, np.ndarray] = field(default_factory=dict)
    embedded_at: dict[str, float] = field(default_factory=dict)
    model_name: str = DEFAULT_MODEL
    dim: int = 384

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "vectors": self.vectors,
                    "embedded_at": self.embedded_at,
                    "model_name": self.model_name,
                    "dim": self.dim,
                },
                f,
                protocol=pickle.HIGHEST_PROTOCOL,
            )

    @classmethod
    def load(cls, path: str) -> "EmbedStore":
        if not os.path.isfile(path):
            return cls()
        with open(path, "rb") as f:
            data = pickle.load(f)
        return cls(
            vectors=data.get("vectors", {}),
            embedded_at=data.get("embedded_at", {}),
            model_name=data.get("model_name", DEFAULT_MODEL),
            dim=data.get("dim", 384),
        )


class Embedder:
    """Lazy-loaded sentence-transformer wrapper."""

    _model: Any | None = None
    _model_name: str = ""

    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model_name = model_name

    def _ensure_model(self):
        if self._model is None or self._model_name != self.model_name:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            self._model_name = self.model_name
        return self._model

    def encode(self, texts: list[str]) -> np.ndarray:
        model = self._ensure_model()
        vecs = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return np.asarray(vecs, dtype=np.float32)

    def encode_one(self, text: str) -> np.ndarray:
        return self.encode([text])[0]


def store_path(vault: Vault) -> str:
    return os.path.join(vault.root, ".embed_cache", "embeddings.pkl")


def reembed_drift(vault: Vault, batch_size: int = 32, verbose: bool = False) -> dict[str, int]:
    """Re-embed any note whose mtime is newer than its last embed."""
    cfg = vault.manifest.embedding()
    model_name = cfg.get("model", DEFAULT_MODEL)
    store = EmbedStore.load(store_path(vault))
    if store.model_name != model_name or store.dim != int(cfg.get("dim", 384)):
        store = EmbedStore(model_name=model_name, dim=int(cfg.get("dim", 384)))

    embedder = Embedder(model_name)
    pending_paths: list[str] = []
    pending_texts: list[str] = []

    for note in vault.iter_notes(include_kks=False, include_graph=False, include_identity=False):
        try:
            mtime = os.path.getmtime(note.path)
        except FileNotFoundError:
            continue
        last = store.embedded_at.get(note.path, 0.0)
        if mtime > last or note.path not in store.vectors:
            pending_paths.append(note.path)
            pending_texts.append(_text_for_embedding(note))

    embedded = 0
    for i in range(0, len(pending_texts), batch_size):
        batch_paths = pending_paths[i : i + batch_size]
        batch_texts = pending_texts[i : i + batch_size]
        vecs = embedder.encode(batch_texts)
        now = time.time()
        for p, v in zip(batch_paths, vecs):
            store.vectors[p] = v
            store.embedded_at[p] = now
            embedded += 1
        if verbose:
            print(f"  embedded batch {i // batch_size + 1} ({embedded}/{len(pending_paths)})")

    # Drop vectors for deleted notes.
    removed = 0
    for p in list(store.vectors.keys()):
        if not os.path.isfile(p):
            del store.vectors[p]
            store.embedded_at.pop(p, None)
            removed += 1

    store.save(store_path(vault))
    return {"embedded": embedded, "removed": removed, "total": len(store.vectors)}


def semantic_search(
    vault: Vault,
    query: str,
    k: int = 10,
    threshold: float | None = None,
    wing: str | None = None,
) -> list[tuple[str, float]]:
    """Return top-k (note_path, score) tuples above threshold."""
    cfg = vault.manifest.embedding()
    model_name = cfg.get("model", DEFAULT_MODEL)
    thr = threshold if threshold is not None else float(cfg.get("threshold", 0.35))

    store = EmbedStore.load(store_path(vault))
    if not store.vectors:
        return []

    embedder = Embedder(model_name)
    qv = embedder.encode_one(query)

    paths = list(store.vectors.keys())
    if wing:
        wing_prefix = os.path.join(vault.root, wing) + os.sep
        paths = [p for p in paths if p.startswith(wing_prefix)]

    if not paths:
        return []

    mat = np.stack([store.vectors[p] for p in paths])
    scores = mat @ qv  # already unit-normalized
    order = np.argsort(-scores)
    results: list[tuple[str, float]] = []
    for idx in order[:k]:
        score = float(scores[idx])
        if score >= thr:
            results.append((paths[idx], score))
    return results


def _text_for_embedding(note: Note) -> str:
    """Build the text blob to embed. Title + tags + body snippet."""
    parts: list[str] = []
    if note.title:
        parts.append(note.title)
    if note.tags:
        parts.append(" ".join(note.tags))
    if note.entities:
        parts.append(" ".join(note.entities))
    parts.append(note.body[:4000])
    return "\n".join(parts)
