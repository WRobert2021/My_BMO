"""Raspberry Pi camera capture and image rotation."""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image


CAPTURE_TIMEOUT_SECONDS = 15


def capture_image(
    output_path: str | Path,
    *,
    rotation: int = 0,
) -> str:
    """Capture one still image, rotate it if configured, and return its path."""
    image_path = Path(output_path)
    subprocess.run(
        [
            "rpicam-still",
            "-t",
            "500",
            "-n",
            "--width",
            "4608",
            "--height",
            "2592",
            "-o",
            str(image_path),
        ],
        check=True,
        timeout=CAPTURE_TIMEOUT_SECONDS,
    )
    if rotation:
        with Image.open(image_path) as image:
            image.rotate(rotation, expand=True).save(image_path)
    return str(image_path)
