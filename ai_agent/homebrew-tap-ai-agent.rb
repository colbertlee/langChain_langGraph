# Homebrew Formula for AI Agent
#
# 安装方式（用户）：
#   brew tap colbertlee/tap
#   brew install ai-agent
#
# 仓库结构（用户需创建独立 repo: homebrew-tap）：
#   homebrew-tap/
#     Formula/
#       ai-agent.rb       ← 本文件
#     README.md
#
# 自动化发布流程（可选）：
#   1. 创建新 repo: github.com/colbertlee/homebrew-tap
#   2. 把 Formula/ 目录 push 上去
#   3. 更新 version / sha256 字段（用 brew release 自动）
#   4. 用户：`brew update && brew upgrade ai-agent`

class AiAgent < Formula
  desc "AI Agent Console — LangChain + LangGraph + MCP backend with React UI"
  homepage "https://github.com/colbertlee/langChain_langGraph"
  url "https://github.com/colbertlee/langChain_langGraph/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "fa760fe0ebbf6e90baa84024311ff92db26d96848cc379f6f7580dde73495d54"
  license "MIT"
  head "https://github.com/colbertlee/langChain_langGraph.git", branch: "main"

  depends_on "python@3.11"

  # ─────────────── 安装 ───────────────
  def install
    # 进入 ai_agent 子目录（不是 root）
    cd "ai_agent" do
      # 创建 venv 隔离依赖
      virtualenv_install_with_resources
    end
  end

  # ─────────────── 测试 ───────────────
  test do
    # smoke test：跑 13 个 pytest
    cd "ai_agent" do
      system libexec/"bin/python", "-m", "pytest", "tests/", "-v", "--tb=short"
    end
  end
end
