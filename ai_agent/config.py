import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "")

# ============ 国内模型 API Keys ============
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")  # 通义千问（阿里云 DashScope）
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")  # MiniMax
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")  # 智谱 GLM
MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "")  # Kimi（月之暗面）
BAIDU_API_KEY = os.getenv("BAIDU_API_KEY", "")  # 文心一言
BAIDU_SECRET_KEY = os.getenv("BAIDU_SECRET_KEY", "")
SPARK_API_KEY = os.getenv("SPARK_API_KEY", "")  # 讯飞星火
SPARK_SECRET_KEY = os.getenv("SPARK_SECRET_KEY", "")
SPARK_APP_ID = os.getenv("SPARK_APP_ID", "")
# 字节跳动 豆包（Doubao）—— 通过火山引擎方舟（Volcengine Ark）
DOUBAO_API_KEY = os.getenv("DOUBAO_API_KEY", "")  # ARK_API_KEY
# 腾讯 混元（Hunyuan）
HUNYUAN_API_KEY = os.getenv("HUNYUAN_API_KEY", "")  # hunyuan API key
# 硅基流动（SiliconFlow）—— 一站式接入多家国产模型
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")
# 智谱 GLM 单独：GLM-Z1 系列推理模型需要单独 endpoint
GLM_API_KEY = os.getenv("GLM_API_KEY", "") or ZHIPU_API_KEY  # 别名

# ============ 模型配置 ============
# 模型类型:
#   openai      OpenAI（gpt-4o 系列）
#   deepseek    DeepSeek
#   qwen        通义千问（DashScope 兼容 OpenAI）
#   zhipu       智谱 GLM
#   moonshot    Kimi（月之暗面）
#   minimax     MiniMax
#   baidu       文心一言
#   spark       讯飞星火
#   doubao      字节豆包（火山方舟 Ark OpenAI 兼容）
#   hunyuan     腾讯混元
#   siliconflow 硅基流动（聚合：Qwen/DeepSeek/GLM/Yi 等）
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "openai")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")

# 各 provider 的默认模型名（从稳定/低价到最新，截至 2026-07）
MODEL_VERSIONS = {
    # ============== OpenAI（全球） ==============
    "openai": [
        "gpt-5.6-sol",         # 2026-06 旗舰
        "gpt-5.5",
        "gpt-5",
        "o3-mini",
        "o3",
        "o4-mini",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
    ],
    # ============== DeepSeek ==============
    # 2026-07 最新：V4 系列（pro/flash）+ V3.2
    "deepseek": [
        "deepseek-v4-pro",         # 旗舰
        "deepseek-v4-flash",       # 高性价比
        "deepseek-v3.2",
        "deepseek-v3.2-exp",       # 非思考
        "deepseek-v3.1",           # 非思考
        "deepseek-r1",             # 推理
        "deepseek-r1-0528",
        "deepseek-v3",
        "deepseek-chat",
        "deepseek-coder",
    ],
    # ============== 通义千问 Qwen ==============
    # 2026-07 最新：Qwen3.8-max-preview / 3.7-max / 3.7-plus / 3.6-plus
    "qwen": [
        "qwen3.8-max-preview",     # 2026-07 预览旗舰
        "qwen3.7-max",             # 2026-05 旗舰
        "qwen3.7-plus",            # 2026-05 增强版
        "qwen3.7-max-2026-05-17",
        "qwen3.7-max-2026-05-20",
        "qwen3.7-max-2026-06-08",
        "qwen3.6-plus",            # 平衡版
        "qwen3.6-flash",           # 极速
        "qwen3.5-omni-plus",       # 多模态
        "qwen3-coder-plus",        # 代码
        "qwen3-coder-flash",
        "qwen3-coder-next",
        "qwen3-max",
        "qwen-plus",
        "qwen-flash",
        "qwen-turbo",
    ],
    # ============== 智谱 GLM ==============
    # 2026-06-17 最新：GLM-5.2（开源 + 1M 上下文）
    "zhipu": [
        "glm-5.2",                 # 2026-06 旗舰（对标 Opus 4.8）
        "glm-5.1",
        "glm-5",
        "glm-4.7",
        "glm-4.6",
        "glm-4.5",
        "glm-4.5-air",
        "glm-z1-flash",            # 推理
        "glm-z1-air",
        "glm-4-flash",
        "glm-4-plus",
        "glm-4-long",
    ],
    # ============== Kimi (Moonshot) ==============
    # 2026-07-15 最新：Kimi K3（开源 1M 上下文，2.8T 参数）
    "moonshot": [
        "kimi-k3",                 # 2026-07 开源旗舰
        "kimi-k2.7-code",          # 2026-06 代码优化
        "kimi-k2.7-code-highspeed",
        "kimi-k2.6",
        "kimi-k2.5",
        "kimi-k2-thinking",
        "kimi-k2-0711-preview",
        "moonshot-v1-128k",
        "moonshot-v1-32k",
        "moonshot-v1-8k",
    ],
    # ============== MiniMax ==============
    # 2026-07 最新：MiniMax-M3（官方）
    "minimax": [
        "MiniMax-M3",              # 2026-07 官方旗舰
        "MiniMax-M2.7",            # 2026-05
        "MiniMax-M2.7-highspeed",
        "MiniMax-M2.5",
        "MiniMax-M2.1",
        "minimax-text-01",         # 旧名 alias
        "abab6.5s-chat",
    ],
    # ============== 文心一言 (Baidu) ==============
    # 2026 最新：ERNIE 5.0 + X1 Turbo
    "baidu": [
        "ernie-5.0",               # 2026 旗舰
        "ernie-x1-turbo-32k",      # 2025-04 深度思考
        "ernie-x1-32k",
        "ernie-4.5-turbo-128k",
        "ernie-4.5-turbo-vl-32k",  # 多模态
        "ernie-4.5-8k-preview",
        "ernie-4.0-8k",
        "ernie-4.0-turbo-128k",
        "ernie-speed-128k",
        "ernie-lite-8k",
    ],
    # ============== 讯飞星火 (Spark) ==============
    # 2026 最新：Spark 4.0 Ultra
    "spark": [
        "spark-4.0-ultra",         # 2026 旗舰
        "spark-4.0-lite",
        "spark-3.5-max",
        "spark-3.5",
        "spark-3.0",
    ],
    # ============== 字节豆包 (Doubao / 火山方舟 ARK) ==============
    # 2026-07 最新：doubao-seed-2.0-pro
    "doubao": [
        "doubao-seed-2-0-pro",     # 2026-07 旗舰
        "doubao-seed-2-0-lite",
        "doubao-seed-1.6",         # 2026 多模态
        "doubao-seed-1-6-flash",
        "doubao-1-5-thinking-pro",  # 推理
        "doubao-1-5-pro-32k",
        "doubao-pro-256k",
        "doubao-pro-32k",
        "doubao-lite-32k",
    ],
    # ============== 腾讯混元 (Hunyuan) ==============
    # 2026-07 最新：hunyuan-turbo-latest / Hy3
    "hunyuan": [
        "hunyuan-turbo-latest",    # 2026-07
        "hunyuan-Hy3",             # 新一代
        "hunyuan-large",           # 389B MoE
        "hunyuan-pro",
        "hunyuan-standard-256k",
        "hunyuan-standard",
        "hunyuan-vision",          # 多模态
        "hunyuan-turbo",
    ],
    # ============== 硅基流动 (SiliconFlow) ==============
    # 一站式接入 Qwen/DeepSeek/GLM/Kimi 等开源 + 闭源代理
    "siliconflow": [
        "Qwen/Qwen3-235B-A22B-Instruct-2507",   # 2026 Qwen3
        "Qwen/Qwen3-32B",
        "Qwen/Qwen3-Coder-480B-A35B-Instruct",
        "Qwen/QwQ-32B-Preview",
        "deepseek-ai/DeepSeek-V4-Pro",
        "deepseek-ai/DeepSeek-R1",
        "THUDM/glm-4-9b-chat",
        "moonshotai/Kimi-K2-Instruct",
        "01-ai/Yi-1.5-34B-Chat-16K",
        "meta-llama/Meta-Llama-3.1-70B-Instruct",
        "internlm/internlm2_5-20b-chat",
    ],
}

# Provider 展示信息（中文名 / Logo 字符 / 描述）—— 前端下拉分组用
# 截至 2026-07
PROVIDER_META: dict = {
    "openai":       {"label": "OpenAI",                 "group": "global",   "desc": "GPT-5.6 / GPT-5 / o3/o4 推理"},
    "deepseek":     {"label": "DeepSeek",               "group": "china",    "desc": "V4 Pro/Flash · R1 推理"},
    "qwen":         {"label": "通义千问 (Qwen)",        "group": "china",    "desc": "Qwen3.7/3.8-Max · 阿里 DashScope"},
    "zhipu":        {"label": "智谱 GLM",               "group": "china",    "desc": "GLM-5.2 · 1M 上下文 · Coding 标杆"},
    "moonshot":     {"label": "Kimi (Moonshot)",        "group": "china",    "desc": "K3 · 400 万 token · Agent 之王"},
    "minimax":      {"label": "MiniMax",                "group": "china",    "desc": "MiniMax-M3/M2.7 · 1M 上下文"},
    "baidu":        {"label": "文心一言 (Baidu)",       "group": "china",    "desc": "ERNIE 5.0 · X1 Turbo 推理"},
    "spark":        {"label": "讯飞星火 (Spark)",       "group": "china",    "desc": "Spark 4.0 Ultra"},
    "doubao":       {"label": "豆包 (Doubao)",          "group": "china",    "desc": "Doubao-seed-2.0 Pro · 字节/火山"},
    "hunyuan":      {"label": "腾讯混元 (Hunyuan)",     "group": "china",    "desc": "Hunyuan Hy3 · 389B MoE"},
    "siliconflow":  {"label": "硅基流动 (SiliconFlow)", "group": "china",    "desc": "一站式接入 Qwen/DeepSeek/GLM/Kimi"},
}

# ============ 其他配置 ============
MAX_HISTORY_LENGTH = 10
TEMPERATURE = 0.7
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Embedding 模型配置
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
EMBEDDING_MODEL_TYPE = os.getenv("EMBEDDING_MODEL_TYPE", "openai")  # openai/minimax/zhipu/jina
