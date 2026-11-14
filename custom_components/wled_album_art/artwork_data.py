"""Prepare bounded artwork and colors for Home Assistant entities."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from .const import MAX_SOURCE_IMAGE_BYTES, MAX_SOURCE_IMAGE_PIXELS
from .image_processing import extract_theme_palette, prepare_image


@dataclass(frozen=True)
class PreparedArtwork:
    """Immutable artwork shared by image and color entities."""

    image: bytes
    content_type: str
    palette: tuple[tuple[int, int, int], ...]
    width: int
    height: int
    is_animated: bool
    source_is_animated: bool
    source_frame_count: int
    fingerprint: str


def prepare_artwork_data(
    data: bytes,
    animated_artwork: bool = True,
    palette_count: int = 8,
) -> PreparedArtwork:
    """Create a thumbnail and palette without requiring a lighting output.

    Animated sources use the same thumbnail dimensions with animation on or
    off. Static sources retain more detail for dashboard backgrounds.
    """
    try:
        with Image.open(BytesIO(data)) as source:
            width, height = source.size
            if width < 1 or height < 1:
                raise ValueError("Artwork image dimensions must be positive")
            if width * height > MAX_SOURCE_IMAGE_PIXELS:
                raise ValueError("Artwork image dimensions exceed the pixel safety limit")
            source_frame_count = max(1, int(getattr(source, "n_frames", 1)))
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        OSError,
        EOFError,
    ) as err:
        raise ValueError("Artwork did not contain a safe, supported image") from err

    source_is_animated = source_frame_count > 1
    width, height = _thumbnail_dimensions(
        width, height, 256 if source_is_animated else 512
    )
    use_animation = source_is_animated and animated_artwork

    def prepare_export(export_width: int, export_height: int) -> bytes:
        preview, animation = prepare_image(
            data,
            export_width,
            export_height,
            "contain",
            animated_artwork=animated_artwork,
        )
        return animation if use_animation else preview

    image = prepare_export(width, height)
    if len(image) > MAX_SOURCE_IMAGE_BYTES:
        retry_width, retry_height = _thumbnail_dimensions(width, height, 128)
        if (retry_width, retry_height) == (width, height):
            raise ValueError("Prepared artwork exceeds the image size limit")
        width, height = retry_width, retry_height
        image = prepare_export(width, height)
        if len(image) > MAX_SOURCE_IMAGE_BYTES:
            raise ValueError("Prepared artwork exceeds the image size limit")

    is_animated = False
    if use_animation:
        with Image.open(BytesIO(image)) as prepared:
            # GIF encoders can merge identical source frames.
            is_animated = int(getattr(prepared, "n_frames", 1)) > 1

    return PreparedArtwork(
        image=image,
        content_type="image/gif" if use_animation else "image/png",
        palette=tuple(extract_theme_palette(data, palette_count)),
        width=width,
        height=height,
        is_animated=is_animated,
        source_is_animated=source_is_animated,
        source_frame_count=source_frame_count,
        fingerprint=sha256(image).hexdigest(),
    )


def _thumbnail_dimensions(width: int, height: int, limit: int) -> tuple[int, int]:
    """Fit dimensions within a square while retaining aspect and never upscaling."""
    scale = min(1.0, limit / width, limit / height)
    return max(1, round(width * scale)), max(1, round(height * scale))
