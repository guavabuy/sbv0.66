from __future__ import annotations

from typing import Optional


def read_url(url: str, *, max_chars: int = 8000, timeout: int = 20) -> str:
    """
    读取网页内容（通过 r.jina.ai 转换为可读文本）。

    设计目标：
    - 任何异常不抛出：返回可读的错误字符串
    - 内容过短时返回“工具不可用/读取失败”的提示，避免 LLM 瞎编
    """
    u = (url or "").strip()
    if not u:
        return ""

    # 兼容：用户给的是 http(s) 或裸域名都尽量尝试
    source_url: str = u
    jina_url = f"https://r.jina.ai/{source_url}"

    try:
        import requests
    except Exception:
        return "工具不可用：缺少 requests 依赖。"

    try:
        resp = requests.get(jina_url, timeout=int(timeout))
        if resp.status_code != 200:
            return f"工具不可用：读取失败（HTTP {resp.status_code}）。"
        text = (resp.text or "").strip()
        if len(text) < 50:
            return "工具不可用：抓取内容无效（过短），请不要编造摘要。"
        return text[: int(max_chars)]
    except Exception as e:
        return f"工具不可用：读取失败（{e}）。"


