"""Only authorized message-resource references may become core image parts."""

from trendradar.ai.media import ImagePart, image_mime, validate_images

from .client import FeishuClient
from .models import FeishuInbound


def resolve_images(event: FeishuInbound, client: FeishuClient) -> tuple[ImagePart, ...]:
    images = []
    for part in event.media:
        downloaded = (
            part if part.data else client.download_image(event.message_id, part.resource_key)
        )
        if downloaded is None or not downloaded.data:
            raise ValueError("image resource unavailable")
        images.append(ImagePart(downloaded.data, image_mime(downloaded.data)))
    return validate_images(tuple(images))
