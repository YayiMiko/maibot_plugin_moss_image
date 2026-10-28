"""Effective model, sampling and style configuration for explicit commands."""

from typing import Any
from urllib.parse import urlparse

from maibot_sdk import Field, PluginConfigBase
from pydantic import field_validator, model_validator

from .styles import parse_style_definition

CONFIG_VERSION = "0.2.0"


def _ui(label: str, example: Any, **extra: Any) -> dict[str, Any]:
    """Attach human-readable WebUI metadata without changing config keys."""
    return {"label": label, "example": example, **extra}


class PluginMetadata(PluginConfigBase):
    """插件内部元数据。"""

    __ui_label__ = "插件信息"
    __ui_order__ = 0
    config_version: str = Field(
        default=CONFIG_VERSION,
        description="配置文件结构版本，由插件维护；通常不需要手动修改。",
        json_schema_extra=_ui("配置版本", CONFIG_VERSION, hidden=True),
    )


class Connection(PluginConfigBase):
    """ComfyUI 地址、使用权限和任务保留策略。"""

    __ui_label__ = "连接与权限"
    __ui_order__ = 10
    enabled: bool = Field(
        default=True,
        description="关闭后所有 /moss 指令只返回关闭提示，不提交任何任务。",
        json_schema_extra=_ui("启用 MOSS", True),
    )
    comfyui_base_url: str = Field(
        default="http://127.0.0.1:8188",
        description="MaiBot 所在机器能访问的 ComfyUI HTTP 地址；不要填写带账号、查询参数或末尾斜杠的地址。",
        json_schema_extra=_ui("ComfyUI 地址", "http://100.64.0.10:8188"),
    )
    allowed_sender_ids: list[str] = Field(
        default_factory=list,
        description="留空沿用宿主权限；填写后只允许列表中的 QQ 用户使用。",
        json_schema_extra=_ui("允许使用的 QQ 用户", ["123456789"]),
    )
    max_pending: int = Field(
        default=4,
        ge=1,
        le=16,
        description="同时运行的任务上限；超过后新请求提示队列已满。",
        json_schema_extra=_ui("最大同时任务数", 4, hidden=True),
    )
    generation_timeout: int = Field(
        default=600,
        ge=30,
        le=3600,
        description="单次远端生图的等待上限；超时后不会再发送迟到图片。",
        json_schema_extra=_ui("生图等待上限（秒）", 600, hidden=True),
    )
    retention_days: int = Field(
        default=30,
        ge=0,
        le=3650,
        description="仅清理已结束任务；0 表示停用清理，未确认的远端任务会保留。",
        json_schema_extra=_ui("任务记录保留天数", 30, hidden=True),
    )
    qq_cache_roots: list[str] = Field(
        default_factory=list,
        description="解析原图允许读取的 QQ 缓存挂载根目录；留空仅使用 QQ HTTPS 图片。",
        json_schema_extra=_ui("QQ 缓存目录", ["/opt/ntqq/cache"], hidden=True),
    )

    @field_validator("comfyui_base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        """Require an explicit HTTP API root without embedded credentials."""
        parsed = urlparse(value.strip())
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Use an HTTP(S) ComfyUI URL without credentials or query")
        return value.strip().rstrip("/")


class DrawLimits(PluginConfigBase):
    """抽卡准备的内部预算，通常无需修改。"""

    __ui_label__ = "抽卡高级预算"
    prepare_timeout: int = Field(
        default=180,
        ge=30,
        le=300,
        description="抽卡准备阶段的总时限；包含搜索、读页、视觉审核和改编。",
        json_schema_extra=_ui("准备时限（秒）", 180, hidden=True),
    )
    search_budget: int = Field(
        default=2,
        ge=1,
        le=2,
        description="每轮抽卡最多搜索次数；不是每次都必须用完。",
        json_schema_extra=_ui("搜索次数上限", 2, hidden=True),
    )
    cache_mib: int = Field(
        default=256,
        ge=16,
        le=256,
        description="参考图缓存上限；达到上限时清理旧缓存。",
        json_schema_extra=_ui("参考图缓存（MiB）", 256, hidden=True),
    )


class Draw(PluginConfigBase):
    """模板抽卡开关和搜索凭据。"""

    __ui_label__ = "模板抽卡"
    __ui_order__ = 20
    model_config = {**PluginConfigBase.model_config, "extra": "ignore"}
    enabled: bool = Field(
        default=False,
        description="开启自动联网选图、模板适用性审核与单张生图，无需人工选图或校准。",
        json_schema_extra=_ui("启用模板抽卡", False),
    )
    tavily_api_key: str = Field(
        default="",
        repr=False,
        max_length=256,
        pattern=r"^[^\s]*$",
        description="Tavily 搜索凭据；不会读取其他插件或写入任务快照。",
        json_schema_extra=_ui(
            "Tavily API Key",
            "tvly-...",
            input_type="password",
            **{"x-widget": "password"},
            order=1,
        ),
    )
    limits: DrawLimits = Field(
        default_factory=DrawLimits,
        description="抽卡准备阶段的超时、搜索和缓存预算；一般无需修改。",
        json_schema_extra=_ui(
            "高级预算（一般无需修改）",
            "prepare_timeout=180, search_budget=2, cache_mib=256",
            hidden=True,
            order=2,
        ),
    )


class Rendering(PluginConfigBase):
    """MOSS 模型、采样参数和默认画幅。"""

    __ui_label__ = "生图模型与画幅"
    __ui_order__ = 30
    unet_name: str = Field(
        default="moss_image_sft_int8_convrot.safetensors",
        description="ComfyUI 中实际安装的 MOSS 主模型文件名。",
        json_schema_extra=_ui(
            "MOSS 主模型文件", "moss_image_sft_int8_convrot.safetensors", hidden=True
        ),
    )
    clip_name: str = Field(
        default="qwen3.5_9b_int8_convrot.safetensors",
        description="ComfyUI 中实际安装的文本编码器文件名。",
        json_schema_extra=_ui(
            "文本编码器文件", "qwen3.5_9b_int8_convrot.safetensors", hidden=True
        ),
    )
    vae_name: str = Field(
        default="flux2-vae.safetensors",
        description="ComfyUI 中实际安装的 VAE 文件名。",
        json_schema_extra=_ui("VAE 文件", "flux2-vae.safetensors", hidden=True),
    )
    aspect_ratio: str = Field(
        default="3:4",
        description="未指定画幅时使用；宽高最终对齐 16。",
        json_schema_extra=_ui("默认画幅", "3:4", order=3),
    )
    megapixels: float = Field(
        default=1,
        ge=0.25,
        le=4,
        allow_inf_nan=False,
        description="未明确尺寸时使用的像素量（MP）；1 MP 约等于 1024×1024。",
        json_schema_extra=_ui("默认像素量（MP）", 1, order=4),
    )
    max_megapixels: float = Field(
        default=2,
        ge=0.25,
        le=4,
        allow_inf_nan=False,
        description="允许的像素上限；明确尺寸超过上限时提示，不静默缩放。",
        json_schema_extra=_ui("像素上限（MP）", 2, order=5),
    )
    steps: int = Field(
        default=50,
        ge=1,
        le=200,
        description="采样步数；提高通常更精细，但耗时和显存也增加。",
        json_schema_extra=_ui("采样步数", 50, order=6),
    )
    cfg: float = Field(
        default=3,
        ge=0,
        le=20,
        allow_inf_nan=False,
        description="提示词引导强度；过高容易僵硬，过低容易偏离描述。",
        json_schema_extra=_ui("CFG 引导", 3, order=7),
    )
    sampler: str = Field(
        default="euler",
        description="ComfyUI 采样器名称；需与当前工作流兼容。",
        json_schema_extra=_ui("采样器", "euler", hidden=True),
    )
    scheduler: str = Field(
        default="sgm_uniform",
        description="ComfyUI 调度器名称；需与当前工作流兼容。",
        json_schema_extra=_ui("调度器", "sgm_uniform", hidden=True),
    )
    negative_prompt: str = Field(
        default="worst quality, bad anatomy, watermark, jpeg artifact",
        description="每次生图附带的负面提示词；留空不添加。",
        json_schema_extra=_ui(
            "负面提示词", "worst quality, bad anatomy, watermark", order=8
        ),
    )

    @field_validator("aspect_ratio")
    @classmethod
    def valid_ratio(cls, value: str) -> str:
        """Validate ratios without changing the user's intended framing."""
        parts = value.split(":")
        if len(parts) != 2 or not all(
            p.isdigit() and 1 <= int(p) <= 100 for p in parts
        ):
            raise ValueError("Aspect ratio must be positive integers such as 3:4")
        return value

    @model_validator(mode="after")
    def within_budget(self):
        if self.megapixels > self.max_megapixels:
            raise ValueError("Default megapixels exceed the configured limit")
        return self


class Planning(PluginConfigBase):
    """生图提示词规划使用的宿主模型路由。"""

    __ui_label__ = "提示词规划"
    __ui_order__ = 40
    model_task: str = Field(
        default="utils",
        description="宿主 LLM 任务路由，不注入聊天人设或历史。",
        json_schema_extra=_ui("规划模型任务", "utils"),
    )
    model_name: str = Field(
        default="",
        description="可指定宿主已配置模型；留空使用任务路由。",
        json_schema_extra=_ui("指定规划模型", "deepseek-v4", order=1),
    )
    max_tokens: int = Field(
        default=4096,
        ge=256,
        le=32768,
        description="规划模型的输出预算，不是最低字数或 Tag 数量。",
        json_schema_extra=_ui("规划输出上限", 4096, order=2),
    )
    timeout: int = Field(
        default=180,
        ge=10,
        le=600,
        description="单次规划请求的等待上限。",
        json_schema_extra=_ui("规划超时（秒）", 180, order=3),
    )
    danbooru_enabled: bool = Field(
        default=True,
        description="允许角色识别时查询 Danbooru；关闭后只使用模型知识。",
        json_schema_extra=_ui("启用 Danbooru 查询", True, hidden=True),
    )
    danbooru_budget: float = Field(
        default=8,
        ge=1,
        le=20,
        description="每轮角色识别的 Danbooru 查询预算。",
        json_schema_extra=_ui("Danbooru 查询预算", 8, hidden=True),
    )


class Vision(PluginConfigBase):
    """图片反推使用的宿主多模态模型路由。"""

    __ui_label__ = "图片反推"
    __ui_order__ = 50
    model_task: str = Field(
        default="vlm",
        description="宿主原生多模态模型任务；不会使用聊天人设。",
        json_schema_extra=_ui("反推模型任务", "vlm"),
    )
    model_name: str = Field(
        default="",
        description="可指定宿主已配置的视觉模型；留空沿用 vlm 路由。",
        json_schema_extra=_ui("指定反推模型", "qwen-vl", order=1),
    )
    max_tokens: int = Field(
        default=2048,
        ge=256,
        le=8192,
        description="反推结果的输出预算。",
        json_schema_extra=_ui("反推输出上限", 2048, order=2),
    )
    timeout: int = Field(
        default=180,
        ge=10,
        le=600,
        description="单次图片反推的等待上限。",
        json_schema_extra=_ui("反推超时（秒）", 180, order=3),
    )


class Styles(PluginConfigBase):
    """正面前缀和旧版风格配置兼容项。"""

    __ui_label__ = "风格与提示词"
    __ui_order__ = 60
    positive_prefix: str = Field(
        default="best quality, highres,",
        max_length=4096,
        description="仅用于 /moss 生成；与所选风格、用户原文直接拼接，不调用 LLM 扩写。留空不添加。",
        json_schema_extra=_ui("正面前缀", "best quality, highres,"),
    )
    presets: list[str] = Field(
        default_factory=list,
        max_length=64,
        description="旧版配置兼容项；插件启动时会导入 styles.json，实际风格库请用 /moss 风格 管理。",
        json_schema_extra=_ui(
            "旧版风格列表（已迁移）",
            ["千代风格=@artist, 简洁干净的二次元平涂画风"],
            hidden=True,
            order=1,
        ),
    )

    @model_validator(mode="after")
    def valid_library(self):
        """Reject ambiguous duplicate names."""
        entries = [parse_style_definition(item) for item in self.presets]
        names = [name for name, _ in entries]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate style preset names")
        return self


class Characters(PluginConfigBase):
    """OC 角色库管理员权限，不包含运行时角色内容。"""

    __ui_label__ = "OC 权限"
    __ui_order__ = 70
    admin_user_ids: list[str] = Field(
        default_factory=list,
        max_length=64,
        description="允许编辑、删除其他人 OC 的用户 ID；留空仅创建者可修改。不使用群昵称或客户端管理员标记。",
        json_schema_extra=_ui("OC 管理员 QQ", ["123456789"]),
    )


class Delivery(PluginConfigBase):
    """发送等待和长消息转发策略。"""

    __ui_label__ = "发送与维护"
    __ui_order__ = 80
    timeout_seconds: int = Field(
        default=200,
        ge=30,
        le=600,
        description="插件外层等待；网关及 OneBot 内层超时仍需由宿主协调。",
        json_schema_extra=_ui("发送超时（秒）", 200),
    )
    group_forward_threshold: int = Field(
        default=800,
        ge=100,
        le=32768,
        description="文本超过该长度时改用合并转发，避免普通消息被截断。",
        json_schema_extra=_ui("长消息转发阈值", 800, hidden=True, order=1),
    )


class MossConfig(PluginConfigBase):
    model_config = {**PluginConfigBase.model_config, "hide_input_in_errors": True}
    plugin: PluginMetadata = Field(default_factory=PluginMetadata)
    connection: Connection = Field(default_factory=Connection)
    draw: Draw = Field(default_factory=Draw)
    rendering: Rendering = Field(default_factory=Rendering)
    planning: Planning = Field(default_factory=Planning)
    vision: Vision = Field(default_factory=Vision)
    styles: Styles = Field(default_factory=Styles)
    characters: Characters = Field(default_factory=Characters)
    delivery: Delivery = Field(default_factory=Delivery)
