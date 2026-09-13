from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from app.ids import new_id

register_heif_opener()

MAX_PHOTO_BYTES = 15 * 1024 * 1024
MAX_PHOTO_PIXELS = 40_000_000
EXTENSIONS_BY_MIME = {
    "image/heic": ".heic",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def detect_mime_type(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    if (
        len(content) >= 12
        and content[4:8] == b"ftyp"
        and content[8:12] in {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}
    ):
        return "image/heic"
    return None


@dataclass(frozen=True)
class StoredPhoto:
    relative_path: str
    absolute_path: Path
    sha256: str
    mime_type: str


class PhotoStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def save_original(self, item_id: str, content: bytes, mime_type: str) -> StoredPhoto:
        mime_aliases = {"image/heif": "image/heic", "image/jpg": "image/jpeg"}
        declared_mime = mime_aliases.get(mime_type, mime_type)
        detected_mime = detect_mime_type(content)
        extension = EXTENSIONS_BY_MIME.get(declared_mime)
        if extension is None:
            raise ValueError("photo must be HEIC, JPEG, PNG, or WebP")
        if not content:
            raise ValueError("photo is empty")
        if len(content) > MAX_PHOTO_BYTES:
            raise ValueError("photo exceeds the 15 MB limit")
        if detected_mime != declared_mime:
            raise ValueError("photo contents do not match its media type")
        assert detected_mime is not None
        relative = Path(item_id) / f"{new_id()}-original{extension}"
        absolute = self.root / relative
        absolute.parent.mkdir(parents=True, exist_ok=True)
        absolute.write_bytes(content)
        return StoredPhoto(
            relative_path=str(relative),
            absolute_path=absolute,
            sha256=hashlib.sha256(content).hexdigest(),
            mime_type=detected_mime,
        )

    def normalize_for_edit(self, photo: StoredPhoto) -> Path:
        output = photo.absolute_path.with_name(f"{photo.absolute_path.stem}-input.png")
        try:
            with Image.open(BytesIO(photo.absolute_path.read_bytes())) as source:
                source.load()
                if source.width * source.height > MAX_PHOTO_PIXELS:
                    raise ValueError("photo exceeds the 40 megapixel limit")
                normalized = ImageOps.exif_transpose(source)
                if normalized.mode not in {"RGB", "RGBA"}:
                    normalized = normalized.convert("RGB")
                normalized.save(output, format="PNG", optimize=True)
        except (UnidentifiedImageError, OSError) as exc:
            output.unlink(missing_ok=True)
            raise ValueError("photo could not be decoded") from exc
        return output

    def enhanced_path(self, item_id: str, photo_id: str) -> StoredPhoto:
        relative = Path(item_id) / f"{photo_id}-enhanced.png"
        absolute = self.root / relative
        return StoredPhoto(
            relative_path=str(relative),
            absolute_path=absolute,
            sha256="",
            mime_type="image/png",
        )

    @staticmethod
    def sha256_file(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def resolve(self, relative_path: str) -> Path:
        resolved = (self.root / relative_path).resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("invalid photo path")
        return resolved
