# 高美学抽卡

`/moss 抽卡 <要求>` 联网寻找优秀视觉作品，用配置的反推模型观察设计，再将角色和主题改编为官方 Caption/Layout，直接进入已有 ComfyUI 链路。一次只生成一张图片，参考图不作为图生图条件。

- 通常只审核一张候选，通过就停止；不合格或无法读取才换，含下载失败最多三个作品。
- 仅给角色时属于宽要求：角色及作品名只用于身份校正和最终改编，不作为参考图必须出现的内容。规划器先给出 2～4 个不同设计方向，由任务随机种子决定先探索哪一个；无明确媒介要求时覆盖可用的海报、插画类别。具体主题会单独保存在 `reference_requirements`，各方向保留这些原文要求。
- 最多检索两个方向；有后续方向时先尝试当前方向一条候选，失败后换方向，剩余候选机会留给后续方向，总数仍不超过三。元数据优先避开已尝试的来源域名和近期作品；只看过链接但未尝试的作品可以进入下一次搜索结果，不会提前被去重丢弃。
- 视觉审核同时返回合格图的详细蓝图，不另开常规反推、横向比较或自动返工。
- 简报、视觉审核、改编导出是常规三次串行模型调用；可选角色识别并行，整个任务最多八次调用。宿主供应商内部的重试由宿主控制，不等同插件调用次数。
- 准备阶段默认最多 180 秒，包含搜索、模型和处理，不包含排队或实际生图；这是截止时间，不是已测得的延迟。
- 明确比例/尺寸优先；没指定就跟随选中参考的比例，并按现有 MP 上限换算、对齐 16。
- 抽卡不叠加“千代风格”等共通风格预设，即使风格用途设为“全部”也不生效。直接写在抽卡要求里的画风仍会保留；未指定时按参考作品的视觉处理改编。固定质量前缀仍只用于“生成”。
- 简报硬要求只能引用用户原文。简报结构或来源校验失败时最多纠正一次，并与最终导出共享这一次修正预算；明确拒绝不触发纠正。简报失败会明确提示尚未搜参考图，不能笼统标成最终导出失败。

## 启用前

抽卡开关 `draw.enabled` 与“使用个人审美档案” `draw.use_profile` 是两个独立设置。插件初始抽卡关闭；个人档案也默认关闭。**使用内置规则不需要建立档案或准备正反例**。部署和离线检查不代表完成真实模型、美学或生图验收。

1. 在 MOSS 配置页的“高美学抽卡”填写 `tavily_api_key`，确认规划与视觉模型路由，设置 `draw.enabled=true`。可复用 bot 的 Tavily Key；只有用户授权时才从现有配置复制，插件不会自动读取兄弟插件。Key 为密码字段，不进入任务快照、模型消息、缓存或诊断。
2. 保持 `draw.use_profile=false`：使用内置的海报/插画评审规则，检查构图、视觉层级、色彩/明暗组织、媒介表现及完成度。只上传当前一张候选，不读取任何个人档案，也不虚构正反例或声称已经校准。
3. 默认限定 ArtStation `/artwork/`、Behance `/gallery/`、[Pentagram 项目](https://www.pentagram.com/work)、[It's Nice That 作品报道](https://www.itsnicethat.com/articles) 页面。逐次核对页面声明的图片关联，并执行真实图像审核。记录为 `publisher_page`，不因域名知名就声称作者、策展或奖项已核实。无法读取原图时换候选或停止，不能以平台名补偿美学不合格。

使用内置规则仍需视觉模型能真实理解图片。能力不足、服务错误、拒绝或没有合格图时停止，不转成纯文字猜图。不会因打开开关就自动调用付费模型探测或提交测试生图；真实联网与实图验收单独进行。

## 可选个人审美档案

只有 `draw.use_profile=true` 时才读取 `draw_profiles/<profile>/manifest.json` 及锚点。`draw.profile` 默认 `default`；目录位于 SDK 持久私有数据下。

- 每个启用品类（`poster` / `illustration`）至少两张正例、两张反例，并写出认可/不认可的具体原因。不要把黑白、密集细节、高饱和或“官方”当作通用标准。
- 档案可指定额外认可的发布渠道及证据；核实至少两个渠道能取得完整作品，不能将整个平台的作品都认证为优秀。
- 验证视觉路由确实能区分候选、正例、反例三张图片，用未参与校准的作品做人工盲比较，再设置相应验证字段。
- 开启后，缺失/损坏档案、验证未完成、哈希不匹配或模型路由改变都会提示尚未校准，**不静默退回内置规则**。主动关闭档案后才恢复内置规则。
- 不自动抓取用户附图建立锚点，不将未经认可的作品标为已校准。其他生图功能不受影响。

## 导入档案

维护者可在受信任的机器上准备一份 JSON spec，再导入明确选择的本地文件：

```text
python scripts/import_draw_profile.py profile-spec.json --destination /absolute/new/draw_profiles/default
```

目标须是新目录；导入会规范图片、移除元数据、保存哈希。它**总是关闭**能力/来源/品类验收字段，也不会修改 `draw.use_profile`，不能用导入代替真实验证。spec 例子（锚点路径按实际填写，每类至少两个）：

```json
{
  "version": "taste-1",
  "rules_version": "draw-v1",
  "vision_model_task": "vlm",
  "vision_model_name": "",
  "planning_model_task": "utils",
  "planning_model_name": "",
  "sources": [
    {"domain": "artist.example.com", "path_prefix": "/portfolio/", "kind": "creator_verified", "evidence": "Replace with independently verified original publisher evidence"},
    {"domain": "studio.example.com", "path_prefix": "/projects/", "kind": "creator_verified", "evidence": "Replace with independently verified original studio evidence"}
  ],
  "categories": {
    "poster": {
      "positive": [
        {"source_path": "/absolute/positive1.png", "reason": "Concrete hierarchy and shape relationships the user approves"},
        {"source_path": "/absolute/positive2.png", "reason": "Another approved design with different visual treatment"}
      ],
      "negative": [
        {"source_path": "/absolute/negative1.png", "reason": "Specific visible hierarchy problem"},
        {"source_path": "/absolute/negative2.png", "reason": "Specific visible composition problem"}
      ]
    }
  }
}
```

例子的域名不是可用图源，不要直接认证。`path_prefix` 按路径段匹配，域名精确匹配；策展证据应指向已核实的策展集合，不能将普通作者页面冒充获奖记录。

导入后的 `manifest.json` 将 `source_path` 替换为受控文件名和 SHA-256。明确验收后，维护者才修改 `multimodal_verified`、`sources_verified` 及对应品类的 `calibrated` 为 true。一个启用品类至少四张锚点，全档案最多十六张、16MiB。

## 来源和失败边界

使用 [Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search) 发现作品页，通常一次查询，最多一次补查。搜索分数只表示相关性。实际参考取自通过来源规则的作品页所声明的 `og:image` / `twitter:image`，不把聚合 images 的第一张强行归给第一条网页。仅能取得截图、样机、缩略图、拼贴长图或无图页面时，会由技术/视觉审核拒绝。

没有作品页面、页面/图片读取失败、重复或画幅不适用、实际经过视觉审核后未达门槛分别报告。未调用视觉审核时不能宣称“审美未通过”。读取失败保存 page/image/decode 阶段、受控错误码、可用的 HTTP 状态和去掉查询参数的网址；不保存认证头或响应正文。

纯 JavaScript、登录限制、没有可核验图片关联的站点可能无法取图。本版不驻留浏览器、不绕过访问控制。维护者应先实测图源，不能把写进域名名单等同于已经接通。

下载限公共 HTTPS，DNS 和实际连接地址校验，重定向重新检查，不继承代理。凭据只发固定 Tavily API；图片限静态 JPEG/PNG/WebP、8MiB、12MP。候选单张取图；HTTP 后台工作线程最多两个。拒绝或没有合格参考时不提交默认图、不自动重试 GPU 或 QQ 发送。

审美门槛是按内置规则或启用的用户锚点进行的模型判断，不能保证每张参考都符合个人口味，也不能保证文生图复制原图效果。要求与设计关系会校验是否有实际草稿描述落点；无法机械判定的语义和最终美学仍要通过真人实图验收。

## 私有记录与维护

每任务 `draw/` 保存简报、`discovery.json` 中的探索顺序/随机种子/搜索返回及过滤数量、来源与读取错误、结构化评语、选图理由、原图蓝图、改编和预算结果；官方草稿与工作流继续保存在原任务目录。原始 LLM 返回仍只保留最近任务四次调用，不增加原始响应历史库。

来源只保存去掉 query 的展示 URL；实际图片的身份/去重依靠内容哈希，不将带签名下载地址写入历史。候补页面优先避开当前用户/会话近期作品；这不是聊天记忆，也不建立个人审美画像。仅保留最近 128 条摘要。

选中图片独立缓存，最多 256MiB、最长七天；活动准备期不清理，空闲维护按小时清理。锚点不参与淘汰，输出图、旧任务和角色库不用于腾空间。没有审美通过缓存，每个新任务重新核对本次要求和实际图像。
