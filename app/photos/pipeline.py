from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import Engine
from sqlmodel import Session

from app.models import Item, PhotoRole, PhotoStatus, ProductPhoto
from app.photos.editor import PhotoPreset, ProductPhotoEditor, build_edit_prompt
from app.photos.reviewer import PhotoTruthReviewer
from app.photos.storage import PhotoStorage


class PhotoPipelineError(RuntimeError):
    pass


class PhotoItemNotFound(PhotoPipelineError):
    pass


class PhotoInputError(PhotoPipelineError):
    pass


class PhotoEditError(PhotoPipelineError):
    pass


@dataclass(frozen=True, slots=True)
class EnhancementResult:
    original: ProductPhoto
    enhanced: ProductPhoto


async def enhance_product_photo(
    *,
    engine: Engine,
    item_id: str,
    content: bytes,
    mime_type: str,
    preset: PhotoPreset,
    editor: ProductPhotoEditor,
    storage: PhotoStorage,
    reviewer: PhotoTruthReviewer | None = None,
) -> EnhancementResult:
    with Session(engine) as session:
        if session.get(Item, item_id) is None:
            raise PhotoItemNotFound("item not found")

    try:
        stored = storage.save_original(item_id, content, mime_type)
    except ValueError as exc:
        raise PhotoInputError(str(exc)) from exc
    try:
        edit_source = storage.normalize_for_edit(stored)
    except ValueError as exc:
        stored.absolute_path.unlink(missing_ok=True)
        raise PhotoInputError(str(exc)) from exc

    with Session(engine) as session:
        item = session.get(Item, item_id)
        if item is None:
            stored.absolute_path.unlink(missing_ok=True)
            edit_source.unlink(missing_ok=True)
            raise PhotoItemNotFound("item not found")
        prompt = build_edit_prompt(item, preset)
        item_title = item.title
        known_defects = item.constraints_json.get("defects", [])
        if isinstance(known_defects, str):
            known_defects = [known_defects]
        original = ProductPhoto(
            item_id=item.id,
            role=PhotoRole.ORIGINAL,
            status=PhotoStatus.ORIGINAL,
            file_path=stored.relative_path,
            mime_type=stored.mime_type,
            sha256=stored.sha256,
        )
        session.add(original)
        session.flush()
        target = storage.enhanced_path(item.id, original.id)
        enhanced = ProductPhoto(
            item_id=item.id,
            source_photo_id=original.id,
            role=PhotoRole.ENHANCED,
            status=PhotoStatus.PROCESSING,
            file_path=target.relative_path,
            mime_type="image/png",
            sha256="pending",
            preset=preset.value,
            prompt=prompt,
            model=editor.model,
            disclosure="AI-enhanced lighting and background. Original image retained.",
        )
        session.add(enhanced)
        item.photo_paths = [*item.photo_paths, original.file_path]
        session.add(item)
        session.commit()
        original_id = original.id
        enhanced_id = enhanced.id

    truth_disclosure = ""
    try:
        await asyncio.to_thread(editor.edit, edit_source, target.absolute_path, prompt)
        if not target.absolute_path.exists() or target.absolute_path.stat().st_size == 0:
            raise RuntimeError("image editor produced an empty output")
        if reviewer is not None:
            truth_check = await reviewer.review(
                edit_source,
                target.absolute_path,
                item_title=item_title,
                known_defects=known_defects,
            )
            if not (
                truth_check.passed
                and truth_check.identity_preserved
                and truth_check.visible_defects_preserved
            ):
                raise RuntimeError("automated truth check rejected the enhanced photo")
            truth_disclosure = (
                f" Automated truth check passed with {truth_check.confidence:.0%} confidence."
            )
    except Exception as exc:
        target.absolute_path.unlink(missing_ok=True)
        with Session(engine) as session:
            failed = session.get(ProductPhoto, enhanced_id)
            if failed is not None:
                failed.status = PhotoStatus.FAILED
                failed.failure_reason = type(exc).__name__
                session.add(failed)
                session.commit()
        raise PhotoEditError("image enhancement failed") from exc
    finally:
        edit_source.unlink(missing_ok=True)

    with Session(engine) as session:
        ready = session.get(ProductPhoto, enhanced_id)
        original = session.get(ProductPhoto, original_id)
        if ready is None or original is None:
            raise PhotoPipelineError("photo record was lost")
        ready.status = PhotoStatus.REVIEW
        ready.sha256 = storage.sha256_file(target.absolute_path)
        ready.disclosure = f"{ready.disclosure}{truth_disclosure}"
        session.add(ready)
        session.commit()
        session.refresh(ready)
        session.refresh(original)
        return EnhancementResult(original=original, enhanced=ready)
