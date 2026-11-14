from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from wled_album_art_under_test.image_processing import (
    ensure_visible_color,
    extract_theme_palette,
    order_palette_for_contrast,
    prepare_image,
)


def make_test_art(size: tuple[int, int] = (180, 120)) -> bytes:
    image = Image.new("RGB", size, (0, 0, 0))
    pixels = image.load()
    for y in range(size[1]):
        for x in range(size[0]):
            if x < size[0] // 3:
                pixels[x, y] = (220, 30, 40)
            elif x < size[0] * 2 // 3:
                pixels[x, y] = (20, 90, 220)
            else:
                pixels[x, y] = (8, 8, 8)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("fit_mode", ["crop", "contain", "blurred_background"])
def test_prepare_image_returns_matrix_sized_png_and_single_frame_gif(fit_mode: str) -> None:
    png, gif = prepare_image(make_test_art(), 32, 32, fit_mode)

    with Image.open(BytesIO(png)) as image:
        assert image.format == "PNG"
        assert image.size == (32, 32)

    with Image.open(BytesIO(gif)) as image:
        assert image.format == "GIF"
        assert image.size == (32, 32)
        assert image.n_frames == 1


@pytest.mark.parametrize(
    "source_durations",
    [
        pytest.param([100] * 120, id="uniform-delays"),
        pytest.param([20 + (index % 7) * 30 for index in range(120)], id="variable-delays"),
    ],
)
def test_sampled_animation_preserves_actual_source_timing(source_durations: list[int]) -> None:
    """Reducing a long animation must preserve its total duration and end hold."""
    frames = [Image.new("RGB", (8, 8), (index + 1, 80, 200)) for index in range(120)]
    source = BytesIO()
    frames[0].save(
        source, format="GIF", save_all=True, append_images=frames[1:],
        duration=source_durations, loop=0, disposal=2,
    )

    _preview, gif = prepare_image(source.getvalue(), 8, 8, "crop")

    with Image.open(BytesIO(gif)) as image:
        assert image.n_frames == 60
        assert image.info["loop"] == 0
        output_durations = []
        source_indices = []
        for frame_index in range(image.n_frames):
            image.seek(frame_index)
            output_durations.append(image.info["duration"])
            source_indices.append(image.convert("RGB").getpixel((0, 0))[0] - 1)

    assert source_indices[0] == 0
    assert source_indices[-1] == 119
    assert sum(output_durations) == sum(source_durations)
    assert output_durations[-1] == source_durations[-1]
    # Each retained image represents the time until the next retained image.
    for position, source_index in enumerate(source_indices[:-1]):
        assert output_durations[position] == sum(
            source_durations[source_index:source_indices[position + 1]]
        )


def test_blurred_background_fills_letterbox_regions_instead_of_black_bars() -> None:
    """The visible output is the WLED GIF, not just the intermediate PNG."""
    source = Image.new("RGB", (160, 80), (220, 20, 30))
    pixels = source.load()
    for y in range(40, 80):
        for x in range(160):
            pixels[x, y] = (20, 90, 220)
    buffer = BytesIO()
    source.save(buffer, format="PNG")
    art = buffer.getvalue()

    _contain_png, contain_gif = prepare_image(art, 32, 32, "contain")
    _blurred_png, blurred_gif = prepare_image(art, 32, 32, "blurred_background")

    with Image.open(BytesIO(contain_gif)) as image:
        contain_top = image.convert("RGB").getpixel((16, 1))
    with Image.open(BytesIO(blurred_gif)) as image:
        blurred_top = image.convert("RGB").getpixel((16, 1))

    assert contain_top == (0, 0, 0)
    assert max(blurred_top) > 50
    assert blurred_top != contain_top


def test_prepare_image_rejects_non_positive_dimensions() -> None:
    with pytest.raises(ValueError, match="positive"):
        prepare_image(make_test_art(), 0, 32, "crop")


def test_palette_is_non_empty_and_has_valid_rgb_channels() -> None:
    palette = extract_theme_palette(make_test_art(), 4)

    assert palette
    assert len(palette) <= 4
    for color in palette:
        assert len(color) == 3
        assert all(0 <= channel <= 255 for channel in color)


def test_dark_color_protection_keeps_near_black_colors_visible() -> None:
    assert max(ensure_visible_color((0, 0, 0))) >= 64
    assert ensure_visible_color((0, 0, 0), prevent_dark=False) == (0, 0, 0)
    assert max(ensure_visible_color((5, 7, 10))) >= 64


def test_contrast_palette_keeps_dominant_first_then_selects_distinct_accents() -> None:
    dominant = (220, 30, 40)
    nearby = (210, 45, 48)
    contrasting = (20, 200, 210)

    ordered = order_palette_for_contrast([dominant, nearby, contrasting])

    assert ordered[0] == dominant
    assert ordered[1] == contrasting
    assert ordered[2] == nearby


def test_contrast_palette_handles_empty_short_and_duplicate_palettes() -> None:
    assert order_palette_for_contrast([]) == []
    assert order_palette_for_contrast([(1, 2, 3)]) == [(1, 2, 3)]
    assert order_palette_for_contrast([(1, 2, 3), (1, 2, 3)]) == [(1, 2, 3)]


def test_original_theme_color_modes_are_preserved() -> None:
    from wled_album_art_under_test.image_processing import build_theme_colors

    palette = [(220, 30, 40), (20, 90, 220), (30, 190, 90)]
    assert build_theme_colors(palette, "palette", 3) == palette
    assert build_theme_colors(palette, "shared", 3) == [palette[0]] * 3

    contrast = build_theme_colors(palette, "contrast", 3)
    assert contrast[0] == palette[0]
    assert sorted(contrast) == sorted(palette)


def test_complementary_style_keeps_cover_color_then_adds_opposite_hue() -> None:
    from wled_album_art_under_test.image_processing import build_theme_colors

    dominant = (220, 30, 40)
    colors = build_theme_colors([dominant, (210, 40, 48)], "complementary", 3)
    assert colors[0] == dominant
    assert colors[1] == colors[2]
    # Complement to a red cover color should be in the cyan/green-blue family.
    assert colors[1][1] > colors[1][0]
    assert colors[1][2] > colors[1][0]


def test_analogous_style_creates_distinct_neighboring_cover_derived_hues() -> None:
    from wled_album_art_under_test.image_processing import build_theme_colors

    colors = build_theme_colors([(220, 30, 40), (20, 90, 220)], "analogous", 4)
    assert colors[0] == (220, 30, 40)
    assert len(set(colors)) == 4


def test_cinematic_style_uses_subdued_base_and_artwork_accent() -> None:
    from wled_album_art_under_test.image_processing import build_theme_colors

    palette = [(220, 30, 40), (20, 90, 220), (30, 190, 90)]
    colors = build_theme_colors(palette, "cinematic", 3)
    assert len(colors) == 3
    assert max(colors[0]) < max(palette[0])
    assert colors[1] in palette[1:]
    assert colors[1] == colors[2]


def test_monochrome_style_keeps_hue_and_varies_tone() -> None:
    import colorsys

    from wled_album_art_under_test.image_processing import build_theme_colors

    colors = build_theme_colors([(220, 30, 40), (20, 90, 220)], "monochrome", 4)
    assert len(colors) == 4
    hues = [colorsys.rgb_to_hsv(*(channel / 255 for channel in color))[0] for color in colors]
    assert max(hues) - min(hues) < 0.005  # RGB quantization slightly shifts computed hue
    values = [colorsys.rgb_to_hsv(*(channel / 255 for channel in color))[2] for color in colors]
    assert values == sorted(values)


def test_vibrant_style_keeps_dominant_first_and_ranks_saturated_accents() -> None:
    from wled_album_art_under_test.image_processing import build_theme_colors

    dominant = (180, 120, 120)
    muted = (150, 130, 130)
    vivid = (10, 230, 230)
    colors = build_theme_colors([dominant, muted, vivid], "vibrant", 3)
    assert colors[0] == dominant
    assert colors[1] == vivid


def test_color_spectrum_balancing_is_opt_in_to_preserve_original_palette_feel() -> None:
    from wled_album_art_under_test.const import DEFAULT_BALANCE_THEME_SPECTRUM
    from wled_album_art_under_test.image_processing import balance_color_spectrum

    sample = (32, 92, 174)
    assert DEFAULT_BALANCE_THEME_SPECTRUM is False
    assert balance_color_spectrum(sample) == sample
    assert balance_color_spectrum(sample, enabled=True) != sample
