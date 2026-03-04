import json
import os
import time
from typing import Any, Dict, List, Optional

import dashscope
import requests
from dashscope import MultiModalConversation

from app.config import settings


class DashScopeError(RuntimeError):
    pass


class DashScopeClient:
    def __init__(self) -> None:
        self.api_key = settings.dashscope_api_key
        self.timeout = settings.request_timeout
        self.max_retries = settings.max_retries
        self.chat_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self.session = requests.Session()
        if settings.disable_env_proxy:
            # 避免系统代理（如 Privoxy）拦截 DashScope 请求。
            self.session.trust_env = False

    def _post_with_retry(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.post(
                    url,
                    headers=self.headers,
                    json=payload,
                    timeout=self.timeout,
                )
                if response.status_code >= 400:
                    raise DashScopeError(
                        f"DashScope 请求失败，url={url}, status={response.status_code}, body={response.text}"
                    )
                content_type = response.headers.get("Content-Type", "")
                if "application/json" not in content_type.lower():
                    preview = response.text[:240]
                    raise DashScopeError(
                        "DashScope 返回非 JSON 数据，可能被本机代理拦截。"
                        f" content_type={content_type}, body_preview={preview}"
                    )
                return response.json()
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if attempt < self.max_retries:
                    time.sleep(1.5 * attempt)
                else:
                    raise DashScopeError(f"请求重试失败: {exc}") from exc
        raise DashScopeError(f"请求失败: {last_err}")

    def chat_json(
        self, system_prompt: str, user_prompt: str, model: str | None = None
    ) -> Dict[str, Any]:
        payload = {
            "model": model or settings.text_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
        }
        result = self._post_with_retry(f"{self.chat_base_url}/chat/completions", payload)
        content = self._extract_chat_content(result)
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise DashScopeError(f"模型返回不是合法 JSON: {content}") from exc

    def generate_image(self, prompt: str, size: str) -> Optional[str]:
        normalized_size = size.replace("x", "*").replace("X", "*")
        messages = [
            {
                "role": "user",
                "content": [{"text": prompt}],
            }
        ]
        result = self._call_image_with_retry(
            messages=messages, size=normalized_size, model=settings.image_model
        )
        return self._extract_image_url(result)

    def edit_image(
        self, reference_image_base64: str, prompt: str, size: str
    ) -> Optional[str]:
        """使用 qwen-image-edit 模型，以参考图 + 文本编辑生成新图，提升一致性。"""
        normalized_size = size.replace("x", "*").replace("X", "*")
        messages = [
            {
                "role": "user",
                "content": [
                    {"image": reference_image_base64},
                    {"text": prompt},
                ],
            }
        ]
        result = self._call_image_edit_with_retry(
            messages=messages, size=normalized_size
        )
        return self._extract_image_url_from_edit(result)

    def _call_image_with_retry(
        self,
        messages: List[Dict[str, Any]],
        size: str,
        model: str | None = None,
    ) -> Dict[str, Any]:
        model = model or settings.image_model
        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                if settings.disable_env_proxy:
                    proxy_backup = self._clear_proxy_env()
                else:
                    proxy_backup = {}

                dashscope.base_http_api_url = settings.dashscope_base_http_api_url
                response = MultiModalConversation.call(
                    api_key=self.api_key,
                    model=model,
                    messages=messages,
                    result_format="message",
                    stream=False,
                    watermark=settings.image_watermark,
                    prompt_extend=settings.image_prompt_extend,
                    negative_prompt=settings.image_negative_prompt,
                    size=size,
                )
                if response.status_code != 200:
                    raise DashScopeError(
                        "DashScope 图片生成失败，"
                        f"status={response.status_code}, code={response.code}, message={response.message}"
                    )
                if hasattr(response, "output") and response.output:
                    return {"output": response.output}
                return dict(response)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if attempt < self.max_retries:
                    time.sleep(1.5 * attempt)
                else:
                    raise DashScopeError(f"图片请求重试失败: {exc}") from exc
            finally:
                if settings.disable_env_proxy:
                    self._restore_proxy_env(proxy_backup)
        raise DashScopeError(f"图片请求失败: {last_err}")

    def _call_image_edit_with_retry(
        self, messages: List[Dict[str, Any]], size: str
    ) -> Dict[str, Any]:
        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                if settings.disable_env_proxy:
                    proxy_backup = self._clear_proxy_env()
                else:
                    proxy_backup = {}

                dashscope.base_http_api_url = settings.dashscope_base_http_api_url
                response = MultiModalConversation.call(
                    api_key=self.api_key,
                    model=settings.image_edit_model,
                    messages=messages,
                    stream=False,
                    n=1,
                    watermark=settings.image_watermark,
                    negative_prompt=settings.image_negative_prompt or " ",
                    prompt_extend=settings.image_prompt_extend,
                    size=size,
                )
                if response.status_code != 200:
                    raise DashScopeError(
                        "DashScope 图像编辑失败，"
                        f"status={response.status_code}, code={response.code}, message={response.message}"
                    )
                if hasattr(response, "output") and response.output:
                    return {"output": response.output}
                return dict(response)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if attempt < self.max_retries:
                    time.sleep(1.5 * attempt)
                else:
                    raise DashScopeError(f"图像编辑重试失败: {exc}") from exc
            finally:
                if settings.disable_env_proxy:
                    self._restore_proxy_env(proxy_backup)
        raise DashScopeError(f"图像编辑失败: {last_err}")

    @staticmethod
    def _clear_proxy_env() -> Dict[str, str]:
        keys = [
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ]
        backup: Dict[str, str] = {}
        for key in keys:
            value = os.environ.get(key)
            if value is not None:
                backup[key] = value
                os.environ.pop(key, None)
        return backup

    @staticmethod
    def _restore_proxy_env(backup: Dict[str, str]) -> None:
        for key, value in backup.items():
            os.environ[key] = value

    @staticmethod
    def _extract_image_url_from_edit(resp: Dict[str, Any]) -> Optional[str]:
        """解析 qwen-image-edit 返回的 content[].image"""
        output = resp.get("output", {})
        choices = output.get("choices", [])
        if not choices:
            return None
        message = choices[0].get("message", {})
        content = message.get("content", [])
        if isinstance(content, list) and content:
            item = content[0]
            if isinstance(item, dict):
                return item.get("image") or item.get("url")
        return None

    @staticmethod
    def _extract_chat_content(resp: Dict[str, Any]) -> str:
        choices = resp.get("choices", [])
        if not choices:
            raise DashScopeError(f"chat 返回为空: {resp}")
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, list):
            text_parts: List[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
            content = "".join(text_parts)
        if not isinstance(content, str) or not content.strip():
            raise DashScopeError(f"chat content 非法: {resp}")
        return content.strip()

    @staticmethod
    def _extract_image_url(resp: Dict[str, Any]) -> Optional[str]:
        data = resp.get("data")
        if isinstance(data, list) and data:
            url = data[0].get("url")
            if isinstance(url, str):
                return url

        output = resp.get("output", {})
        results = output.get("results", [])
        if isinstance(results, list) and results:
            url = results[0].get("url")
            if isinstance(url, str):
                return url

        # MultiModalConversation result_format=message 常见结构
        choices = output.get("choices", [])
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            content = message.get("content", [])
            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    image_url = item.get("image") or item.get("url")
                    if isinstance(image_url, str):
                        return image_url
        return None
