import base64
import json
import mimetypes
from pathlib import Path
from typing import Any


def encode_image_to_base64(file_path: Path) -> str:
    """将本地图片编码为 data:{mime};base64,{data} 格式，供 qwen-image-edit 使用。"""
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if not mime_type or not mime_type.startswith("image/"):
        raise ValueError(f"不支持或无法识别的图像格式: {file_path}")
    data = Path(file_path).read_bytes()
    encoded = base64.b64encode(data).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def ensure_dir(path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

