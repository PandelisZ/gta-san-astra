"""Prepare compact model inputs while preserving raw screenshot evidence."""
from pathlib import Path
import time
from PIL import Image, ImageOps


def prepare_frame(source: Path, directory: Path, *, max_edge: int = 640,
                  quality: int = 65, colormode: str = "rgb") -> dict:
    if not 64 <= max_edge <= 4096 or not 1 <= quality <= 95:
        raise ValueError("vision max edge must be 64..4096; JPEG quality must be 1..95")
    if colormode not in ("rgb", "gray", "contrast"):
        raise ValueError("vision color mode must be rgb, gray, or contrast")
    source, directory = Path(source).resolve(), Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    output = directory / f"{source.stem}-{source.stat().st_mtime_ns}-{max_edge}-{quality}-{colormode}.jpg"
    with Image.open(source) as original:
        original_dimensions = list(original.size)
        frame = original.convert("RGB")
        frame.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        if colormode == "gray":
            frame = ImageOps.grayscale(frame)
        elif colormode == "contrast":
            frame = ImageOps.autocontrast(frame, cutoff=1)
        frame.save(output, "JPEG", quality=quality, optimize=True)
        dimensions = list(frame.size)
    return {"source_image_path": str(source), "image_path": str(output),
            "source_dimensions": original_dimensions, "dimensions": dimensions,
            "source_bytes": source.stat().st_size, "bytes": output.stat().st_size,
            "format": "jpeg", "quality": quality, "colormode": colormode,
            "processing_ms": round((time.monotonic() - started) * 1000, 2)}
