"""Embedding backends for VEDA's schedule entity-resolution index.

Production recommendation: BAAI/bge-m3 through FlagEmbedding.  VEDA does not
silently download multi-GB models in an offline/critical-infrastructure runtime;
set VEDA_EMBEDDING_BACKEND=bge-m3 and either provide VEDA_EMBEDDING_MODEL_PATH
or opt into model download with VEDA_ALLOW_MODEL_DOWNLOAD=1.

A deterministic hashing fallback keeps the application and test suite usable
without ML packages.  It is intentionally a fallback, not the recommended
production retriever.
"""
from __future__ import annotations

import hashlib
import importlib.util
import math
import os
import re
from array import array
from pathlib import Path
from typing import Iterable

_DIM = int(os.environ.get("VEDA_HASH_EMBED_DIM", "512"))
_BACKEND = os.environ.get("VEDA_EMBEDDING_BACKEND", "auto").strip().lower()
_MODEL = os.environ.get("VEDA_EMBEDDING_MODEL", "BAAI/bge-m3").strip()
_MODEL_PATH = os.environ.get("VEDA_EMBEDDING_MODEL_PATH", "").strip()
_RERANKER_MODEL = os.environ.get("VEDA_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3").strip()
_RERANKER_PATH = os.environ.get("VEDA_RERANKER_MODEL_PATH", "").strip()
_ALLOW_DOWNLOAD = os.environ.get("VEDA_ALLOW_MODEL_DOWNLOAD", "0").lower() in ("1", "true", "yes")


def _norm(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def pack_vector(v: Iterable[float]) -> bytes:
    return array("f", [float(x) for x in v]).tobytes()


def unpack_vector(blob: bytes | None) -> list[float]:
    if not blob:
        return []
    a = array("f")
    a.frombytes(blob)
    return list(a)


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    aa, bb = list(a), list(b)
    if not aa or not bb or len(aa) != len(bb):
        return 0.0
    dot = sum(x * y for x, y in zip(aa, bb))
    na = math.sqrt(sum(x * x for x in aa)) or 1.0
    nb = math.sqrt(sum(y * y for y in bb)) or 1.0
    return max(-1.0, min(1.0, dot / (na * nb)))


class HashEmbeddingBackend:
    """Dependency-free signed hashing over word + character n-grams.

    This preserves some robustness to `P-101A` vs `P101A` and spelling drift,
    but does not replace a learned semantic model.  Its purpose is graceful
    offline fallback.
    """
    name = "hash-ngram-v2"
    dim = _DIM

    @staticmethod
    def _features(text: str) -> list[str]:
        s = re.sub(r"\s+", " ", str(text or "").lower()).strip()
        words = re.findall(r"[a-z0-9][a-z0-9_./:-]*", s)
        feats = list(words)
        # Character ngrams are most useful on engineering identifiers. Applying
        # them to the entire multi-line activity document is expensive and adds
        # mostly noise. Keep all lexical words, plus identifier-focused ngrams
        # and lightweight word bigrams.
        for a,b in zip(words,words[1:]):
            feats.append(a+"::"+b)
        for token in words:
            compact=re.sub(r"[^a-z0-9]","",token)
            if len(compact)<3 or len(compact)>40 or not any(ch.isdigit() for ch in compact):
                continue
            for n in (3,4,5):
                feats.extend(compact[i:i+n] for i in range(max(0,len(compact)-n+1)))
        return feats

    def encode(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            v = [0.0] * self.dim
            for feat in self._features(text):
                h = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
                idx = int.from_bytes(h[:4], "little") % self.dim
                sign = 1.0 if h[4] & 1 else -1.0
                v[idx] += sign
            out.append(_norm(v))
        return out

    def encode_payload(self, texts: list[str]) -> dict:
        return {"dense": self.encode(texts), "sparse": [None for _ in texts]}

    def pair_scores(self, pairs: list[tuple[str, str]]) -> list[float] | None:
        return None

    def diagnostics(self) -> dict:
        return {"backend": self.name, "dim": self.dim, "reranker_loaded": False,
                "native_sparse": False, "device": "cpu"}


class BgeM3Backend:
    name = "bge-m3"

    def __init__(self, model_ref: str):
        from FlagEmbedding import BGEM3FlagModel  # type: ignore
        use_fp16 = os.environ.get("VEDA_EMBEDDING_FP16", "1").lower() not in ("0", "false", "no")
        self.use_fp16 = use_fp16
        self.model_ref = model_ref
        self.name = "bge-m3:" + str(model_ref)
        self._model = BGEM3FlagModel(model_ref, use_fp16=use_fp16)
        self._reranker = None
        # A dedicated cross-encoder is more accurate for the final Top-K than
        # bi-encoder similarity. Load it only when explicitly local/cached or
        # downloads are allowed, preserving VEDA's offline-safe behaviour.
        rref = _local_hf_ref(_RERANKER_MODEL, _RERANKER_PATH)
        if rref or _ALLOW_DOWNLOAD:
            try:
                from FlagEmbedding import FlagReranker  # type: ignore
                self._reranker = FlagReranker(
                    rref or _RERANKER_MODEL, query_max_length=256,
                    passage_max_length=int(os.environ.get("VEDA_RERANK_MAX_LENGTH", "512")),
                    use_fp16=use_fp16)
            except Exception:
                self._reranker = None
        self.dim = 1024

    def encode_payload(self, texts: list[str]) -> dict:
        if not texts:
            return {"dense": [], "sparse": []}
        batch = int(os.environ.get("VEDA_EMBEDDING_BATCH", "32"))
        # Activity documents are compact.  Keeping this far below BGE-M3's 8192
        # maximum materially reduces latency without truncating normal schedule context.
        max_len = int(os.environ.get("VEDA_EMBEDDING_MAX_LENGTH", "512"))
        out = self._model.encode(texts, batch_size=batch, max_length=max_len,
                                 return_dense=True, return_sparse=True,
                                 return_colbert_vecs=False)
        dense = [list(map(float, v)) for v in out["dense_vecs"]]
        sparse = []
        for obj in out.get("lexical_weights") or [None for _ in texts]:
            if obj is None:
                sparse.append(None)
            else:
                sparse.append({str(k): float(v) for k,v in dict(obj).items()})
        return {"dense": dense, "sparse": sparse}

    def encode(self, texts: list[str]) -> list[list[float]]:
        return self.encode_payload(texts)["dense"]

    def diagnostics(self) -> dict:
        dev = None
        try:
            dev = str(getattr(self._model, "devices", None) or getattr(self._model, "device", None) or "auto")
        except Exception:
            dev = "auto"
        return {"backend": self.name, "model_ref": str(self.model_ref), "dim": self.dim,
                "reranker_loaded": self._reranker is not None,
                "reranker_model": (_RERANKER_PATH or _RERANKER_MODEL) if self._reranker is not None else None,
                "native_sparse": True, "fp16": self.use_fp16, "device": dev,
                "embedding_max_length": int(os.environ.get("VEDA_EMBEDDING_MAX_LENGTH", "512")),
                "rerank_max_length": int(os.environ.get("VEDA_RERANK_MAX_LENGTH", "512"))}

    def pair_scores(self, pairs: list[tuple[str, str]]) -> list[float] | None:
        if not pairs:
            return []
        payload = [[q, d] for q, d in pairs]
        if self._reranker is not None:
            try:
                # Dedicated BGE reranker is a true cross-encoder over query +
                # activity document.  normalize=True only makes its own output
                # bounded; VEDA still calibrates final identity probability
                # independently from human decisions.
                result = self._reranker.compute_score(payload, normalize=True)
                if isinstance(result, (list, tuple)):
                    return [float(x) for x in result]
                if result is not None and len(payload) == 1:
                    return [float(result)]
            except Exception:
                pass
        # If the cross-encoder is not cached, BGE-M3's own dense+sparse+ColBERT
        # interaction is a strong local reranking fallback without another model.
        max_passage = int(os.environ.get("VEDA_RERANK_MAX_LENGTH", "512"))
        result = self._model.compute_score(
            payload, max_passage_length=max_passage,
            weights_for_different_modes=[0.42, 0.23, 0.35],
        )
        if isinstance(result, dict):
            vals = (result.get("colbert+sparse+dense") or result.get("dense") or [])
            return [float(x) for x in vals]
        if isinstance(result, (list, tuple)):
            return [float(x) for x in result]
        return None


def sparse_dot(a: dict | None, b: dict | None) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b): a,b=b,a
    return float(sum(float(v) * float(b.get(str(k), 0.0)) for k,v in a.items()))


_BACKEND_SINGLETON = None


def _local_hf_ref(model: str, explicit_path: str = "") -> str | None:
    if explicit_path:
        p = Path(explicit_path).expanduser()
        return str(p) if p.exists() else None
    # HuggingFace cache detection without importing transformers. A cached
    # snapshot is enough to safely let FlagEmbedding resolve the model name.
    home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    hub = home / "hub"
    slug = "models--" + model.replace("/", "--")
    return model if (hub / slug).exists() else None


def _local_model_ref() -> str | None:
    return _local_hf_ref(_MODEL, _MODEL_PATH)


def get_backend():
    global _BACKEND_SINGLETON
    if _BACKEND_SINGLETON is not None:
        return _BACKEND_SINGLETON

    if _BACKEND in ("hash", "hashed", "fallback"):
        _BACKEND_SINGLETON = HashEmbeddingBackend()
        return _BACKEND_SINGLETON

    can_import = importlib.util.find_spec("FlagEmbedding") is not None
    model_ref = _local_model_ref()
    should_try = _BACKEND in ("bge", "bge-m3") or (
        _BACKEND == "auto" and can_import and (model_ref or _ALLOW_DOWNLOAD)
    )
    if should_try and can_import:
        try:
            _BACKEND_SINGLETON = BgeM3Backend(model_ref or _MODEL)
            return _BACKEND_SINGLETON
        except Exception:
            # Critical-infrastructure-friendly failure mode: retrieval remains
            # available and the caller can inspect the backend name in results.
            pass

    _BACKEND_SINGLETON = HashEmbeddingBackend()
    return _BACKEND_SINGLETON
