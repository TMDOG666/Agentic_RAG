"""grag.model.reranker_client

重排序客户端。

当前实现重点支持：
- vLLM reranker 服务
- 兼容 /v1/rerank 与 /v1/score
- 失败时稳定降级为原始顺序
"""

import json
import ipaddress
import os
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, request
from urllib.parse import urlparse

from ..config import ProviderType, get_config_manager


class RerankerClient:
    """统一的重排序客户端。"""

    def __init__(self, provider_name: Optional[str] = None):
        self.provider_name = provider_name
        self._reranker = None
        self._settings = get_config_manager().get_settings()

    def is_available(self) -> bool:
        """检查当前 provider 是否已配置。"""
        try:
            provider_config = self._settings.get_provider_config(
                ProviderType.RERANKER,
                self.provider_name,
            )
            return provider_config is not None
        except Exception:
            return False

    def get_reranker(self):
        """获取或懒加载重排序器实例。"""
        if self._reranker is None and self.is_available():
            self._reranker = self._create_reranker()
        return self._reranker

    def _create_reranker(self):
        """根据配置创建重排序器实例。"""
        provider_config = self._settings.get_provider_config(
            ProviderType.RERANKER,
            self.provider_name,
        )

        provider_name = self.provider_name or self._settings.reranker_provider
        model = self._get_env_override("GRAG_RERANKER_MODEL") or provider_config.model
        base_url = self._get_env_override("GRAG_RERANKER_BASE_URL") or provider_config.base_url
        timeout = provider_config.timeout
        default_top_k = provider_config.top_k
        api_key = self._get_api_key(provider_config)

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
        model: str,
        api_key: Optional[str],
        base_url: Optional[str],
        timeout: int,
        default_top_k: int,
    ):
        """创建兼容 vLLM rerank/score 的重排序器。"""
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

            def rerank(
                self,
                query: str,
                documents: List[str],
                top_k: Optional[int] = None,
            ) -> List[Tuple[str, float]]:
                if not documents:
                    return []

                limit = top_k if top_k is not None else default_top_k

                rerank_errors: List[str] = []
                rerank_payloads = [
                    {
                        "model": model,
                        "query": query,
                        "documents": documents,
                        "top_n": limit,
                    },
                    {
                        "model": model,
                        "query": query,
                        "documents": [{"text": doc} for doc in documents],
                        "top_n": limit,
                    },
                ]

                for endpoint in rerank_endpoints:
                    for payload in rerank_payloads:
                        try:
                            response = self._outer._post_json(
                                url=endpoint,
                                payload=payload,
                                headers=headers,
                                timeout=timeout,
                            )
                            parsed = self._outer._parse_rerank_response(
                                response=response,
                                documents=documents,
                                top_k=limit,
                            )
                            if parsed:
                                return parsed
                        except Exception as exc:
                            rerank_errors.append(f"{endpoint}: {exc}")

                score_results: List[Tuple[str, float]] = []
                score_errors: List[str] = []
                for index, doc in enumerate(documents):
                    score = None
                    for endpoint in score_endpoints:
                        payload = {
                            "model": model,
                            "text_1": query,
                            "text_2": doc,
                        }
                        try:
                            response = self._outer._post_json(
                                url=endpoint,
                                payload=payload,
                                headers=headers,
                                timeout=timeout,
                            )
                            score = self._outer._parse_score_response(response)
                            break
                        except Exception as exc:
                            score_errors.append(f"{endpoint}[{index}]: {exc}")

                    if score is None:
                        raise RuntimeError(
                            "; ".join(rerank_errors + score_errors)
                            or "vLLM rerank/score 请求失败"
                        )
                    score_results.append((doc, score))

                score_results.sort(key=lambda item: item[1], reverse=True)
                return score_results[:limit]

        return VLLMReranker(self)

    def _create_endpoint_reranker(
        self,
        model: str,
        api_key: Optional[str],
        base_url: Optional[str],
        timeout: int,
        default_top_k: int,
        rerank_paths: List[str],
    ):
        """创建通用 endpoint 型 reranker。"""
        if not base_url:
            raise ValueError("reranker 缺少 base_url 配置")

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        endpoints = self._join_paths(self._normalize_base_url(base_url), rerank_paths)

        class EndpointReranker:
            def __init__(self, outer: "RerankerClient"):
                self._outer = outer

            def rerank(
                self,
                query: str,
                documents: List[str],
                top_k: Optional[int] = None,
            ) -> List[Tuple[str, float]]:
                if not documents:
                    return []

                limit = top_k if top_k is not None else default_top_k
                payload = {
                    "model": model,
                    "query": query,
                    "documents": documents,
                    "top_n": limit,
                }

                errors_seen: List[str] = []
                for endpoint in endpoints:
                    try:
                        response = self._outer._post_json(
                            url=endpoint,
                            payload=payload,
                            headers=headers,
                            timeout=timeout,
                        )
                        parsed = self._outer._parse_rerank_response(
                            response=response,
                            documents=documents,
                            top_k=limit,
                        )
                        if parsed:
                            return parsed
                    except Exception as exc:
                        errors_seen.append(f"{endpoint}: {exc}")

                raise RuntimeError("; ".join(errors_seen) or "rerank 请求失败")

        return EndpointReranker(self)

    def _normalize_base_url(self, base_url: str) -> str:
        return str(base_url or "").strip().rstrip("/")

    def _join_paths(self, base_url: str, paths: List[str]) -> List[str]:
        urls: List[str] = []
        for path in paths:
            if not path.startswith("/"):
                path = "/" + path
            if base_url.endswith("/v1") and path.startswith("/v1/"):
                candidate = base_url + path[3:]
            else:
                candidate = base_url + path
            if candidate not in urls:
                urls.append(candidate)
        return urls

    def _post_json(
        self,
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
            raise RuntimeError(f"HTTP {exc.code} {detail}".strip()) from exc
        except error.URLError as exc:
            raise RuntimeError(f"网络错误: {exc.reason}") from exc

        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"响应不是合法 JSON: {raw[:200]}") from exc

        if not isinstance(data, dict):
            raise RuntimeError(f"响应格式异常: {type(data).__name__}")
        if data.get("error"):
            raise RuntimeError(str(data["error"]))
        return data

    def _parse_rerank_response(
        self,
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
            score = item.get("relevance_score", item.get("score", 0.0))
            try:
                score_value = float(score)
            except Exception:
                score_value = 0.0
            reranked.append((documents[index], score_value))

        if top_k is not None:
            reranked = reranked[:top_k]
        if not reranked:
            raise RuntimeError(f"响应中没有可用的 rerank 结果: {response}")
        return reranked

    def _parse_score_response(self, response: Dict[str, Any]) -> float:
        raw_data = response.get("data")
        if isinstance(raw_data, list) and raw_data:
            item = raw_data[0]
            if isinstance(item, dict):
                score = item.get("score")
                if score is not None:
                    return float(score)
        if "score" in response:
            return float(response["score"])
        raise RuntimeError(f"响应缺少 score 字段: {response}")

    def _create_default_reranker(self):
        class DefaultReranker:
            def rerank(
                self,
                query: str,
                documents: List[str],
                top_k: Optional[int] = None,
            ) -> List[Tuple[str, float]]:
                results = [(doc, 1.0) for doc in documents]
                if top_k:
                    results = results[:top_k]
                return results

        return DefaultReranker()

    def _get_api_key(self, provider_config) -> Optional[str]:
        api_key = os.environ.get("GRAG_RERANKER_API_KEY")
        if api_key:
            return api_key
        if hasattr(provider_config, "api_key_env") and provider_config.api_key_env:
            api_key = os.environ.get(provider_config.api_key_env)
            if api_key:
                return api_key
        if provider_config.base_url and self._is_local_url(provider_config.base_url):
            return "EMPTY"
        return None

    def _get_env_override(self, env_var: str) -> Optional[str]:
        return os.environ.get(env_var)

    def _is_local_url(self, url: str) -> bool:
        if not url:
            return False
        local_indicators = ["localhost", "127.0.0.1", "0.0.0.0", "local", ".local"]
        url_lower = url.lower()
        if any(indicator in url_lower for indicator in local_indicators):
            return True
        try:
            host = (urlparse(url).hostname or "").strip()
            if not host:
                return False
            ip = ipaddress.ip_address(host)
            return ip.is_loopback or ip.is_private
        except ValueError:
            return False

    def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: Optional[int] = None,
    ) -> List[Tuple[str, float]]:
        if not self.is_available():
            results = [(doc, 1.0) for doc in documents]
            if top_k:
                results = results[:top_k]
            return results

        try:
            reranker = self.get_reranker()
            return reranker.rerank(query, documents, top_k)
        except Exception as e:
            print(f"重排序失败，使用原始顺序: {e}")
            results = [(doc, 1.0) for doc in documents]
            if top_k:
                results = results[:top_k]
            return results

    def test_connection(self) -> bool:
        if not self.is_available():
            return False
        try:
            results = self.rerank("test query", ["doc1", "doc2", "doc3"], top_k=2)
            return len(results) > 0
        except Exception as e:
            print(f"重排序连接测试失败: {e}")
            return False

    def get_provider_info(self) -> Dict[str, Any]:
        if not self.is_available():
            return {"available": False}
        provider_config = self._settings.get_provider_config(
            ProviderType.RERANKER,
            self.provider_name,
        )
        return {
            "provider_name": self.provider_name or self._settings.reranker_provider,
            "model": provider_config.model,
            "base_url": provider_config.base_url,
            "top_k": provider_config.top_k,
            "timeout": provider_config.timeout,
            "available": True,
        }

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
    client = get_reranker_client(provider_name)
    return client.rerank(query, documents, top_k)


def is_reranker_available(provider_name: Optional[str] = None) -> bool:
    client = get_reranker_client(provider_name)
    return client.is_available()


def test_reranker_connection(provider_name: Optional[str] = None) -> bool:
    client = get_reranker_client(provider_name)
    return client.test_connection()
