"""
digidice_image.py — resize token art to the DigiDice's fixed card size.
"""

from __future__ import annotations

from PIL import Image

TOKEN_W = 488
TOKEN_H = 681


def resize_token(img: Image.Image, size=(TOKEN_W, TOKEN_H)) -> Image.Image:
    """Scale to *cover* the target size (preserving aspect ratio, no
    distortion) and center-crop to exactly `size`. This matches how card-art
    thumbnails are typically prepared — fills the frame completely rather
    than letterboxing.
    """
    img = img.convert("RGB")
    target_w, target_h = size
    src_w, src_h = img.size

    scale = max(target_w / src_w, target_h / src_h)
    new_w, new_h = round(src_w * scale), round(src_h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)

    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def resize_token_file(src_path: str, dst_path: str, size=(TOKEN_W, TOKEN_H)) -> None:
    with Image.open(src_path) as img:
        out = resize_token(img, size)
        out.save(dst_path, quality=92)
