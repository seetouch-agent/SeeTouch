"""截图编码：默认 JPEG（体积小），需要时仍可无损 PNG。"""

import random

from PIL import Image

from seetouch.perception.screen import (
    DEFAULT_IMAGE_FORMAT,
    encode_image_data_url,
)


def _noisy(width=360, height=640):
    image = Image.new("RGB", (width, height))
    rnd = random.Random(7)
    image.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
                   for _ in range(width * height)])
    return image


def test_default_format_is_jpeg():
    assert DEFAULT_IMAGE_FORMAT == "JPEG"
    url = encode_image_data_url(Image.new("RGB", (64, 64), (1, 2, 3)))
    assert url.startswith("data:image/jpeg;base64,")


def test_png_remains_available():
    url = encode_image_data_url(Image.new("RGB", (64, 64)), "PNG")
    assert url.startswith("data:image/png;base64,")


def test_jpeg_is_smaller_than_png_for_a_screenshot_like_image():
    image = _noisy()
    jpeg = encode_image_data_url(image)
    png = encode_image_data_url(image, "PNG")
    assert len(jpeg) < len(png)


def test_rgba_is_converted_before_jpeg():
    image = Image.new("RGBA", (64, 64), (10, 20, 30, 128))
    url = encode_image_data_url(image)
    assert url.startswith("data:image/jpeg;base64,")


def test_quality_controls_size():
    image = _noisy()
    low = encode_image_data_url(image, quality=20)
    high = encode_image_data_url(image, quality=95)
    assert len(low) < len(high)
