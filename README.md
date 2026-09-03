# Noctalia Omarchy Menu

把 Omarchy 4 的完整系统菜单带到 **Niri + Noctalia**：Apps、Learn、Trigger、Style、Setup、Install、Remove、Update、About 和 System 都在一个原生 Noctalia 浮动面板中。

本项目不是 Omarchy 或 Noctalia 的官方组件。它不会启动 Omarchy Shell，也不会接管 Noctalia 的状态栏、通知、剪贴板、锁屏或 OSD。

> 当前版本：`0.1.0`，面向 Noctalia 5、插件 API 24 和 Omarchy 4。

## 功能

- 直接读取本机 Omarchy 菜单，不维护一份容易过期的菜单副本。
- 将已审查的 Hyprland/Omarchy Shell 操作映射到 Niri 或 Noctalia。
- 保留 Omarchy 原有的 Install、Remove、Update、About、System 等菜单结构。
- 支持搜索、鼠标、方向键、翻页键和层级导航。
- 不兼容的项目仍会显示，但会被禁用并标出原因。
- 首次成功加载后缓存已脱敏的视图；再次打开时先显示缓存，再在后台刷新。
- 叶子操作使用目标级校验，避免在执行前重新计算所有无关菜单状态。

键盘操作：

| 按键 | 行为 |
| --- | --- |
| `↑` / `↓` | 选择上一项 / 下一项 |
| `PageUp` / `PageDown` | 向上 / 向下翻页 |
| `←` | 返回上一级 |
| `→` | 打开菜单或执行所选操作 |
| `Enter` | 搜索框聚焦时执行当前所选项 |
| `Esc` | 关闭面板（由 Noctalia 处理） |

## 截图

截图将在首个公开版本发布后补充。这里暂不使用与实际界面不一致的示意图。

## 依赖

核心环境：

- Omarchy 4，且系统菜单位于 `/usr/share/omarchy/default/omarchy/omarchy-menu.jsonc`
- Noctalia 5，支持插件 API 24
- Niri
- Python 3

`plugin.toml` 声明的直接依赖是 `python3` 和 `omarchy`。部分可选功能还需要下列命令；缺少依赖时，相应菜单项会被安全禁用：

| 功能 | 额外命令 |
| --- | --- |
| 区域 OCR | `slurp`、`grim`、`tesseract`、`wl-copy` |
| 二维码识别 | `slurp`、`grim`、`zbarimg`、`wl-copy` |
| 字体菜单 | `fc-list` 以及 Omarchy 自带的字体辅助命令 |
| 录屏 | Omarchy 录屏命令及可用的桌面门户 |

OCR 默认使用英语。可通过环境变量指定已安装的 Tesseract 语言，例如 `OMARCHY_OCR_LANGS=eng+chi_sim`。

## 当前兼容快照

仓库当前审计的是 `omarchy-dev 4.0.0.r2014.gf99d33a-1`（上游提交 [`f99d33a`](https://github.com/basecamp/omarchy/commit/f99d33a)）以及 Noctalia `5.0.0-beta.10` / 插件 API 24。

`compatibility.json` 会精确固定 Omarchy 辅助脚本的内容摘要，因此其他 Omarchy 构建即使菜单结构相同，也可能将受影响的操作安全禁用。安装后请先运行 `python3 tools/audit_compatibility.py`；若不是 `ok: true`，请等待对应快照更新或按下文流程完成审查，不要直接替换摘要。

## 安装

克隆仓库，然后只复制运行时文件：

```bash
git clone https://github.com/misakait/noctalia-omarchy-menu.git
cd noctalia-omarchy-menu

plugin_dir="$HOME/.local/share/noctalia/plugins/omarchy-menu"
install -d "$plugin_dir/scripts"
install -m 0644 plugin.toml panel.luau menu_adapter.py compatibility.json "$plugin_dir/"
install -m 0755 \
  scripts/capture-qr \
  scripts/capture-text \
  scripts/font-set \
  scripts/system-reboot \
  scripts/system-shutdown \
  "$plugin_dir/scripts/"

noctalia plugins lint "$plugin_dir"
noctalia msg plugins enable misakait/omarchy-menu
```

如果 Noctalia 当前没有运行，最后一条命令会失败；登录图形会话后在 Noctalia 的插件设置中启用 `misakait/omarchy-menu`，或再次运行该命令即可。安装前请自行备份同名插件目录；上面的命令不会删除仓库之外的文件。

## Niri 快捷键

在 `~/.config/niri/config.kdl` 的 `binds` 块中加入：

```kdl
Mod+Alt+Space hotkey-overlay-title="Omarchy Menu" {
    spawn "noctalia" "msg" "panel-toggle" "misakait/omarchy-menu:menu";
}
```

在通常的 Niri 配置中，`Mod` 对应 Super/Win 键，因此默认组合是 **Super+Alt+Space**。这不会改动 `Mod+Space` 的 Noctalia 应用启动器。

Omarchy 的 About 和浮动终端窗口可选用以下规则：

```kdl
window-rule {
    match app-id=r#"^org\.omarchy\.about$"#
    open-floating true
}
window-rule {
    match app-id=r#"^org\.omarchy\.terminal$"#
    open-floating true
}
```

修改后检查配置：

```bash
niri validate
```

## 缓存与刷新

面板通过 Noctalia 的 `pluginDataDir()` 保存 `menu-cache-v1.json`，不假设数据目录的绝对路径。缓存只包含适配器输出的脱敏视图模型，最大接受 2 MiB；不会缓存原始命令、guard 表达式或执行载荷。

每次打开面板仍会在后台重新读取 Omarchy 系统菜单、可选的用户扩展 `~/.config/omarchy/extensions/omarchy-menu.jsonc` 和兼容清单。新结果校验成功后才会替换当前界面与缓存；刷新失败时保留最后一个可用版本。

## 安全模型

这个项目的菜单会执行真实的系统操作。选择 Install、Remove、Update、Logout、Reboot 或 Shutdown 前，请确认自己选择的项目。

- 插件本身不增加二次确认，以保持 Omarchy 原版菜单的交互；Omarchy 命令自身已有的提示和确认仍会保留。
- 每个 Omarchy 系统 action/provider 必须匹配 `compatibility.json` 中的精确签名。
- 已审查的 `omarchy-*` 辅助脚本及其依赖闭包使用 SHA-256 固定；脚本变更后对应操作会失败关闭，而不是静默放行。
- 面板只收到经过白名单过滤的视图模型，不包含原始 action、dispatch 载荷或 guard。
- 执行时必须同时匹配当前 revision、菜单 ID 和不透明 action token，并重新检查所选项目的可见性、启用状态和依赖。
- 脚本映射只能从插件目录内解析，子进程使用关闭的标准流并与适配器进程分离。
- 永远不要直接修改 `/usr/share/omarchy`；该目录由 Omarchy 软件包管理。

## Omarchy 升级后的 audit / regenerate

Omarchy 更新可能新增菜单项、改变 action 签名，或修改辅助脚本。更新后先在项目目录运行只读审计：

```bash
python3 menu_adapter.py audit
# 或查看完整审计报告：
python3 tools/audit_compatibility.py
```

退出码为 `0` 且报告中的 `ok` 为 `true` 才表示当前兼容清单完整。失败时，现有清单会让新增或改变的操作保持不可执行。

不要在未审查差异时直接发布重新生成的清单。维护者流程是：

1. 对照 `/usr/share/omarchy/default/omarchy/omarchy-menu.jsonc` 检查新增、删除和签名改变的项目。
2. 阅读发生变化的 `/usr/bin/omarchy-*` 脚本及其相关依赖，确认它们在 Niri 下是否安全。
3. 在 `tools/generate_compatibility.py` 中明确更新映射、禁用分类、依赖和审计的软件包版本。
4. 运行生成器并逐项审查 diff：

   ```bash
   python3 tools/generate_compatibility.py
   git diff -- compatibility.json tools/generate_compatibility.py
   ```

5. 重新运行 audit、完整测试和 Noctalia lint。只有全部通过后，才把新的 `compatibility.json` 安装到插件目录。

## 开发与测试

```bash
python3 -m unittest discover -s tests -v
python3 tools/audit_compatibility.py
python3 menu_adapter.py render >/dev/null
noctalia plugins lint .
niri validate
```

测试使用惰性 fixture，不会执行真实的 Omarchy 菜单 action。请勿使用真实 revision/token 手动调用 `dispatch` 来做冒烟测试。

项目结构：

```text
plugin.toml                  Noctalia 插件清单
panel.luau                   原生面板、导航和缓存
menu_adapter.py              菜单解析、兼容处理和安全 dispatch
compatibility.json           当前已审查的 Omarchy 清单
scripts/                     Niri/Noctalia 专用映射脚本
tools/                       兼容清单审计与生成工具
tests/                       Python 与 Luau 契约测试
```

## English

Noctalia Omarchy Menu exposes the full Omarchy 4 menu as a native Noctalia 5 panel for Niri. It reads the installed Omarchy menu, maps reviewed compositor-specific actions to Niri/Noctalia, keeps unsupported entries visible but disabled, and never starts Omarchy Shell.

The panel requires plugin API 24. Install the runtime files into `~/.local/share/noctalia/plugins/omarchy-menu`, enable `misakait/omarchy-menu`, and bind `Mod+Alt+Space` to:

```bash
noctalia msg panel-toggle misakait/omarchy-menu:menu
```

Cached data is a redacted view model only; every open triggers a background refresh. Action dispatch is fail-closed and validates the current revision, entry ID, action token, state, exact compatibility signature, and audited helper digests. The plugin adds no extra confirmation, so real update/install/remove/power actions should be selected with care.

After every Omarchy upgrade, run `python3 tools/audit_compatibility.py`. Do not regenerate and publish `compatibility.json` until every upstream change has been reviewed and the full test suite passes.

## License

[MIT](LICENSE) © 2026 Misakait
