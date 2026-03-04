from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    dashscope_api_key: str
    text_model: str = "qwen-plus"
    judge_model: str = "qwen-max"
    image_model: str = "qwen-image"
    image_edit_model: str = "qwen-image-edit"
    image_size: str = "1024x1024"
    output_dir: str = "outputs"
    max_retries: int = 3
    request_timeout: int = 120
    disable_env_proxy: bool = True
    dashscope_base_http_api_url: str = "https://dashscope.aliyuncs.com/api/v1"
    image_watermark: bool = False
    image_prompt_extend: bool = True
    image_negative_prompt: str = (
        "低分辨率，低画质，肢体畸形，手指畸形，画面过饱和，蜡像感，人脸无细节，"
        "过度光滑，画面具有AI感，构图混乱，文字模糊，扭曲。"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @property
    def output_path(self) -> Path:
        return Path(self.output_dir).resolve()


settings = Settings()
