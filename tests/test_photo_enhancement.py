from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image
from pillow_heif import from_pillow

from app.config import Mode, Settings
from app.main import create_app
from app.photos.editor import OpenAIProductPhotoEditor


def make_test_jpeg() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 3), color=(32, 64, 96)).save(buffer, format="JPEG")
    return buffer.getvalue()


TEST_JPEG = make_test_jpeg()


def make_test_heic() -> bytes:
    buffer = BytesIO()
    from_pillow(Image.new("RGB", (4, 3), color=(96, 64, 32))).save(buffer)
    return buffer.getvalue()


class FakePhotoEditor:
    model = "fake-image-editor"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def edit(self, source_path: Path, output_path: Path, prompt: str) -> None:
        assert source_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        self.prompts.append(prompt)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x89PNG\r\n\x1a\nenhanced-photo")


def create_item(client: TestClient) -> str:
    response = client.post(
        "/api/items",
        json={
            "seller_handle": "+14155550123",
            "title": "Sony WH-1000XM5 headphones",
            "brand": "Sony",
            "model": "WH-1000XM5",
            "market_value_cents": 20_500,
            "sigma_cents": 2_500,
            "floor_cents": 17_000,
            "deadline_hours": 72,
        },
    )
    assert response.status_code == 201
    return response.json()["item_id"]


def test_enhance_requires_review_and_preserves_original(tmp_path: Path) -> None:
    editor = FakePhotoEditor()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
        ),
        photo_editor=editor,
    )
    with TestClient(app) as client:
        item_id = create_item(client)
        response = client.post(
            f"/api/items/{item_id}/photos/enhance",
            files={"upload": ("headphones.jpg", TEST_JPEG, "image/jpeg")},
            data={"preset": "clean_tabletop"},
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload["status"] == "review"
        assert payload["requires_seller_approval"] is True
        assert client.get(payload["original_url"]).content == TEST_JPEG
        assert client.get(payload["enhanced_url"]).content.startswith(b"\x89PNG")

        prompt = editor.prompts[0]
        assert "Keep every visible defect equally visible" in prompt
        assert "Do not retouch the product itself" in prompt
        assert "no added props" not in prompt

        photos = client.get(f"/api/items/{item_id}/photos").json()
        assert [photo["role"] for photo in photos] == ["original", "enhanced"]
        assert [photo["status"] for photo in photos] == ["original", "review"]

        review = client.post(
            f"/api/items/{item_id}/photos/{payload['enhanced_photo_id']}/review",
            json={"approved": True},
        )
        assert review.status_code == 200
        assert review.json()["status"] == "approved"

        second_review = client.post(
            f"/api/items/{item_id}/photos/{payload['enhanced_photo_id']}/review",
            json={"approved": True},
        )
        assert second_review.status_code == 409


def test_enhance_is_unavailable_without_openai_configuration(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            openai_api_key=None,
        )
    )
    with TestClient(app) as client:
        item_id = create_item(client)
        response = client.post(
            f"/api/items/{item_id}/photos/enhance",
            files={"upload": ("headphones.jpg", TEST_JPEG, "image/jpeg")},
        )
        assert response.status_code == 503


def test_enhance_rejects_unsupported_files(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
        ),
        photo_editor=FakePhotoEditor(),
    )
    with TestClient(app) as client:
        item_id = create_item(client)
        response = client.post(
            f"/api/items/{item_id}/photos/enhance",
            files={"upload": ("notes.txt", b"not-a-photo", "text/plain")},
        )
        assert response.status_code == 422


def test_enhance_accepts_iphone_heic(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
        ),
        photo_editor=FakePhotoEditor(),
    )
    with TestClient(app) as client:
        item_id = create_item(client)
        response = client.post(
            f"/api/items/{item_id}/photos/enhance",
            files={"upload": ("IMG_0001.HEIC", make_test_heic(), "image/heic")},
        )
        assert response.status_code == 201
        assert response.json()["status"] == "review"


def test_openai_editor_sends_truth_prompt_and_writes_png(tmp_path: Path) -> None:
    calls: list[dict] = []

    class FakeImages:
        def edit(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                data=[SimpleNamespace(b64_json=base64.b64encode(b"edited-png").decode())]
            )

    client = SimpleNamespace(images=FakeImages())
    editor = OpenAIProductPhotoEditor(
        "unused-test-key",
        client=client,
        model="gpt-image-2.5-sunburst",
        quality="high",
        size="1024x1024",
    )
    source = tmp_path / "source.jpg"
    output = tmp_path / "output.png"
    source.write_bytes(TEST_JPEG)

    editor.edit(source, output, "preserve every visible defect")

    assert output.read_bytes() == b"edited-png"
    assert calls[0]["model"] == "gpt-image-2.5-sunburst"
    assert calls[0]["quality"] == "high"
    assert calls[0]["output_format"] == "png"
    assert "response_format" not in calls[0]
    assert calls[0]["prompt"] == "preserve every visible defect"
