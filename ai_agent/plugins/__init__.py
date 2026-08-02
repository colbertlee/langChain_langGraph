"""内置插件包。

约定：
- 每个子包提供一个或多个 Plugin 子类（PLUGIN_CLASS）。
- 同级提供 manifest.json，由 PluginManager 通过 entry_point 加载。
- 插件只声明"能力 (capabilities)"与"钩子 (hooks)"，不感知 agent 内部细节。
"""