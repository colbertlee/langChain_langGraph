# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置（跨平台版）
- 入口：main.py（CLI）；要打 Web 服务版把 main.py 改为 app.py 重新打包
- 平台：Windows / Linux / macOS
- 同一份 spec，三端通用
- 已剔除 Windows 专属参数（win_xxx / codesign_identity / entitlements_file）
"""
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

IS_WINDOWS = sys.platform.startswith('win')
IS_MAC     = sys.platform == 'darwin'

block_cipher = None

# 数据文件（langchain_chroma / rfc3987_syntax 等带 .lark / .json / .csv 资源）
datas = [
    ('knowledge_base', 'knowledge_base'),
    ('prompts', 'prompts'),
    ('.env.example', '.'),
    ('mcp_config.json', '.'),
]
for pkg in ['rfc3987_syntax', 'langchain_chroma', 'langchain_community',
            'chromadb', 'langgraph', 'langchain', 'jsonschema']:
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass

# LangChain / LangGraph / MCP 子模块较多，必须显式收
hidden = []
for pkg in [
    'langchain', 'langchain_core', 'langchain_openai', 'langchain_community',
    'langchain_chroma', 'langchain_text_splitters',
    'langgraph', 'langgraph.checkpoint', 'langgraph.checkpoint.sqlite',
    'mcp', 'mcp.server', 'mcp.client',
    'chromadb', 'chromadb.api',
    'uvicorn', 'uvicorn.loops', 'uvicorn.loops.auto',
    'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.websockets',
    'uvicorn.lifespan', 'uvicorn.lifespan.on',
    'starlette', 'fastapi', 'sse_starlette',
    'pandas', 'numpy', 'matplotlib',
    'akshare', 'serpapi',
]:
    hidden += collect_submodules(pkg)

# 跨平台 excludes
EXCLUDES = [
    'tkinter', 'test', 'unittest', 'pydoc',
    'matplotlib.tests', 'numpy.tests', 'pandas.tests',
    'IPython', 'jupyter', 'notebook',
]
# Windows 专属模块在 Linux/macOS 上本来就没有，但显式排除更稳
if not IS_WINDOWS:
    EXCLUDES += ['win32api', 'win32com', 'win32gui', 'winreg']
# onnxruntime / torch 在 Linux PyInstaller 下会触发 pybind11 ABI 冲突
# （典型错误：generic_type: cannot initialize type "GradBucket"）
# 我们没直接用 torch（embedding 走 OpenAI），所以安全排除
if not IS_WINDOWS:
    EXCLUDES += ['onnxruntime', 'onnxruntime.capi', 'onnxruntime.tools',
                 'onnxruntime.transformers', 'onnxruntime.training',
                 'torch', 'torchvision', 'torchaudio']

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=sorted(set(hidden)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 跨平台 name：Windows 加 .exe，其他平台不加
exe_name = 'ai-agent.exe' if IS_WINDOWS else 'ai-agent'

# 跨平台 icon：仅 Windows + macOS 需要，且文件必须存在
import os
icon = None
if IS_WINDOWS and os.path.exists('icon.ico'):
    icon = 'icon.ico'
elif IS_MAC and os.path.exists('icon.icns'):
    icon = 'icon.icns'

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=exe_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,                 # CLI 程序，保留控制台
    disable_windowed_traceback=False,
    target_arch=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ai-agent',
)
