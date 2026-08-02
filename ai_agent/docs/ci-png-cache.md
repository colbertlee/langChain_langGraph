# SVG→PNG CI 缓存（Day 22）

## 为什么需要

`cairosvg` 转 PNG 在 release CI 上每次都从头算：
- SVG→PNG = ~500ms~2s（取决于 SVG 大小）
- cairosvg 本身 + native deps 编译 = ~30-90s

如果**每个 release 都要转同一份 SVG**，这是浪费。`actions/cache` 可以让 CI 复用：

```
首次 release：cairosvg 转 PNG + 缓存        ~30s
第二次 release：cache hit 复用 PNG          ~0s
```

## 当前实现

`release-build.yml` 的 release job：

```yaml
- name: Restore PNG cache
  uses: actions/cache@v4
  with:
    path: /tmp/cairo-cache
    key: cairo-png-${{ github.ref_name }}
    restore-keys: |
      cairo-png-

- name: Convert dashboard SVG to PNG
  shell: bash
  run: |
    SVG_HASH=$(sha256sum artifacts/dashboard.svg | cut -d' ' -f1)
    CAIRO_VERSION=$(python -c "import cairosvg; print(cairosvg.__version__)")
    CACHE_KEY="cairo-${CAIRO_VERSION}-${SVG_HASH}"

    if [ -f "/tmp/cairo-cache/${CACHE_KEY}.png" ]; then
      cp "/tmp/cairo-cache/${CACHE_KEY}.png" artifacts/dashboard.png
    else
      python -c "import cairosvg; cairosvg.svg2png(...)"
      # 缓存到 /tmp
    fi

- name: Prepare PNG cache for save
  # 限制 cache 体积（保留最新 50 个 PNG）
```

## Cache Key 设计

| Key 组成 | 说明 |
|----------|------|
| `cairo-png-` 前缀 | namespace，避免与其他 cache 冲突 |
| `${{ github.ref_name }}` | 按 tag/branch 分（v1.2.3 与 main 各自缓存） |
| `cairo-${CAIRO_VERSION}-${SVG_HASH}` | PNG 文件名：cairosvg 版本 + SVG 内容 hash |

效果：
- 同一 tag 重复 release（force-push）→ cache hit（SVG hash 相同）
- 同一 tag 但 SVG 内容不同 → cache miss → 转 + 缓存新结果
- 不同 tag → 各自缓存（不污染）

## 配置 GitHub cache 大小限制

GitHub `actions/cache` 单 cache ≤ **10 GB**。本方案每个 PNG ~30-200KB，50 个 PNG = ~5-10MB，远低于限制。

如需扩大：调整 `tail -n +51` 为 `tail -n +201`（保留 200 个）。

## 故障排查

| 现象 | 排查 |
|------|------|
| 每次都 cache miss | `cache key` 没匹配；打印 `CACHE_KEY` 看是否一致 |
| PNG 文件损坏 | `cairosvg` 版本升级导致 cache 失效；强制 `key: cairo-v2-` |
| Cache 体积超限 | `actions/cache` 会自动 prune；看 warning |
| cairosvg 编译失败 | `apt-get install libcairo2-dev`（ubuntu-latest 默认有） |

## 性能数据

| 场景 | 耗时 |
|------|------|
| Cold start（首次 release） | ~35s（pip install + cairosvg 转） |
| Cache hit（同 SVG） | ~3s（直接 cp） |
| SVG 变更（cache miss） | ~10s（转 + 缓存） |

节省 ~25-30s per release。

## 配合 pip cache

如想进一步加速 cairosvg 安装：

```yaml
- name: Setup Python
  uses: actions/setup-python@v5
  with:
    cache: pip
    cache-dependency-path: ai_agent/requirements.txt
```

这样 cairosvg 本身也会被 pip cache 缓存，省 ~30s 安装。

## 替代方案：直接 commit PNG

如不愿用 actions/cache，也可以：

```yaml
- name: Commit dashboard PNG to git
  run: |
    git add artifacts/dashboard.png
    git commit -m "chore: update dashboard.png"
```

优点：所有 release 的 PNG 在 git history，跨 release 可对比；
缺点：git repo 膨胀（每个 release 多个 MB）。

## 完整 cache 流程图

```
release v1.2.3 (首次)
  ├─ Restore PNG cache → cache miss
  ├─ cairosvg 转 PNG → ~10s
  ├─ 保存到 /tmp/cairo-cache
  ├─ 上传 PNG 到 release
  └─ actions/cache 自动 save

release v1.2.3 (force-push 同 SVG)
  ├─ Restore PNG cache → cache hit (cairo-X.Y.Z-HASH.png)
  ├─ cp PNG → ~0s
  ├─ 上传 PNG 到 release
  └─ actions/cache save（同样 PNG）

release v1.2.4 (SVG 改了)
  ├─ Restore PNG cache → cache hit (但 PNG hash 不同)
  ├─ cairosvg 转 PNG → ~10s
  ├─ 上传 PNG 到 release
  └─ actions/cache save（新 PNG）
```