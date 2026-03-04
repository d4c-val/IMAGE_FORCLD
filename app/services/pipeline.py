from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

from app.config import settings
from app.schemas import (
    GenerateRequest,
    GenerateResponse,
    ImageItem,
    PreviewRequest,
    ReferenceCandidate,
    StoryboardItem,
)
from app.services.dashscope_client import DashScopeClient
from app.services.image_service import ImageService
from app.services.prompt_service import PromptService
from app.services.storyboard_service import StoryboardService
from app.utils.io_utils import ensure_dir, write_json


class StoryToImagePipeline:
    def __init__(self) -> None:
        client = DashScopeClient()
        self.storyboard_service = StoryboardService(client)
        self.prompt_service = PromptService()
        self.image_service = ImageService(client)

    def build_preview(
        self,
        request: PreviewRequest,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        task_id: str | None = None,
    ) -> dict:
        task_id = task_id or self._build_task_id()
        task_dir = ensure_dir(settings.output_path / task_id)

        storyboard_result = self.storyboard_service.split_story_to_storyboards(
            story_text=request.story_text,
            style_hint=request.style_hint,
            shot_count=request.shot_count,
        )
        self._emit(
            progress_callback,
            {
                "progress": 15,
                "message": "已完成故事拆分与分镜预览",
                "storyboards": [item.model_dump() for item in storyboard_result.storyboards],
                "character_guide": storyboard_result.character_guide,
                "style_bible": storyboard_result.style_bible,
            },
        )
        write_json(task_dir / "story.json", {"story_text": request.story_text})
        write_json(task_dir / "storyboards.json", storyboard_result.model_dump())

        candidates = self._prepare_reference_candidates(
            request=request,
            character_guide=storyboard_result.character_guide,
            style_bible=storyboard_result.style_bible,
            task_dir=task_dir,
        )
        write_json(
            task_dir / "reference_candidates.json",
            [item.model_dump() for item in candidates],
        )
        selected_reference_index = 0 if candidates else None
        reference_image_url = candidates[0].web_url if candidates else None
        self._emit(
            progress_callback,
            {
                "progress": 25,
                "message": "预览阶段完成，请检查分镜并确认",
                "reference_image_url": reference_image_url,
                "reference_candidates": [item.model_dump() for item in candidates],
            },
        )
        return {
            "task_id": task_id,
            "storyboards": storyboard_result.storyboards,
            "character_guide": storyboard_result.character_guide,
            "style_bible": storyboard_result.style_bible,
            "reference_candidates": candidates,
            "selected_reference_index": selected_reference_index,
            "reference_image_url": reference_image_url,
        }

    def render_from_preview(
        self,
        task_id: str,
        storyboards: list[StoryboardItem],
        character_guide: str,
        style_bible: str,
        style_hint: str,
        reference_candidates: list[ReferenceCandidate],
        selected_reference_index: int,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> GenerateResponse:
        task_dir = ensure_dir(settings.output_path / task_id)
        selected_reference = self._pick_reference(
            reference_candidates=reference_candidates,
            selected_reference_index=selected_reference_index,
        )
        reference_image_url = selected_reference.web_url or selected_reference.remote_url
        reference_image_path = (
            Path(selected_reference.local_path).resolve()
            if selected_reference.local_path
            else None
        )

        outputs: list[ImageItem] = []
        prompts_dump: list[dict] = []
        total = len(storyboards)
        for idx, shot in enumerate(storyboards, start=1):
            has_character = self.storyboard_service.shot_has_character(shot)
            use_edit = has_character
            if use_edit:
                if not reference_image_path or not reference_image_path.exists():
                    raise ValueError("当前分镜涉及人物，但未选择可用参考图，无法保证一致性")
                prompt = self.prompt_service.build_shot_edit_prompt(
                    shot=shot,
                    style_hint=style_hint,
                )
                remote_url = self.image_service.edit_image(
                    reference_image_path,
                    prompt,
                )
            else:
                prompt = self.prompt_service.build_shot_prompt(
                    shot=shot,
                    character_guide=character_guide,
                    style_bible=style_bible,
                    style_hint=style_hint,
                    reference_image_url=reference_image_url,
                )
                remote_url = self.image_service.generate_image(prompt)
            local_path = None
            if remote_url:
                image_name = f"shot_{shot.shot_id:02d}.png"
                local_file = self.image_service.download_image(
                    remote_url, task_dir / "images" / image_name
                )
                local_path = str(local_file)

            outputs.append(
                ImageItem(
                    shot_id=shot.shot_id,
                    title=shot.title,
                    prompt=prompt,
                    uses_edit_model=use_edit,
                    remote_url=remote_url,
                    local_path=local_path,
                )
            )
            prompts_dump.append({"shot_id": shot.shot_id, "prompt": prompt})
            progress = 25 + int((idx / total) * 75)
            self._emit(
                progress_callback,
                {
                    "progress": min(progress, 100),
                    "message": f"分镜 {idx}/{total} 已生成",
                    "output": {
                        "shot_id": shot.shot_id,
                        "title": shot.title,
                        "prompt": prompt,
                        "uses_edit_model": use_edit,
                        "remote_url": remote_url,
                        "local_path": local_path,
                        "web_url": local_path_to_web_url(local_path),
                    },
                },
            )

        write_json(task_dir / "prompts.json", prompts_dump)
        write_json(task_dir / "result.json", [item.model_dump() for item in outputs])

        return GenerateResponse(
            task_id=task_id,
            storyboards=storyboards,
            character_guide=character_guide,
            style_bible=style_bible,
            reference_image_url=reference_image_url,
            reference_candidates=reference_candidates,
            selected_reference_index=selected_reference_index,
            outputs=outputs,
        )

    def run(
        self,
        request: GenerateRequest,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        task_id: str | None = None,
    ) -> GenerateResponse:
        preview = self.build_preview(
            request=request,
            progress_callback=progress_callback,
            task_id=task_id,
        )
        if not preview["reference_candidates"]:
            raise ValueError("未生成可用参考图")
        return self.render_from_preview(
            task_id=preview["task_id"],
            storyboards=preview["storyboards"],
            character_guide=preview["character_guide"],
            style_bible=preview["style_bible"],
            style_hint=request.style_hint,
            reference_candidates=preview["reference_candidates"],
            selected_reference_index=0,
            progress_callback=progress_callback,
        )

    def _prepare_reference_candidates(
        self,
        request: PreviewRequest,
        character_guide: str,
        style_bible: str,
        task_dir: Path,
    ) -> list[ReferenceCandidate]:
        return self.regenerate_reference_candidates(
            task_id=task_dir.name,
            character_guide=character_guide,
            style_bible=style_bible,
            style_hint=request.style_hint,
            reference_mode=request.reference_mode,
            reference_image_url=request.reference_image_url,
            upload_reference_strategy=request.upload_reference_strategy,
        )

    def regenerate_reference_candidates(
        self,
        task_id: str,
        character_guide: str,
        style_bible: str,
        style_hint: str,
        reference_mode: str,
        reference_image_url: str | None,
        upload_reference_strategy: str = "use_original",
    ) -> list[ReferenceCandidate]:
        candidates: list[ReferenceCandidate] = []
        task_dir = ensure_dir(settings.output_path / task_id)
        ref_dir = ensure_dir(task_dir / "reference_candidates")

        if reference_mode == "upload":
            if not reference_image_url:
                raise ValueError("reference_mode=upload 时必须提供 reference_image_url")
            ref_path = self._resolve_reference_path(reference_image_url)
            if not ref_path or not ref_path.exists():
                raise ValueError("上传参考图不存在或路径无效")
            if upload_reference_strategy == "regenerate":
                prompt = self.prompt_service.build_upload_regenerate_reference_prompt(
                    character_guide=character_guide,
                    style_bible=style_bible,
                    style_hint=style_hint,
                )
                remote_url = self.image_service.edit_image(ref_path, prompt)
                if not remote_url:
                    raise ValueError("基于上传图生成风格参考图失败，请改用“直接使用上传图”")
                filename = "reference_regenerated.png"
                saved = self.image_service.download_image(remote_url, ref_dir / filename)
                candidates.append(
                    ReferenceCandidate(
                        index=0,
                        prompt=prompt,
                        remote_url=remote_url,
                        local_path=str(saved.resolve()),
                        web_url=local_path_to_web_url(str(saved)),
                    )
                )
            else:
                candidates.append(
                    ReferenceCandidate(
                        index=0,
                        prompt="用户上传参考图（直接使用）",
                        local_path=str(ref_path.resolve()),
                        web_url=reference_image_url,
                    )
                )
            write_json(task_dir / "reference_candidates.json", [c.model_dump() for c in candidates])
            return candidates

        # 纯文本模式：生成3张可选人物参考图
        for idx in range(3):
            prompt = self.prompt_service.build_reference_prompt(
                character_guide=character_guide,
                style_bible=style_bible,
                variant_index=idx,
            )
            remote_url = self.image_service.generate_image(prompt)
            local_path = None
            web_url = None
            if remote_url:
                filename = f"reference_{idx + 1:02d}.png"
                saved = self.image_service.download_image(remote_url, ref_dir / filename)
                local_path = str(saved)
                web_url = local_path_to_web_url(local_path)
            candidates.append(
                ReferenceCandidate(
                    index=idx,
                    prompt=prompt,
                    remote_url=remote_url,
                    local_path=local_path,
                    web_url=web_url,
                )
            )
        write_json(task_dir / "reference_candidates.json", [c.model_dump() for c in candidates])
        return candidates

    @staticmethod
    def _resolve_reference_path(reference_url: str) -> Path | None:
        if not reference_url.startswith("/outputs/"):
            return None
        rel = reference_url[len("/outputs/") :].replace("\\", "/")
        return settings.output_path / rel

    @staticmethod
    def _pick_reference(
        reference_candidates: list[ReferenceCandidate], selected_reference_index: int
    ) -> ReferenceCandidate:
        if not reference_candidates:
            raise ValueError("没有可用参考图候选")
        matched = [
            item for item in reference_candidates if item.index == selected_reference_index
        ]
        if not matched:
            raise ValueError("选择的参考图不存在")
        return matched[0]

    @staticmethod
    def _emit(
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
        payload: Dict[str, Any],
    ) -> None:
        if progress_callback:
            progress_callback(payload)

    @staticmethod
    def _build_task_id() -> str:
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{now}_{uuid4().hex[:8]}"


def local_path_to_web_url(path: str | None) -> str | None:
    if not path:
        return None
    full = Path(path).resolve()
    base = settings.output_path
    try:
        rel = full.relative_to(base)
    except ValueError:
        return None
    return f"/outputs/{rel.as_posix()}"
