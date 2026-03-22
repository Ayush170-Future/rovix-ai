import os
from datetime import datetime, timedelta
from uuid import uuid4
from typing import Literal, Optional

import google.auth
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from google.cloud import storage
from google.api_core.exceptions import GoogleAPIError

from dependencies import get_org
from models.organization import Organization
from repositories.game_repository import GameRepository
from repositories.build_repository import BuildRepository

router = APIRouter(tags=["Builds"])
_game_repo = GameRepository()
_build_repo = BuildRepository()

DEFAULT_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "rovix_ai_bucket")
DEFAULT_BUILDS_PREFIX = os.getenv("GCS_BUILDS_PREFIX", "game_builds")
SIGNED_URL_TTL_SECONDS = int(os.getenv("GCS_SIGNED_URL_TTL_SECONDS", "900"))
# When set, signed URLs use IAM SignBlob (caller creds must have iam.serviceAccounts.signBlob on this SA).
GCS_SIGNING_SERVICE_ACCOUNT = os.getenv("GCS_SIGNING_SERVICE_ACCOUNT", "").strip()
_GCS_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)
_storage_client = storage.Client()


class CreateUploadUrlRequest(BaseModel):
    platform: Literal["android", "ios", "unity"]
    artifact_type: Literal["apk", "aab", "ipa", "zip"] = "apk"
    version_name: str = ""
    version_code: Optional[int] = None
    build_number: str = ""
    channel: Literal["dev", "qa", "staging", "prod"] = "qa"
    file_name: str = "build"
    content_type: Optional[str] = None


class FinalizeBuildRequest(BaseModel):
    file_size_bytes: Optional[int] = None
    checksum_sha256: str = ""
    status: Literal["ready", "failed"] = "ready"
    upload_error: str = ""
    android_app_package: Optional[str] = None
    android_app_activity: Optional[str] = None


@router.post("/api/games/{game_id}/builds/upload-url")
async def create_build_upload_url(
    game_id: str,
    request: CreateUploadUrlRequest,
    org: Organization = Depends(get_org),
):
    game = await _game_repo.find_by_id(game_id)
    if not game or game.org_id != str(org.id):
        raise HTTPException(status_code=404, detail="Game not found")

    filename = request.file_name.strip() or "build"
    safe_filename = filename.replace("/", "_")
    object_key = (
        f"{DEFAULT_BUILDS_PREFIX}/{str(org.id)}/{game_id}/{request.platform}/"
        f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid4().hex}_{safe_filename}"
    )
    build = await _build_repo.create(
        org_id=str(org.id),
        game_id=game_id,
        platform=request.platform,
        artifact_type=request.artifact_type,
        object_key=object_key,
        bucket_name=DEFAULT_BUCKET_NAME,
        version_name=request.version_name,
        version_code=request.version_code,
        build_number=request.build_number,
        channel=request.channel,
        uploaded_by=org.slug,
    )

    content_type = request.content_type or _default_content_type(request.artifact_type)
    upload_url = _generate_signed_upload_url(
        bucket_name=DEFAULT_BUCKET_NAME,
        object_key=build.object_key,
        content_type=content_type,
        ttl_seconds=SIGNED_URL_TTL_SECONDS,
    )
    return {
        "build": _build_response(build),
        "upload": {
            "method": "PUT",
            "url": upload_url,
            "headers": {"Content-Type": content_type},
            "expires_in_seconds": SIGNED_URL_TTL_SECONDS,
        },
    }


@router.post("/api/builds/{build_id}/finalize")
async def finalize_build(
    build_id: str,
    request: FinalizeBuildRequest,
    org: Organization = Depends(get_org),
):
    build = await _build_repo.find_by_id(build_id)
    if not build or build.org_id != str(org.id):
        raise HTTPException(status_code=404, detail="Build not found")

    blob = _get_blob_or_404(build.bucket_name, build.object_key)
    object_exists = blob.exists(_storage_client)
    if request.status == "ready" and not object_exists:
        raise HTTPException(status_code=400, detail="Upload not found in storage")

    resolved_file_size = request.file_size_bytes
    if object_exists:
        blob.reload(client=_storage_client)
        if blob.size is not None:
            resolved_file_size = int(blob.size)

    build = await _build_repo.finalize(
        build,
        file_size_bytes=resolved_file_size,
        checksum_sha256=request.checksum_sha256,
        status=request.status,
        upload_error=request.upload_error,
        android_app_package=request.android_app_package,
        android_app_activity=request.android_app_activity,
    )
    return _build_response(build)


@router.get("/api/games/{game_id}/builds")
async def list_builds(
    game_id: str,
    platform: Optional[Literal["android", "ios", "unity"]] = None,
    status: Optional[Literal["uploading", "ready", "failed", "archived"]] = None,
    org: Organization = Depends(get_org),
):
    game = await _game_repo.find_by_id(game_id)
    if not game or game.org_id != str(org.id):
        raise HTTPException(status_code=404, detail="Game not found")

    builds = await _build_repo.find_by_game(
        game_id,
        platform=platform,
        status=status,
    )
    return [_build_response(build) for build in builds]


@router.get("/api/builds/{build_id}")
async def get_build(build_id: str, org: Organization = Depends(get_org)):
    build = await _build_repo.find_by_id(build_id)
    if not build or build.org_id != str(org.id):
        raise HTTPException(status_code=404, detail="Build not found")
    return _build_response(build)


def _build_response(build) -> dict:
    return {
        "id": str(build.id),
        "org_id": build.org_id,
        "game_id": build.game_id,
        "platform": build.platform,
        "artifact_type": build.artifact_type,
        "object_key": build.object_key,
        "bucket_name": build.bucket_name,
        "version_name": build.version_name,
        "version_code": build.version_code,
        "build_number": build.build_number,
        "channel": build.channel,
        "file_size_bytes": build.file_size_bytes,
        "checksum_sha256": build.checksum_sha256,
        "status": build.status,
        "upload_error": build.upload_error,
        "uploaded_by": build.uploaded_by,
        "android_app_package": build.android_app_package,
        "android_app_activity": build.android_app_activity,
        "created_at": build.created_at,
        "updated_at": build.updated_at,
    }


def _default_content_type(artifact_type: str) -> str:
    mapping = {
        "apk": "application/vnd.android.package-archive",
        "aab": "application/octet-stream",
        "ipa": "application/octet-stream",
        "zip": "application/zip",
    }
    return mapping.get(artifact_type, "application/octet-stream")


def _generate_signed_upload_url(
    *,
    bucket_name: str,
    object_key: str,
    content_type: str,
    ttl_seconds: int,
) -> str:
    """
    Signed URL generation:
    - If GCS_SIGNING_SERVICE_ACCOUNT is set: IAM SignBlob path (caller token signs as that SA).
    - Else if ADC is a service account key JSON: local signing (private key).
    - Else: fail fast with configuration instructions.
    """
    try:
        credentials = _get_refreshed_credentials()
        has_sa_key = isinstance(credentials, service_account.Credentials)

        if not GCS_SIGNING_SERVICE_ACCOUNT and not has_sa_key:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Cannot sign GCS URLs: Application Default Credentials are not a service account "
                    "key file. Either set GOOGLE_APPLICATION_CREDENTIALS to a service account JSON key, "
                    "or set GCS_SIGNING_SERVICE_ACCOUNT to the service account email to sign as "
                    "(your user/runtime identity needs iam.serviceAccounts.signBlob on that SA)."
                ),
            )

        bucket = _storage_client.bucket(bucket_name)
        blob = bucket.blob(object_key)
        expiration = timedelta(seconds=ttl_seconds)
        kwargs = {
            "version": "v4",
            "expiration": expiration,
            "method": "PUT",
            "content_type": content_type,
            "credentials": credentials,
        }
        if GCS_SIGNING_SERVICE_ACCOUNT:
            # IAM Credentials API (signBlob) — no local private key required.
            kwargs["service_account_email"] = GCS_SIGNING_SERVICE_ACCOUNT
            kwargs["access_token"] = credentials.token
        return blob.generate_signed_url(**kwargs)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate signed URL: {exc}",
        ) from exc


def _get_refreshed_credentials():
    credentials, _ = google.auth.default(scopes=list(_GCS_SCOPES))
    credentials.refresh(Request())
    return credentials


def _get_blob_or_404(bucket_name: str, object_key: str):
    try:
        bucket = _storage_client.bucket(bucket_name)
        return bucket.blob(object_key)
    except GoogleAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Storage access error: {exc}") from exc
