import pickle
from pathlib import Path
from typing import Optional

import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.tokenizer import tokenize as _tokenize

DATA_DIR = Path(__file__).parent.parent / "knowledge_data"
DATA_DIR.mkdir(exist_ok=True)

INDEX_VERSION = 2


class HybridSearch:
    def __init__(self):
        self.chunks: list[str] = []
        self.doc_ids: list[int] = []
        self.bm25: Optional[BM25Okapi] = None
        self.tfidf: Optional[TfidfVectorizer] = None
        self.tfidf_matrix = None
        self._load()

    def _save(self):
        data = {
            "chunks": self.chunks,
            "doc_ids": self.doc_ids,
            "version": INDEX_VERSION,
        }
        with open(DATA_DIR / "index.pkl", "wb") as f:
            pickle.dump(data, f)

    def _load(self):
        index_path = DATA_DIR / "index.pkl"
        if index_path.exists():
            with open(index_path, "rb") as f:
                data = pickle.load(f)
            self.chunks = data["chunks"]
            self.doc_ids = data["doc_ids"]
            self._rebuild_index()
            if data.get("version", 1) != INDEX_VERSION:
                self._save()

    def _rebuild_index(self):
        if not self.chunks:
            self.bm25 = None
            self.tfidf = None
            self.tfidf_matrix = None
            return

        tokenized = [_tokenize(c) for c in self.chunks]
        # BM25Okapi requires non-empty token lists; filter out empty ones
        tokenized = [t if t else [""] for t in tokenized]
        self.bm25 = BM25Okapi(tokenized)

        self.tfidf = TfidfVectorizer(tokenizer=_tokenize, token_pattern=None)
        self.tfidf_matrix = self.tfidf.fit_transform(self.chunks)

    def add_chunks(self, doc_id: int, chunks: list[str]):
        self.chunks.extend(chunks)
        self.doc_ids.extend([doc_id] * len(chunks))
        self._rebuild_index()
        self._save()

    def search(self, query: str, n_results: int = 5) -> list[dict]:
        if not self.chunks or not self.bm25 or not self.tfidf:
            return []

        tokenized_query = _tokenize(query)

        # BM25 scores
        bm25_scores = self.bm25.get_scores(tokenized_query)
        bm25_max = bm25_scores.max() if bm25_scores.max() > 0 else 1
        bm25_norm = np.clip(bm25_scores / bm25_max, 0, None)

        # TF-IDF cosine similarity
        query_vec = self.tfidf.transform([query])
        tfidf_scores = cosine_similarity(query_vec, self.tfidf_matrix).flatten()

        # Hybrid: weighted combination (BM25 0.5 + TF-IDF 0.5)
        combined = 0.5 * bm25_norm + 0.5 * tfidf_scores

        top_indices = combined.argsort()[::-1][:n_results]

        results = []
        for idx in top_indices:
            score = float(combined[idx])
            if score < 0.05:
                continue
            results.append({
                "content": self.chunks[idx],
                "doc_id": self.doc_ids[idx],
                "score": score,
            })
        return results

    def delete_by_doc_id(self, doc_id: int):
        pairs = [(c, d) for c, d in zip(self.chunks, self.doc_ids) if d != doc_id]
        if pairs:
            self.chunks, self.doc_ids = list(zip(*pairs))
            self.chunks = list(self.chunks)
            self.doc_ids = list(self.doc_ids)
        else:
            self.chunks = []
            self.doc_ids = []
        self._rebuild_index()
        self._save()


# Singleton instance
search_engine = HybridSearch()


def add_chunks(doc_id: int, chunks: list[str], embeddings=None):
    search_engine.add_chunks(doc_id, chunks)


def search(query_embedding=None, n_results: int = 5, query: str = "") -> list[dict]:
    return search_engine.search(query, n_results)


def delete_by_doc_id(doc_id: int):
    search_engine.delete_by_doc_id(doc_id)
