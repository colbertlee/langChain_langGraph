============================================================
  AI Agent - Linux / macOS Complete Distribution
============================================================

This is a STANDALONE program. Just copy the entire folder to any
Linux x64 (or macOS arm64/x64) machine, then:

  1.  chmod +x ai-agent install.sh run.sh
  2.  ./install.sh        (creates .env and folders)
  3.  edit .env           set LLM_API_KEY=...
  4.  ./run.sh            start the CLI

NO Python install needed - everything is bundled inside ai-agent.

Files
-----
  ai-agent            main program (PyInstaller bundle)
  _internal/          Python runtime + dependencies
  install.sh          first-run setup
  run.sh              start CLI
  run-web.sh          start Web service
  .env.example        env var template
  mcp_config.json     MCP server config
  knowledge_base/     built-in knowledge base
  prompts/            prompt templates
  smoke_install.sh    smoke test (developer)
  smoke_run.sh        smoke test (developer)
  BUILD_ON_LINUX.md   how to (re)build ai-agent binary
  README.txt          this file

Quick Start
-----------
  chmod +x ai-agent install.sh run.sh
  ./install.sh
  nano .env       # set LLM_API_KEY
  ./run.sh

Then chat:
  你: 现在几点了？
  你: exit

Troubleshooting
---------------
  - "LLM_API_KEY not set":
      edit .env, set LLM_API_KEY
  - "libpython3.x.so not found":
      sudo apt install libpython3.11   (Ubuntu)
      sudo yum install python3-libs    (RHEL)
  - "Permission denied":
      chmod +x ai-agent run.sh
  - matplotlib errors:
      run.sh sets MPLBACKEND=Agg automatically
  - The ai-agent binary is missing:
      See BUILD_ON_LINUX.md to build it on a Linux host

Uninstall
---------
  Just delete this entire folder.

============================================================
