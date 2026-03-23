# TODO: Have to use padb to interact with ADB and also take care of error handling when running ADB commands
# right now the launch failure is not getting logged properly in the code

# TODO: Failures are often because the ADB server is not listening (default 127.0.0.1:5037) or
# Appium is not running (default http://localhost:4723 / APPIUM_URL) — surface clearer errors.

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Optional, Tuple
from google.cloud import storage
from ppadb.client import Client as AdbClient

from agent.logger import get_logger
from models.build import Build

logger = get_logger("agent.services.android_build_runner")


def find_aapt_binary() -> Optional[str]:
    path = shutil.which("aapt")
    if path:
        return path
    android_home = os.getenv("ANDROID_HOME") or os.getenv("ANDROID_SDK_ROOT")
    if android_home:
        matches = sorted(glob.glob(os.path.join(android_home, "build-tools", "*", "aapt")), reverse=True)
        if matches:
            return matches[0]
    return None


def parse_apk_package_and_activity(apk_path: str) -> Tuple[str, str]:
    """Parse package + launchable activity from APK via aapt dump badging."""
    aapt = find_aapt_binary()
    if not aapt:
        raise RuntimeError(
            "aapt not found (install Android build-tools or add aapt to PATH / set ANDROID_HOME). "
            "Alternatively set android_app_package and android_app_activity on the build at finalize time."
        )
    out = subprocess.check_output(
        [aapt, "dump", "badging", apk_path],
        text=True,
        stderr=subprocess.DEVNULL,
        timeout=120,
    )
    m_pkg = re.search(r"package:\s*name='([^']+)'", out)
    if not m_pkg:
        raise RuntimeError("Could not parse package name from APK (aapt dump badging)")
    pkg = m_pkg.group(1)
    m_act = re.search(r"launchable-activity:\s*name='([^']+)'", out)
    if m_act:
        activity = m_act.group(1)
    else:
        # Fallback for some Unity / merged manifests
        m_act2 = re.search(r"^\s*launchable-activity-name:\s*'([^']+)'", out, re.MULTILINE)
        activity = m_act2.group(1) if m_act2 else ""
    if not activity:
        activity = os.getenv("DEFAULT_UNITY_ACTIVITY", "com.unity3d.player.UnityPlayerActivity")
        logger.warning(f"No launchable-activity in APK; using fallback activity: {activity}")
    return pkg, activity


def resolve_launch_components(apk_path: str, build: Build) -> Tuple[str, str]:
    """Prefer DB fields; fill gaps with aapt."""
    pkg = (build.android_app_package or "").strip()
    act = (build.android_app_activity or "").strip()

    if pkg and act:
        return pkg, act
    parsed_pkg, parsed_act = parse_apk_package_and_activity(apk_path)
    if not pkg:
        pkg = parsed_pkg
    if not act:
        act = parsed_act
    if not pkg or not act:
        raise RuntimeError("Could not resolve Android package/activity for this build")
    return pkg, act


def assert_device_connected(serial: str) -> None:
    client = AdbClient(host="127.0.0.1", port=5037)
    devices = client.devices()
    found = {d.serial for d in devices}
    if serial not in found:
        raise RuntimeError(
            f"ADB device '{serial}' is not connected (available: {sorted(found) if found else 'none'}). "
            "Check USB debugging and `adb devices`."
        )


def download_apk_from_gcs(bucket_name: str, object_key: str, dest_path: str) -> None:
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_key)
    if not blob.exists(client=client):
        raise RuntimeError(f"Build artifact not found in GCS: gs://{bucket_name}/{object_key}")
    blob.download_to_filename(dest_path, client=client)
    if not os.path.exists(dest_path) or os.path.getsize(dest_path) == 0:
        raise RuntimeError("Downloaded APK is missing or empty")


def adb_install(serial: str, apk_path: str) -> None:
    r = subprocess.run(
        ["adb", "-s", serial, "install", "-r", apk_path],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if r.returncode != 0:
        msg = (r.stdout or "") + (r.stderr or "")
        raise RuntimeError(f"adb install failed: {msg.strip() or r.returncode}")



def adb_launch_app(serial: str, package: str, activity: str) -> None:
    """
    Bring app to foreground. Prefer explicit component; fall back to monkey launcher.
    """
    if "/" in activity:
        comp = activity
    else:
        comp = f"{package}/{activity}"

    r = subprocess.run(
        ["adb", "-s", serial, "shell", "am", "start", "-n", comp],
        capture_output=True,
        text=True,
        timeout=90,
    )
    if r.returncode == 0:
        return
    logger.warning(f"am start failed ({r.stderr or r.stdout}); trying monkey launcher")
    r2 = subprocess.run(
        ["adb", "-s", serial, "shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
        capture_output=True,
        text=True,
        timeout=90,
    )
    if r2.returncode != 0:
        msg = (r2.stdout or "") + (r2.stderr or "")
        raise RuntimeError(f"Could not launch app {package}: {msg.strip() or r2.returncode}")


def create_action_executor_for_build(
    *,
    device_udid: str,
    build: Build,
    use_appium: bool,
) -> Any:
    if build.platform != "android":
        raise RuntimeError(f"Device install path only supports Android builds (got platform={build.platform})")
    if build.artifact_type != "apk":
        raise RuntimeError(
            f"Only APK artifacts are supported for automatic install (got {build.artifact_type}). "
            "AAB/IPA require a different pipeline."
        )
    if build.status != "ready":
        raise RuntimeError(f"Build must be ready (status={build.status})")

    assert_device_connected(device_udid)

    fd, tmp_apk = tempfile.mkstemp(suffix=".apk")
    os.close(fd)
    try:
        logger.info(f"Downloading build from gs://{build.bucket_name}/{build.object_key}")
        # download_apk_from_gcs(build.bucket_name, build.object_key, tmp_apk)

        package, activity = resolve_launch_components(tmp_apk, build)
        logger.info(f"Installing APK on {device_udid} (package={package})")
        # adb_install(device_udid, tmp_apk)

        logger.info(f"Launching {package} / {activity}")
        adb_launch_app(device_udid, package, activity)
    finally:
        try:
            os.unlink(tmp_apk)
        except OSError:
            pass

    if use_appium:
        from agent.appium_manager import AppiumManager

        return AppiumManager(
            appium_url=os.getenv("APPIUM_URL", "http://localhost:4723"),
            device_name=os.getenv("DEVICE_NAME"),
            udid=device_udid,
            app_package=package,
            app_activity=activity,
            screenshot_timeout=float(os.getenv("SCREENSHOT_TIMEOUT", "10.0")),
            screenshot_max_retries=int(os.getenv("SCREENSHOT_MAX_RETRIES", "3")),
        )

    from agent.adb_manager import ADBManager

    return ADBManager(
        host="127.0.0.1",
        port=5037,
        serial=device_udid,
        screenshot_timeout=float(os.getenv("SCREENSHOT_TIMEOUT", "10.0")),
        screenshot_max_retries=int(os.getenv("SCREENSHOT_MAX_RETRIES", "3")),
    )


__all__ = ["create_action_executor_for_build"]
