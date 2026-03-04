import json

from app.config import settings
from app.schemas import StoryboardItem, StoryboardResult
from app.services.dashscope_client import DashScopeClient, DashScopeError


class StoryboardService:
    def __init__(self, client: DashScopeClient) -> None:
        self.client = client

    def split_story_to_storyboards(
        self, story_text: str, style_hint: str, shot_count: int = 10
    ) -> StoryboardResult:
        system_prompt = (
            "你是专业动画分镜师。"
            "请把用户故事拆分为最合适的分镜数量（1到10个）。"
            "分镜数量由故事节奏决定，不要机械凑满。"
            "保持人物一致性并适配儿童绘本表达。"
            "只输出 JSON，不要输出解释。"
        )
        user_prompt = f"""
请基于下面故事生成 JSON，结构必须为：
{{
  "character_guide": "字符串，主角外观与服饰细节，后续全程一致",
  "style_bible": "字符串，统一绘画风格与色彩规则",
  "storyboards": [
    {{
      "shot_id": 1,
      "title": "分镜标题",
      "scene_description": "画面描述，含关键动作",
      "camera_language": "镜头语言",
      "mood": "情绪氛围"
    }}
  ]
}}

硬性要求：
1) storyboards 长度范围为 1..{shot_count}，shot_id 必须连续整数（会在后处理重排）。
2) 每个 scene_description 要包含角色状态与环境信息。
3) style_bible 必须可执行，能约束色彩、材质、光影与构图。
4) 分镜数量必须服务叙事清晰度，优先少而精。

故事内容：
{story_text}

补充风格偏好：
{style_hint}
"""
        data = self.client.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=settings.text_model,
        )
        try:
            parsed = StoryboardResult.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            raise DashScopeError(f"分镜结构校验失败: {exc}, raw={data}") from exc
        parsed.storyboards = self._normalize_shot_ids(parsed.storyboards)
        return parsed

    def shot_has_character(self, shot: StoryboardItem) -> bool:
        system_prompt = (
            "你是分镜标签助手。判断给定分镜是否涉及人物或角色主体。"
            "只输出 JSON。"
        )
        user_prompt = f"""
请判断下面分镜是否涉及人物（人类、拟人角色、主要动物角色都算）：
{json.dumps(shot.model_dump(), ensure_ascii=False)}

输出格式：
{{
  "has_character": true
}}
"""
        try:
            data = self.client.chat_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=settings.judge_model,
            )
            return bool(data.get("has_character", False))
        except Exception:
            # 兜底关键词判断，避免判断接口异常时中断主流程。
            text = (
                f"{shot.title} {shot.scene_description} {shot.camera_language} {shot.mood}"
            ).lower()
            keywords = ["人物", "男孩", "女孩", "主角", "角色", "人", "孩子", "少年"]
            return any(word in text for word in keywords)

    @staticmethod
    def _normalize_shot_ids(storyboards: list[StoryboardItem]) -> list[StoryboardItem]:
        normalized: list[StoryboardItem] = []
        for index, item in enumerate(storyboards, start=1):
            normalized.append(
                StoryboardItem(
                    shot_id=index,
                    title=item.title,
                    scene_description=item.scene_description,
                    camera_language=item.camera_language,
                    mood=item.mood,
                )
            )
        return normalized
