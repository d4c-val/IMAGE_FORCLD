from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class StoryboardItem(BaseModel):
    shot_id: int = Field(..., ge=1, le=10)
    title: str
    scene_description: str
    camera_language: str
    mood: str


class StoryboardResult(BaseModel):
    character_guide: str
    style_bible: str
    storyboards: List[StoryboardItem] = Field(..., min_length=1, max_length=10)


class PreviewRequest(BaseModel):
    story_text: str = Field(..., min_length=30)
    shot_count: int = Field(default=10, ge=1, le=10)
    style_hint: str = Field(default="小王子风格，暖色童话绘本，水彩质感，柔和留白")
    reference_mode: Literal["upload", "text"] = "text"
    upload_reference_strategy: Literal["use_original", "regenerate"] = "use_original"
    reference_image_url: Optional[str] = None


class ReferenceCandidate(BaseModel):
    index: int = Field(..., ge=0, le=2)
    prompt: str
    remote_url: Optional[str] = None
    local_path: Optional[str] = None
    web_url: Optional[str] = None


class ApproveRequest(BaseModel):
    storyboards: List[StoryboardItem] = Field(..., min_length=1, max_length=10)
    selected_reference_index: int = Field(..., ge=0, le=2)


class ImageItem(BaseModel):
    shot_id: int
    title: str
    prompt: str
    uses_edit_model: bool = False
    remote_url: Optional[str] = None
    local_path: Optional[str] = None


class GenerateResponse(BaseModel):
    task_id: str
    storyboards: List[StoryboardItem]
    character_guide: str
    style_bible: str
    reference_image_url: Optional[str] = None
    reference_candidates: List[ReferenceCandidate] = Field(default_factory=list)
    selected_reference_index: Optional[int] = None
    outputs: List[ImageItem]


# CLI 兼容旧命名，避免破坏现有入口
GenerateRequest = PreviewRequest
