import argparse
import json
from pathlib import Path

from app.schemas import GenerateRequest
from app.services.pipeline import StoryToImagePipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Qwen 绘本分镜与出图 CLI")
    parser.add_argument("--story-file", type=str, help="故事文本文件路径")
    parser.add_argument("--story-text", type=str, help="直接输入故事文本")
    parser.add_argument(
        "--style-hint",
        type=str,
        default="小王子风格，暖色童话绘本，水彩质感，柔和留白",
        help="附加风格偏好",
    )
    return parser.parse_args()


def load_story_text(args: argparse.Namespace) -> str:
    if args.story_text:
        return args.story_text
    if args.story_file:
        return Path(args.story_file).read_text(encoding="utf-8").strip()
    raise ValueError("必须提供 --story-file 或 --story-text")


def main() -> None:
    args = parse_args()
    story_text = load_story_text(args)
    req = GenerateRequest(story_text=story_text, style_hint=args.style_hint)

    pipeline = StoryToImagePipeline()
    result = pipeline.run(req)

    payload = {
        "task_id": result.task_id,
        "character_guide": result.character_guide,
        "style_bible": result.style_bible,
        "reference_image_url": result.reference_image_url,
        "storyboards": [item.model_dump() for item in result.storyboards],
        "outputs": [item.model_dump() for item in result.outputs],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
