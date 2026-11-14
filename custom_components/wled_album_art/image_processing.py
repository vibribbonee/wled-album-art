"""Image preparation and color palette extraction for Music Artwork Lighting."""
from __future__ import annotations

import colorsys
from io import BytesIO

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError

from .const import MAX_ANIMATED_ARTWORK_FRAMES, MAX_SOURCE_IMAGE_PIXELS


def prepare_image(
    data: bytes,
    width: int,
    height: int,
    fit_mode: str,
    zoom: float = 100,
    crop_position: str = "center",
    blur_strength: float = 16,
    background_brightness: float = 62,
    animated_artwork: bool = True,
) -> tuple[bytes, bytes]:
    """Return a full-color preview frame and a WLED-ready GIF.

    Static covers remain single-frame GIFs. Animated artwork is resized and
    fitted frame by frame so WLED 16's Image effect can play it natively.
    Disabling animation uses the first frame without decoding later frames.
    """
    if width < 1 or height < 1:
        raise ValueError("Image width and height must be positive")

    target_size = (int(width), int(height))
    centering = _crop_centering(crop_position)
    zoom = max(100.0, min(200.0, float(zoom))) / 100
    blur_strength = max(0.0, min(40.0, float(blur_strength)))
    background_brightness = max(0.0, min(100.0, float(background_brightness))) / 100
    frames: list[Image.Image] = []
    durations: list[int] = []
    animated = False
    try:
        with Image.open(BytesIO(data)) as source:
            if source.width * source.height > MAX_SOURCE_IMAGE_PIXELS:
                raise ValueError("Artwork image dimensions exceed the pixel safety limit")
            total_frames = (
                int(getattr(source, "n_frames", 1)) if animated_artwork else 1
            )
            animated = total_frames > 1
            sampled_frames = min(total_frames, MAX_ANIMATED_ARTWORK_FRAMES)
            if sampled_frames < total_frames:
                frame_indices = [
                    round(index * (total_frames - 1) / (sampled_frames - 1))
                    for index in range(sampled_frames)
                ]
            else:
                frame_indices = list(range(total_frames))
            for position, frame_index in enumerate(frame_indices):
                source.seek(frame_index)
                if source.width * source.height > MAX_SOURCE_IMAGE_PIXELS:
                    raise ValueError("Artwork image dimensions exceed the pixel safety limit")
                frames.append(_fit_image(
                    source.convert("RGB"), target_size, fit_mode, centering,
                    zoom, blur_strength, background_brightness,
                ))
                if animated:
                    duration = int(source.info.get("duration", 100) or 100)
                    next_frame_index = (
                        frame_indices[position + 1]
                        if position + 1 < len(frame_indices)
                        else total_frames
                    )
                    # Keep the selected frame on screen for the actual time
                    # covered by all skipped frames, including variable delays.
                    # The final bucket stops at the source's final frame.
                    for skipped_index in range(frame_index + 1, next_frame_index):
                        source.seek(skipped_index)
                        duration += int(source.info.get("duration", 100) or 100)
                    durations.append(max(20, min(2000, duration)))
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as err:
        raise ValueError("The media-player artwork URL did not return a safe, supported image") from err
    if not frames:
        raise ValueError("Artwork image did not contain any frames")

    image = frames[0]
    png_buffer = BytesIO()
    image.save(png_buffer, format="PNG", optimize=True)
    gif_buffer = BytesIO()
    if animated:
        frames[0].save(
            gif_buffer,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            disposal=2,
            optimize=True,
        )
    else:
        # GIF's 256-color limit is inherent to WLED 16's current matrix Image path.
        image.save(gif_buffer, format="GIF", optimize=True)
    return png_buffer.getvalue(), gif_buffer.getvalue()


def _fit_image(
    image: Image.Image,
    target_size: tuple[int, int],
    fit_mode: str,
    centering: tuple[float, float],
    zoom: float,
    blur_strength: float,
    background_brightness: float,
) -> Image.Image:
    """Fit one source frame to the matrix using the selected artwork style."""
    width, height = target_size
    if fit_mode == "crop":
        image = _fit_cover(image, target_size, centering, zoom)
    elif fit_mode == "contain":
        image = _contain_on_background(
            _zoom_crop(image, zoom, centering), target_size, (0, 0, 0)
        )
    elif fit_mode in {
        "blurred_background_soft", "blurred_background",
        "blurred_background_strong", "blurred_background_custom",
    }:
        # Fill the entire matrix with a visibly soft, color-matched backdrop.
        # Preserve the historic value as the medium-strength setting.
        preset_blur = {
            "blurred_background_soft": 8.0,
            "blurred_background": 16.0,
            "blurred_background_strong": 28.0,
        }.get(fit_mode)
        blur_percent = preset_blur if preset_blur is not None else blur_strength
        background_level = 0.62 if preset_blur is not None else background_brightness
        background = _fit_cover(image, target_size, centering, zoom)
        if blur_percent > 0:
            background = background.filter(
                ImageFilter.GaussianBlur(
                    radius=max(1, round(min(width, height) * blur_percent / 100))
                )
            )
        background = ImageEnhance.Color(background).enhance(1.12)
        background = ImageEnhance.Brightness(background).enhance(background_level)
        foreground = ImageOps.contain(
            _zoom_crop(image, zoom, centering), target_size,
            method=Image.Resampling.LANCZOS,
        )
        image = _paste_centered(background, foreground)
    elif fit_mode in {"solid_background", "mirrored_background"}:
        foreground = ImageOps.contain(
            _zoom_crop(image, zoom, centering), target_size,
            method=Image.Resampling.LANCZOS,
        )
        if fit_mode == "solid_background":
            background_color = _dominant_color(image)
            canvas = Image.new("RGB", target_size, background_color)
        else:
            canvas = _mirror_extend(foreground, target_size)
        canvas = ImageEnhance.Brightness(canvas).enhance(background_brightness)
        image = _paste_centered(canvas, foreground)
    else:
        image = _fit_cover(image, target_size, centering, zoom)
    return image


def _crop_centering(position: str) -> tuple[float, float]:
    """Translate the configured 3-by-3 crop anchor into Pillow centering."""
    return {
        "top_left": (0.0, 0.0),
        "top": (0.5, 0.0),
        "top_right": (1.0, 0.0),
        "left": (0.0, 0.5),
        "center": (0.5, 0.5),
        "right": (1.0, 0.5),
        "bottom_left": (0.0, 1.0),
        "bottom": (0.5, 1.0),
        "bottom_right": (1.0, 1.0),
    }.get(position, (0.5, 0.5))


def _fit_cover(
    image: Image.Image,
    target_size: tuple[int, int],
    centering: tuple[float, float],
    zoom: float,
) -> Image.Image:
    """Crop to fill the matrix while respecting zoom and the selected anchor."""
    source_width, source_height = image.size
    target_width, target_height = target_size
    target_ratio = target_width / target_height
    if source_width / source_height > target_ratio:
        crop_height = source_height / zoom
        crop_width = crop_height * target_ratio
    else:
        crop_width = source_width / zoom
        crop_height = crop_width / target_ratio
    left = (source_width - crop_width) * centering[0]
    top = (source_height - crop_height) * centering[1]
    cropped = image.crop((left, top, left + crop_width, top + crop_height))
    return cropped.resize(target_size, Image.Resampling.LANCZOS)


def _zoom_crop(
    image: Image.Image, zoom: float, centering: tuple[float, float]
) -> Image.Image:
    """Zoom into artwork without changing its aspect ratio."""
    if zoom <= 1:
        return image
    source_width, source_height = image.size
    crop_width, crop_height = source_width / zoom, source_height / zoom
    left = (source_width - crop_width) * centering[0]
    top = (source_height - crop_height) * centering[1]
    return image.crop((left, top, left + crop_width, top + crop_height)).resize(
        image.size, Image.Resampling.LANCZOS
    )


def _contain_on_background(
    foreground: Image.Image,
    target_size: tuple[int, int],
    background_color: tuple[int, int, int],
) -> Image.Image:
    """Center an entire cover on a solid background."""
    foreground = ImageOps.contain(foreground, target_size, method=Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", target_size, background_color)
    return _paste_centered(canvas, foreground)


def _paste_centered(background: Image.Image, foreground: Image.Image) -> Image.Image:
    """Center a fitted foreground image on its background canvas."""
    background.paste(
        foreground,
        (
            (background.width - foreground.width) // 2,
            (background.height - foreground.height) // 2,
        ),
    )
    return background


def _mirror_extend(foreground: Image.Image, target_size: tuple[int, int]) -> Image.Image:
    """Repeat reflected artwork edges into the matrix's otherwise-empty margins."""
    image = foreground
    if image.width < target_size[0]:
        image = _mirror_extend_axis(image, target_size[0], horizontal=True)
    if image.height < target_size[1]:
        image = _mirror_extend_axis(image, target_size[1], horizontal=False)
    return image.crop((0, 0, target_size[0], target_size[1]))


def _mirror_extend_axis(image: Image.Image, target_length: int, horizontal: bool) -> Image.Image:
    """Tile a fitted image across one axis, flipping every other tile."""
    source_length = image.width if horizontal else image.height
    before = (target_length - source_length) // 2
    after = target_length - source_length - before
    tiles_before = (before + source_length - 1) // source_length
    tiles_after = (after + source_length - 1) // source_length
    center_index = tiles_before
    tile_count = tiles_before + 1 + tiles_after
    canvas_size = (
        (tile_count * source_length, image.height)
        if horizontal else (image.width, tile_count * source_length)
    )
    canvas = Image.new("RGB", canvas_size)
    for index in range(tile_count):
        relative = index - center_index
        tile = image
        if abs(relative) % 2:
            tile = tile.transpose(
                Image.Transpose.FLIP_LEFT_RIGHT if horizontal
                else Image.Transpose.FLIP_TOP_BOTTOM
            )
        offset = (index * source_length, 0) if horizontal else (0, index * source_length)
        canvas.paste(tile, offset)
    origin = center_index * source_length - before
    if horizontal:
        return canvas.crop((origin, 0, origin + target_length, image.height))
    return canvas.crop((0, origin, image.width, origin + target_length))


def _dominant_color(image: Image.Image) -> tuple[int, int, int]:
    """Pick a stable cover-derived fill color for letterboxed artwork."""
    thumbnail = image.copy()
    thumbnail.thumbnail((48, 48), Image.Resampling.LANCZOS)
    quantized = thumbnail.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette() or []
    histogram = quantized.getcolors(maxcolors=256) or []
    if not histogram:
        return (0, 0, 0)
    palette_index = max(histogram, key=lambda item: item[0])[1]
    offset = palette_index * 3
    return tuple(int(palette[offset + channel]) for channel in range(3))


def extract_theme_palette(data: bytes, count: int = 8) -> list[tuple[int, int, int]]:
    """Extract visually useful colors, down-weighting near-black/near-white colors."""
    try:
        with Image.open(BytesIO(data)) as source:
            if source.width * source.height > MAX_SOURCE_IMAGE_PIXELS:
                raise ValueError("Artwork image dimensions exceed the pixel safety limit")
            source.seek(0)
            image = source.convert("RGB")
            image = _sample_palette_frames(source, image)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as err:
        raise ValueError("The media-player artwork URL did not return a safe, supported image") from err

    image.thumbnail((96, 96), Image.Resampling.LANCZOS)
    color_count = max(2, min(16, int(count)))
    quantized = image.quantize(colors=color_count, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette() or []
    histogram = quantized.getcolors(maxcolors=256) or []
    ranked: list[tuple[float, int, tuple[int, int, int]]] = []

    for pixel_count, palette_index in histogram:
        offset = palette_index * 3
        if offset + 2 >= len(palette):
            continue
        rgb = tuple(int(palette[offset + channel]) for channel in range(3))
        saturation = colorsys.rgb_to_hsv(*(channel / 255 for channel in rgb))[1]
        brightness = max(rgb)
        score = float(pixel_count) * (1.0 + 0.45 * saturation)
        if brightness < 28:
            score *= 0.18
        elif min(rgb) > 238 and saturation < 0.12:
            score *= 0.45
        ranked.append((score, pixel_count, rgb))

    ranked.sort(key=lambda item: item[0], reverse=True)
    result: list[tuple[int, int, int]] = []
    limit = max(1, min(16, int(count)))
    for _score, _pixels, rgb in ranked:
        if any(sum((a - b) ** 2 for a, b in zip(rgb, old)) < 30**2 for old in result):
            continue
        result.append(rgb)
        if len(result) >= limit:
            break
    if not result and ranked:
        result = [ranked[0][2]]
    return result


def _sample_palette_frames(source: Image.Image, first_image: Image.Image) -> Image.Image:
    """Use a few animation frames only when its first frame is nearly blank.

    Static and nonblank first-frame palettes retain their original path. This
    produces one stable palette for an animation, never per-frame light changes.
    Later frames are optional: a damaged frame must not discard a valid cover.
    """
    def thumbnail_on_black() -> Image.Image:
        if source.width * source.height > MAX_SOURCE_IMAGE_PIXELS:
            raise ValueError("Artwork image dimensions exceed the pixel safety limit")
        rgba = source.convert("RGBA")
        rgba.thumbnail((96, 96), Image.Resampling.LANCZOS)
        thumbnail = Image.new("RGB", rgba.size, (0, 0, 0))
        thumbnail.paste(rgba, mask=rgba.getchannel("A"))
        return thumbnail

    try:
        # Checking animation before compositing keeps static covers untouched,
        # including intentionally dark artwork and transparent PNGs.
        frame_count = int(getattr(source, "n_frames", 1))
        if frame_count <= 1:
            return first_image
        source.seek(0)
        first_thumbnail = thumbnail_on_black()
        pixels = list(first_thumbnail.getdata())
        if not pixels or sum(max(pixel) < 28 for pixel in pixels) < len(pixels) * 0.95:
            return first_image
    except (OSError, EOFError, ValueError, SyntaxError, IndexError, Image.DecompressionBombError):
        return first_image

    samples = [first_thumbnail]
    for index in dict.fromkeys((1, frame_count // 2, frame_count - 1)):
        try:
            source.seek(index)
            samples.append(thumbnail_on_black())
        except (OSError, EOFError, ValueError, SyntaxError, IndexError, Image.DecompressionBombError):
            continue
    if len(samples) == 1:
        return first_image

    # Equal-sized source frames receive equal area; the final quantizer still
    # works on at most 96 pixels per axis, as with a normal cover.
    width = max(sample.width for sample in samples)
    height = max(sample.height for sample in samples)
    montage = Image.new("RGB", (width * len(samples), height), (0, 0, 0))
    for index, sample in enumerate(samples):
        montage.paste(sample, (index * width, 0))
    montage.thumbnail((96, 96), Image.Resampling.LANCZOS)
    return montage



def _rgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """Convert sRGB to CIE Lab (D65) for perceptual palette comparisons."""
    channels = []
    for channel in rgb:
        value = max(0.0, min(255.0, float(channel))) / 255.0
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    x = (red * 0.4124564 + green * 0.3575761 + blue * 0.1804375) / 0.95047
    y = red * 0.2126729 + green * 0.7151522 + blue * 0.0721750
    z = (red * 0.0193339 + green * 0.1191920 + blue * 0.9503041) / 1.08883

    def pivot(value: float) -> float:
        return value ** (1 / 3) if value > 0.008856 else 7.787 * value + 16 / 116

    fx, fy, fz = pivot(x), pivot(y), pivot(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def order_palette_for_contrast(
    palette: list[tuple[int, int, int]],
) -> list[tuple[int, int, int]]:
    """Keep the dominant color first, then order accents by perceptual contrast.

    CIE Lab distance is used instead of raw RGB distance because it better
    approximates human perception. This only reorders colors found in the art;
    it never invents a complementary color that is absent from the cover.
    """
    colors = list(dict.fromkeys(tuple(int(v) for v in color) for color in palette))
    if len(colors) < 3:
        return colors

    lab = {color: _rgb_to_lab(color) for color in colors}
    selected = [colors.pop(0)]
    while colors:
        def distance_to_selected(color: tuple[int, int, int]) -> float:
            candidate = lab[color]
            return min(
                sum((candidate[i] - lab[chosen][i]) ** 2 for i in range(3)) ** 0.5
                for chosen in selected
            )

        next_color = max(colors, key=distance_to_selected)
        selected.append(next_color)
        colors.remove(next_color)
    return selected


def order_palette_for_vibrance(
    palette: list[tuple[int, int, int]],
) -> list[tuple[int, int, int]]:
    """Keep the dominant color first, then rank cover colors by vividness."""
    colors = list(dict.fromkeys(tuple(int(v) for v in color) for color in palette))
    if len(colors) < 3:
        return colors
    dominant, accents = colors[0], colors[1:]

    def vividness(rgb: tuple[int, int, int]) -> float:
        hue, saturation, value = colorsys.rgb_to_hsv(*(channel / 255 for channel in rgb))
        del hue
        return saturation * (0.35 + 0.65 * value)

    return [dominant, *sorted(accents, key=vividness, reverse=True)]


def _hsv_to_rgb_tuple(hue: float, saturation: float, value: float) -> tuple[int, int, int]:
    """Convert normalized HSV components into a clamped integer RGB tuple."""
    red, green, blue = colorsys.hsv_to_rgb(
        hue % 1.0,
        max(0.0, min(1.0, saturation)),
        max(0.0, min(1.0, value)),
    )
    return tuple(max(0, min(255, int(round(channel * 255)))) for channel in (red, green, blue))


def build_theme_colors(
    palette: list[tuple[int, int, int]], mode: str, count: int,
) -> list[tuple[int, int, int]]:
    """Create an intentional music-reactive color assignment for ordered lights.

    The three original styles (artwork palette, dominant + contrast, dominant
    color) retain their original behavior. Additional styles derive a coherent
    treatment from the dominant cover color and, where appropriate, accent
    colors actually extracted from the artwork.
    """
    count = max(0, int(count))
    colors = list(dict.fromkeys(tuple(max(0, min(255, int(v))) for v in color) for color in palette))
    if not colors or count == 0:
        return []

    dominant = colors[0]
    if mode == "shared":
        return [dominant] * count
    if mode == "contrast":
        ordered = order_palette_for_contrast(colors)
        return [ordered[index % len(ordered)] for index in range(count)]
    if mode == "palette":
        return [colors[index % len(colors)] for index in range(count)]
    if mode == "vibrant":
        ordered = order_palette_for_vibrance(colors)
        return [ordered[index % len(ordered)] for index in range(count)]

    hue, saturation, value = colorsys.rgb_to_hsv(*(channel / 255 for channel in dominant))
    if mode == "complementary":
        complement = _hsv_to_rgb_tuple((hue + 0.5) % 1.0, max(0.55, saturation), max(0.72, value))
        return [dominant] + [complement] * (count - 1)

    if mode == "analogous":
        # Keep the first light faithful to the cover and fan out neighboring hues
        # around that color for a coordinated, music-poster-like wash.
        offsets = (0.0, -0.075, 0.075, -0.15, 0.15, -0.22, 0.22)
        results = [dominant]
        for index in range(1, count):
            results.append(_hsv_to_rgb_tuple(
                hue + offsets[index % len(offsets)], max(0.42, saturation), value
            ))
        return results

    if mode == "cinematic":
        base_color = _hsv_to_rgb_tuple(hue, saturation * 0.72, value * 0.66)
        accents = order_palette_for_vibrance(colors[1:])
        if accents:
            lab_dominant = _rgb_to_lab(dominant)

            def accent_score(rgb: tuple[int, int, int]) -> float:
                _, sat, val = colorsys.rgb_to_hsv(*(channel / 255 for channel in rgb))
                lab_color = _rgb_to_lab(rgb)
                distance = sum((lab_color[i] - lab_dominant[i]) ** 2 for i in range(3)) ** 0.5
                return sat * 0.7 + min(1.0, distance / 100.0) * 0.3 + val * 0.1

            accent = max(accents, key=accent_score)
        else:
            # Very limited/monochrome covers still get a subtle derived accent.
            accent = _hsv_to_rgb_tuple(hue + 0.5, max(0.5, saturation), max(0.7, value))
        return [base_color] + [accent] * (count - 1)

    if mode == "monochrome":
        # Keep the artwork's main hue while creating a deliberate intensity ramp.
        tonal_saturation = max(0.42, min(0.9, saturation))
        levels = (0.48, 0.62, 0.76, 0.9)
        return [
            _hsv_to_rgb_tuple(hue, tonal_saturation, levels[index % len(levels)])
            for index in range(count)
        ]

    # Unknown/legacy values fall back to the default artwork-derived palette.
    return [colors[index % len(colors)] for index in range(count)]



def balance_color_spectrum(
    rgb: tuple[int, int, int], enabled: bool = False
) -> tuple[int, int, int]:
    """Compress extreme palette brightness while preserving hue and saturation.

    When enabled, HSV value is mapped into a moderate 64..210 range. This gently
    lifts dark cover colors and softens white/high-intensity picks without making
    every light the same brightness. The opt-in default preserves legacy behavior.
    """
    channels = tuple(max(0, min(255, int(channel))) for channel in rgb)
    if not enabled:
        return channels
    hue, saturation, value = colorsys.rgb_to_hsv(*(channel / 255.0 for channel in channels))
    balanced_value = (64.0 + value * (210.0 - 64.0)) / 255.0
    red, green, blue = colorsys.hsv_to_rgb(hue, saturation, balanced_value)
    return (
        int(round(red * 255)),
        int(round(green * 255)),
        int(round(blue * 255)),
    )

def ensure_visible_color(
    rgb: tuple[int, int, int], prevent_dark: bool = True
) -> tuple[int, int, int]:
    """Lift near-black colors to a subtle visible accent without turning lights off."""
    channels = [max(0, min(255, int(channel))) for channel in rgb]
    if not prevent_dark:
        return tuple(channels)
    peak = max(channels)
    minimum_peak = 64
    if peak < minimum_peak:
        if peak == 0:
            return (minimum_peak, 38, 12)
        scale = minimum_peak / peak
        channels = [min(255, int(round(channel * scale))) for channel in channels]
    return tuple(channels)
