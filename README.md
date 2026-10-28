# MaiBot MOSS 绘图

MaiBot 的 MOSS 生图插件：原文直出、官方 Caption／Layout 规划、单页漫画与表情包、风格与 OC、模板抽卡，通过 ComfyUI 发送到 QQ。

[![Release](https://img.shields.io/github/v/release/YayiMiko/maibot_plugin_moss_image?label=release)](https://github.com/YayiMiko/maibot_plugin_moss_image/releases)
[![CI](https://github.com/YayiMiko/maibot_plugin_moss_image/actions/workflows/checks.yml/badge.svg)](https://github.com/YayiMiko/maibot_plugin_moss_image/actions/workflows/checks.yml)
[![License](https://img.shields.io/github/license/YayiMiko/maibot_plugin_moss_image)](LICENSE)

最新 Release：[v0.2.7](https://github.com/YayiMiko/maibot_plugin_moss_image/releases/tag/v0.2.7)。`main` 还可能包含未发布改动；离线测试通过不代表服务器加载、真实 QQ 收图或画面效果已验收。

[使用说明](docs/usage.md) · [抽卡说明](docs/aesthetic-draw.md) · [配置示例](docs/config.example.toml) · [更新记录](docs/CHANGELOG.md) · [开发说明](docs/development.md)

## 快速开始

需要 MaiBot 1.3.x、Plugin SDK 2.8.2～2.13.x、Python 3.12+，以及可访问的 ComfyUI。

1. 将插件目录放入 MaiBot `plugins/`，按 `pyproject.toml` 安装依赖。
2. 在插件配置页填写 **MaiBot 所在机器** 能访问的 ComfyUI 地址，并确认模型文件名与 ComfyUI 一致。
3. 发送第一条指令：

```text
/moss 生成 成年旅人在雨后的车站等车
```

完整配置项见[配置示例](docs/config.example.toml)。当前 `main` 的配置页底部“运行时状态（只读）”会显示当前风格库、OC 名称和运行任务数，刷新页面后更新。

跨机器部署不能把回环地址当成用户电脑。插件不会启动本地 ComfyUI，也不会从历史消息或“最新图片”隐式取图。

## 能做什么

| 功能 | 指令 | 说明 |
|---|---|---|
| 原文直出 | `/moss 生成 <要求>` | 保留原始描述，只拼接固定前缀、显式风格和必要身份说明 |
| 官方规划 | `/moss 规划 <要求>` | 使用随插件携带的官方 Caption skill |
| 官方布局 | `/moss 布局 <要求>` | 使用官方 Layout 规划与编译器 |
| 单页漫画 | `/moss 漫画 <剧情> [+OC]` | 一次采样，支持 1～4 格和固定对白 |
| 静态表情包 | `/moss 表情包 <要求> [+OC]` | 一次一张，默认方图，可配字 |
| 模板抽卡 | `/moss 抽卡 <要求>` | 自动发现参考、审核模板并生图 |
| 风格库 | `/moss 风格` | 查看、新建、编辑共享风格 |
| OC 角色 | `/moss 角色` | 管理外观、服装、别名和权限 |
| 法术解析 | `/moss 解析法术` | 读取原图元数据，不调用视觉模型 |
| 图片反推 | `/moss 反推` | 用宿主 VLM 输出可见画面 tags，不自动生图 |

直接发送 `/moss` 查看帮助。不提供状态、调试、任务恢复或“最新图片”指令；普通聊天提到 MOSS 不会触发生成。

## 常用配置

| 配置 | 作用 | 示例 |
|---|---|---|
| `connection.enabled` | 是否启用插件 | `true` |
| `connection.comfyui_base_url` | MaiBot 能访问的 ComfyUI 地址 | `http://100.64.0.10:8188` |
| `planning.model_task` / `model_name` | 生图规划模型；留空使用任务路由 | `utils` / 留空 |
| `vision.model_task` / `model_name` | 反推视觉模型；留空沿用 `vlm` | `vlm` / 留空 |
| `draw.enabled` | 是否启用模板抽卡 | `false` |
| `draw.tavily_api_key` | 抽卡搜索凭据 | `tvly-...` |
| `characters.admin_user_ids` | 可管理其他人 OC 的 QQ 用户 | `["123456789"]` |
| `styles.positive_prefix` | 仅生成模式使用的正面前缀 | `best quality, highres,` |

模型文件、采样器、缓存预算和任务保留策略属于维护项，默认隐藏在配置页；需要时直接编辑 `config.toml`。

## 常用玩法

### 生成与画幅

```text
/moss 生成 夕阳洒在她身上，比例4：3
/moss 生成 白猫睡在窗边 --尺寸 1024x1024
```

支持中英文冒号、空格和相邻标点；引号里的比例会保留为画面文字。明确尺寸须为 16 的倍数，且不超过配置的像素上限。

### 风格与 OC

默认提供 `立绘` 风格，可直接用 `@立绘` 调用；其他风格先创建，再在每次请求中显式调用。未指定时不自动套用。

```text
/moss 风格 新建 墨色=monochrome ink illustration,
/moss 生成 狐莉站在雨夜街头 @墨色 +狐莉
/moss 生成 狐莉站在雨夜街头 @立绘 +狐莉

/moss 角色 新建 狐莉=白发、蓝眼睛的小狐娘，狐狸耳朵
/moss 角色 服装 狐莉=白色连衣裙
/moss 漫画 狐莉和荧争抢最后一个包子 +狐莉
```

名称含空格时使用引号，例如 `@"墨色 风格" +"狐 莉"`。完整选择器规则见[使用说明](docs/usage.md)。

### 模板抽卡

```text
/moss 抽卡 鸣潮角色卡缇希娅
```

抽卡会先发现公开参考，再判断“这张图能否作为本次模板”，通常可用即停，最多审核三张；参考图只用于分析，不作为图生图输入。配置和失败边界见[抽卡说明](docs/aesthetic-draw.md)。

## 故障排查

| 现象 | 先检查 |
|---|---|
| 提示 MOSS 已关闭或没有权限 | `connection.enabled`、`connection.allowed_sender_ids` 和宿主权限 |
| `remote_connect_timeout` / 连不上 ComfyUI | 地址是否从 MaiBot 机器可达；ComfyUI 是否以 `--listen 0.0.0.0` 启动；Tailscale／防火墙 |
| 模型文件不存在 | `rendering.unet_name`、`clip_name`、`vae_name` 是否与 ComfyUI 完全一致 |
| 队列已满 | `connection.max_pending`，或等待当前任务结束 |
| 抽卡未启用 | `draw.enabled` 和 `draw.tavily_api_key` |
| 找不到风格或角色 | 用 `/moss 风格`、`/moss 角色` 查看；确认 `@名称`、`+名称` 拼写 |
| 反推未完成 | 附一张静态图或引用同一会话的目标图片；多图时单独指定 |
| 发送超时或未确认 | 查看任务记录；不要重复发送，未知远端任务不会自动重试 |

<details>
<summary><strong>进阶：生成、任务与隐私</strong></summary>

- `/moss 生成` 不调用正文优化模型，不翻译、不扩写、不转成 tags，也不进入官方 Caption 编译。
- 任务按会话、用户和消息编号去重，保存独立配置快照、随机 seed 和输出目录；GPU 提交串行。
- 成功只发送图片。`remote_unknown`／`delivery_unknown` 不会自动重提或重发；只有明确的平台消息 ID 回执才算已发送。
- 原始 LLM 返回只保留最近一次任务的诊断，不自动发到 QQ，也不写入历史任务。
- 任务记录默认保留 30 天，仅清理已结束任务；未知远端任务、活动任务和链接目标保留。
- 图片反推会把输入缩至最长边 1536 并重编码，移除原图元数据；不叠加前缀或风格。

详细机制、Danbooru 校正、发送语义和离线验证见[开发说明](docs/development.md)。

</details>

## 文档

| 文档 | 内容 |
|---|---|
| [使用说明](docs/usage.md) | 指令、选择器、风格、OC、漫画、表情包、抽卡和反推示例 |
| [抽卡说明](docs/aesthetic-draw.md) | 抽卡配置、来源、审核边界和验收 |
| [配置示例](docs/config.example.toml) | 不含凭证的 `config.toml` 模板 |
| [开发说明](docs/development.md) | 架构、运行行为、任务、隐私和离线验证 |
| [更新记录](docs/CHANGELOG.md) | 版本变更 |
| [NOTICE](NOTICE) | 上游来源和版权说明 |

## License

原插件代码使用 MIT；官方 MOSS skill 保留其 Apache-2.0 许可。
