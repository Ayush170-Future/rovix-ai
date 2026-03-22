from datetime import datetime
from typing import List, Optional

from models.build import Build


class BuildRepository:
    async def create(
        self,
        *,
        org_id: str,
        game_id: str,
        platform: str,
        artifact_type: str,
        object_key: str,
        bucket_name: str,
        version_name: str = "",
        version_code: Optional[int] = None,
        build_number: str = "",
        channel: str = "qa",
        uploaded_by: str = "",
    ) -> Build:
        build = Build(
            org_id=org_id,
            game_id=game_id,
            platform=platform,
            artifact_type=artifact_type,
            object_key=object_key,
            bucket_name=bucket_name,
            version_name=version_name,
            version_code=version_code,
            build_number=build_number,
            channel=channel,
            uploaded_by=uploaded_by,
        )
        await build.insert()
        return build

    async def find_by_id(self, build_id: str) -> Optional[Build]:
        return await Build.get(build_id)

    async def find_by_game(
        self,
        game_id: str,
        *,
        platform: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Build]:
        query = Build.find(Build.game_id == game_id)
        if platform:
            query = query.find(Build.platform == platform)
        if status:
            query = query.find(Build.status == status)
        return await query.sort("-created_at").to_list()

    async def finalize(
        self,
        build: Build,
        *,
        file_size_bytes: Optional[int] = None,
        checksum_sha256: str = "",
        status: str = "ready",
        upload_error: str = "",
        android_app_package: Optional[str] = None,
        android_app_activity: Optional[str] = None,
    ) -> Build:
        build.file_size_bytes = file_size_bytes
        build.checksum_sha256 = checksum_sha256
        build.status = status
        build.upload_error = upload_error
        if android_app_package is not None:
            build.android_app_package = android_app_package or None
        if android_app_activity is not None:
            build.android_app_activity = android_app_activity or None
        build.updated_at = datetime.utcnow()
        await build.save()
        return build
