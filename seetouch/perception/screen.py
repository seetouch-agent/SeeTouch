"""感知:坐标归一化 <-> 像素 转换,以及图像编码工具。

模型与 Action 都使用 0-1000 归一化坐标;设备控制层接收的是像素坐标。
本模块负责无损转换。
"""

from __future__ import annotations

import base64
import io
from typing import Tuple

from PIL import Image


NORM_MAX = 1000

# 截图工作分辨率:上传给 VLM、落盘日志统一缩到此宽度。
# 坐标走 0-1000 归一化(设备控制层用真实 window_size 换算像素),
# 因此缩放不影响点击/滑动精度,只省上传带宽与磁盘。
WORK_MAX_WIDTH = 720


def norm_to_pixel(
    x_norm: int | float,
    y_norm: int | float,
    screen_size: Tuple[int, int],
) -> Tuple[int, int]:
    """归一化坐标 [0,1000] -> 像素坐标。

    Args:
        x_norm, y_norm: 归一化坐标
        screen_size:    设备像素尺寸 (width, height)

    Returns:
        (x_pixel, y_pixel)
    """
    width, height = screen_size
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid screen_size: {screen_size}")

    x_pixel = round(_clip_norm(x_norm) / NORM_MAX * width)
    y_pixel = round(_clip_norm(y_norm) / NORM_MAX * height)
    # 限制到屏幕内,避免点到边界外
    x_pixel = max(0, min(width - 1, x_pixel))
    y_pixel = max(0, min(height - 1, y_pixel))
    return x_pixel, y_pixel


def pixel_to_norm(
    x_pixel: int | float,
    y_pixel: int | float,
    screen_size: Tuple[int, int],
) -> Tuple[int, int]:
    """像素坐标 -> 归一化坐标 [0,1000]。"""
    width, height = screen_size
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid screen_size: {screen_size}")

    x_norm = round(float(x_pixel) / width * NORM_MAX)
    y_norm = round(float(y_pixel) / height * NORM_MAX)
    return _clip_norm(x_norm), _clip_norm(y_norm)


def _clip_norm(value: int | float) -> int:
    return int(max(0, min(NORM_MAX, round(float(value)))))


def downscale(image: Image.Image, max_width: int = WORK_MAX_WIDTH) -> Image.Image:
    """等比缩小到最大宽度,降低上传体积与日志体积。

    模型与 Action 走 0-1000 归一化坐标,设备控制层用真实分辨率换算像素,
    所以缩放不改变任何坐标语义,只是少传/少存像素。已经不超过 max_width 时原样返回。
    """
    if image.width <= max_width:
        return image
    ratio = max_width / image.width
    new_size = (max_width, round(image.height * ratio))
    return image.resize(new_size, Image.LANCZOS)


# 截图默认用 JPEG：手机截图是不透明图像，PNG 的体积约为 JPEG 的 3-5 倍，
# 而每步都要上传一次。需要无损时显式传 image_format="PNG"。
DEFAULT_IMAGE_FORMAT = "JPEG"
DEFAULT_JPEG_QUALITY = 85


def encode_image_data_url(
    image: Image.Image,
    image_format: str = DEFAULT_IMAGE_FORMAT,
    *,
    quality: int = DEFAULT_JPEG_QUALITY,
) -> str:
    """把 PIL Image 编码成 data URL,供多模态 chat API 使用。

    JPEG 路径会先转成 RGB（截图带 alpha 时 JPEG 无法保存），并用 ``quality`` 压一次；
    PNG 路径保持无损。
    """
    fmt = (image_format or DEFAULT_IMAGE_FORMAT).upper()
    buf = io.BytesIO()
    if fmt in ("JPEG", "JPG"):
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.save(buf, format="JPEG", quality=int(quality), optimize=True)
        mime = "jpeg"
    else:
        image.save(buf, format=fmt)
        mime = fmt.lower()
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/{mime};base64,{b64}"
