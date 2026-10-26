"""The E2E pass/fail checkers must not trust the agent's own completion claim."""

from e2e import run_e2e


def test_settings_home_requires_settings_foreground(monkeypatch):
    monkeypatch.setattr(run_e2e, "foreground", lambda serial: {
        "package": "com.android.settings", "activity": ".Settings",
    })
    passed, _ = run_e2e.settings_home("emulator-5554")
    assert passed
    monkeypatch.setattr(run_e2e, "foreground", lambda serial: {
        "package": "com.android.launcher3", "activity": ".Launcher",
    })
    passed, _ = run_e2e.settings_home("emulator-5554")
    assert not passed


def test_about_phone_requires_both_package_and_label(monkeypatch):
    monkeypatch.setattr(run_e2e, "_adb", lambda *args, **kwargs: "")
    monkeypatch.setattr(run_e2e, "foreground", lambda serial: {
        "package": "com.android.settings", "activity": ".Settings$MyDeviceInfoActivity",
    })
    monkeypatch.setattr(run_e2e, "ui_text", lambda serial: 'text="About phone"')
    assert run_e2e.about_phone("emulator-5554")[0]
    monkeypatch.setattr(run_e2e, "foreground", lambda serial: {
        "package": "com.android.settings", "activity": ".Settings",
    })
    monkeypatch.setattr(run_e2e, "ui_text", lambda serial: 'text="关于模拟设备"')
    assert not run_e2e.about_phone("emulator-5554")[0]


def test_bluetooth_checker_requires_toggle_and_home(monkeypatch):
    monkeypatch.setattr(run_e2e, "bluetooth_enabled", lambda serial: True)
    monkeypatch.setattr(run_e2e, "foreground", lambda serial: {
        "package": "com.android.settings", "activity": ".Settings",
    })
    assert run_e2e.bluetooth_on_and_back_home("emulator-5554")[0]
    monkeypatch.setattr(run_e2e, "foreground", lambda serial: {
        "package": "com.android.settings", "activity": ".SubSettings",
    })
    assert not run_e2e.bluetooth_on_and_back_home("emulator-5554")[0]


def test_chrome_app_info_accepts_spa_hosted_page(monkeypatch):
    monkeypatch.setattr(run_e2e, "_adb", lambda *args, **kwargs: "")
    monkeypatch.setattr(run_e2e, "foreground", lambda serial: {
        "package": "com.android.settings", "activity": ".spa.SpaActivity",
    })
    monkeypatch.setattr(
        run_e2e, "ui_text",
        lambda serial: 'text="Chrome" text="强行停止" text="存储和缓存"',
    )
    assert run_e2e.chrome_app_info("emulator-5554")[0]
