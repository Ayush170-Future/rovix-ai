from datetime import datetime
from typing import List, Optional

from models.device import Device


class DeviceRepository:
    async def find_all_enabled(self, org_id: str) -> List[Device]:
        return await Device.find(Device.org_id == org_id, Device.enabled == True).to_list()

    async def find_by_device_id(self, org_id: str, device_id: str) -> Optional[Device]:
        return await Device.find_one(Device.org_id == org_id, Device.device_id == device_id)

    async def find_by_udid(self, org_id: str, udid: str) -> Optional[Device]:
        return await Device.find_one(Device.org_id == org_id, Device.udid == udid)

    async def create(
        self,
        *,
        org_id: str,
        device_id: str,
        label: str,
        udid: str,
        adb_host: str,
        adb_port: int = 5037,
        appium_url: str,
        enabled: bool = True,
    ) -> Device:
        device = Device(
            org_id=org_id,
            device_id=device_id,
            label=label,
            udid=udid,
            adb_host=adb_host,
            adb_port=adb_port,
            appium_url=appium_url,
            enabled=enabled,
            created_at=datetime.utcnow(),
        )
        await device.insert()
        return device

    async def delete(self, org_id: str, device_id: str) -> bool:
        d = await self.find_by_device_id(org_id, device_id)
        if not d:
            return False
        await d.delete()
        return True
