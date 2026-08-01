from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from app.core.config import settings
from app.projects.context import ProjectContext

INDEX_PATH = ".aisync/vector_index.json"
INDEX_VERSION = 2
SUPPORTED_SUFFIXES = (".md", ".txt", ".yaml", ".yml", ".json")
IGNORED_PREFIXES = (".aisync/", ".vectordb/")
CHUNK_CHARS = 900
CHUNK_OVERLAP = 140
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
EMBEDDING_BATCH_SIZE = 32
_PERSISTENT_CLIENT: Any = None
_PERSISTENT_CLIENT_LOADED = False


def _persistent_client_class() -> Any:
    global _PERSISTENT_CLIENT, _PERSISTENT_CLIENT_LOADED
    if not _PERSISTENT_CLIENT_LOADED:
        try:
            from chromadb import PersistentClient

            _PERSISTENT_CLIENT = PersistentClient
        except Exception:
            _PERSISTENT_CLIENT = None
        _PERSISTENT_CLIENT_LOADED = True
    return _PERSISTENT_CLIENT


class NullVectorStore:
    async def query(self, text: str, collections: list[str] | None = None, top_k: int = 10) -> list[dict]:
        return []

    async def index_file(self, file_path: str) -> None:
        return None

    async def query_exact_terms(
        self,
        terms: list[str],
        collections: list[str] | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        return []

    async def check_consistency(self, new_content: str) -> list[dict]:
        return []


class ProjectVectorStore(NullVectorStore):
    def __init__(self, context: ProjectContext) -> None:
        self.context = context

    async def query(self, text: str, collections: list[str] | None = None, top_k: int = 10) -> list[dict]:
        query = text.strip()
        if not query:
            return []
        if self._use_chroma_backend():
            chroma_results = await self._query_chroma(query, collections=collections, top_k=top_k)
            if chroma_results:
                return chroma_results
        index = await self._load_or_build_index()
        query_vector = self._vectorize(query)
        query_embedding = await self._embed_text(query)
        results: list[dict[str, Any]] = []
        collection_set = set(collections or [])

        for chunk in index.get("chunks", []):
            if collection_set and chunk.get("collection") not in collection_set:
                continue
            lexical_score = self._cosine(query_vector, chunk.get("vector") or chunk.get("lexical_vector") or {})
            embedding_score = 0.0
            chunk_embedding = chunk.get("embedding_vector")
            if query_embedding and isinstance(chunk_embedding, list):
                embedding_score = self._cosine(query_embedding, chunk_embedding)
            score = self._combined_score(lexical_score, embedding_score)
            if score <= 0:
                continue
            results.append({
                "path": chunk["path"],
                "collection": chunk.get("collection", "other"),
                "content": chunk["text"],
                "score": round(score, 4),
                "chunk_id": chunk["id"],
            })

        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:top_k]

    async def query_exact_terms(
        self,
        terms: list[str],
        collections: list[str] | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        normalized_terms = self._normalize_exact_terms(terms)
        if not normalized_terms:
            return []

        index = await self._load_or_build_index()
        collection_set = set(collections or [])
        results: list[dict[str, Any]] = []
        for chunk in index.get("chunks", []):
            if collection_set and chunk.get("collection") not in collection_set:
                continue
            content = str(chunk.get("text") or "")
            path = str(chunk.get("path") or "")
            score, matched_terms = self._exact_match_score(content, path, normalized_terms)
            if score <= 0:
                continue
            results.append({
                "path": path,
                "collection": chunk.get("collection", "other"),
                "content": content,
                "score": round(score, 4),
                "chunk_id": chunk["id"],
                "match_type": "exact",
                "matched_terms": matched_terms,
            })

        results.sort(
            key=lambda item: (
                item["score"],
                -len(str(item.get("content") or "")),
                str(item.get("path") or ""),
            ),
            reverse=True,
        )
        return results[:top_k]

    async def index_file(self, file_path: str) -> None:
        await self.rebuild()

    async def status(self) -> dict[str, Any]:
        files = await self._eligible_files()
        signatures = await self._file_signatures(files)
        exists = await self.context.exists(INDEX_PATH)
        if not exists:
            return {
                "status": "missing",
                "indexed": False,
                "stale": True,
                "files": len(files),
                "chunks": 0,
                "collections": {},
                "backend": self._backend_name(),
                "chroma_available": self._chroma_available(),
                "index_path": INDEX_PATH,
            }

        try:
            data = await self.context.read_json(INDEX_PATH)
        except Exception:
            return {
                "status": "invalid",
                "indexed": False,
                "stale": True,
                "files": len(files),
                "chunks": 0,
                "collections": {},
                "backend": self._backend_name(),
                "chroma_available": self._chroma_available(),
                "index_path": INDEX_PATH,
            }

        chunks = data.get("chunks", []) if isinstance(data, dict) else []
        collections: dict[str, int] = {}
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            collection = str(chunk.get("collection") or "other")
            collections[collection] = collections.get(collection, 0) + 1

        stale = not (
            isinstance(data, dict)
            and data.get("version") == INDEX_VERSION
            and data.get("files") == files
            and data.get("signatures") == signatures
        )
        return {
            "status": "stale" if stale else "ready",
            "indexed": True,
            "stale": stale,
            "files": len(files),
            "indexed_files": len(data.get("files", [])) if isinstance(data, dict) else 0,
            "chunks": len(chunks) if isinstance(chunks, list) else 0,
            "collections": collections,
            "embedding_model": data.get("embedding_model") if isinstance(data, dict) else None,
            "embedding_configured": bool(settings.embedding_model_name),
            "backend": self._backend_name(),
            "chroma_available": self._chroma_available(),
            "index_path": INDEX_PATH,
        }

    async def rebuild(self) -> dict[str, Any]:
        files = await self._eligible_files()
        payload = await self._build_index_payload(files)
        await self.context.write_json(INDEX_PATH, payload)
        if self._use_chroma_backend():
            await self._sync_chroma_index(payload)
        return payload

    async def _load_or_build_index(self) -> dict[str, Any]:
        if await self.context.exists(INDEX_PATH):
            try:
                data = await self.context.read_json(INDEX_PATH)
                current_files = await self._eligible_files()
                current_signatures = await self._file_signatures(current_files)
                if (
                    isinstance(data, dict)
                    and data.get("version") == INDEX_VERSION
                    and data.get("embedding_model") == settings.embedding_model_name
                    and data.get("files") == current_files
                    and data.get("signatures") == current_signatures
                ):
                    return data
            except Exception:
                pass
        return await self.rebuild()

    async def _build_index_payload(self, files: list[str]) -> dict[str, Any]:
        chunks: list[dict[str, Any]] = []
        signatures: dict[str, str] = {}
        chunk_specs: list[dict[str, Any]] = []
        for file_path in files:
            try:
                content = await self.context.read_text(file_path)
            except Exception:
                continue
            content = content.lstrip("\ufeff")
            signatures[file_path] = hashlib.sha1(content.encode("utf-8")).hexdigest()
            for index, text in enumerate(self._chunk_text(content)):
                chunk_id = hashlib.sha1(f"{file_path}:{index}:{text}".encode("utf-8")).hexdigest()
                chunk_specs.append({
                    "id": chunk_id,
                    "path": file_path,
                    "collection": self._collection_for(file_path),
                    "text": text,
                    "vector": self._vectorize(text),
                })

        embedding_vectors = await self._embed_chunks([spec["text"] for spec in chunk_specs])
        for index, spec in enumerate(chunk_specs):
            spec["embedding_vector"] = embedding_vectors[index] if index < len(embedding_vectors) else None
            chunks.append(spec)

        return {
            "version": INDEX_VERSION,
            "embedding_model": settings.embedding_model_name,
            "files": files,
            "signatures": signatures,
            "chunks": chunks,
            "backend": self._backend_name(),
        }

    async def _file_signatures(self, files: list[str]) -> dict[str, str]:
        signatures: dict[str, str] = {}
        for file_path in files:
            try:
                content = await self.context.read_text(file_path)
            except Exception:
                continue
            signatures[file_path] = hashlib.sha1(content.lstrip("\ufeff").encode("utf-8")).hexdigest()
        return signatures

    async def _eligible_files(self) -> list[str]:
        files: list[str] = []
        for file_path in await self.context.list_files():
            normalized = file_path.replace("\\", "/")
            if normalized.startswith(IGNORED_PREFIXES):
                continue
            if normalized.endswith(SUPPORTED_SUFFIXES):
                files.append(normalized)
        return sorted(files)

    def _collection_for(self, file_path: str) -> str:
        root = file_path.split("/", 1)[0]
        if root in {"chapters", "characters", "world", "plot"}:
            return root
        return "other"

    def _chunk_text(self, content: str) -> list[str]:
        text = content.lstrip("\ufeff").strip()
        if not text:
            return []
        if len(text) <= CHUNK_CHARS:
            return [text]
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(len(text), start + CHUNK_CHARS)
            chunks.append(text[start:end].strip())
            if end == len(text):
                break
            start = max(end - CHUNK_OVERLAP, start + 1)
        return [chunk for chunk in chunks if chunk]

    def _tokens(self, text: str) -> list[str]:
        normalized = text.lower()
        base = TOKEN_RE.findall(normalized)
        cjk = [char for char in normalized if "\u4e00" <= char <= "\u9fff"]
        bigrams = [f"{cjk[index]}{cjk[index + 1]}" for index in range(len(cjk) - 1)]
        return base + bigrams

    def _vectorize(self, text: str) -> dict[str, float]:
        counts = Counter(self._tokens(text))
        if not counts:
            return {}
        length = math.sqrt(sum(value * value for value in counts.values())) or 1.0
        return {token: value / length for token, value in counts.items()}

    def _cosine(self, left: Any, right: Any) -> float:
        if not left or not right:
            return 0.0
        if isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                return 0.0
            return sum(float(a) * float(b) for a, b in zip(left, right))
        if len(left) > len(right):
            left, right = right, left
        return sum(value * float(right.get(token, 0.0)) for token, value in left.items())

    def _combined_score(self, lexical_score: float, embedding_score: float) -> float:
        if embedding_score > 0:
            return round(0.35 * lexical_score + 0.65 * embedding_score, 4)
        return round(lexical_score, 4)

    def _normalize_exact_terms(self, terms: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_term in terms:
            term = re.sub(r"\s+", "", str(raw_term or "").strip().lower())
            if len(term) < 2 or len(term) > 24 or term in seen:
                continue
            seen.add(term)
            normalized.append(term)
        return normalized[:16]

    def _exact_match_score(self, content: str, path: str, terms: list[str]) -> tuple[float, list[str]]:
        lowered_content = content.lower()
        compact_content = re.sub(r"\s+", "", lowered_content)
        compact_path = re.sub(r"\s+", "", path.lower())
        leading_content = compact_content[:240]
        first_line = re.sub(r"^[#\-*+>\s]+", "", lowered_content.splitlines()[0] if lowered_content else "")
        compact_first_line = re.sub(r"\s+", "", first_line)
        stripped_content = lowered_content.lstrip()
        has_document_title = bool(
            re.match(r"^#{1,6}\s+", stripped_content)
            or re.match(r"^(?:name|title|姓名|名称)\s*[:：]", stripped_content)
        )
        score = 0.0
        matched_terms: list[str] = []

        for term in terms:
            content_count = compact_content.count(term)
            path_match = term in compact_path
            if not content_count and not path_match:
                continue
            matched_terms.append(term)
            term_weight = 1.0 + min(len(term), 8) / 8
            score += min(content_count, 3) * term_weight
            if path_match:
                score += 4.0 * term_weight
            if has_document_title and term in compact_first_line:
                score += 6.0 * term_weight
            elif term in leading_content:
                score += 3.0 * term_weight

        return score, matched_terms

    def _backend_name(self) -> str:
        return settings.vector_backend if settings.vector_backend in {"local", "chroma"} else "local"

    def _use_chroma_backend(self) -> bool:
        return self._backend_name() == "chroma" and self._chroma_available()

    def _chroma_available(self) -> bool:
        return _persistent_client_class() is not None and bool(settings.embedding_model_name)

    def _chroma_path(self) -> Path:
        return self.context.root / settings.chroma_persist_path

    def _chroma_collection_name(self) -> str:
        return settings.chroma_collection_name or "aisync_chunks"

    async def _sync_chroma_index(self, payload: dict[str, Any]) -> None:
        if not self._use_chroma_backend():
            return
        chunks = [chunk for chunk in payload.get("chunks", []) if isinstance(chunk, dict) and isinstance(chunk.get("embedding_vector"), list)]
        if not chunks:
            return
        await self.context.ensure_dir(Path(settings.chroma_persist_path).parent if Path(settings.chroma_persist_path).parent != Path(".") else settings.chroma_persist_path)
        persistent_client = _persistent_client_class()
        if persistent_client is None:
            return
        client = persistent_client(path=str(self._chroma_path()))
        collection_name = self._chroma_collection_name()
        try:
            client.delete_collection(collection_name)
        except Exception:
            pass
        collection = client.get_or_create_collection(collection_name, metadata={"hnsw:space": "cosine"})
        batch_size = EMBEDDING_BATCH_SIZE
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start:start + batch_size]
            collection.add(
                ids=[str(chunk["id"]) for chunk in batch],
                documents=[str(chunk["text"]) for chunk in batch],
                embeddings=[list(chunk["embedding_vector"]) for chunk in batch],
                metadatas=[
                    {
                        "path": str(chunk["path"]),
                        "collection": str(chunk.get("collection") or "other"),
                    }
                    for chunk in batch
                ],
            )

    async def _query_chroma(self, text: str, collections: list[str] | None = None, top_k: int = 10) -> list[dict]:
        if not self._use_chroma_backend():
            return []
        try:
            persistent_client = _persistent_client_class()
            if persistent_client is None:
                return []
            client = persistent_client(path=str(self._chroma_path()))
            collection = client.get_collection(self._chroma_collection_name())
        except Exception:
            return []
        query_embedding = await self._embed_text(text)
        if not query_embedding:
            return []
        query_kwargs: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": max(1, min(top_k * 3, 50)),
        }
        if collections:
            query_kwargs["where"] = {"collection": {"$in": collections}}
        try:
            response = collection.query(**query_kwargs)
        except Exception:
            return []

        items: list[dict[str, Any]] = []
        ids = (response.get("ids") or [[]])[0]
        documents = (response.get("documents") or [[]])[0]
        metadatas = (response.get("metadatas") or [[]])[0]
        distances = (response.get("distances") or [[]])[0]
        for index, chunk_id in enumerate(ids):
            metadata = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
            document = documents[index] if index < len(documents) else ""
            distance = float(distances[index]) if index < len(distances) else 1.0
            score = round(max(0.0, 1.0 - distance), 4)
            items.append({
                "path": str(metadata.get("path") or ""),
                "collection": str(metadata.get("collection") or "other"),
                "content": str(document),
                "score": score,
                "chunk_id": str(chunk_id),
            })
        items.sort(key=lambda item: item["score"], reverse=True)
        return items[:top_k]

    async def _embed_chunks(self, texts: list[str]) -> list[list[float] | None]:
        if not texts or not self._embedding_enabled():
            return [None] * len(texts)
        results: list[list[float] | None] = []
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[start:start + EMBEDDING_BATCH_SIZE]
            batch_vectors = await self._embed_texts(batch)
            results.extend(batch_vectors)
        return results

    async def _embed_texts(self, texts: list[str]) -> list[list[float] | None]:
        if not self._embedding_enabled():
            return [None] * len(texts)
        try:
            client = self._embedding_client()
            if not client:
                return [None] * len(texts)
            response = await client.embeddings.create(
                model=str(settings.embedding_model_name),
                input=texts,
            )
            items = sorted(response.data, key=lambda item: int(getattr(item, "index", 0)))
            vectors = [self._normalize_embedding(getattr(item, "embedding", [])) for item in items]
            if len(vectors) < len(texts):
                vectors.extend([None] * (len(texts) - len(vectors)))
            return vectors[:len(texts)]
        except Exception:
            return [None] * len(texts)

    async def _embed_text(self, text: str) -> list[float] | None:
        vectors = await self._embed_texts([text])
        return vectors[0] if vectors else None

    def _embedding_enabled(self) -> bool:
        return bool(settings.embedding_model_name and settings.llm_provider in {"openai", "custom"})

    def _embedding_client(self) -> AsyncOpenAI | None:
        if not self._embedding_enabled():
            return None
        api_key = settings.llm_api_key
        if not api_key and settings.llm_api_key_env:
            import os

            api_key = os.getenv(settings.llm_api_key_env)
        if not api_key:
            return None
        return AsyncOpenAI(api_key=api_key, base_url=settings.llm_api_base)

    def _normalize_embedding(self, values: Any) -> list[float] | None:
        if not isinstance(values, list) or not values:
            return None
        floats = [float(item) for item in values]
        length = math.sqrt(sum(value * value for value in floats))
        if not length:
            return None
        return [value / length for value in floats]
