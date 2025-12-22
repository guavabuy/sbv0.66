import os
from typing import Any, List, Optional, Sequence
from dotenv import load_dotenv

def get_llm_backend(
    provider: str,
    model: str,
    temperature: float = 0.3,
    timeout: int = 30,
    max_retries: int = 2,
):
    """
    获取 LLM 实例（目前支持 Google GenAI）。
    """
    load_dotenv()
    
    if provider == "google_genai":
        from langchain_google_genai import ChatGoogleGenerativeAI
        if not os.getenv("GOOGLE_API_KEY"):
            raise RuntimeError("缺少 GOOGLE_API_KEY，无法调用 google_genai。")
            
        return ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
            timeout=timeout,
            max_retries=max_retries,
        )
    elif provider == "openai":
        # 预留 OpenAI 接口
        # from langchain_openai import ChatOpenAI
        # return ChatOpenAI(model=model, ...)
        raise NotImplementedError(f"Provider {provider} 尚未实现适配。")
    else:
        raise ValueError(f"不支持的 LLM Provider: {provider}")

def normalize_reply(reply: Any) -> str:
    """
    统一清洗模型返回的文本。
    """
    if not isinstance(reply, list):
        return str(reply) if reply is not None else ""
    
    clean_text = ""
    for item in reply:
        if isinstance(item, dict) and "text" in item:
            clean_text += str(item.get("text") or "")
    return clean_text

