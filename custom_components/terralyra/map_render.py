"""Bounded annotations for the static FRMv3 map image."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from io import BytesIO
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from .geocoding import MapPlace
from .products.fire_risk import FireRiskError

MAX_IMAGE_DIMENSION = 1024
RISK_COLORS = (
    ("low", "#10cfe0"),
    ("moderate", "#00e83f"),
    ("high", "#fff000"),
    ("very_high", "#ff7f00"),
    ("extreme", "#ff0000"),
)
LABELS = {
    "en": {
        "home": "Home",
        "valid": "Valid",
        "low": "Low",
        "moderate": "Moderate",
        "high": "High",
        "very_high": "Very high",
        "extreme": "Extreme",
    },
    "hu": {
        "home": "Otthon",
        "valid": "Érvényes",
        "low": "Alacsony",
        "moderate": "Mérsékelt",
        "high": "Magas",
        "very_high": "Nagyon magas",
        "extreme": "Szélsőséges",
    },
}


def _load_country_borders() -> tuple[tuple[tuple[float, float], ...], ...]:
    """Load the small bundled Natural Earth Europe extract."""
    path = Path(__file__).parent / "data" / "country_borders.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        lines = payload["lines"]
        if not isinstance(lines, list) or len(lines) > 500:
            raise ValueError("unexpected boundary count")
        result = []
        for line in lines:
            if not isinstance(line, list) or not 2 <= len(line) <= 500:
                raise ValueError("unexpected boundary shape")
            points = tuple((float(point[0]), float(point[1])) for point in line)
            if any(not (-180 <= lon <= 180 and -90 <= lat <= 90) for lon, lat in points):
                raise ValueError("invalid boundary coordinate")
            result.append(points)
        return tuple(result)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as err:
        raise FireRiskError("Bundled country boundaries could not be loaded") from err


COUNTRY_BORDERS = _load_country_borders()


def annotate_fire_risk_map(
    image_bytes: bytes,
    bbox: tuple[float, float, float, float],
    home_latitude: float,
    home_longitude: float,
    valid_date: date,
    places: Iterable[MapPlace],
    language: str,
) -> bytes:
    """Add context without changing or interpreting the source risk pixels."""
    west, south, east, north = bbox
    if not (west < east and south < north):
        raise FireRiskError("FRMv3 map annotation bounds are invalid")
    try:
        with Image.open(BytesIO(image_bytes)) as source:
            if (
                source.format != "PNG"
                or source.width > MAX_IMAGE_DIMENSION
                or source.height > MAX_IMAGE_DIMENSION
            ):
                raise FireRiskError("FRMv3 map image has unexpected dimensions")
            source.load()
            image = source.convert("RGBA")
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as err:
        raise FireRiskError("FRMv3 map image could not be decoded") from err

    labels = LABELS.get(language, LABELS["en"])
    draw = ImageDraw.Draw(image, "RGBA")
    font = ImageFont.load_default(size=15)
    small_font = ImageFont.load_default(size=13)
    width, height = image.size

    _draw_country_borders(draw, bbox, width, height)

    title = f"FRMv3 · {labels['valid']}: {valid_date.isoformat()}"
    draw.rounded_rectangle((10, 10, 266, 42), radius=8, fill=(0, 0, 0, 185))
    draw.text((20, 18), title, font=font, fill="white")

    for place in places:
        x, y = _map_pixel(place.latitude, place.longitude, bbox, width, height)
        if 18 < x < width - 80 and 48 < y < height - 50:
            draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(0, 0, 0, 220))
            draw.text(
                (x + 5, y - 8),
                place.name[:32],
                font=small_font,
                fill="black",
                stroke_width=2,
                stroke_fill="white",
            )

    home_x, home_y = _map_pixel(
        home_latitude, home_longitude, bbox, width, height
    )
    draw.ellipse(
        (home_x - 10, home_y - 10, home_x + 10, home_y + 10),
        fill=(255, 255, 255, 235),
        outline=(20, 20, 20, 255),
        width=3,
    )
    draw.line((home_x - 6, home_y, home_x + 6, home_y), fill="black", width=2)
    draw.line((home_x, home_y - 6, home_x, home_y + 6), fill="black", width=2)
    draw.text(
        (home_x + 14, home_y - 9),
        labels["home"],
        font=font,
        fill="black",
        stroke_width=2,
        stroke_fill="white",
    )

    legend_width = 142
    row_height = 22
    legend_height = 12 + len(RISK_COLORS) * row_height
    left = width - legend_width - 10
    top = height - legend_height - 10
    draw.rounded_rectangle(
        (left, top, width - 10, height - 10), radius=8, fill=(255, 255, 255, 220)
    )
    for index, (key, color) in enumerate(RISK_COLORS):
        row_top = top + 8 + index * row_height
        draw.rectangle((left + 10, row_top, left + 28, row_top + 14), fill=color)
        draw.text((left + 35, row_top - 1), labels[key], font=small_font, fill="black")

    output = BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()


def _draw_country_borders(
    draw: ImageDraw.ImageDraw,
    bbox: tuple[float, float, float, float],
    width: int,
    height: int,
) -> None:
    """Draw clipped country boundaries with a contrasting halo."""
    west, south, east, north = bbox
    for line in COUNTRY_BORDERS:
        if not any(west <= lon <= east and south <= lat <= north for lon, lat in line):
            continue
        pixels = [_map_pixel(lat, lon, bbox, width, height) for lon, lat in line]
        draw.line(pixels, fill=(255, 255, 255, 210), width=3, joint="curve")
        draw.line(pixels, fill=(35, 35, 35, 210), width=1, joint="curve")


def _map_pixel(
    latitude: float,
    longitude: float,
    bbox: tuple[float, float, float, float],
    width: int,
    height: int,
) -> tuple[int, int]:
    west, south, east, north = bbox
    x = round((longitude - west) / (east - west) * (width - 1))
    y = round((north - latitude) / (north - south) * (height - 1))
    return max(0, min(width - 1, x)), max(0, min(height - 1, y))
