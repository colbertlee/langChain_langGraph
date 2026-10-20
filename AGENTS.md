# AGENTS.md · 跨工具入口指针

本项目的完整开发档案见 [`docs/PROMPT-PACK.md`](file:///e:/langChain_langGraph/docs/PROMPT-PACK.md)，AI 助手行为细则见 [`AGENT_RULES.md`](file:///e:/langChain_langGraph/AGENT_RULES.md)，代码实际约定见 [`CONVENTIONS.md`](file:///e:/langChain_langGraph/CONVENTIONS.md)，动手前先读这三份。

如果你被要求"继续开发本项目的 agent"：
1. 读完 `docs/PROMPT-PACK.md` 第 0、1、3 章。
2. 读完 `AGENT_RULES.md` §1（工作流程）、§4（工具权限边界）、§7（红线）。
3. 遵守第 1.4（硬性约束）与第 1.6（反幻觉纪律），冲突时以 PROMPT-PACK §1.4/§1.6 为准（见 `AGENT_RULES.md` §6）。
4. 完成后按 `docs/PROMPT-PACK.md` 第 4、5 章更新产出清单与未决问题，并在第 2 章追加本轮原文（优先用 `scripts/build-prompt-pack.ps1` 机械重建）。