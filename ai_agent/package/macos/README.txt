============================================================
  AI Agent - macOS Complete Distribution
  Architectures: Apple Silicon (arm64) / Intel (x86_64)
============================================================

This is a STANDALONE program. Just copy the entire folder to your
Mac, then:

  1.  chmod +x ai-agent install.sh run.sh
  2.  xattr -dr com.apple.quarantine ai-agent   (remove Gatekeeper quarantine)
  3.  ./install.sh        (creates .env and folders)
  4.  edit .env           set LLM_API_KEY=...
  5.  ./run.sh            start the CLI
  6.  ./run-web.sh        start the Web service (browser: http://localhost:8000)

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
  README.txt          this file

Quick Start
-----------
  chmod +x ai-agent install.sh run.sh
  xattr -dr com.apple.quarantine ai-agent
  ./install.sh
  nano .env       # set LLM_API_KEY
  ./run.sh

Then chat:
  你: 现在几点了？
  你: exit

Gatekeeper / First-launch
-------------------------
If macOS says "ai-agent cannot be opened because the developer cannot be verified":

  System Settings -> Privacy & Security -> scroll down ->
  click "Open Anyway" next to the ai-agent message.

Or via CLI (for the folder):
  xattr -dr com.apple.quarantine ai-agent

Architectures
-------------
  Apple Silicon (M1/M2/M3/M4):  ai-agent-macos-arm64.tar.gz
  Intel (x86_64):                ai-agent-macos-x64.tar.gz

Verify with `uname -m`:
  uname -m    # arm64 or x86_64

Troubleshooting
---------------
* "ai-agent is damaged" - run the xattr command above
* Port 8000 in use      - set PORT=9000 in .env before ./run-web.sh
* LLM API call fails    - double-check the API key in .env, then `cat agent.log`
* Web UI blank          - open browser devtools, ensure backend is on /api/health

Building from source
--------------------
On macOS, build with PyInstaller:
  cd ../..
  python -m pip install -r requirements.txt
  pyinstaller ai_agent.spec
  # Output: dist/ai-agent/ai-agent
  # Package into this folder as part of release.

More info: https://github.com/colbertlee/langChain_langGraph