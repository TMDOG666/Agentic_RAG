"""grag.model.embedding_client

向量嵌入客户端。

职责：
- 创建并管理 Embedding 模型实例
- 屏蔽不同 provider 的差异
- 提供文本/查询的统一嵌入接口
- 对超长文本做兜底拆分，避免单条输入超过模型上下文上限
"""

import os
import re
from typing import Any, Dict, List, Optional

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from ..config import ProviderType, get_config_manager


class EmbeddingClient:
    """统一的向量嵌入客户端。"""

    def __init__(self, provider_name: Optional[str] = None):
        self.provider_name = provider_name
        self._embeddings: Optional[Embeddings] = None
        self._settings = get_config_manager().get_settings()

    def get_embeddings(self) -> Embeddings:
        if self._embeddings is None:
            self._embeddings = self._create_embeddings()
        return self._embeddings

    def _create_embeddings(self) -> Embeddings:
        provider_config = self._settings.get_provider_config(
            ProviderType.EMBEDDING,
            self.provider_name,
        )
        provider_name = self.provider_name or self._settings.embedding_provider

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
                api_key = self._get_api_key(provider_config)
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
            raise RuntimeError(f"创建嵌入模型失败: {exc}") from exc

    def _get_api_key(self, provider_config) -> Optional[str]:
        api_key = os.environ.get("GRAG_EMBEDDING_API_KEY")
        if api_key:
            return api_key

        if hasattr(provider_config, "api_key_env") and provider_config.api_key_env:
            api_key = os.environ.get(provider_config.api_key_env)
            if api_key:
                return api_key

        provider_name = self.provider_name or self._settings.embedding_provider
        if provider_name == "siliconflow":
            api_key = os.environ.get("SILICONFLOW_API_KEY")
            if api_key:
                return api_key

        if provider_name == "huggingface":
            return None

        if provider_config.base_url and self._is_local_url(provider_config.base_url):
            return "EMPTY"

        return None

    def _get_env_override(self, env_var: str) -> Optional[str]:
        return os.environ.get(env_var)

    def _is_local_url(self, url: str) -> bool:
        if not url:
            return False
        url_lower = url.lower()
        local_indicators = ["localhost", "127.0.0.1", "0.0.0.0", "local", ".local"]
        return any(indicator in url_lower for indicator in local_indicators)

    def _validate_dimensions(self, embeddings: Embeddings, expected_dim: int) -> None:
        try:
            test_embedding = embeddings.embed_query("test")
            actual_dim = len(test_embedding)
            if actual_dim != expected_dim:
                print(f"警告: 嵌入维度不匹配，期望 {expected_dim}，实际 {actual_dim}")
        except Exception:
            pass

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """嵌入文本列表。

        两层保护：
        1. 正常短文本走批处理。
        2. 批处理失败后降级到逐条；逐条仍超长时继续拆分并聚合。
        """
        try:
            embeddings = self.get_embeddings()
            if not texts:
                return []

            provider_config = self._settings.get_provider_config(
                ProviderType.EMBEDDING,
                self.provider_name,
            )

            max_bs = getattr(provider_config, "max_batch_size", None)
            try:
                max_bs_int = int(max_bs) if max_bs is not None else 0
            except Exception:
                max_bs_int = 0
            batch_size = max_bs_int if max_bs_int and max_bs_int > 0 else 64

            safe_batch: List[str] = []
            safe_batch_indices: List[int] = []
            results: List[Optional[List[float]]] = [None] * len(texts)

            def flush_safe_batch() -> None:
                if not safe_batch:
                    return
                batch_vectors = self._embed_batch_with_fallback(embeddings, safe_batch)
                for idx, vector in zip(safe_batch_indices, batch_vectors):
                    results[idx] = vector
                safe_batch.clear()
                safe_batch_indices.clear()

            for idx, text in enumerate(texts):
                normalized = (text or "").strip()
                if not normalized:
                    results[idx] = []
                    continue

                if self._should_split_text_for_embedding(normalized):
                    flush_safe_batch()
                    results[idx] = self._embed_long_text_with_fallback(embeddings, normalized)
                    continue

                safe_batch.append(normalized)
                safe_batch_indices.append(idx)
                if len(safe_batch) >= batch_size:
                    flush_safe_batch()

            flush_safe_batch()
            return [vector or [] for vector in results]
        except Exception as exc:
            raise RuntimeError(f"文本嵌入失败: {exc}") from exc

    def embed_query(self, text: str) -> List[float]:
        try:
            embeddings = self.get_embeddings()
            return embeddings.embed_query(text)
        except Exception as exc:
            raise RuntimeError(f"查询嵌入失败: {exc}") from exc

    def test_connection(self) -> bool:
        try:
            embedding = self.embed_query("Hello world")
            return len(embedding) > 0
        except Exception as exc:
            print(f"嵌入连接测试失败: {exc}")
            return False

    def get_provider_info(self) -> Dict[str, Any]:
        provider_config = self._settings.get_provider_config(
            ProviderType.EMBEDDING,
            self.provider_name,
        )
        return {
            "provider_name": self.provider_name or self._settings.embedding_provider,
            "model": provider_config.model,
            "base_url": provider_config.base_url,
            "dimension": provider_config.dimension,
            "max_batch_size": provider_config.max_batch_size,
            "timeout": provider_config.timeout,
        }

    def get_dimension(self) -> int:
        provider_config = self._settings.get_provider_config(
            ProviderType.EMBEDDING,
            self.provider_name,
        )
        return provider_config.dimension

    def refresh_embeddings(self) -> None:
        self._embeddings = None

    def _should_split_text_for_embedding(self, text: str) -> bool:
        return self._estimate_token_count(text) > self._get_safe_embedding_token_limit()

    def _get_safe_embedding_token_limit(self) -> int:
        # 服务端上限是 4096，这里保守留足余量。
        return 2400

    def _estimate_token_count(self, text: str) -> int:
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

    def _split_by_double_newline(self, text: str) -> List[str]:
        parts = [part.strip() for part in text.split("\n\n") if part.strip()]
        return parts or [text]

    def _split_by_single_newline(self, text: str) -> List[str]:
        parts = [part.strip() for part in text.split("\n") if part.strip()]
        return parts or [text]

    def _split_by_sentence(self, text: str) -> List[str]:
        parts = [part.strip() for part in re.split(r"(?<=[。！？!?\.])\s*", text) if part.strip()]
        return parts or [text]

    def _split_by_fixed_chars(self, text: str, step: int) -> List[str]:
        return [text[i : i + step].strip() for i in range(0, len(text), step) if text[i : i + step].strip()]

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

    def _average_vectors(self, vectors: List[List[float]]) -> List[float]:
        dimension = len(vectors[0])
        sums = [0.0] * dimension
        for vector in vectors:
            for idx, value in enumerate(vector):
                sums[idx] += value
        count = float(len(vectors))
        return [value / count for value in sums]

    def _is_context_length_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "maximum context length" in message
            or "input_tokens" in message
            or "context length" in message
        )


_default_embedding_client: Optional[EmbeddingClient] = None


def get_embedding_client(provider_name: Optional[str] = None) -> EmbeddingClient:
    global _default_embedding_client
    if _default_embedding_client is None or provider_name is not None:
        _default_embedding_client = EmbeddingClient(provider_name)
    return _default_embedding_client


def get_embeddings(provider_name: Optional[str] = None) -> Embeddings:
    client = get_embedding_client(provider_name)
    return client.get_embeddings()


def embed_texts(texts: List[str], provider_name: Optional[str] = None) -> List[List[float]]:
    client = get_embedding_client(provider_name)
    return client.embed_texts(texts)


def embed_query(text: str, provider_name: Optional[str] = None) -> List[float]:
    client = get_embedding_client(provider_name)
    return client.embed_query(text)


def test_embedding_connection(provider_name: Optional[str] = None) -> bool:
    client = get_embedding_client(provider_name)
    return client.test_connection()
