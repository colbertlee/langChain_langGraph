"""鉴权 / HITL 渠道插件集合。

提供两类抽象：
- AuthProvider    把外部凭证（token / header / OAuth bearer）解析为 (agent_id, roles)。
- HITLNotifier    把 HITL 审批事件分发到外部渠道（飞书 / 企微 / 控制台 / Webhook）。

PermissionGuard / HumanInLoopGuard 通过 registry 加载实现，保持向后兼容。
"""