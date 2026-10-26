"""DeviceController 抽象接口。

DEPRECATED 异常: 使用 seetouch.core.exceptions 中的统一异常替代。
为向后兼容保留 re-export。
"""

from __future__ import annotations

from typing import Protocol, Tuple, runtime_checkable

from PIL import Image

# 向后兼容: re-export 统一异常
from ..core.exceptions import (
    AppLaunchError as OpenAppFailed,
    DeviceError,
    OpenAppNeedsVisual,
    OpenAppNotFound,
)


@runtime_checkable
class DeviceController(Protocol):
    """跨平台设备控制抽象。

    所有坐标接口都使用归一化坐标 [0, 1000];实现内部负责到像素的换算。
    """

    def screenshot(self) -> Image.Image:
        """获取当前屏幕截图(PIL Image)。"""
        ...

    def screen_size(self) -> Tuple[int, int]:
        """返回设备像素尺寸 (width, height)。"""
        ...

    def click(self, x_norm: int, y_norm: int) -> None:
        """单击。坐标范围 [0, 1000]。"""
        ...

    def long_press(self, x_norm: int, y_norm: int) -> None:
        """长按。坐标范围 [0, 1000]。用于唤出上下文菜单/进入应用信息等。"""
        ...

    def type_text(self, text: str) -> None:
        """在当前焦点输入框输入文本(支持中文)。"""
        ...

    def scroll(
        self,
        start_norm: Tuple[int, int],
        end_norm: Tuple[int, int],
    ) -> None:
        """从 start 滑到 end,坐标归一化。"""
        ...

    def open_app(self, name_or_package: str) -> None:
        """启动 app。接受应用显示名(首选)或 Android package name。

        实现应基于应用索引解析:精确/强模糊命中则启动;
        歧义时 raise OpenAppNotFound(携带候选);
        无索引可用且无法解析时 raise OpenAppNeedsVisual。
        """
        ...

    def go_home(self) -> None:
        """回到桌面。"""
        ...

    def back(self) -> None:
        """按系统返回键:回到上一层页面 / 关闭当前弹窗或子页面。"""
        ...

    def current_app(self) -> str | None:
        """当前前台 app 的 package name。无法获取时返回 None。

        Runner 用此判断 OPEN 是否真的把目标 app 推到了前台,
        以及视觉兜底过程中前台是否已经从桌面切到了某个真实 app。
        """
        ...

    def learn_app_from_visual(self, request: str, package: str) -> None:
        """视觉兜底成功后,把(用户/模型给出的名字 -> 实际 package)记入持久化缓存。

        非 Android 实现可以无操作。
        """
        ...


__all__ = [
    "DeviceController",
    "DeviceError",
    "OpenAppFailed",
    "OpenAppNeedsVisual",
    "OpenAppNotFound",
]
