from __future__ import annotations

import httpx
import pytest

from app.market.ebay import EbayClient, EbayError, EbaySandboxClient

SUCCESS_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<UploadSiteHostedPicturesResponse xmlns="urn:ebay:apis:eBLBaseComponents">'
    "<Timestamp>2026-09-13T17:00:00.000Z</Timestamp><Ack>Success</Ack>"
    "<SiteHostedPictureDetails><PictureName>liquid-photo-1</PictureName>"
    "<FullURL>https://i.sandbox.ebayimg.com/00/s/NjQwWDY0MA==/z/abc/$_1.JPG?set_id=1</FullURL>"
    "</SiteHostedPictureDetails></UploadSiteHostedPicturesResponse>"
)
FAILURE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<UploadSiteHostedPicturesResponse xmlns="urn:ebay:apis:eBLBaseComponents">'
    "<Ack>Failure</Ack><Errors><ShortMessage>Bad picture.</ShortMessage>"
    "<LongMessage>The image file is corrupt.</LongMessage><ErrorCode>21916017</ErrorCode>"
    "</Errors></UploadSiteHostedPicturesResponse>"
)
JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg-bytes" * 4
XML_HEADERS = {"content-type": "text/xml"}


@pytest.mark.asyncio
async def test_sandbox_upload_uses_the_trading_api_multipart_call() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/identity/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "access-token", "expires_in": 7200})
        if request.url.path == "/ws/api.dll":
            seen.append(request)
            return httpx.Response(200, content=SUCCESS_XML.encode(), headers=XML_HEADERS)
        return httpx.Response(404)

    client = EbaySandboxClient(
        "id", "secret", "refresh", client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    url = await client.upload_picture(JPEG, filename="photo-1.jpg", picture_name="liquid-photo-1")
    await client.close()

    assert url.startswith("https://i.sandbox.ebayimg.com/")
    request = seen[0]
    assert request.url.host == "api.sandbox.ebay.com"
    assert request.headers["x-ebay-api-call-name"] == "UploadSiteHostedPictures"
    assert request.headers["x-ebay-api-iaf-token"] == "access-token"
    assert request.headers["x-ebay-api-siteid"] == "0"
    assert request.headers["content-type"].startswith("multipart/form-data")
    body = request.read()
    assert b'name="XML Payload"' in body
    assert b"<PictureName>liquid-photo-1</PictureName>" in body
    assert b'filename="photo-1.jpg"' in body
    assert JPEG in body


@pytest.mark.asyncio
async def test_upload_failure_surfaces_ebays_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/identity/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 7200})
        return httpx.Response(200, content=FAILURE_XML.encode(), headers=XML_HEADERS)

    client = EbaySandboxClient(
        "id", "secret", "refresh", client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(EbayError, match="corrupt"):
        await client.upload_picture(JPEG)
    with pytest.raises(EbayError, match="empty"):
        await client.upload_picture(b"")
    await client.close()


@pytest.mark.asyncio
async def test_production_upload_uses_the_media_api() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/identity/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 7200})
        if request.url == "https://apim.ebay.com/commerce/media/v1_beta/image/create_image_from_file":
            assert b'name="image"' in request.read()
            return httpx.Response(
                201,
                headers={"Location": "https://apim.ebay.com/commerce/media/v1_beta/image/img-9"},
            )
        if request.url == "https://apim.ebay.com/commerce/media/v1_beta/image/img-9":
            return httpx.Response(200, json={"imageUrl": "https://i.ebayimg.com/images/g/x/s-l1600.jpg"})
        return httpx.Response(404)

    client = EbayClient(
        "id",
        "secret",
        "refresh",
        environment="production",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    url = await client.upload_picture(JPEG, filename="a.jpg")
    await client.close()
    assert url == "https://i.ebayimg.com/images/g/x/s-l1600.jpg"
