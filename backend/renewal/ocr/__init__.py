"""Camera normalization and pluggable local OCR for borrower documents."""
from .camera import CameraSettings, CameraError, prepare_scan, assess_quality, scans_to_pdf
from .engines import TesseractEngine, DoclingEngine, OCREngineError
