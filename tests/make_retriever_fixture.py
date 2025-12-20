# tests/make_retriever_fixture.py
import os
import re
import pickle
import inspect
import importlib.util
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]  # 项目根目录
MR_PATH = ROOT / "memory_retriever.py"
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "retriever_return.pkl"


def _load_memory_retriever():
    if not MR_PATH.exists():
        raise FileNotFoundError(f"找不到文件: {MR_PATH}")
    spec = importlib.util.spec_from_file_location("memory_retriever", str(MR_PATH))
    mr = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mr)
    return mr


def _is_picklable(obj: Any) -> bool:
    try:
        pickle.dumps(obj)
        return True
    except Exception:
        return False


def _sanitize(obj: Any) -> Any:
    """把复杂对象转成可 pickle 的基础结构"""
    # tuple: (doc, score)
    if isinstance(obj, tuple) and len(obj) == 2:
        a, b = obj
        if isinstance(b, (int, float)):
            return {"doc": _sanitize(a), "score": float(b)}
        if isinstance(a, (int, float)):
            return {"doc": _sanitize(b), "score": float(a)}
        return {"a": _sanitize(a), "b": _sanitize(b)}

    # LangChain Document 兼容：page_content + metadata
    if hasattr(obj, "page_content"):
        meta = getattr(obj, "metadata", None)
        if not isinstance(meta, dict):
            meta = {}
        return {"page_content": getattr(obj, "page_content", ""), "metadata": meta}

    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(_sanitize(x) for x in obj)

    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj

    return str(obj)


def _extract_candidate_names_from_files() -> List[str]:
    """从 main.py / tg_bot.py 里提取 from memory_retriever import xxx 以及 memory_retriever.xxx 的调用"""
    names: List[str] = []
    for fname in ("main.py", "tg_bot.py"):
        p = ROOT / fname
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")

        # from memory_retriever import a, b
        for m in re.finditer(r"from\s+memory_retriever\s+import\s+([^\n]+)", text):
            chunk = m.group(1).split("#")[0]
            for part in [x.strip() for x in chunk.split(",")]:
                if part and part.isidentifier():
                    names.append(part)

        # memory_retriever.xxx(
        for m in re.finditer(r"memory_retriever\.(\w+)\s*\(", text):
            names.append(m.group(1))

    # 去重保序
    uniq = []
    for n in names:
        if n not in uniq:
            uniq.append(n)
    return uniq


def _list_public_callables(mr) -> List[str]:
    out = []
    for n in dir(mr):
        if n.startswith("_"):
            continue
        v = getattr(mr, n, None)
        if callable(v):
            out.append(n)
    return out


def _try_call(fn, query: str):
    """
    尽量兼容各种签名：
    - 无参
    - (query)
    - (query, k)
    - (top_k=5/k=5/n=5/limit=5/max_snippets=5)
    - corpus_path / corpus_file / path 类参数
    """
    attempts: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = [
        ((), {}),
        ((query,), {}),
        ((query, 5), {}),
        ((query,), {"top_k": 5}),
        ((query,), {"k": 5}),
        ((query,), {"n": 5}),
        ((query,), {"limit": 5}),
        ((query,), {"max_snippets": 5}),
        ((query,), {"max_results": 5}),
        ((), {"top_k": 5}),
        ((), {"k": 5}),
        ((), {"n": 5}),
        ((), {"limit": 5}),
        ((), {"max_snippets": 5}),
    ]

    # 根据参数名做“智能猜测”
    try:
        sig = inspect.signature(fn)
        params = sig.parameters
        guess_kwargs = {}
        for name, p in params.items():
            if p.default is not inspect._empty:
                continue  # 有默认值就不强塞
            lname = name.lower()
            if "query" in lname:
                guess_kwargs[name] = query
            elif "k" == lname or "top_k" in lname or "limit" in lname or "n" == lname:
                guess_kwargs[name] = 5
            elif "corpus" in lname or "path" in lname or "file" in lname:
                guess_kwargs[name] = "outputs/corpus.jsonl"
        if guess_kwargs:
            attempts.insert(0, ((), guess_kwargs))
    except Exception:
        pass

    last_err = None
    for args, kwargs in attempts:
        try:
            return fn(*args, **kwargs), (args, kwargs)
        except Exception as e:
            last_err = e
            continue
    raise last_err


def main():
    query = os.getenv("FIXTURE_QUERY", "帮我总结一下我最近的主要关注点是什么？")
    prefer_fn = os.getenv("RETRIEVER_FN")  # 允许你指定函数名

    mr = _load_memory_retriever()
    public_fns = _list_public_callables(mr)

    # 候选：先从 main/tg_bot 里提取，再加常见名字，再遍历所有 callable
    extracted = _extract_candidate_names_from_files()
    common = [
        "get_recent_corpus_snippets",
        "retrieve",
        "search",
        "query",
        "retrieve_memory",
        "retrieve_relevant",
        "get_relevant",
        "memory_search",
        "retrieve_context",
    ]
    candidates = []
    for n in ([prefer_fn] if prefer_fn else []) + extracted + common + public_fns:
        if n and n not in candidates:
            candidates.append(n)

    raw = None
    used = None
    used_call = None
    tried = []

    for name in candidates:
        fn = getattr(mr, name, None)
        if not callable(fn):
            continue
        try:
            raw, used_call = _try_call(fn, query)
            used = name
            break
        except Exception as e:
            tried.append((name, str(e)))

    if raw is None:
        print("❌ 我没能自动找到可调用的 retriever 函数。")
        print("我在 memory_retriever.py 里发现这些可调用函数：")
        for n in public_fns:
            print("  -", n)
        print("\n你可以这样做：")
        print("1) 任选一个你认为是“检索”的函数名，比如上面列表里的某个")
        print("2) 用环境变量指定它再跑一次，例如：")
        print('   RETRIEVER_FN="get_recent_corpus_snippets" python3 tests/make_retriever_fixture.py')
        print("\n我尝试过的函数及失败原因（前 10 条）：")
        for n, err in tried[:10]:
            print(f"  - {n}: {err}")
        raise RuntimeError("自动选择失败（请用 RETRIEVER_FN 指定函数名）")

    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)

    to_save = raw if _is_picklable(raw) else _sanitize(raw)
    with open(FIXTURE_PATH, "wb") as f:
        pickle.dump(to_save, f)

    print(f"✅ 已生成 fixture: {FIXTURE_PATH}")
    print(f"✅ 使用的函数: {used}")
    print(f"✅ 实际调用参数: {used_call}")
    print(f"✅ 保存为: {'raw' if to_save is raw else 'sanitized'}")
    print(f"✅ raw 返回类型: {type(raw)}")


if __name__ == "__main__":
    main()
