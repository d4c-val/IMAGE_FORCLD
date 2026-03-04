from pathlib import Path
from typing import Optional

import requests

from app.config import settings
from app.services.dashscope_client import DashScopeClient
from app.utils.io_utils import encode_image_to_base64


class ImageService:
    def __init__(self, client: DashScopeClient) -> None:
        self.client = client
        self.session = requests.Session()
        if settings.disable_env_proxy:
            self.session.trust_env = False

    def generate_image(self, prompt: str) -> Optional[str]:
        return self.client.generate_image(prompt=prompt, size=settings.image_size)

    def edit_image(self, reference_image_path: Path, prompt: str) -> Optional[str]:
        """以参考图为输入，调用 qwen-image-edit 生成分镜图，提升一致性。"""
        base64_img = encode_image_to_base64(reference_image_path)
        return self.client.edit_image(
            reference_image_base64=base64_img,
            prompt=prompt,
            size=settings.image_size,
        )

    def download_image(self, url: str, output_file: Path) -> Path:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        response = self.session.get(url, timeout=settings.request_timeout)
        response.raise_for_status()
        output_file.write_bytes(response.content)
        return output_file
