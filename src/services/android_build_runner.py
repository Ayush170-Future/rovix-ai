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

# ADB server location — override for split-VM deployments where the ADB server
# (and emulator) live on a separate host from the backend.
ADB_HOST = os.getenv("ADB_HOST", "127.0.0.1")
ADB_PORT = int(os.getenv("ADB_PORT", "5037"))


def _adb_client() -> AdbClient:
    """Return a ppadb client pointed at the configured ADB server."""
    return AdbClient(host=ADB_HOST, port=ADB_PORT)


def _get_device(client: AdbClient, serial: str):
    """Return the ppadb device object for *serial*, or raise a clear RuntimeError."""
    devices = client.devices()
    for d in devices:
        if d.serial == serial:
            return d
    available = sorted(d.serial for d in devices)
    raise RuntimeError(
        f"ADB device '{serial}' not found (ADB server: {ADB_HOST}:{ADB_PORT}, "
        f"available: {available or 'none'}). "
        "Ensure the emulator is running and `adb devices` lists it."
    )


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
    """Raise RuntimeError if *serial* is not visible to the configured ADB server."""
    client = _adb_client()
    _get_device(client, serial)  # raises with a descriptive message if not found


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
    client = _adb_client()
    device = _get_device(client, serial)
    # ppadb pushes to /data/local/tmp then runs pm install -r
    result = device.install(apk_path)
    if result is not True and "Success" not in str(result):
        raise RuntimeError(f"adb install failed: {result}")


def adb_launch_app(serial: str, package: str, activity: str) -> None:
    """
    Bring app to foreground via ppadb device.shell().
    Prefer explicit component (package/activity); fall back to monkey launcher.
    """
    client = _adb_client()
    device = _get_device(client, serial)

    comp = activity if "/" in activity else f"{package}/{activity}"

    out = device.shell(f"am start -n {comp}")
    logger.debug(f"am start output: {out!r}")

    # `am start` exits 0 even on some errors; check the output text instead.
    if out and ("Error" in out or "Exception" in out):
        logger.warning(f"am start may have failed ({out.strip()}); trying monkey launcher")
        out2 = device.shell(
            f"monkey -p {package} -c android.intent.category.LAUNCHER 1"
        )
        logger.debug(f"monkey output: {out2!r}")
        if out2 and ("Error" in out2 or "Exception" in out2):
            raise RuntimeError(f"Could not launch app {package}: {out2.strip()}")


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

    # ── Step 1: device check ──────────────────────────────────────────────────
    try:
        assert_device_connected(device_udid)
    except RuntimeError as e:
        raise RuntimeError(f"[device_check] {e}") from e

    fd, tmp_apk = tempfile.mkstemp(suffix=".apk")
    os.close(fd)
    try:
        # ── Step 2: download APK from GCS ─────────────────────────────────────
        try:
            logger.info(f"Downloading build from gs://{build.bucket_name}/{build.object_key}")
            download_apk_from_gcs(build.bucket_name, build.object_key, tmp_apk)
        except Exception as e:
            raise RuntimeError(f"[apk_download] {e}") from e

        # ── Step 3: resolve package / activity ────────────────────────────────
        try:
            package, activity = resolve_launch_components(tmp_apk, build)
        except Exception as e:
            raise RuntimeError(f"[apk_parse] {e}") from e

        # ── Step 4: install APK ───────────────────────────────────────────────
        try:
            logger.info(f"Installing APK on {device_udid} (package={package})")
            adb_install(device_udid, tmp_apk)
        except Exception as e:
            raise RuntimeError(f"[apk_install] {e}") from e

        # ── Step 5: launch app ────────────────────────────────────────────────
        try:
            logger.info(f"Launching {package} / {activity}")
            adb_launch_app(device_udid, package, activity)
        except Exception as e:
            raise RuntimeError(f"[app_launch] {e}") from e

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
        host=ADB_HOST,
        port=ADB_PORT,
        serial=device_udid,
        screenshot_timeout=float(os.getenv("SCREENSHOT_TIMEOUT", "10.0")),
        screenshot_max_retries=int(os.getenv("SCREENSHOT_MAX_RETRIES", "3")),
    )


__all__ = ["create_action_executor_for_build"]
