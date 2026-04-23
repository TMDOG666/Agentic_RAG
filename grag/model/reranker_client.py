from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, request

from ..config import ProviderType
from .provider_client_base import ProviderClientBase


class RerankerClient(ProviderClientBase):
    """统一的 reranker 客户端。"""

    def __init__(self, provider_name: Optional[str] = None):
        super().__init__(provider_name=provider_name)
        self._reranker = None

    def is_available(self) -> bool:
        try:
            return self._get_provider_config(ProviderType.RERANKER) is not None
        except Exception:
            return False

    def get_reranker(self):
        if self._reranker is None and self.is_available():
            self._reranker = self._create_reranker()
        return self._reranker

    def _create_reranker(self):
        settings = self._get_settings()
        provider_config = self._get_provider_config(ProviderType.RERANKER)
        provider_name = self.provider_name or settings.reranker_provider
        model = self._get_env_override("GRAG_RERANKER_MODEL") or provider_config.model
        base_url = self._get_env_override("GRAG_RERANKER_BASE_URL") or provider_config.base_url
        timeout = provider_config.timeout
        default_top_k = provider_config.top_k
        api_key = self._resolve_api_key(
            provider_config=provider_config,
            provider_name=provider_name,
            env_override_name="GRAG_RERANKER_API_KEY",
        )

        if provider_name == "vllm":
            return self._create_vllm_reranker(
                model=model,
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                default_top_k=default_top_k,
            )
        if provider_name in {"ollama", "lmstudio"}:
            return self._create_endpoint_reranker(
                model=model,
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                default_top_k=default_top_k,
                rerank_paths=["/v1/rerank", "/rerank", "/v2/rerank"],
            )
        if provider_name in {"siliconflow", "openai", "openai_compatible"}:
            return self._create_endpoint_reranker(
                model=model,
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                default_top_k=default_top_k,
                rerank_paths=["/v1/rerank"],
            )
        return self._create_default_reranker()

    def _create_vllm_reranker(
        self,
        *,
        model: str,
        api_key: Optional[str],
        base_url: Optional[str],
        timeout: int,
        default_top_k: int,
    ):
        if not base_url:
            raise ValueError("vLLM reranker 缺少 base_url 配置")

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        base = self._normalize_base_url(base_url)
        rerank_endpoints = self._join_paths(base, ["/v1/rerank", "/rerank", "/v2/rerank"])
        score_endpoints = self._join_paths(base, ["/v1/score", "/score"])

        class VLLMReranker:
            def __init__(self, outer: "RerankerClient"):
                self._outer = outer

            def rerank(self, query: str, documents: List[str], top_k: Optional[int] = None) -> List[Tuple[str, float]]:
                if not documents:
                    return []
                limit = top_k if top_k is not None else default_top_k
                rerank_errors: List[str] = []
                rerank_payloads = [
                    {"model": model, "query": query, "documents": documents, "top_n": limit},
                    {"model": model, "query": query, "documents": [{"text": doc} for doc in documents], "top_n": limit},
                ]
                for endpoint in rerank_endpoints:
                    for payload in rerank_payloads:
                        try:
                            response = self._outer._post_json(url=endpoint, payload=payload, headers=headers, timeout=timeout)
                            parsed = self._outer._parse_rerank_response(response=response, documents=documents, top_k=limit)
                            if parsed:
                                return parsed
                        except Exception as exc:
                            rerank_errors.append(f"{endpoint}: {exc}")

                score_results: List[Tuple[str, float]] = []
                score_errors: List[str] = []
                for index, document in enumerate(documents):
                    score = None
                    for endpoint in score_endpoints:
                        try:
                            response = self._outer._post_json(
                                url=endpoint,
                                payload={"model": model, "text_1": query, "text_2": document},
                                headers=headers,
                                timeout=timeout,
                            )
                            score = self._outer._parse_score_response(response)
                            break
                        except Exception as exc:
                            score_errors.append(f"{endpoint}[{index}]: {exc}")
                    if score is None:
                        raise RuntimeError("; ".join(rerank_errors + score_errors) or "vLLM rerank/score 请求失败")
                    score_results.append((document, score))
                score_results.sort(key=lambda item: item[1], reverse=True)
                return score_results[:limit]

        return VLLMReranker(self)

    def _create_endpoint_reranker(
        self,
        *,
        model: str,
        api_key: Optional[str],
        base_url: Optional[str],
        timeout: int,
        default_top_k: int,
        rerank_paths: List[str],
    ):
        if not base_url:
            raise ValueError("reranker 缺少 base_url 配置")

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        endpoints = self._join_paths(self._normalize_base_url(base_url), rerank_paths)

        class EndpointReranker:
            def __init__(self, outer: "RerankerClient"):
                self._outer = outer

            def rerank(self, query: str, documents: List[str], top_k: Optional[int] = None) -> List[Tuple[str, float]]:
                if not documents:
                    return []
                limit = top_k if top_k is not None else default_top_k
                payload = {"model": model, "query": query, "documents": documents, "top_n": limit}
                errors_seen: List[str] = []
                for endpoint in endpoints:
                    try:
                        response = self._outer._post_json(url=endpoint, payload=payload, headers=headers, timeout=timeout)
                        parsed = self._outer._parse_rerank_response(response=response, documents=documents, top_k=limit)
                        if parsed:
                            return parsed
                    except Exception as exc:
                        errors_seen.append(f"{endpoint}: {exc}")
                raise RuntimeError("; ".join(errors_seen) or "rerank 请求失败")

        return EndpointReranker(self)

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        return str(base_url or "").strip().rstrip("/")

    def _join_paths(self, base_url: str, paths: List[str]) -> List[str]:
        urls: List[str] = []
        for path in paths:
            normalized = path if path.startswith("/") else f"/{path}"
            if base_url.endswith("/v1") and normalized.startswith("/v1/"):
                candidate = base_url + normalized[3:]
            else:
                candidate = base_url + normalized
            if candidate not in urls:
                urls.append(candidate)
        return urls

    def _post_json(
        self,
        *,
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        timeout: int,
    ) -> Dict[str, Any]:
        req = request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(detail or f"HTTP {exc.code}") from exc
        except error.URLError as exc:
            raise RuntimeError(str(exc.reason)) from exc

        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"响应不是合法 JSON: {raw[:200]}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"响应格式异常: {type(data).__name__}")
        if data.get("error"):
            raise RuntimeError(str(data["error"]))
        return data

    @staticmethod
    def _parse_rerank_response(
        *,
        response: Dict[str, Any],
        documents: List[str],
        top_k: Optional[int],
    ) -> List[Tuple[str, float]]:
        raw_results = response.get("results")
        if raw_results is None:
            raw_results = response.get("data")
        if not isinstance(raw_results, list):
            raise RuntimeError(f"响应缺少 results/data 字段: {response}")

        reranked: List[Tuple[str, float]] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            if not isinstance(index, int) or index < 0 or index >= len(documents):
                continue
            try:
                score_value = float(item.get("relevance_score", item.get("score", 0.0)))
            except Exception:
                score_value = 0.0
            reranked.append((documents[index], score_value))
        if top_k is not None:
            reranked = reranked[:top_k]
        if not reranked:
            raise RuntimeError(f"响应中没有可用的 rerank 结果: {response}")
        return reranked

    @staticmethod
    def _parse_score_response(response: Dict[str, Any]) -> float:
        raw_data = response.get("data")
        if isinstance(raw_data, list) and raw_data:
            item = raw_data[0]
            if isinstance(item, dict) and item.get("score") is not None:
                return float(item["score"])
        if "score" in response:
            return float(response["score"])
        raise RuntimeError(f"响应缺少 score 字段: {response}")

    @staticmethod
    def _create_default_reranker():
        class DefaultReranker:
            def rerank(self, query: str, documents: List[str], top_k: Optional[int] = None) -> List[Tuple[str, float]]:
                results = [(document, 1.0) for document in documents]
                if top_k:
                    results = results[:top_k]
                return results

        return DefaultReranker()

    def rerank(self, query: str, documents: List[str], top_k: Optional[int] = None) -> List[Tuple[str, float]]:
        if not self.is_available():
            results = [(document, 1.0) for document in documents]
            return results[:top_k] if top_k else results
        try:
            reranker = self.get_reranker()
            return reranker.rerank(query, documents, top_k)
        except Exception as exc:
            print(
                self._format_provider_error(
                    operation="重排序失败，使用原始顺序",
                    exc=exc,
                    provider_info=self.get_provider_info(),
                )
            )
            results = [(document, 1.0) for document in documents]
            return results[:top_k] if top_k else results

    def test_connection(self) -> bool:
        if not self.is_available():
            return False
        try:
            return len(self.rerank("test query", ["doc1", "doc2", "doc3"], top_k=2)) > 0
        except Exception as exc:
            print(f"重排序连接测试失败: {exc}")
            return False

    def get_provider_info(self) -> Dict[str, Any]:
        if not self.is_available():
            return {"available": False}
        settings = self._get_settings()
        provider_config = self._get_provider_config(ProviderType.RERANKER)
        return self._build_provider_info(
            provider_name=self.provider_name or settings.reranker_provider,
            provider_config=provider_config,
            extra={"top_k": provider_config.top_k, "available": True},
        )

    def refresh_reranker(self) -> None:
        self._reranker = None


_default_reranker_client: Optional[RerankerClient] = None


def get_reranker_client(provider_name: Optional[str] = None) -> RerankerClient:
    global _default_reranker_client
    if _default_reranker_client is None or provider_name is not None:
        _default_reranker_client = RerankerClient(provider_name)
    return _default_reranker_client


def rerank_documents(
    query: str,
    documents: List[str],
    top_k: Optional[int] = None,
    provider_name: Optional[str] = None,
) -> List[Tuple[str, float]]:
    return get_reranker_client(provider_name).rerank(query, documents, top_k)


def is_reranker_available(provider_name: Optional[str] = None) -> bool:
    return get_reranker_client(provider_name).is_available()


def test_reranker_connection(provider_name: Optional[str] = None) -> bool:
    return get_reranker_client(provider_name).test_connection()
