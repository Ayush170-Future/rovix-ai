import asyncio
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from dependencies import get_org
from models.organization import Organization
from ppadb.client import Client as AdbClient
from repositories.device_repository import DeviceRepository
from services.execution_service import ExecutionService

router = APIRouter(prefix="/api/devices", tags=["Devices"])
_device_repo = DeviceRepository()


class RegisterDeviceRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=128)
    label: str = Field(..., min_length=1, max_length=256)
    udid: str = Field(..., min_length=1, max_length=256)
    adb_host: str = Field(..., min_length=1)
    adb_port: int = Field(default=5037, ge=1, le=65535)
    appium_url: str = Field(..., min_length=1)
    agent_url: Optional[str] = None  # URL of device_agent.py sidecar on the VM
    enabled: bool = True


def _appium_status_url(appium_url: str) -> str:
    return f"{appium_url.rstrip('/')}/status"


async def _probe_appium(appium_url: str) -> bool:
    url = _appium_status_url(appium_url)

    def _get() -> bool:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            return False

    return await asyncio.to_thread(_get)


@router.get("")
async def list_devices(
    request: Request,
    org: Organization = Depends(get_org),
):
    execution_service: ExecutionService = request.app.state.execution_service
    devices = await _device_repo.find_all_enabled(str(org.id))
    out: List[Dict[str, Any]] = []
    for d in devices:
        busy = execution_service.is_device_busy(d.udid)
        out.append(
            {
                "device_id": d.device_id,
                "label": d.label,
                "udid": d.udid,
                "adb_host": d.adb_host,
                "adb_port": d.adb_port,
                "appium_url": d.appium_url,
                "platform": d.platform,
                "enabled": d.enabled,
                "status": "busy" if busy else "free",
            }
        )
    return out


@router.post("")
async def register_device(request_body: RegisterDeviceRequest, org: Organization = Depends(get_org)):
    existing = await _device_repo.find_by_device_id(str(org.id), request_body.device_id)
    if existing:
        raise HTTPException(status_code=409, detail="device_id already exists for this organization")
    udid_taken = await _device_repo.find_by_udid(str(org.id), request_body.udid)
    if udid_taken:
        raise HTTPException(status_code=409, detail="udid already registered for this organization")

    device = await _device_repo.create(
        org_id=str(org.id),
        device_id=request_body.device_id.strip(),
        label=request_body.label.strip(),
        udid=request_body.udid.strip(),
        adb_host=request_body.adb_host.strip(),
        adb_port=request_body.adb_port,
        appium_url=request_body.appium_url.strip(),
        agent_url=request_body.agent_url,
        enabled=request_body.enabled,
    )
    return {
        "device_id": device.device_id,
        "label": device.label,
        "udid": device.udid,
        "adb_host": device.adb_host,
        "adb_port": device.adb_port,
        "appium_url": device.appium_url,
        "agent_url": device.agent_url,
        "platform": device.platform,
        "enabled": device.enabled,
        "created_at": device.created_at,
    }


@router.delete("/{device_id}")
async def delete_device(device_id: str, org: Organization = Depends(get_org)):
    ok = await _device_repo.delete(str(org.id), device_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Device not found")
    return {"ok": True}


@router.get("/{device_id}/health")
async def device_health(device_id: str, org: Organization = Depends(get_org)):
    device = await _device_repo.find_by_device_id(str(org.id), device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    def _probe_adb() -> Dict[str, Any]:
        try:
            client = AdbClient(host=device.adb_host, port=device.adb_port)
            devices = client.devices()
            serials = [d.serial for d in devices]
            return {
                "adb_reachable": True,
                "device_online": device.udid in serials,
                "serials_seen": serials,
            }
        except Exception:
            return {
                "adb_reachable": False,
                "device_online": False,
                "serials_seen": [],
            }

    adb_info = await asyncio.to_thread(_probe_adb)
    appium_reachable = await _probe_appium(device.appium_url)

    return {
        "device_id": device.device_id,
        "adb_reachable": adb_info["adb_reachable"],
        "appium_reachable": appium_reachable,
        "device_online": adb_info["device_online"],
        "serials_seen": adb_info["serials_seen"],
    }
