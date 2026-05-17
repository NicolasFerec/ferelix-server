"""Profile image storage helpers."""

import uuid
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_PROFILE_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_PROFILE_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PROFILE_IMAGE_PIXELS = 20_000_000
PROFILE_IMAGE_SIZE = 512
DEFAULT_PROFILE_IMAGE_DIR = "/config/images/profile"

Image.MAX_IMAGE_PIXELS = MAX_PROFILE_IMAGE_PIXELS


def profile_image_dir() -> Path:
    """Return the directory used for uploaded user profile images."""
    directory = Path(DEFAULT_PROFILE_IMAGE_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


async def save_profile_image(user_id: int, image: UploadFile) -> str:
    """Validate, normalize, and persist an uploaded profile image."""
    contents = await image.read()
    if not contents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid profile image",
        )
    if len(contents) > MAX_PROFILE_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Profile image is too large",
        )

    output_image = normalize_profile_image(contents)
    output_path = profile_image_dir() / f"user-{user_id}-{uuid.uuid4().hex}.jpg"
    output_image.save(output_path, format="JPEG", quality=90, optimize=True, progressive=True)

    return str(output_path)


def normalize_profile_image(contents: bytes) -> Image.Image:
    """Decode, crop, resize, and re-encode-safe an uploaded image."""
    try:
        with Image.open(BytesIO(contents)) as source:
            if source.format not in ALLOWED_PROFILE_IMAGE_FORMATS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Unsupported profile image type",
                )
            if source.width * source.height > MAX_PROFILE_IMAGE_PIXELS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Profile image is too large",
                )

            source.load()
            image = ImageOps.exif_transpose(source)
            image = crop_center_square(image)
            image = image.resize((PROFILE_IMAGE_SIZE, PROFILE_IMAGE_SIZE), Image.Resampling.LANCZOS)

            if image.mode in {"RGBA", "LA"}:
                background = Image.new("RGB", image.size, (255, 255, 255))
                alpha = image.getchannel("A")
                background.paste(image.convert("RGB"), mask=alpha)
                return background

            return image.convert("RGB")
    except Image.DecompressionBombError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Profile image is too large",
        ) from exc
    except UnidentifiedImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid profile image",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid profile image",
        ) from exc


def crop_center_square(image: Image.Image) -> Image.Image:
    """Crop an image to a centered square."""
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


def delete_profile_image(path: str | None) -> None:
    """Delete a stored profile image if it still exists."""
    if not path:
        return

    try:
        image_path = Path(path)
        if image_path.exists():
            image_path.unlink()
    except OSError:
        pass
