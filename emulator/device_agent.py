#!/usr/bin/env python3
"""
device_agent.py — Lightweight FastAPI sidecar that runs on the emulator VM.

Responsibilities:
  1. Receive a signed GCS download URL from the backend.
  2. Download the APK locally (no GCS credentials needed on the VM).
  3. Optionally verify SHA-256 checksum.
  4. Run `adb -s <serial> install -r` from localhost (fast — no network hop).
  5. Optionally parse package/activity via aapt so the backend does not need to.

Start:
  uvicorn device_agent:app --host 0.0.0.0 --port 8080

Secure with a shared secret token (AGENT_TOKEN env var).
"""

from __future__ import annotations

import glob
import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("device_agent")

AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")  # set this on the VM; backend sends it in X-Agent-Token
ADB_PATH = shutil.which("adb") or "adb"

app = FastAPI(title="Device Agent", version="1.0.0")


# ─── Auth ────────────────────────────────────────────────────────────────────

def _verify_token(x_agent_token: str = Header(default="")) -> None:
    if AGENT_TOKEN and x_agent_token != AGENT_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid agent token")


# ─── Models ──────────────────────────────────────────────────────────────────

class InstallRequest(BaseModel):
    download_url: str          # signed GCS URL (HTTPS); valid for ~30-60 min
    serial: str                # ADB serial, e.g. "192.168.240.112:5555"
    checksum_sha256: str = ""  # optional; agent will verify before install


class InstallResponse(BaseModel):
    success: bool
    package: str = ""
    activity: str = ""
    detail: str = ""


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _download(url: str, dest: str, checksum_sha256: str = "") -> None:
    """Stream download URL → dest file, then optionally verify SHA-256."""
    logger.info(f"Downloading APK to {dest} …")
    with httpx.stream("GET", url, follow_redirects=True, timeout=300) as r:
        r.raise_for_status()
        hasher = hashlib.sha256()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=1 << 20):
                f.write(chunk)
                hasher.update(chunk)

    if not os.path.exists(dest) or os.path.getsize(dest) == 0:
        raise RuntimeError("Downloaded APK is empty or missing")

    if checksum_sha256:
        actual = hasher.hexdigest()
        if actual != checksum_sha256.lower():
            raise RuntimeError(
                f"SHA-256 mismatch: expected {checksum_sha256}, got {actual}"
            )
        logger.info("Checksum verified ✓")


def _adb_install(serial: str, apk_path: str) -> None:
    """Run adb install -r against the local ADB server (127.0.0.1:5037)."""
    logger.info(f"Installing {apk_path} on {serial} …")
    result = subprocess.run(
        [ADB_PATH, "-s", serial, "install", "-r", apk_path],
        capture_output=True,
        text=True,
        timeout=1200,
    )
    detail = (result.stdout + result.stderr).strip()
    if result.returncode != 0 or "Success" not in result.stdout:
        raise RuntimeError(f"adb install failed: {detail}")
    logger.info(f"Install succeeded: {detail}")


def _find_aapt() -> Optional[str]:
    path = shutil.which("aapt")
    if path:
        return path
    android_home = os.getenv("ANDROID_HOME") or os.getenv("ANDROID_SDK_ROOT")
    if android_home:
        matches = sorted(
            glob.glob(os.path.join(android_home, "build-tools", "*", "aapt")), reverse=True
        )
        if matches:
            return matches[0]
    return None


def _parse_apk(apk_path: str) -> tuple[str, str]:
    """Return (package, launchable_activity) via aapt; returns ('', '') if aapt not found."""
    aapt = _find_aapt()
    if not aapt:
        logger.warning("aapt not found; package/activity will not be returned by agent")
        return "", ""
    try:
        out = subprocess.check_output(
            [aapt, "dump", "badging", apk_path],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=120,
        )
    except Exception as e:
        logger.warning(f"aapt failed: {e}")
        return "", ""

    m_pkg = re.search(r"package:\s*name='([^']+)'", out)
    pkg = m_pkg.group(1) if m_pkg else ""
    m_act = re.search(r"launchable-activity:\s*name='([^']+)'", out)
    activity = m_act.group(1) if m_act else ""
    return pkg, activity


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "adb": ADB_PATH}


@app.post("/install", response_model=InstallResponse)
def install(req: InstallRequest, _: None = Depends(_verify_token)):
    fd, tmp_apk = tempfile.mkstemp(suffix=".apk")
    os.close(fd)
    try:
        # 1. Download from signed URL
        try:
            _download(req.download_url, tmp_apk, req.checksum_sha256)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"[download] {e}")

        # 2. Parse package/activity (best-effort, before install so we return it)
        pkg, activity = _parse_apk(tmp_apk)

        # 3. Install
        try:
            _adb_install(req.serial, tmp_apk)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"[adb_install] {e}")

        return InstallResponse(success=True, package=pkg, activity=activity)

    finally:
        try:
            os.unlink(tmp_apk)
        except OSError:
            pass
