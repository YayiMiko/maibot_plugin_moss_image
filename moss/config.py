"""Effective model, sampling and style configuration for explicit commands."""

from urllib.parse import urlparse

from maibot_sdk import Field, PluginConfigBase
from pydantic import field_validator, model_validator

from .styles import parse_style_definition


class PluginMetadata(PluginConfigBase):
    config_version: str = Field(default="0.1.0", json_schema_extra={"hidden": True})


class Connection(PluginConfigBase):
    __ui_label__ = "连接与使用权限"
    enabled: bool = True
    comfyui_base_url: str = Field(
        default="http://127.0.0.1:8188",
        description="MaiBot 所在机器能访问的 ComfyUI 地址。",
    )
    allowed_sender_ids: list[str] = Field(
        default_factory=list,
        description="留空沿用宿主权限；填写后只允许这些 QQ 用户使用。",
    )
    max_pending: int = Field(default=4, ge=1, le=16)
    generation_timeout: int = Field(default=600, ge=30, le=3600)
    retention_days: int = Field(
        default=30,
        ge=0,
        le=3650,
        description="仅清理已结束任务；0 停用。未确认的远端任务保留。",
    )
    qq_cache_roots: list[str] = Field(
        default_factory=list,
        description="解析原图允许读取的 QQ 缓存挂载根目录；留空仅使用 QQ HTTPS 图片。",
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


class Planning(PluginConfigBase):
    __ui_label__ = "提示词规划"
    model_task: str = Field(
        default="utils", description="宿主 LLM 任务路由，不注入聊天人设或历史。"
    )
    model_name: str = Field(
        default="", description="可指定宿主已配置模型；留空使用任务路由。"
    )
    max_tokens: int = Field(
        default=4096,
        ge=256,
        le=32768,
        description="规划模型的输出预算，不是最低字数或 Tag 数量。",
    )
    timeout: int = Field(default=180, ge=10, le=600)
    danbooru_enabled: bool = True
    danbooru_budget: float = Field(default=8, ge=1, le=20)


class Rendering(PluginConfigBase):
    __ui_label__ = "MOSS 模型与采样"
    unet_name: str = "moss_image_sft_int8_convrot.safetensors"
    clip_name: str = "qwen3.5_9b_int8_convrot.safetensors"
    vae_name: str = "flux2-vae.safetensors"
    aspect_ratio: str = Field(
        default="3:4", description="未指定画幅时使用；宽高最终对齐 16。"
    )
    megapixels: float = Field(default=1, ge=0.25, le=4, allow_inf_nan=False)
    max_megapixels: float = Field(
        default=2,
        ge=0.25,
        le=4,
        allow_inf_nan=False,
        description="允许的像素上限；明确尺寸超过上限时提示，不静默缩放。",
    )
    steps: int = Field(default=50, ge=1, le=200)
    cfg: float = Field(default=3, ge=0, le=20, allow_inf_nan=False)
    sampler: str = "euler"
    scheduler: str = "sgm_uniform"
    negative_prompt: str = "worst quality, bad anatomy, watermark, jpeg artifact"

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


class Styles(PluginConfigBase):
    __ui_label__ = "正面前缀与画风"
    positive_prefix: str = Field(
        default="best quality, highres,",
        max_length=4096,
        description="仅用于 /moss 生成；在千代式正文规划后由程序拼接。留空不添加。",
    )
    presets: list[str] = Field(
        default_factory=lambda: [
            "千代风格=@yuasa akira, @tomose shunsaku, @kithera, @enuzoushigaya, 简洁干净的二次元平涂画风，"
        ],
        max_length=64,
        description="名称=完整风格内容；不做画师格式转换。聊天编辑会覆盖同名项。人数由用户要求和正文决定。",
    )
    default_style: str = Field(default="千代风格", max_length=80)

    @model_validator(mode="after")
    def valid_library(self):
        """Reject ambiguous duplicate names and missing configured defaults."""
        entries = [parse_style_definition(item) for item in self.presets]
        names = [name for name, _ in entries]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate style preset names")
        if self.default_style and self.default_style not in names:
            raise ValueError("Default style must name a configured preset")
        return self


class Delivery(PluginConfigBase):
    __ui_label__ = "发送"
    timeout_seconds: int = Field(
        default=200,
        ge=30,
        le=600,
        description="插件外层等待；网关及 OneBot 内层超时仍需由宿主协调。",
    )
    group_forward_threshold: int = Field(default=800, ge=100, le=32768)


class Vision(PluginConfigBase):
    __ui_label__ = "图片反推"
    model_task: str = Field(
        default="vlm", description="宿主原生多模态模型任务；不会使用聊天人设。"
    )
    model_name: str = Field(
        default="", description="可指定宿主已配置的视觉模型；留空沿用 vlm 路由。"
    )
    max_tokens: int = Field(default=2048, ge=256, le=8192)
    timeout: int = Field(default=180, ge=10, le=600)


class MossConfig(PluginConfigBase):
    plugin: PluginMetadata = Field(default_factory=PluginMetadata)
    connection: Connection = Field(default_factory=Connection)
    planning: Planning = Field(default_factory=Planning)
    styles: Styles = Field(default_factory=Styles)
    rendering: Rendering = Field(default_factory=Rendering)
    delivery: Delivery = Field(default_factory=Delivery)
    vision: Vision = Field(default_factory=Vision)
