"""Shared download bounds and decoding checks for artwork candidates."""
from __future__ import annotations

from io import BytesIO

from PIL import Image, UnidentifiedImageError

from .const import MAX_SOURCE_IMAGE_BYTES, MAX_SOURCE_IMAGE_PIXELS

_MAX_SOURCE_FRAMES = 1000
_MAX_DECODED_FRAME_PIXELS = 400_000_000


async def read_bounded_image(response) -> bytes:
    """Bound the decoded HTTP body even without a truthful Content-Length."""
    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_SOURCE_IMAGE_BYTES:
        raise ValueError("Artwork image exceeds the 15 MB safety limit")
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.content.iter_chunked(64 * 1024):
        size += len(chunk)
        if size > MAX_SOURCE_IMAGE_BYTES:
            raise ValueError("Artwork image exceeds the 15 MB safety limit")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise ValueError("Artwork response was empty")
    return data


def validate_image(data: bytes) -> None:
    """Reject corrupt or unsafe candidates without changing original GIF bytes.

    Run this in an executor. Verification checks the file structure; loading
    frames also catches compressed image data that only fails during decoding.
    Frames are visited one at a time so animated covers are not held in memory.
    """
    validate_image_animation(data)


def validate_image_animation(data: bytes) -> bool:
    """Validate an image and report whether its decoded container has multiple frames.

    Run in an executor, just like ``validate_image``. Inspecting the actual
    frames avoids treating a still GIF or an animated image without a GIF URL
    suffix as the wrong kind of cover.
    """
    if not data or len(data) > MAX_SOURCE_IMAGE_BYTES:
        raise ValueError("Artwork image is empty or exceeds the size safety limit")
    try:
        with Image.open(BytesIO(data)) as source:
            _check_dimensions(source)
            source.verify()
        with Image.open(BytesIO(data)) as source:
            frame_count = max(1, int(getattr(source, "n_frames", 1)))
            if frame_count > _MAX_SOURCE_FRAMES:
                raise ValueError("Artwork animation exceeds the 1000-frame safety limit")
            decoded_pixels = 0
            for index in range(frame_count):
                source.seek(index)
                _check_dimensions(source)
                decoded_pixels += source.width * source.height
                if decoded_pixels > _MAX_DECODED_FRAME_PIXELS:
                    raise ValueError("Artwork animation exceeds the decoded pixel safety limit")
                source.load()
            return frame_count > 1
    except (
        UnidentifiedImageError, Image.DecompressionBombError,
        OSError, EOFError, SyntaxError,
    ) as err:
        raise ValueError("Artwork did not contain a safe, supported image") from err


def _check_dimensions(source: Image.Image) -> None:
    if source.width < 1 or source.height < 1:
        raise ValueError("Artwork image dimensions must be positive")
    if source.width * source.height > MAX_SOURCE_IMAGE_PIXELS:
        raise ValueError("Artwork image dimensions exceed the pixel safety limit")
