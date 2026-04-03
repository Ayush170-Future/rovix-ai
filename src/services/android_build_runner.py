from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import tempfile
from datetime import timedelta
from typing import Any, Optional, Tuple

import requests as _requests
from google.cloud import storage
from ppadb.client import Client as AdbClient

from agent.logger import get_logger
from models.build import Build

logger = get_logger("agent.services.android_build_runner")

# Defaults — override per-device via create_action_executor_for_build for multi-host setups.
ADB_HOST = os.getenv("ADB_HOST", "127.0.0.1")
ADB_PORT = int(os.getenv("ADB_PORT", "5037"))


def _adb_client(host: Optional[str] = None, port: Optional[int] = None) -> AdbClient:
    h = ADB_HOST if host is None else host
    p = ADB_PORT if port is None else port
    return AdbClient(host=h, port=p)


def _get_device(client: AdbClient, serial: str):
    """Return the ppadb device object for *serial*, or raise a clear RuntimeError."""
    devices = client.devices()
    for d in devices:
        if d.serial == serial:
            return d
    available = sorted(d.serial for d in devices)
    host = getattr(client, "host", None)
    port = getattr(client, "port", None)
    where = f"{host}:{port}" if host is not None and port is not None else "configured ADB server"
    raise RuntimeError(
        f"ADB device '{serial}' not found (ADB server: {where}, "
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


def assert_device_connected(
    serial: str,
    *,
    adb_host: Optional[str] = None,
    adb_port: Optional[int] = None,
) -> None:
    """Raise RuntimeError if *serial* is not visible to the configured ADB server."""
    ah = ADB_HOST if adb_host is None else adb_host
    ap = ADB_PORT if adb_port is None else adb_port
    client = _adb_client(ah, ap)
    _get_device(client, serial)  # raises with a descriptive message if not found


def generate_signed_url(bucket_name: str, object_key: str, expiry_minutes: int = 30) -> str:
    """
    Generate a V4 signed GET URL for a GCS object.
    Works with ADC on GCP VMs (uses IAM sign-blob under the hood).
    The VM agent downloads via this URL — no GCS credentials needed on the VM.
    """
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_key)
    if not blob.exists(client=client):
        raise RuntimeError(f"Build artifact not found in GCS: gs://{bucket_name}/{object_key}")
    url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=expiry_minutes),
        method="GET",
    )
    return url


def download_apk_from_gcs(bucket_name: str, object_key: str, dest_path: str) -> None:
    """Download APK directly on this host (backend fallback when no agent_url is set)."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_key)
    if not blob.exists(client=client):
        raise RuntimeError(f"Build artifact not found in GCS: gs://{bucket_name}/{object_key}")
    blob.download_to_filename(dest_path, client=client)
    if not os.path.exists(dest_path) or os.path.getsize(dest_path) == 0:
        raise RuntimeError("Downloaded APK is missing or empty")


def _install_via_agent(
    agent_url: str,
    download_url: str,
    serial: str,
    checksum_sha256: str = "",
    agent_token: str = "",
) -> tuple[str, str]:
    """
    POST to device_agent /install endpoint.
    Returns (package, activity) — may be empty strings if aapt not on VM.
    Raises RuntimeError on failure.
    """
    headers = {}
    if agent_token:
        headers["X-Agent-Token"] = agent_token

    payload = {
        "download_url": download_url,
        "serial": serial,
        "checksum_sha256": checksum_sha256,
    }
    try:
        resp = _requests.post(
            f"{agent_url.rstrip('/')}/install",
            json=payload,
            headers=headers,
            timeout=900,
        )
    except _requests.RequestException as e:
        raise RuntimeError(f"Agent unreachable: {e}")

    if not resp.ok:
        raise RuntimeError(f"Agent returned {resp.status_code}: {resp.text}")

    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"Agent install failed: {data.get('detail', 'unknown')}")

    return data.get("package", ""), data.get("activity", "")


def device_cleanup_after_run(
    serial: str,
    package: str,
    *,
    adb_host: Optional[str] = None,
    adb_port: Optional[int] = None,
) -> None:
    """
    After a run: HOME, then optional force-stop so the next test starts from a sane launcher state.
    Never raises — callers can wrap in try/except if they prefer to log failures only.
    """
    ah = ADB_HOST if adb_host is None else adb_host
    ap = ADB_PORT if adb_port is None else adb_port
    adb = shutil.which("adb")
    if not adb:
        logger.warning("device_cleanup_after_run: adb not found in PATH")
        return

    result = subprocess.run(
        [adb, "-H", ah, "-P", str(ap), "-s", serial, "shell", "input", "keyevent", "3"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        logger.warning(
            "device_cleanup_after_run: HOME keyevent failed: %s",
            (result.stdout + result.stderr).strip() or result.returncode,
        )

    pkg = (package or "").strip()
    if pkg:
        fs = subprocess.run(
            [adb, "-H", ah, "-P", str(ap), "-s", serial, "shell", "am", "force-stop", pkg],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if fs.returncode != 0:
            logger.warning(
                "device_cleanup_after_run: force-stop failed for %s: %s",
                pkg,
                (fs.stdout + fs.stderr).strip() or fs.returncode,
            )


def adb_install(
    serial: str,
    apk_path: str,
    *,
    adb_host: Optional[str] = None,
    adb_port: Optional[int] = None,
) -> None:
    ah = ADB_HOST if adb_host is None else adb_host
    ap = ADB_PORT if adb_port is None else adb_port
    adb = shutil.which("adb")
    if not adb:
        raise RuntimeError("adb binary not found in PATH. Install Android SDK platform-tools.")
    result = subprocess.run(
        [adb, "-H", ah, "-P", str(ap), "-s", serial, "install", "-r", apk_path],
        capture_output=True,
        text=True,
        timeout=1200,
    )
    if result.returncode != 0 or "Success" not in result.stdout:
        detail = (result.stdout + result.stderr).strip()
        raise RuntimeError(f"adb install failed: {detail}")


def adb_launch_app(
    serial: str,
    package: str,
    activity: str,
    *,
    adb_host: Optional[str] = None,
    adb_port: Optional[int] = None,
) -> None:
    """
    Bring app to foreground via ppadb device.shell().
    Prefer explicit component (package/activity); fall back to monkey launcher.
    """
    ah = ADB_HOST if adb_host is None else adb_host
    ap = ADB_PORT if adb_port is None else adb_port
    client = _adb_client(ah, ap)
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
    appium_url: Optional[str] = None,
    adb_host: Optional[str] = None,
    adb_port: Optional[int] = None,
    agent_url: Optional[str] = None,
) -> Tuple[Any, str]:
    if build.platform != "android":
        raise RuntimeError(f"Device install path only supports Android builds (got platform={build.platform})")
    if build.artifact_type != "apk":
        raise RuntimeError(
            f"Only APK artifacts are supported for automatic install (got {build.artifact_type}). "
            "AAB/IPA require a different pipeline."
        )
    if build.status != "ready":
        raise RuntimeError(f"Build must be ready (status={build.status})")

    ah = ADB_HOST if adb_host is None else adb_host
    ap = ADB_PORT if adb_port is None else adb_port
    au = os.getenv("APPIUM_URL", "http://localhost:4723") if appium_url is None else appium_url
    agent_token = os.getenv("AGENT_TOKEN", "")

    # ── Step 1: device check ──────────────────────────────────────────────────
    try:
        assert_device_connected(device_udid, adb_host=ah, adb_port=ap)
    except RuntimeError as e:
        raise RuntimeError(f"[device_check] {e}") from e

    # ── Fast path: delegate download + install to VM-local device agent ────────
    if agent_url:
        try:
            logger.info(
                f"Agent path: generating signed URL for gs://{build.bucket_name}/{build.object_key}"
            )
            signed_url = generate_signed_url(build.bucket_name, build.object_key)
        except Exception as e:
            raise RuntimeError(f"[signed_url] {e}") from e

        try:
            logger.info(f"Delegating install to agent at {agent_url} (serial={device_udid})")
            package, activity = _install_via_agent(
                agent_url=agent_url,
                download_url=signed_url,
                serial=device_udid,
                checksum_sha256=build.checksum_sha256 or "",
                agent_token=agent_token,
            )
        except Exception as e:
            raise RuntimeError(f"[agent_install] {e}") from e

        # Agent may not have aapt — fall back to DB fields if empty.
        if not package:
            package = (build.android_app_package or "").strip()
        if not activity:
            activity = (build.android_app_activity or "").strip()
        if not package or not activity:
            raise RuntimeError(
                "package/activity could not be resolved: agent did not return them and "
                "build.android_app_package / android_app_activity are not set in DB."
            )

        logger.info(f"Agent install complete — package={package} activity={activity}")

    # ── Slow path: backend downloads, pushes via ADB ──────────────────────────
    else:
        fd, tmp_apk = tempfile.mkstemp(suffix=".apk")
        os.close(fd)
        try:
            try:
                logger.info(f"Downloading build from gs://{build.bucket_name}/{build.object_key}")
                download_apk_from_gcs(build.bucket_name, build.object_key, tmp_apk)
            except Exception as e:
                raise RuntimeError(f"[apk_download] {e}") from e

            try:
                package, activity = resolve_launch_components(tmp_apk, build)
            except Exception as e:
                raise RuntimeError(f"[apk_parse] {e}") from e

            try:
                logger.info(f"Installing APK on {device_udid} (package={package})")
                adb_install(device_udid, tmp_apk, adb_host=ah, adb_port=ap)
            except Exception as e:
                raise RuntimeError(f"[apk_install] {e}") from e
        finally:
            try:
                os.unlink(tmp_apk)
            except OSError:
                pass

    # ── Step: launch app (both paths) ────────────────────────────────────────
    try:
        logger.info(f"Launching {package} / {activity}")
        adb_launch_app(device_udid, package, activity, adb_host=ah, adb_port=ap)
    except Exception as e:
        raise RuntimeError(f"[app_launch] {e}") from e

    if use_appium:
        from agent.appium_manager import AppiumManager

        return (
            AppiumManager(
                appium_url=au,
                device_name=os.getenv("DEVICE_NAME"),
                udid=device_udid,
                app_package=package,
                app_activity=activity,
                screenshot_timeout=float(os.getenv("SCREENSHOT_TIMEOUT", "10.0")),
                screenshot_max_retries=int(os.getenv("SCREENSHOT_MAX_RETRIES", "3")),
            ),
            package,
        )

    from agent.adb_manager import ADBManager

    return (
        ADBManager(
            host=ah,
            port=ap,
            serial=device_udid,
            screenshot_timeout=float(os.getenv("SCREENSHOT_TIMEOUT", "10.0")),
            screenshot_max_retries=int(os.getenv("SCREENSHOT_MAX_RETRIES", "3")),
        ),
        package,
    )


__all__ = ["create_action_executor_for_build", "device_cleanup_after_run"]
