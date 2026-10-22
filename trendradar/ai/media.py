"""In-memory image input shared by Assistant and Gemini, without transport types."""

from dataclasses import dataclass, field

MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 4


def image_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("unsupported image format")


@dataclass(frozen=True, slots=True)
class ImagePart:
    data: bytes = field(repr=False)
    mime_type: str

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or not 0 < len(self.data) <= MAX_IMAGE_BYTES:
            raise ValueError("invalid image size")
        if image_mime(self.data) != self.mime_type:
            raise ValueError("image MIME mismatch")


def validate_images(images: tuple[ImagePart, ...]) -> tuple[ImagePart, ...]:
    result = tuple(images)
    if len(result) > MAX_IMAGES or any(not isinstance(item, ImagePart) for item in result):
        raise ValueError("invalid image inputs")
    if sum(len(item.data) for item in result) > MAX_TOTAL_IMAGE_BYTES:
        raise ValueError("image inputs exceed total byte limit")
    return result
