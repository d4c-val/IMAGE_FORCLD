from pathlib import Path
from threading import Lock, Thread
from typing import Any, Dict
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.schemas import ApproveRequest, PreviewRequest, ReferenceCandidate, StoryboardItem
from app.services.dashscope_client import DashScopeError
from app.services.pipeline import StoryToImagePipeline, local_path_to_web_url

app = FastAPI(title="Qwen Storybook Generator", version="0.1.0")
pipeline = StoryToImagePipeline()
jobs: Dict[str, Dict[str, Any]] = {}
jobs_lock = Lock()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

web_dir = Path(__file__).resolve().parent.parent / "web"
app.mount("/web", StaticFiles(directory=str(web_dir)), name="web")
app.mount("/outputs", StaticFiles(directory=str(settings.output_path)), name="outputs")


@app.get("/")
def root() -> FileResponse:
    return FileResponse(web_dir / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/preview")
def preview(req: PreviewRequest) -> dict:
    job_id = uuid4().hex
    with jobs_lock:
        jobs[job_id] = {
            "job_id": job_id,
            "status": "queued_preview",
            "phase": "preview",
            "progress": 0,
            "message": "预览任务已创建，等待执行",
            "story_text": req.story_text,
            "style_hint": req.style_hint,
            "reference_mode": req.reference_mode,
            "upload_reference_strategy": req.upload_reference_strategy,
            "storyboards": [],
            "reference_candidates": [],
            "selected_reference_index": None,
            "outputs": [],
            "reference_image_url": req.reference_image_url,
            "result_json_url": None,
            "images_zip_url": None,
        }

    worker = Thread(target=_run_preview_job, args=(job_id, req), daemon=True)
    worker.start()
    return {"job_id": job_id, "status": "queued_preview", "phase": "preview"}


@app.post("/api/jobs/{job_id}/regenerate-references")
def regenerate_references(job_id: str) -> dict:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        if job.get("phase") != "preview":
            raise HTTPException(status_code=400, detail="仅预览阶段可重新生成参考图")
        if job.get("status") not in {"preview_ready"}:
            raise HTTPException(status_code=400, detail="当前任务状态不允许重生参考图")
        character_guide = job.get("character_guide") or ""
        style_bible = job.get("style_bible") or ""
        style_hint = job.get("style_hint") or ""
        reference_mode = job.get("reference_mode") or "text"
        reference_image_url = job.get("reference_image_url")
        upload_reference_strategy = job.get("upload_reference_strategy") or "use_original"

    # 用户主动点击“重生”时，上传模式默认走重绘，避免重复拿到同一原图。
    if reference_mode == "upload":
        upload_reference_strategy = "regenerate"

    try:
        candidates = pipeline.regenerate_reference_candidates(
            task_id=job_id,
            character_guide=character_guide,
            style_bible=style_bible,
            style_hint=style_hint,
            reference_mode=reference_mode,
            reference_image_url=reference_image_url,
            upload_reference_strategy=upload_reference_strategy,
        )
    except DashScopeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with jobs_lock:
        jobs[job_id].update(
            {
                "reference_candidates": [c.model_dump() for c in candidates],
                "selected_reference_index": 0 if candidates else None,
                "reference_image_url": (
                    candidates[0].web_url if candidates else jobs[job_id].get("reference_image_url")
                ),
                "message": "参考图已重新生成，请重新选择后继续",
                "progress": 25,
            }
        )
        updated = jobs[job_id]
    return {
        "job_id": job_id,
        "reference_candidates": updated["reference_candidates"],
        "selected_reference_index": updated["selected_reference_index"],
        "reference_image_url": updated["reference_image_url"],
        "message": updated["message"],
    }


@app.post("/api/jobs/{job_id}/approve")
def approve(job_id: str, req: ApproveRequest) -> dict:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        if job.get("status") != "preview_ready":
            raise HTTPException(status_code=400, detail="当前任务还未到可审核状态")
        if not job.get("reference_candidates"):
            raise HTTPException(status_code=400, detail="没有可用参考图候选")
        if job.get("phase") != "preview":
            raise HTTPException(status_code=400, detail="任务阶段不允许审核")
        available_indexes = {item.get("index") for item in job["reference_candidates"]}
        if req.selected_reference_index not in available_indexes:
            raise HTTPException(status_code=400, detail="所选参考图索引无效")
        # 覆盖分镜为用户审核后的版本，并重排 shot_id，避免前端编辑顺序造成异常。
        normalized_storyboards = _normalize_storyboards(req.storyboards)
        job["storyboards"] = [item.model_dump() for item in normalized_storyboards]
        job["selected_reference_index"] = req.selected_reference_index
        job["status"] = "queued_render"
        job["phase"] = "render"
        job["progress"] = 25
        job["message"] = "审核通过，准备开始生成图片"

    worker = Thread(
        target=_run_render_job,
        args=(job_id, normalized_storyboards, req.selected_reference_index),
        daemon=True,
    )
    worker.start()
    return {"job_id": job_id, "status": "queued_render", "phase": "render"}


@app.post("/api/generate")
def generate_compat(req: PreviewRequest) -> dict:
    # 兼容旧入口：一键走完整流程，默认选第一张参考图。
    job_id = uuid4().hex
    with jobs_lock:
        jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "phase": "render",
            "progress": 0,
            "message": "任务已创建，等待执行",
            "story_text": req.story_text,
            "style_hint": req.style_hint,
            "reference_mode": req.reference_mode,
            "upload_reference_strategy": req.upload_reference_strategy,
            "storyboards": [],
            "reference_candidates": [],
            "selected_reference_index": 0,
            "outputs": [],
            "reference_image_url": req.reference_image_url,
            "result_json_url": None,
            "images_zip_url": None,
        }
    worker = Thread(target=_run_legacy_generate, args=(job_id, req), daemon=True)
    worker.start()
    return {"job_id": job_id, "status": "queued", "phase": "render"}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@app.get("/api/jobs/{job_id}/download-images")
def download_images_zip(job_id: str) -> FileResponse:
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.get("status") != "completed":
        raise HTTPException(status_code=400, detail="任务未完成，暂不可下载")

    task_id = job.get("task_id") or job_id
    task_dir = settings.output_path / task_id
    images_dir = task_dir / "images"
    if not images_dir.exists():
        raise HTTPException(status_code=404, detail="未找到可打包图片目录")

    zip_path = task_dir / "images.zip"
    with ZipFile(zip_path, mode="w", compression=ZIP_DEFLATED) as zf:
        for image_file in sorted(images_dir.glob("*.png")):
            zf.write(image_file, arcname=image_file.name)

    return FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=f"{task_id}_images.zip",
    )


@app.post("/api/upload-reference")
async def upload_reference(file: UploadFile = File(...)) -> dict:
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名为空")
    ext = Path(file.filename).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail="仅支持 png/jpg/jpeg/webp")

    target_dir = settings.output_path / "reference_uploads"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_name = f"{uuid4().hex[:10]}{ext}"
    target = target_dir / target_name
    content = await file.read()
    target.write_bytes(content)
    return {
        "reference_image_url": f"/outputs/reference_uploads/{target_name}",
        "local_path": str(target),
    }


def _run_preview_job(job_id: str, req: PreviewRequest) -> None:
    def on_progress(payload: Dict[str, Any]) -> None:
        with jobs_lock:
            job = jobs[job_id]
            job["progress"] = payload.get("progress", job["progress"])
            job["message"] = payload.get("message", job["message"])
            if payload.get("storyboards"):
                job["storyboards"] = payload["storyboards"]
            if payload.get("reference_candidates"):
                job["reference_candidates"] = payload["reference_candidates"]
            if payload.get("reference_image_url"):
                job["reference_image_url"] = payload["reference_image_url"]

    with jobs_lock:
        jobs[job_id]["status"] = "running_preview"
        jobs[job_id]["phase"] = "preview"
        jobs[job_id]["message"] = "正在生成分镜预览"
    try:
        preview = pipeline.build_preview(req, progress_callback=on_progress, task_id=job_id)
        with jobs_lock:
            jobs[job_id].update(
                {
                    "status": "preview_ready",
                    "phase": "preview",
                    "progress": 25,
                    "message": "分镜预览已生成，请先审核后再出图",
                    "task_id": preview["task_id"],
                    "character_guide": preview["character_guide"],
                    "style_bible": preview["style_bible"],
                    "storyboards": [s.model_dump() for s in preview["storyboards"]],
                    "reference_candidates": [
                        c.model_dump() for c in preview["reference_candidates"]
                    ],
                    "selected_reference_index": preview["selected_reference_index"],
                    "reference_image_url": preview["reference_image_url"],
                }
            )
    except DashScopeError as exc:
        with jobs_lock:
            jobs[job_id].update(
                {
                    "status": "failed",
                    "phase": "preview",
                    "message": str(exc),
                    "error_type": "dashscope",
                }
            )
    except Exception as exc:  # noqa: BLE001
        with jobs_lock:
            jobs[job_id].update(
                {
                    "status": "failed",
                    "phase": "preview",
                    "message": f"内部错误: {exc}",
                    "error_type": "internal",
                }
            )


def _run_render_job(
    job_id: str, storyboards: list[StoryboardItem], selected_reference_index: int
) -> None:
    def on_progress(payload: Dict[str, Any]) -> None:
        with jobs_lock:
            job = jobs[job_id]
            job["progress"] = payload.get("progress", job["progress"])
            job["message"] = payload.get("message", job["message"])
            if payload.get("storyboards"):
                job["storyboards"] = payload["storyboards"]
            if payload.get("reference_image_url"):
                job["reference_image_url"] = payload["reference_image_url"]
            if payload.get("output"):
                output = payload["output"]
                existing = [o for o in job["outputs"] if o["shot_id"] != output["shot_id"]]
                existing.append(output)
                existing.sort(key=lambda x: x["shot_id"])
                job["outputs"] = existing

    with jobs_lock:
        job = jobs[job_id]
        style_hint = job.get("style_hint", "")
        character_guide = job.get("character_guide", "")
        style_bible = job.get("style_bible", "")
        raw_candidates = job.get("reference_candidates", [])
        jobs[job_id]["status"] = "running_render"
        jobs[job_id]["phase"] = "render"
        jobs[job_id]["message"] = "正在根据审核分镜生成图片"
    try:
        candidates = [ReferenceCandidate.model_validate(item) for item in raw_candidates]
        result = pipeline.render_from_preview(
            task_id=job_id,
            storyboards=storyboards,
            character_guide=character_guide,
            style_bible=style_bible,
            style_hint=style_hint,
            reference_candidates=candidates,
            selected_reference_index=selected_reference_index,
            progress_callback=on_progress,
        )
        outputs = []
        for item in result.outputs:
            outputs.append(
                {
                    "shot_id": item.shot_id,
                    "title": item.title,
                    "prompt": item.prompt,
                    "uses_edit_model": item.uses_edit_model,
                    "remote_url": item.remote_url,
                    "local_path": item.local_path,
                    "web_url": local_path_to_web_url(item.local_path),
                }
            )
        with jobs_lock:
            jobs[job_id].update(
                {
                    "status": "completed",
                    "phase": "render",
                    "progress": 100,
                    "message": "任务完成",
                    "task_id": result.task_id,
                    "character_guide": result.character_guide,
                    "style_bible": result.style_bible,
                    "storyboards": [s.model_dump() for s in result.storyboards],
                    "reference_candidates": [
                        c.model_dump() for c in result.reference_candidates
                    ],
                    "selected_reference_index": result.selected_reference_index,
                    "reference_image_url": result.reference_image_url,
                    "outputs": outputs,
                    "result_json_url": f"/outputs/{result.task_id}/result.json",
                    "images_zip_url": f"/api/jobs/{job_id}/download-images",
                }
            )
    except DashScopeError as exc:
        with jobs_lock:
            jobs[job_id].update(
                {
                    "status": "failed",
                    "phase": "render",
                    "message": str(exc),
                    "error_type": "dashscope",
                }
            )
    except Exception as exc:  # noqa: BLE001
        with jobs_lock:
            jobs[job_id].update(
                {
                    "status": "failed",
                    "phase": "render",
                    "message": f"内部错误: {exc}",
                    "error_type": "internal",
                }
            )


def _run_legacy_generate(job_id: str, req: PreviewRequest) -> None:
    # 兼容模式：直接执行完整流程，不经过前端审核。
    preview = pipeline.build_preview(req, task_id=job_id)
    with jobs_lock:
        jobs[job_id].update(
            {
                "character_guide": preview["character_guide"],
                "style_bible": preview["style_bible"],
                "storyboards": [s.model_dump() for s in preview["storyboards"]],
                "reference_candidates": [
                    c.model_dump() for c in preview["reference_candidates"]
                ],
                "selected_reference_index": 0,
                "reference_image_url": preview["reference_image_url"],
                "progress": 25,
            }
        )
    storyboards = _normalize_storyboards(preview["storyboards"])
    selected_reference_index = 0
    _run_render_job(job_id, storyboards, selected_reference_index)


def _normalize_storyboards(items: list[StoryboardItem]) -> list[StoryboardItem]:
    normalized: list[StoryboardItem] = []
    for index, item in enumerate(items, start=1):
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
