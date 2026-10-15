"""Private, bounded image intake for photographed Canadian mortgage documents.

No ML weights or samples are sent to remote services. Image decoding is performed
only after signature, length, and pixel-budget checks. OCR must be enabled explicitly.
The image-processing stages are modular so optional Surya or Docling adapters can
be deployed behind the same evidence contract without copying third-party code.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from math import floor
from typing import Literal
import statistics

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

MAX_BYTES = 14 * 1024 * 1024
MAX_PIXELS = 25_000_000
MIN_EDGE = 500
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "TIFF"}


class CameraError(ValueError):
    """An image failed mandatory security or readability checks."""


@dataclass(frozen=True)
class CameraSettings:
    max_bytes: int = MAX_BYTES
    max_pixels: int = MAX_PIXELS
    min_edge: int = MIN_EDGE
    output_width: int = 2000
    output_format: Literal['PNG', 'JPEG'] = 'PNG'
    contrast: float = 1.25
    sharpness: float = 1.15
    denoise: bool = True
    autocontrast: bool = True
    deskew: bool = False
    min_acceptable_quality: float = 0.35

    def __post_init__(self):
        if self.max_bytes <= 0 or self.max_pixels <= 0:
            raise CameraError('Upload and pixel limits must be positive.')
        if not 128 <= self.output_width <= 8000:
            raise CameraError('Output width is outside the accepted range.')
        if not 0.0 <= self.min_acceptable_quality <= 1.0:
            raise CameraError('Quality threshold must be between zero and one.')
        if not 0.5 <= self.contrast <= 4:
            raise CameraError('Contrast setting is unsupported.')


@dataclass(frozen=True)
class ImageQuality:
    brightness: float
    contrast: float
    sharpness: float
    resolution: float
    clipped_dark: float
    clipped_light: float
    overall: float
    flags: tuple[str, ...]
    advice: tuple[str, ...]

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class PreparedScan:
    normalized_image: bytes = field(repr=False)
    source_sha256: str = ''
    normalized_sha256: str = ''
    original_format: str = ''
    original_size: tuple[int, int] = (0, 0)
    normalized_size: tuple[int, int] = (0, 0)
    original_orientation: int | None = None
    quality: ImageQuality | None = None
    transformations: tuple[str, ...] = ()

    def metadata(self):
        return {
            'source_sha256': self.source_sha256,
            'normalized_sha256': self.normalized_sha256,
            'original_format': self.original_format,
            'original_size': self.original_size,
            'normalized_size': self.normalized_size,
            'original_orientation': self.original_orientation,
            'quality': self.quality.to_dict() if self.quality else None,
            'transformations': self.transformations,
        }


def sniff_image(data: bytes) -> str:
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'PNG'
    if data.startswith(b'\xff\xd8\xff'):
        return 'JPEG'
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'WEBP'
    if data.startswith((b'II*\x00', b'MM\x00*')):
        return 'TIFF'
    raise CameraError('Unsupported image signature; use JPG, PNG, WebP or TIFF.')


def _clamp(number: float, lower=0.0, upper=1.0) -> float:
    return max(lower, min(upper, number))


def _gray_sample(image: Image.Image, max_edge=500) -> Image.Image:
    img = ImageOps.grayscale(image)
    img.thumbnail((max_edge, max_edge), Image.Resampling.BILINEAR)
    return img


def _edge_energy(image: Image.Image) -> float:
    gray = _gray_sample(image)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    values = list(edges.get_flattened_data() if hasattr(edges, "get_flattened_data") else edges.getdata())
    return statistics.mean(values) if values else 0.0


def _percentile(histogram: list[int], fraction: float) -> int:
    target = sum(histogram) * fraction
    running = 0
    for index, frequency in enumerate(histogram):
        running += frequency
        if running >= target:
            return index
    return 255


def assess_quality(image: Image.Image) -> ImageQuality:
    """Heuristic diagnostics, *not* a probability of accurate OCR.

    Contrast/brightness/sharpness estimates are stable and inexpensive. Source
    OCR confidence must be separately reported by the OCR backend. A clean-looking
    scan may still contain a wrong decimal point or interest rate.
    """
    gray = _gray_sample(image)
    histogram = gray.histogram()
    pixels = max(1, gray.width * gray.height)
    average = ImageStat.Stat(gray).mean[0] / 255
    p10 = _percentile(histogram, .10)
    p90 = _percentile(histogram, .90)
    spread = (p90 - p10) / 255
    edge = _edge_energy(gray) / 255
    min_side = min(image.size)
    resolution = _clamp(min_side / 1400)
    dark = sum(histogram[:12]) / pixels
    light = sum(histogram[244:]) / pixels
    brightness_score = _clamp(1.0 - abs(average - .65) * 1.65)
    contrast_score = _clamp(spread / .55)
    sharpness_score = _clamp(edge / .16)
    score = _clamp(.20 * brightness_score + .26 * contrast_score +
                   .32 * sharpness_score + .22 * resolution)
    flags: list[str] = []
    advice: list[str] = []
    if min_side < MIN_EDGE:
        flags.append('low_resolution')
        advice.append('Photograph the document closer, with its edges visible.')
    if average < .25:
        flags.append('underexposed')
        advice.append('Move to even lighting without glare or flash reflections.')
    if average > .9 or light > .72:
        flags.append('overexposed')
        advice.append('Reduce glare and keep the page away from direct light.')
    if spread < .22:
        flags.append('low_contrast')
        advice.append('Place the document on a contrasting flat surface.')
    if sharpness_score < .20:
        flags.append('possible_blur')
        advice.append('Hold the camera steady and tap to focus on the printed text.')
    if dark > .65:
        flags.append('dark_clipping')
    return ImageQuality(
        brightness=round(average, 4),
        contrast=round(spread, 4),
        sharpness=round(edge, 4),
        resolution=round(resolution, 4),
        clipped_dark=round(dark, 4),
        clipped_light=round(light, 4),
        overall=round(score, 4),
        flags=tuple(flags),
        advice=tuple(advice),
    )


def prepare_scan(data: bytes, settings: CameraSettings | None = None) -> PreparedScan:
    settings = settings or CameraSettings()
    if not isinstance(data, bytes) or not data:
        raise CameraError('Image upload is empty.')
    if len(data) > settings.max_bytes:
        raise CameraError('Image exceeds upload size limit.')
    detected = sniff_image(data)
    try:
        with Image.open(BytesIO(data)) as opened:
            if opened.format != detected or opened.format not in ALLOWED_FORMATS:
                raise CameraError('Image payload does not match its file signature.')
            original_size = opened.size
            if original_size[0] * original_size[1] > settings.max_pixels:
                raise CameraError('Image exceeds the allowed pixel budget.')
            if getattr(opened, "n_frames", 1) > 1:
                raise CameraError('Multi-frame images must be uploaded as separate pages.')
            orientation = opened.getexif().get(274)
            image = ImageOps.exif_transpose(opened)
            image.load()
            image = image.convert('RGB')
    except (UnidentifiedImageError, OSError, ValueError, OverflowError) as exc:
        if isinstance(exc, CameraError):
            raise
        raise CameraError('The image is invalid or could not be decoded.') from exc
    steps: list[str] = []
    if orientation not in (None, 1):
        steps.append('exif_orientation')
    if image.width > settings.output_width:
        ratio = settings.output_width / image.width
        height = max(1, round(image.height * ratio))
        image = image.resize((settings.output_width, height), Image.Resampling.LANCZOS)
        steps.append('downscale_lanczos')
    quality = assess_quality(image)
    if settings.autocontrast:
        image = ImageOps.autocontrast(image, cutoff=.5, preserve_tone=True)
        steps.append('autocontrast')
    if settings.denoise:
        image = image.filter(ImageFilter.MedianFilter(3))
        steps.append('median_denoise')
    if settings.contrast != 1:
        image = ImageEnhance.Contrast(image).enhance(settings.contrast)
        steps.append('contrast')
    if settings.sharpness != 1:
        image = ImageEnhance.Sharpness(image).enhance(settings.sharpness)
        steps.append('sharpness')
    output = BytesIO()
    if settings.output_format == 'JPEG':
        image.save(output, format='JPEG', quality=92, optimize=True)
    else:
        image.save(output, format='PNG', optimize=True)
    normalized = output.getvalue()
    return PreparedScan(
        normalized_image=normalized,
        source_sha256=sha256(data).hexdigest(),
        normalized_sha256=sha256(normalized).hexdigest(),
        original_format=detected,
        original_size=original_size,
        normalized_size=image.size,
        original_orientation=orientation,
        quality=quality,
        transformations=tuple(steps),
    )


def scans_to_pdf(scans: list[PreparedScan], max_pages=12) -> bytes:
    if not scans or len(scans) > max_pages:
        raise CameraError('Select between 1 and 12 document photographs.')
    images = []
    for scan in scans:
        if not scan.normalized_image:
            raise CameraError('A prepared image is missing.')
        images.append(Image.open(BytesIO(scan.normalized_image)).convert('RGB'))
    output = BytesIO()
    first, *rest = images
    first.save(output, format='PDF', save_all=True, append_images=rest, resolution=150)
    for image in images:
        image.close()
    return output.getvalue()


def decide_recapture(quality: ImageQuality, threshold: float = .35) -> dict:
    if not 0 <= threshold <= 1:
        raise CameraError('Invalid threshold.')
    blocking = quality.overall < threshold or 'low_resolution' in quality.flags
    return {
        'needs_recapture': blocking,
        'score': quality.overall,
        'diagnostic_only': True,
        'reasons': list(quality.flags),
        'recommendations': list(quality.advice),
        'notice': 'Visual image quality does not establish OCR or financial-field accuracy.',
    }
