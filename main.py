import os
import requests
import datetime
import sys
import re 
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.tools import tool
from langchain_community.utilities import SerpAPIWrapper
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from memory_retriever import get_recent_corpus_snippets

# 1. 加载配置
load_dotenv()
LOG_FILE = "outputs/brain_memory.md" 

# --- 核心修复点：函数定义必须干净，不能有外部缩进代码 ---
def get_dynamic_system_prompt():
    """
    组合“基础人设”和“动态画像”。
    """
    
    # === 这里的 base_prompt 必须在函数里面 ===
    base_prompt = """
Role: 你是用户的 AI 伙伴和“第二大脑”。
Mission: 像一个老朋友一样与用户对话，利用你掌握的知识为他提供启发。
问到“最近/近期/这阵子”，优先依据：
用户最近输入记录 + 最近30天 Notion/X 摘要；
若两者都没有证据，就直接说没有证据，不要编。
Style Guidelines (强制执行):
1. **拒绝死板**: 绝对不要使用“分析师”式的汇报语气。不要列 PPT 目录。
2. **自然口语**: 就像微信聊天一样，可以说“哈哈”、“对了”、“我觉得”。
3. **格式自由**: 除非必要，否则不要使用 Markdown 列表。
"""

    # 2. 尝试读取 user_profile.md
    profile_content = ""
    if os.path.exists("outputs/user_profile.md"):
        try:
            with open("outputs/user_profile.md", "r", encoding="utf-8") as f:
                profile_content = f.read()
            print("🧠 [System] 成功加载用户动态画像 (User Profile)")
        except Exception as e:
            print(f"⚠️ [System] 画像读取失败: {e}")
    else:
        print("ℹ️ [System] 未找到 user_profile.md，将使用默认出厂设置。")

    # 3. 拼接最终的 Prompt
    full_prompt = base_prompt
    if profile_content:
        full_prompt += f"\n\n【你对用户的核心认知 (长期记忆)】\n{profile_content}\n"
    
    # --- 语气防火墙 ---
    full_prompt += "\n\nIMPORTANT INSTRUCTION: 下面附带的历史对话可能包含旧的“严肃风格”回复。请忽略那些旧的语气，必须用新的“老朋友风格”来回答！"
    
    return full_prompt

# --- 增强版工具 1: 联网搜索 (带数据验证) ---
@tool
def search_tool(query: str):
    """当需要验证事实、查询新闻或生成晨报时使用。"""
    print(f"\n🔍 [Eyes] 系统正在请求 SerpApi 搜索: {query}")
    
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        print("❌ [配置错误] 找不到 SERPAPI_API_KEY，请检查 .env 文件")
        return "系统错误：API Key 缺失。"

    try:
        search = SerpAPIWrapper(serpapi_api_key=api_key)
        result = search.run(query)
        print(f"🐛 [Debug] SerpApi 原始返回数据:\n{result}") 
        
        if not result or len(str(result)) < 10:
            return f"系统提示：搜索失败，未返回有效内容。原始数据: {result}"
        
        print(f"✅ [验证] 搜索成功，数据长度: {len(str(result))} chars")
        return result

    except Exception as e:
        print(f"❌ [错误] 搜索工具崩溃: {e}")
        return f"系统错误: {e}"

# --- 增强版工具 2: URL 读取器 (带防欺诈验证) ---
@tool
def read_url_tool(url: str):
    """读取网页内容。"""
    print(f"\n📖 [Reader] 系统正在请求 Jina 读取: {url}")
    jina_url = f"https://r.jina.ai/{url}"
    try:
        response = requests.get(jina_url, timeout=20)
        content = response.text
        
        if response.status_code != 200:
            print(f"❌ [警告] 抓取失败 (Status: {response.status_code})")
            return f"Error: HTTP {response.status_code}"
        
        if len(content) < 50:
            print(f"❌ [警告] 抓取内容过短 ({len(content)} chars)，可能是反爬虫拦截！AI 可能会瞎编。")
            return "系统警告：抓取内容无效，请不要编造摘要，直接告诉用户读取失败。"
            
        print(f"✅ [验证] 抓取成功，有效内容长度: {len(content)} chars")
        return f"网页内容:\n{content[:8000]}"
    except Exception as e:
        print(f"❌ [错误] 读取工具崩溃: {e}")
        return f"错误: {e}"

# 3. 组装大脑
tools = [search_tool, read_url_tool]
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.3,
    timeout=30,max_retries=2,).bind_tools(tools)

# --- 增强版功能 3: 记忆系统 (带写入回测) ---
def save_to_brain(source, content):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n**[{timestamp}] {source}:**\n{content}\n" + "-"*30 + "\n"
    
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
        if os.path.getsize(LOG_FILE) > 0:
            pass 
        else:
            print("❌ [严重错误] 记忆文件为空，写入可能失败！")
    except Exception as e:
        print(f"❌ [严重错误] 记忆系统失效，无法写入硬盘: {e}")

# --- 新增功能: 启动自检 (Health Check) ---
def system_health_check():
    print("🏥 正在进行系统自检...")
    if not os.getenv("GOOGLE_API_KEY"):
        print("❌ 错误: 缺少 GOOGLE_API_KEY")
        sys.exit(1)
    if not os.getenv("SERPAPI_API_KEY"):
        print("❌ 错误: 缺少 SERPAPI_API_KEY")
        sys.exit(1)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            pass
        print("✅ 记忆存储模块: 正常")
    except:
        print("❌ 错误: 无法写入 brain_memory.md，请检查文件权限")
        sys.exit(1)
    print("✅ 系统自检完成，所有链路正常。\n")

# 6. 主程序
def main():
    print(f">>> v0.6.6 修复版 已启动。")
    print(">>> 调试模式：已合并所有系统提示词。")
    
    # 1. 获取基础人设 (来自 user_profile.md)
    final_prompt = get_dynamic_system_prompt()

    # 1.5 注入最近30天 Notion/X 语料摘要（来自 corpus.jsonl）
    try:
        recent_corpus = get_recent_corpus_snippets(days=30, max_items=18)
        if recent_corpus.strip():
            final_prompt += f"\n\n{'-'*20}\n{recent_corpus}\n{'-'*20}"
            print("🧠 [Memory] 已注入最近30天 Notion/X 语料摘要。")
    except Exception as e:
        print(f"⚠️ [Corpus] 注入最近语料失败: {e}")

        # 2. 读取记忆 (brain_memory.md) 并拼接到人设后面
    def load_recent_user_memory(log_path: str, max_entries: int = 12) -> str:
        """从 brain_memory.md 里只提取最近的 User 输入（带时间戳的块），用于回答“最近/近期”类问题。"""
        if not os.path.exists(log_path):
            return ""

        with open(log_path, "r", encoding="utf-8") as f:
            content = f.read()

        sep = "-" * 30
        blocks = [b.strip() for b in content.split(sep) if b.strip()]

        user_blocks = []
        for b in blocks:
            # 存档格式示例：**[YYYY-MM-DD HH:MM:SS] User:**
            m = re.search(r"\*\*\[(.*?)\]\s*(.*?):\*\*", b)
            if not m:
                continue

            source = m.group(2).strip().lower()
            if source in ("user", "用户"):
                user_blocks.append(b)

        return "\n\n".join(user_blocks[-max_entries:])

    try:
        recent_user_memory = load_recent_user_memory(LOG_FILE, max_entries=12)
        if recent_user_memory.strip():
            final_prompt += (
                f"\n\n{'-'*20}\n"
                f"【以下是用户最近的输入记录（用于回答“最近/近期”类问题）】\n"
                f"{recent_user_memory}\n"
                f"{'-'*20}"
            )
            print(f"🧠 [Memory] 已注入最近 {len(recent_user_memory)} 字符的用户记忆。")
    except Exception as e:
        print(f"⚠️ [Memory] 读取记忆失败: {e}")

    # 3. 初始化消息列表
    messages = [SystemMessage(content=final_prompt)]

    while True:
        try:
            user_input = input("\nUser: ")
            if not user_input.strip(): continue 
            if user_input.lower() in ["q", "quit"]: break
            
            if user_input.lower() == "daily":
                user_input = "请搜索过去24小时 Crypto 市场新闻，总结3个核心要点。"

            messages.append(HumanMessage(content=user_input))
            save_to_brain("User", user_input)

            try:
                response = llm.invoke(messages)
            except Exception as e:
                print(f"❌ [调用错误] AI 思考时发生错误: {e}")
                messages.pop() 
                continue

            # ... (工具调用逻辑) ...
            if response.tool_calls:
                tool_outputs = []
                for tool_call in response.tool_calls:
                    if tool_call["name"] == "read_url_tool":
                        res = read_url_tool.invoke(tool_call["args"])
                    elif tool_call["name"] == "search_tool":
                        res = search_tool.invoke(tool_call["args"])
                    else:
                        res = "未知工具"
                    tool_outputs.append(ToolMessage(tool_call_id=tool_call["id"], content=str(res)))
                
                final_response = llm.invoke(messages + [response] + tool_outputs)
                reply = final_response.content
                
                messages.append(response)
                messages.extend(tool_outputs)
                messages.append(final_response)
            else:
                reply = response.content
                messages.append(response)

            if isinstance(reply, list):
                clean_text = ""
                for item in reply:
                    if isinstance(item, dict) and 'text' in item:
                        clean_text += item['text']
                reply = clean_text

            print(f"\nSecond Brain: \n{reply}")
            save_to_brain("Second Brain", reply)

        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    system_health_check()
    main()