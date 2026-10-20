"""调用兼容 OpenAI chat/completions 的服务（例如 DeepSeek）。只用标准库。"""

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .config import secret

_pool = ThreadPoolExecutor(max_workers=8)


def openai_chat(base_url: str, model: str, api_key: str, timeout: float = 60, max_tokens: int = 2000):
    """返回 chat(system, user, temperature) -> 回复文本（JSON 模式）。
    timeout 是整次请求的上限：服务器慢慢吐字时，单次读取的超时拦不住，所以另起线程计时。"""
    url = base_url.rstrip("/") + "/chat/completions"

    def call(system: str, user: str, temperature: float) -> str:
        # 限制输出长度：JSON 模式偶尔会不停输出空白，直到写满上限
        body = {"model": model, "temperature": temperature, "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}]}
        req = urllib.request.Request(url, json.dumps(body).encode(), {
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)["choices"][0]["message"]["content"]

    def chat(system: str, user: str, temperature: float = 1.0) -> str:
        return _pool.submit(call, system, user, temperature).result(timeout=timeout)

    return chat


def from_config(skin: dict, **kw):
    key = secret(skin["api_key_env"])
    if not key:
        raise SystemExit(f"没有找到 {skin['api_key_env']}：请设置环境变量，或写进仓库根目录的 .env")
    return openai_chat(skin["base_url"], skin["model"], key, **kw)
