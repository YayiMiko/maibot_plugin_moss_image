# MaiBot MOSS 绘图

独立 MaiBot 插件：使用官方 MOSS-Image Prompt Enhancer skill 将自然语言规划为
Caption 或 Layout，通过 ComfyUI 的 MOSS 工作流生成图片并发送到 QQ。

当前版本 **v0.1.1**。已完成离线验证，尚未部署或完成真实 QQ／图像质量验收。

[下载发布包](https://github.com/YayiMiko/maibot_plugin_moss_image/releases/latest) · [更新记录](docs/CHANGELOG.md) · [开发说明](docs/development.md)

## 指令

```text
/moss 少女在雨后的车站等车
/moss 布局 一张咖啡店海报，标题写“今日也要好好休息”
/moss 无优化 A quiet railway platform after the rain.
/moss 解析法术
```

只提供以上四种写法；直接 `/moss` 查看帮助。不提供角色／风格管理、状态、
调试、任务核对或恢复指令。普通聊天提到 MOSS 不触发生成。

可用 `--尺寸 1024x1024` 或 `--比例 16:9` 设置单次画幅。明确尺寸须为 16 倍数，
且满足配置的像素上限；不静默改尺寸。默认使用本机工作流的 3:4、1MP 策略，
换算采用 ComfyUI ResolutionSelector 的 `MP × 1024²` 定义，对齐 16。
Layout 先固定尺寸再规划，Latent 使用同一尺寸，不在采样阶段重新计算。

## 安装与配置

需要 MaiBot 1.3.x、Plugin SDK 2.8.2～2.13.x、Python 3.12+，以及可访问的
ComfyUI。宿主的群聊白名单／发送权限仍然有效。

将完整插件目录放入 MaiBot `plugins/`，按 `pyproject.toml` 安装依赖，并配置：

1. `connection.comfyui_base_url`：从 **MaiBot 所在机器** 能访问的 ComfyUI 地址。
2. `planning.model_task`／`model_name`：宿主已配置的规划模型；不会注入聊天人设。
3. `rendering`：与 ComfyUI 文件名一致的 MOSS 主模型、编码器和 VAE。

[配置示例](docs/config.example.toml) 不含凭证，需要时复制到插件根目录并命名为
`config.toml`。跨机器部署不能把回环地址当成
用户电脑，插件不会启动本地 ComfyUI。仅启用文生图，图片只用于法术解析，
不是像素级图生图，也不会从历史消息或“最新图片”隐式取图。

原图缓存读取可设置 `connection.qq_cache_roots`，只允许指定的 QQ 缓存挂载根目录。
未设置时仍可使用受限 QQ HTTPS URL，不读取任意本地文件。法术解析保留原图
元数据，不调用视觉模型或自动反推；压缩后没有元数据会明确说明。

## 提示词与工作流

完整官方 skill、Layout 参考和编译器随插件携带，来源、固定版本及哈希见
`vendor/provenance.json`；不依赖开发者电脑上的 Codex 安装目录。启动时验证哈希。

规划模型负责描述和像素坐标草稿，官方编译器负责验证和转换。只将 Caption 正文
或单行编译 Layout 交给 MOSS；不会拼接 Anima 画师串、质量词、白底或固定角色。
结构错误最多请求一次文字修正，明确拒绝、服务错误或截断不会重试或提交默认图。
官方 skill 面向工具型 GPT-6 agent；宿主 LLM 的实际遵循和画面效果仍需实测。

Danbooru 校正独立用于用户明确点名的角色。通过 LLM 提取原文名称和候选，使用
Anima 的查询证据与类别验证，向规划器提供身份资料和外观锚点。不替换完整提示词、
不清洗自然语言或 JSON、不将候选当成确认结果，也不添加用户未点名的角色。
查询失败仍保留原始需求。无优化模式跳过全部 LLM 和角色查询；输入 Layout JSON
时仅检查模型格式和画幅边界，不重写正文。尺寸旗标应放在原样 JSON 之前。

`workflows/moss-int8-api.json` 保留原生 MOSS INT8、`moss_image` 编码器、FLUX.2 VAE、
Flow shift 5、负分支 SLG 第 22 层，以及 Euler／sgm_uniform、50 步／CFG 3。
只修改明确绑定的提示词、尺寸、模型和采样参数，不按 JSON 顺序猜正负面节点。
无需旧版 MOSS 自定义 Loader；实际 ComfyUI 须有这些原生节点与模型。

## 任务与发送

任务按会话、用户和消息编号去重，使用独立配置快照、随机 seed 和输出目录。
每个任务保存草稿、编译提示词、实际工作流和采样结果。GPU 提交串行，发送等待
不占采样锁；多插件的最终 GPU 排队交给 ComfyUI。

成功只发送图片。不确定是否提交或是否送达时记录 `remote_unknown`／
`delivery_unknown`，不自动重提、重发或全局中断 ComfyUI。只有明确成功且含平台
消息 ID 的回执才算已发送。插件重载只分类旧任务，不恢复或重试它们。

群聊长法术文本默认超过 800 字符时发送一张合并转发卡片；不明回执不改成长正文
重发。私聊／短结果直发，展示上限 32768 字符并标记省略，不影响模型输出。
发送等待默认 200 秒，SDK 内层为 190 秒；适配器、消息网关及 NapCat 的内层
等待仍由宿主控制。插件没有修改共享网关源码或重启 NapCat。

原始 LLM 返回只在插件私有 `last_llm_response.json` 保留最近一次任务，最多 4 次
调用；单条正文／拒绝各限 32768 字符，超限标记截断。新任务覆盖，迟到返回不覆盖
新任务；原样／解析任务清空旧调用。诊断不会自动发到 QQ，历史任务不存原始回复。

任务默认保留 30 天，仅清理过期已结束记录和对应任务目录。未知远端任务、活动
任务、损坏记录、孤立目录及链接目标保留。删除不可恢复；0 关闭时间清理。

## 二期接口

内部 `ImageRequest.task_type` 预留 `comic_page` 和 `meme`，首版调用会明确拒绝，
没有注册对应命令。二期规划器可生成同一官方 Layout 草稿，并复用角色、采样和
发送边界；不提前提供多页工程、图生图、透明底或自动后处理能力。

## 离线验证

```text
uv sync --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -q -c pyproject.toml
```

测试禁止真实 HTTP，使用模型、ComfyUI 和 QQ 的替身。离线通过不等于服务器加载、
真实工具链、QQ 回执或画面质量验收。部署与实机测试需另行授权。

## License

原插件代码使用 MIT；官方 skill 保留其 Apache-2.0 许可。
上游来源和版权说明见 `NOTICE`、`vendor/` 中的许可文件。
