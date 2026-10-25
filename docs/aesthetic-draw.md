# 高美学抽卡

`/moss 抽卡 <要求>` 联网寻找优秀视觉作品，用配置的反推模型观察设计，再将角色和主题改编为官方 Caption/Layout，直接进入已有 ComfyUI 链路。一次只生成一张图片，参考图不作为图生图条件。

- 通常只审核一张候选，通过就停止；不合格或无法读取才换，含下载失败最多三个作品。
- 视觉审核同时返回合格图的详细蓝图，不另开常规反推、横向比较或自动返工。
- 简报、视觉审核、改编导出是常规三次串行模型调用；可选角色识别并行，整个任务最多八次调用。宿主供应商内部的重试由宿主控制，不等同插件调用次数。
- 准备阶段默认最多 180 秒，包含搜索、模型和处理，不包含排队或实际生图；这是截止时间，不是已测得的延迟。
- 明确比例/尺寸优先；没指定就跟随选中参考的比例，并按现有 MP 上限换算、对齐 16。
- 风格用途为“全部”时包括抽卡，提前参与选图，最终在合法描述字段前部只添加一次。固定质量前缀仍只用于“生成”。

## 启用前

默认 `draw.enabled=false`。代码部署成功不代表已经选好了审美锚点或完成真实模型效果验收。

1. 在 MOSS 配置页的“高美学抽卡”填写 `tavily_api_key`。可用同一 Tavily 账号的 Key，但插件不会读取兄弟插件。Key 为密码字段，不进入任务快照、模型消息、缓存或诊断。
2. 在插件私有数据目录下准备 `draw_profiles/<profile>/manifest.json` 及锚点。`draw.profile` 默认 `default`；这里是 SDK 的持久数据目录，不是代码仓库或临时任务目录。
3. 每个启用品类（`poster` / `illustration`）准备至少两张正例、两张反例，写出认可/不认可的具体原因。不要把黑白、密集细节、高饱和或“官方”当成通用审美标准。
4. 明确核实至少两个不同发布域名的原始作者/策展路径，且能取得单幅完整作品。不是将整个聚合站的所有作品认证为优秀；图片仍逐张审核。来源路径和证据由维护者配置，不接受模型自行认证。
5. 受控验证实际视觉路由能区分候选、正例、反例三张图片；用未参与校准的作品做人工盲比较。核对图源可读取性、输出质量、费用和耗时后再设置相应验证字段。
6. 设置 `draw.enabled=true`。改变规划/视觉模型路由后需重新验证并更新档案；若宿主路由名不变而实际模型改变，同样必须重新验收，插件无法凭同名路由自动判断供应商模型漂移。

不自动探测付费模型，不自动抓取用户的附图作为锚点，不把未经用户认可的作品假装成已校准锚点。缺少档案、验证字段或哈希不匹配时停止，其他生图功能继续使用。

## 导入档案

维护者可在受信任的机器上准备一份 JSON spec，再导入明确选择的本地文件：

```text
python scripts/import_draw_profile.py profile-spec.json --destination /absolute/new/draw_profiles/default
```

目标须是新目录；导入会规范图片、移除元数据、保存哈希。它**总是关闭**能力/来源/品类验收字段，不能用导入代替真实验证。spec 例子（锚点路径按实际填写，每类至少两个）：

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

纯 JavaScript、登录限制、没有可核验图片关联的站点可能无法取图。本版不驻留浏览器、不绕过访问控制。维护者应先实测图源，不能把写进域名名单等同于已经接通。

下载限公共 HTTPS，DNS 和实际连接地址校验，重定向重新检查，不继承代理。凭据只发固定 Tavily API；图片限静态 JPEG/PNG/WebP、8MiB、12MP。候选单张取图；HTTP 后台工作线程最多两个。拒绝或没有合格参考时不提交默认图、不自动重试 GPU 或 QQ 发送。

审美门槛是按用户锚点进行的模型判断，不能保证每张参考都符合个人口味，也不能保证文生图复制原图效果。要求与设计关系会校验是否有实际草稿描述落点；无法机械判定的语义和最终美学仍要通过真人实图验收。

## 私有记录与维护

每任务 `draw/` 保存简报、来源、结构化评语、选图理由、原图蓝图、改编和预算结果；官方草稿与工作流继续保存在原任务目录。原始 LLM 返回仍只保留最近任务四次调用，不增加原始响应历史库。

来源只保存去掉 query 的展示 URL；实际图片的身份/去重依靠内容哈希，不将带签名下载地址写入历史。候补页面优先避开当前用户/会话近期作品；这不是聊天记忆，也不建立个人审美画像。仅保留最近 128 条摘要。

选中图片独立缓存，最多 256MiB、最长七天；活动准备期不清理，空闲维护按小时清理。锚点不参与淘汰，输出图、旧任务和角色库不用于腾空间。没有审美通过缓存，每个新任务重新核对本次要求和实际图像。
