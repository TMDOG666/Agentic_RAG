from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from ..config import ProviderType
from .provider_client_base import ProviderClientBase


class EmbeddingClient(ProviderClientBase):
    """统一的 Embedding 客户端。"""

    def __init__(self, provider_name: Optional[str] = None):
        super().__init__(provider_name=provider_name)
        self._embeddings: Optional[Embeddings] = None

    def get_embeddings(self) -> Embeddings:
        if self._embeddings is None:
            self._embeddings = self._create_embeddings()
        return self._embeddings

    def _create_embeddings(self) -> Embeddings:
        settings = self._get_settings()
        provider_config = self._get_provider_config(ProviderType.EMBEDDING)
        provider_name = self.provider_name or settings.embedding_provider
        model = self._get_env_override("GRAG_EMBEDDING_MODEL") or provider_config.model
        base_url = self._get_env_override("GRAG_EMBEDDING_BASE_URL") or provider_config.base_url
        dimension = provider_config.dimension
        timeout = provider_config.timeout

        try:
            if provider_name == "huggingface":
                embeddings = HuggingFaceEmbeddings(
                    model_name=model,
                    model_kwargs={"device": "auto"},
                    encode_kwargs={"normalize_embeddings": True},
                )
            else:
                api_key = self._resolve_api_key(
                    provider_config=provider_config,
                    provider_name=provider_name,
                    env_override_name="GRAG_EMBEDDING_API_KEY",
                    legacy_env_map={"siliconflow": "SILICONFLOW_API_KEY"},
                )
                if not api_key and base_url and not self._is_local_url(base_url):
                    raise ValueError(f"API Key 不能为空 (provider: {provider_name})")
                embeddings = OpenAIEmbeddings(
                    model=model,
                    api_key=api_key or "EMPTY",
                    base_url=base_url,
                    timeout=timeout,
                    max_retries=3,
                )
            if hasattr(embeddings, "_check_dimensions"):
                self._validate_dimensions(embeddings, dimension)
            return embeddings
        except Exception as exc:
            raise RuntimeError(
                self._format_provider_error(
                    operation="创建嵌入模型失败",
                    exc=exc,
                    provider_info=self.get_provider_info(),
                )
            ) from exc

    @staticmethod
    def _validate_dimensions(embeddings: Embeddings, expected_dim: int) -> None:
        try:
            actual_dim = len(embeddings.embed_query("test"))
            if actual_dim != expected_dim:
                print(f"警告: 嵌入维度不匹配，期望 {expected_dim}，实际 {actual_dim}")
        except Exception:
            pass

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        try:
            embeddings = self.get_embeddings()
            if not texts:
                return []
            provider_config = self._get_provider_config(ProviderType.EMBEDDING)
            max_batch_size = getattr(provider_config, "max_batch_size", None)
            try:
                batch_size = int(max_batch_size) if max_batch_size is not None else 64
            except Exception:
                batch_size = 64

            safe_batch: List[str] = []
            safe_batch_indices: List[int] = []
            results: List[Optional[List[float]]] = [None] * len(texts)

            def flush_safe_batch() -> None:
                if not safe_batch:
                    return
                batch_vectors = self._embed_batch_with_fallback(embeddings, safe_batch)
                for index, vector in zip(safe_batch_indices, batch_vectors):
                    results[index] = vector
                safe_batch.clear()
                safe_batch_indices.clear()

            for index, text in enumerate(texts):
                normalized = (text or "").strip()
                if not normalized:
                    results[index] = []
                    continue
                if self._should_split_text_for_embedding(normalized):
                    flush_safe_batch()
                    results[index] = self._embed_long_text_with_fallback(embeddings, normalized)
                    continue
                safe_batch.append(normalized)
                safe_batch_indices.append(index)
                if len(safe_batch) >= batch_size:
                    flush_safe_batch()

            flush_safe_batch()
            return [vector or [] for vector in results]
        except Exception as exc:
            raise RuntimeError(
                self._format_provider_error(
                    operation="文本嵌入失败",
                    exc=exc,
                    provider_info=self.get_provider_info(),
                )
            ) from exc

    def embed_query(self, text: str) -> List[float]:
        try:
            return self.get_embeddings().embed_query(text)
        except Exception as exc:
            raise RuntimeError(
                self._format_provider_error(
                    operation="查询嵌入失败",
                    exc=exc,
                    provider_info=self.get_provider_info(),
                )
            ) from exc

    def test_connection(self) -> bool:
        try:
            embedding = self.embed_query("Hello world")
            return len(embedding) > 0
        except Exception as exc:
            print(f"嵌入连接测试失败: {exc}")
            return False

    def get_provider_info(self) -> Dict[str, Any]:
        settings = self._get_settings()
        provider_config = self._get_provider_config(ProviderType.EMBEDDING)
        return self._build_provider_info(
            provider_name=self.provider_name or settings.embedding_provider,
            provider_config=provider_config,
            extra={
                "dimension": provider_config.dimension,
                "max_batch_size": provider_config.max_batch_size,
            },
        )

    def get_dimension(self) -> int:
        provider_config = self._get_provider_config(ProviderType.EMBEDDING)
        return provider_config.dimension

    def refresh_embeddings(self) -> None:
        self._embeddings = None

    def _should_split_text_for_embedding(self, text: str) -> bool:
        return self._estimate_token_count(text) > self._get_safe_embedding_token_limit()

    @staticmethod
    def _get_safe_embedding_token_limit() -> int:
        return 2400

    @staticmethod
    def _estimate_token_count(text: str) -> int:
        if not text:
            return 0
        token_like_units = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]|[^\w\s]", text)
        return len(token_like_units)

    def _embed_long_text_with_fallback(self, embeddings: Embeddings, text: str) -> List[float]:
        chunks = self._split_text_for_embedding(text)
        if len(chunks) == 1:
            return self._embed_single_text_once(embeddings, chunks[0])
        vectors = [self._embed_single_text_once(embeddings, chunk) for chunk in chunks if chunk.strip()]
        if not vectors:
            return []
        return self._average_vectors(vectors)

    def _embed_batch_with_fallback(self, embeddings: Embeddings, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        try:
            return embeddings.embed_documents(texts)
        except Exception as exc:
            if not self._is_context_length_error(exc):
                raise
            return [self._embed_single_text_once(embeddings, text) for text in texts]

    def _embed_single_text_once(self, embeddings: Embeddings, text: str) -> List[float]:
        try:
            return embeddings.embed_documents([text])[0]
        except Exception as exc:
            if not self._is_context_length_error(exc):
                raise
            sub_chunks = self._split_text_for_embedding(text, force_split=True)
            if len(sub_chunks) <= 1:
                raise
            vectors = [self._embed_single_text_once(embeddings, chunk) for chunk in sub_chunks if chunk.strip()]
            if not vectors:
                raise
            return self._average_vectors(vectors)

    def _split_text_for_embedding(self, text: str, force_split: bool = False) -> List[str]:
        normalized = (text or "").strip()
        if not normalized:
            return []
        limit = self._get_safe_embedding_token_limit()
        if not force_split and self._estimate_token_count(normalized) <= limit:
            return [normalized]
        units = self._split_by_double_newline(normalized)
        if len(units) == 1:
            units = self._split_by_single_newline(normalized)
        if len(units) == 1:
            units = self._split_by_sentence(normalized)
        if len(units) == 1:
            units = self._split_by_fixed_chars(normalized, 600)
        return self._merge_units_by_token_limit(units, limit)

    @staticmethod
    def _split_by_double_newline(text: str) -> List[str]:
        parts = [part.strip() for part in text.split("\n\n") if part.strip()]
        return parts or [text]

    @staticmethod
    def _split_by_single_newline(text: str) -> List[str]:
        parts = [part.strip() for part in text.split("\n") if part.strip()]
        return parts or [text]

    @staticmethod
    def _split_by_sentence(text: str) -> List[str]:
        parts = [part.strip() for part in re.split(r"(?<=[。！？?!\.])\s*", text) if part.strip()]
        return parts or [text]

    @staticmethod
    def _split_by_fixed_chars(text: str, step: int) -> List[str]:
        return [text[index : index + step].strip() for index in range(0, len(text), step) if text[index : index + step].strip()]

    def _merge_units_by_token_limit(self, units: List[str], limit: int) -> List[str]:
        merged: List[str] = []
        current = ""
        for unit in units:
            unit = unit.strip()
            if not unit:
                continue
            if self._estimate_token_count(unit) > limit:
                if current:
                    merged.append(current)
                    current = ""
                merged.extend(self._split_by_fixed_chars(unit, 400))
                continue
            candidate = f"{current}\n\n{unit}".strip() if current else unit
            if current and self._estimate_token_count(candidate) > limit:
                merged.append(current)
                current = unit
            else:
                current = candidate
        if current:
            merged.append(current)
        return merged or [""]

    @staticmethod
    def _average_vectors(vectors: List[List[float]]) -> List[float]:
        dimension = len(vectors[0])
        sums = [0.0] * dimension
        for vector in vectors:
            for index, value in enumerate(vector):
                sums[index] += value
        count = float(len(vectors))
        return [value / count for value in sums]

    @staticmethod
    def _is_context_length_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return "maximum context length" in message or "input_tokens" in message or "context length" in message


_default_embedding_client: Optional[EmbeddingClient] = None


def get_embedding_client(provider_name: Optional[str] = None) -> EmbeddingClient:
    global _default_embedding_client
    if _default_embedding_client is None or provider_name is not None:
        _default_embedding_client = EmbeddingClient(provider_name)
    return _default_embedding_client


def get_embeddings(provider_name: Optional[str] = None) -> Embeddings:
    return get_embedding_client(provider_name).get_embeddings()


def embed_texts(texts: List[str], provider_name: Optional[str] = None) -> List[List[float]]:
    return get_embedding_client(provider_name).embed_texts(texts)


def embed_query(text: str, provider_name: Optional[str] = None) -> List[float]:
    return get_embedding_client(provider_name).embed_query(text)


def test_embedding_connection(provider_name: Optional[str] = None) -> bool:
    return get_embedding_client(provider_name).test_connection()
