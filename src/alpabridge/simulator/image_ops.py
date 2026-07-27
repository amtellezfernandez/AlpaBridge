"""Generic image-resizing utilities for vision-based trajectory policies.

Not specific to any one model: any policy that expects a fixed input
resolution needs to turn whatever a real camera actually delivers into
that shape, and real camera feeds essentially never match a model's
expected aspect ratio exactly - even a difference of a few thousandths
(1600:900 vs. a real sensor's 568:320, say) is enough to matter. Scaling
by only one dimension and cropping the other, as some reference
implementations do, silently assumes the source is always at least as
wide (or tall) as the target for that one axis - which breaks the moment
a real feed's aspect ratio comes in fractionally narrower.
"""

from __future__ import annotations

from math import ceil

import numpy as np


def resize_and_center_crop(image: np.ndarray, target_height: int, target_width: int) -> np.ndarray:
    """Resize ``image`` to cover ``(target_height, target_width)``, then
    center-crop to exactly that size.

    "Cover" scaling picks the larger of the two required ratios, so the
    resized image is guaranteed at least as big as the target in both
    dimensions regardless of the source's aspect ratio - unlike scaling by
    a single dimension, which only works when the source happens to be at
    least as wide (or tall) as the target on the other axis already.
    """
    from PIL import Image as PILImage

    height, width = image.shape[:2]
    if height == target_height and width == target_width:
        return image

    scale = max(target_height / height, target_width / width)
    new_height = ceil(height * scale)
    new_width = ceil(width * scale)
    pil_image = PILImage.fromarray(image).resize(
        (new_width, new_height), PILImage.Resampling.BILINEAR
    )

    if new_height < target_height or new_width < target_width:
        raise ValueError(
            f"image {new_width}x{new_height} too small after resize, "
            f"need {target_width}x{target_height}"
        )
    top = (new_height - target_height) // 2
    left = (new_width - target_width) // 2
    pil_image = pil_image.crop((left, top, left + target_width, top + target_height))

    return np.array(pil_image)
