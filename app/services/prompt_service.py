from app.schemas import StoryboardItem


class PromptService:
    def build_reference_prompt(
        self, character_guide: str, style_bible: str, variant_index: int = 0
    ) -> str:
        variant_hint = [
            "偏自然站姿，温和微笑",
            "偏动态姿态，轻微动作感",
            "偏沉静神态，电影感构图",
        ][variant_index % 3]
        return (
            "儿童绘本角色设定图，单人全身像，正面站姿，背景简洁。"
            f"角色设定：{character_guide}。"
            f"风格规则：{style_bible}。"
            f"构图变化：{variant_hint}。"
            "画面关键词：小王子风格、暖色童话、水彩质感、柔和留白、高一致性。"
        )

    def build_shot_prompt(
        self,
        shot: StoryboardItem,
        character_guide: str,
        style_bible: str,
        style_hint: str,
        reference_image_url: str | None = None,
    ) -> str:
        reference_text = (
            f"参考角色图URL：{reference_image_url}。请在不改变主角外观的前提下生成新画面。"
            if reference_image_url
            else "无参考图URL，严格遵循角色描述并保持跨分镜一致。"
        )
        return (
            f"分镜{shot.shot_id}：{shot.title}。"
            f"画面描述：{shot.scene_description}。"
            f"镜头语言：{shot.camera_language}。"
            f"情绪：{shot.mood}。"
            f"角色固定设定：{character_guide}。"
            f"统一风格圣经：{style_bible}。"
            f"补充风格偏好：{style_hint}。"
            f"{reference_text}"
            "输出要求：儿童绘本插画，小王子风格，暖色、水彩、柔和光影、简洁背景、构图清晰。"
        )

    def build_shot_edit_prompt(
        self, shot: StoryboardItem, style_hint: str
    ) -> str:
        """供 qwen-image-edit 使用的精简提示词，参考图已包含角色与风格，此处侧重场景变换。"""
        return (
            f"生成一张符合参考图角色与风格的儿童绘本插画，遵循以下描述："
            f"{shot.scene_description}。"
            f"镜头语言：{shot.camera_language}。情绪氛围：{shot.mood}。"
            f"保持小王子风格、暖色、水彩质感、柔和光影、简洁背景、构图清晰。"
            f"风格偏好：{style_hint}。"
        )

    def build_upload_regenerate_reference_prompt(
        self, character_guide: str, style_bible: str, style_hint: str
    ) -> str:
        return (
            "请基于输入参考图重绘一张人物设定参考图。"
            "要求保留人物身份特征与核心外观，但统一到目标绘本风格。"
            f"角色设定：{character_guide}。"
            f"风格规则：{style_bible}。"
            f"补充风格偏好：{style_hint}。"
            "输出为单人角色设定图，背景简洁，正面或3/4侧身，细节清晰。"
        )
