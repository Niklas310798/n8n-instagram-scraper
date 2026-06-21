"""On-screen text extraction with RapidOCR (ONNX, no torch).

Runs OCR over a list of images (video frames and/or carousel images) and
returns distinct text blocks, deduplicating near-identical frames.
"""
from typing import List

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def ocr_image(path: str) -> str:
    engine = _get_engine()
    result, _ = engine(path)
    if not result:
        return ""
    # result rows look like [box, text, score]
    return "\n".join(row[1] for row in result if row[1]).strip()


def ocr_images(paths: List[str]) -> List[str]:
    """Return distinct on-screen text blocks across all images."""
    blocks, seen = [], set()
    for p in paths:
        text = ocr_image(p)
        if not text:
            continue
        norm = " ".join(text.split()).lower()
        if norm in seen:
            continue
        seen.add(norm)
        blocks.append(text)
    return blocks
