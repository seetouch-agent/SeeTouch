"""NativeAndroidController:DeviceController 的 on-device 实现。

与 device/android/controller.py(uiautomator2 + adb,PC 端)对应,
本实现跑在手机 APP 进程内,所有设备操作经 Chaquopy 调 Kotlin
com.seetouch.app.bridge.DeviceBridge(背后是 AccessibilityService)。

OPEN 解析完全复用 AppLauncher;应用索引数据源走 DeviceBridge
(PackageManager 枚举桌面可启动应用的 显示名 -> package)。
"""

from __future__ import annotations

import io
import logging
import time
from typing import Tuple

from PIL import Image

from ..base import DeviceError
from ...harness import nodes_from_rows, render_nodes
from ...perception.screen import norm_to_pixel
from ..android.app_index import AppIndexEntry
from ..android.app_launcher import AppLauncher


logger = logging.getLogger(__name__)

SCROLL_DURATION_MS = 400


def _bridge():
    """延迟导入 Kotlin DeviceBridge(只有 Chaquopy 运行时才有 java 包)。"""
    try:
        from com.seetouch.app.bridge import DeviceBridge  # type: ignore[import-not-found]
    except ImportError as exc:
        raise DeviceError(
            "DeviceBridge unavailable: not running inside SeeTouch Android app"
        ) from exc
    return DeviceBridge


class NativeAndroidController:
    """AccessibilityService 驱动的 on-device DeviceController 实现。"""

    def __init__(self):
        self._b = _bridge()
        if not self._b.isServiceReady():
            raise DeviceError(
                "accessibility service not connected; "
                "enable SeeTouch in system accessibility settings"
            )
        self._screen_size: Tuple[int, int] | None = None
        self._launcher = AppLauncher(
            installed_packages_getter=self._installed_packages,
            start_app=self._start_app,
            go_home=self.go_home,
            verify_launch=self._verify_launch,
            index_source=_BridgeAppIndexSource(self._b),
        )

    # ------------------------- DeviceController API -------------------------

    def set_control_revision(self, revision: int) -> None:
        self._b.expectRevision(revision)

    def takeover_reason(self) -> str | None:
        reason = self._b.takeoverReason()
        return str(reason) if reason else None

    def screenshot(self) -> Image.Image:
        try:
            png = bytes(self._b.screenshotPng())
        except Exception as exc:
            raise DeviceError(f"screenshot failed: {exc}") from exc
        return Image.open(io.BytesIO(png)).convert("RGB")

    def screen_size(self) -> Tuple[int, int]:
        if self._screen_size is None:
            self._screen_size = (int(self._b.screenWidth()), int(self._b.screenHeight()))
        return self._screen_size

    def click(self, x_norm: int, y_norm: int) -> None:
        x, y = norm_to_pixel(x_norm, y_norm, self.screen_size())
        logger.debug("click norm=(%s,%s) px=(%s,%s)", x_norm, y_norm, x, y)
        if not self._b.click(x, y):
            raise DeviceError(f"click({x},{y}) gesture dispatch failed")

    def long_press(self, x_norm: int, y_norm: int) -> None:
        x, y = norm_to_pixel(x_norm, y_norm, self.screen_size())
        logger.debug("long_press norm=(%s,%s) px=(%s,%s)", x_norm, y_norm, x, y)
        if not self._b.longClick(x, y):
            raise DeviceError(f"long_press({x},{y}) gesture dispatch failed")

    def type_text(self, text: str) -> None:
        if not text:
            return
        if not self._b.typeText(text):
            raise DeviceError("type_text failed: no focused editable field")

    def scroll(
        self,
        start_norm: Tuple[int, int],
        end_norm: Tuple[int, int],
    ) -> None:
        size = self.screen_size()
        fx, fy = norm_to_pixel(start_norm[0], start_norm[1], size)
        tx, ty = norm_to_pixel(end_norm[0], end_norm[1], size)
        if not self._b.swipe(fx, fy, tx, ty, SCROLL_DURATION_MS):
            raise DeviceError("scroll gesture dispatch failed")

    def open_app(self, name_or_package: str) -> None:
        self._launcher.open(name_or_package)

    def go_home(self) -> None:
        if not self._b.pressHome():
            raise DeviceError("press HOME failed")
        # 等窗口切换事件到达,避免紧跟其后的 current_app() 读到旧前台
        # (视觉兜底 baseline 依赖此值,读到旧值会误学 launcher 包名)
        time.sleep(0.6)

    def back(self) -> None:
        if not self._b.pressBack():
            raise DeviceError("press BACK failed")

    def current_app(self) -> str | None:
        try:
            pkg = self._b.currentPackage()
            return str(pkg) if pkg is not None else None
        except Exception:
            return None

    def learn_app_from_visual(self, request: str, package: str) -> None:
        self._launcher.learn_from_visual(request, package)

    def ui_elements(self, limit: int = 120) -> list[dict]:
        """结构化控件列表（供 harness 做落点校准与界面签名）。"""
        try:
            rows = [str(row) for row in self._b.uiNodes()]
        except Exception as exc:
            logger.warning("uiNodes failed: %s", exc)
            return []
        width, height = self.screen_size()
        nodes = nodes_from_rows(rows, screen=(width, height))
        return [
            {
                "text": node.text,
                "desc": node.desc,
                "resource": node.resource,
                "class": node.cls,
                "bounds": node.bounds,
                "clickable": node.clickable,
                "scrollable": node.scrollable,
                "editable": node.editable,
                "focused": node.focused,
            }
            for node in nodes[:limit]
        ]

    def ui_context(self, limit: int = 90, max_chars: int = 6000) -> str:
        width, height = self.screen_size()
        try:
            rows = [str(row) for row in self._b.uiNodes()]
        except Exception as exc:
            logger.warning("uiNodes failed: %s", exc)
            return ""
        nodes = nodes_from_rows(rows, screen=(width, height))[:limit]
        return render_nodes(nodes, (width, height), limit=limit, max_chars=max_chars)

    # ------------------------- 内部 helpers -------------------------

    def _installed_packages(self) -> list[str]:
        try:
            return [str(p) for p in self._b.installedPackages()]
        except Exception as exc:
            logger.warning("installedPackages failed: %s", exc)
            return []

    def _start_app(self, package: str) -> None:
        if not self._b.startApp(package):
            raise DeviceError(f"no launch intent for package: {package}")

    def _verify_launch(self, package: str, timeout: float = 3.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.current_app() == package:
                return True
            time.sleep(0.3)
        logger.info("verify_launch(%s) timeout; current=%s", package, self.current_app())
        return False


class _BridgeAppIndexSource:
    """AppIndexSource 实现:经 DeviceBridge 枚举桌面可启动应用。

    Bridge 返回 "package\tlabel" 行数组;控制器生命周期内缓存一次
    (每个任务新建控制器,天然按任务刷新)。
    """

    def __init__(self, bridge):
        self._bridge = bridge
        self._cache: list[AppIndexEntry] | None = None

    def entries(self) -> list[AppIndexEntry]:
        if self._cache is not None:
            return self._cache
        result: list[AppIndexEntry] = []
        try:
            for line in self._bridge.launchableApps():
                package, _, label = str(line).partition("\t")
                if package and label:
                    result.append(AppIndexEntry(label=label, package=package))
        except Exception as exc:
            logger.warning("launchableApps failed: %s", exc)
            return []
        self._cache = result
        return result
