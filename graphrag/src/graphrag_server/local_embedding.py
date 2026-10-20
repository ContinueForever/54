"""Local lightweight embedding provider for GraphRAG.

Uses scikit-learn TF-IDF so that no sentence-transformers or network access is required.
"""
from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer


def _vectorizer_path() -> Path:
    """持久化路径：$GRAPHRAG_ROOT/output/tfidf_vectorizer.pkl（缺省为 cwd/output/）。"""
    root = Path(os.environ.get("GRAPHRAG_ROOT", ".")).resolve()
    return root / "output" / "tfidf_vectorizer.pkl"


class LocalTfidfEmbeddingModel:
    """A tiny, fully-offline embedding model backed by TF-IDF.

    索引时拟合好的 vectorizer 会持久化到 output/tfidf_vectorizer.pkl，
    查询时自动加载，保证索引/查询向量维度一致。
    """

    def __init__(self, name: str, config, cache=None, **kwargs: Any):
        self.name = name
        self.config = config
        self.cache = cache
        self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
        self._fitted = False
        self._fallback_dim = 256
        self._load_vectorizer()

    def _load_vectorizer(self):
        path = _vectorizer_path()
        if not path.exists():
            return
        try:
            with open(path, "rb") as f:
                self.vectorizer = pickle.load(f)
            self._fitted = True
        except Exception:
            self._fitted = False

    def _save_vectorizer(self):
        try:
            path = _vectorizer_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                pickle.dump(self.vectorizer, f)
        except Exception:
            pass

    def _fit_once(self, corpus: list[str]):
        if self._fitted or not corpus:
            return
        try:
            self.vectorizer.fit(corpus)
            self._fitted = True
            self._save_vectorizer()
        except Exception:
            pass

    def _embed(self, text: str) -> list[float]:
        if not text:
            return [0.0] * self._fallback_dim
        if self._fitted:
            vec = self.vectorizer.transform([text])
            arr = vec.toarray().flatten().tolist()
        else:
            arr = self._hash_embedding(text)
        norm = self._l2_norm(arr)
        if norm > 0:
            arr = [x / norm for x in arr]
        else:
            # 中文/未见词汇查询在 char_wb 2-4 ngram 下可能产生全零向量，
            # 回退到字符级 hash 向量（维度与索引向量一致），避免中文检索相似度恒为 0。
            dim = getattr(self.vectorizer, "n_features_", self._fallback_dim) or self._fallback_dim
            arr = self._hash_embedding(text, dim)
        return arr

    def _hash_embedding(self, text: str, dim: int | None = None) -> list[float]:
        dim = dim or self._fallback_dim
        arr = [0.0] * dim
        for i, ch in enumerate(text):
            arr[(hash(ch) + i) % dim] += 1.0
        return arr

    @staticmethod
    def _l2_norm(arr: list[float]) -> float:
        return sum(x * x for x in arr) ** 0.5

    def embed(self, text: str, **kwargs: Any) -> list[float]:
        return self._embed(text)

    def embed_batch(self, text_list: list[str], **kwargs: Any) -> list[list[float]]:
        if not self._fitted:
            self._fit_once(text_list)
        return [self._embed(t) for t in text_list]

    async def aembed(self, text: str, **kwargs: Any) -> list[float]:
        return self._embed(text)

    async def aembed_batch(self, text_list: list[str], **kwargs: Any) -> list[list[float]]:
        if not self._fitted:
            self._fit_once(text_list)
        return [self._embed(t) for t in text_list]
