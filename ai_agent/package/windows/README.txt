============================================================
  AI Agent - Windows Complete Distribution
  Size: ~470 MB (zip)  /  ~1.16 GB (unpacked)
============================================================

This is a STANDALONE program. Just copy the entire folder to any
Windows 10/11 x64 machine, then:

  1. Double-click  install.bat
     (creates .env and logs/uploads/data folders)

  2. Open  .env  in Notepad and fill in your LLM_API_KEY

  3. Double-click  run.bat  to start the CLI

NO Python install needed - everything (Python 3.14, LangChain 1.x,
LangGraph, MCP, ChromaDB, etc.) is bundled inside ai-agent.exe.

Files
-----
  ai-agent.exe         main program (110 MB, PyInstaller bundle)
  _internal/           Python runtime + all dependencies (do not delete)
  install.bat          first-run setup script
  run.bat              start CLI (default)
  run-web.bat          start Web service (requires re-pack with app.py)
  .env.example         env var template
  mcp_config.json      MCP server config
  knowledge_base/      built-in knowledge base
  prompts/             prompt templates
  smoke_install.ps1    smoke test for install.bat (developer)
  smoke_run.ps1        smoke test for run.bat (developer)
  smoke_run_real.ps1   smoke test that actually launches ai-agent.exe
  README.txt           this file

Quick Start
-----------
  Step 1:  Double-click install.bat
  Step 2:  Open .env in Notepad, set LLM_API_KEY=sk-...
  Step 3:  Double-click run.bat

Then you can chat with the agent, e.g.:
  你: 现在几点了？
  你: 计算 2 + 3 * 4
  你: 读取文件 README.md
  你: exit

Troubleshooting
---------------
  - "LLM_API_KEY not set":
      Edit .env, set LLM_API_KEY=your_key
  - Windows Defender warning:
      Click "More info" -> "Run anyway"
      (or sign the exe with a code-signing certificate)
  - Chinese display:
      run.bat sets chcp 65001 automatically
  - matplotlib / display errors:
      run.bat sets MPLBACKEND=Agg automatically

Data Storage
------------
  All runtime data lives in this folder:
    .env             your config (created by install.bat)
    memory.db        conversation history
    context.db       context store
    logs/            runtime logs
    uploads/         uploaded files
    data/            misc data

To reset state, delete the .db files and the three folders.

Uninstall
---------
  Just delete this entire folder.

============================================================
