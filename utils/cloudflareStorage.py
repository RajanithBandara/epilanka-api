import os
import re
import uuid
from typing import Optional, Tuple

from botocore.exceptions import BotoCoreError, ClientError

from utils.r2_clients import r2_client, BUCKET_NAME, PUBLIC_BASE_URL


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_filename(filename: str) -> str:
    base = os.path.basename(filename or "").strip() or "report.pdf"
    cleaned = _SAFE_NAME_RE.sub("_", base).strip("._-")
    return cleaned or "report.pdf"


def _build_object_key(filename: str, *, prefix: str = "reports") -> str:
    safe = _sanitize_filename(filename)
    return f"{prefix}/{uuid.uuid4().hex}-{safe}"


def _public_url_for(object_key: str) -> str:
    base = (PUBLIC_BASE_URL or "").rstrip("/")
    if base:
        return f"{base}/{object_key}"
    account_id = os.getenv("R2_ACCOUNT_ID")
    if account_id:
        return f"https://pub-{account_id}.r2.dev/{object_key}"
    return f"r2://{BUCKET_NAME}/{object_key}"


def upload_file_to_cloudflare_r2(
    file_content: bytes,
    filename: str,
    content_type: str = "application/octet-stream",
) -> Optional[str]:
    """Upload a file to Cloudflare R2 and return its public URL."""
    url, _ = upload_file_to_cloudflare_r2_with_key(file_content, filename, content_type)
    return url


def upload_file_to_cloudflare_r2_with_key(
    file_content: bytes,
    filename: str,
    content_type: str = "application/octet-stream",
) -> Tuple[Optional[str], Optional[str]]:
    """Upload to R2 and return ``(public_url, object_key)``."""
    if not BUCKET_NAME:
        print("R2 bucket not configured (R2_BUCKET_NAME missing).")
        return None, None

    object_key = _build_object_key(filename)

    try:
        r2_client.put_object(
            Bucket=BUCKET_NAME,
            Key=object_key,
            Body=file_content,
            ContentType=content_type,
        )
    except (BotoCoreError, ClientError) as exc:
        print(f"R2 upload failed: {exc}")
        return None, None

    return _public_url_for(object_key), object_key


def delete_file_from_cloudflare_r2(key_or_url: str) -> bool:
    """Delete an object from R2. Accepts either an object key or its public URL."""
    if not BUCKET_NAME or not key_or_url:
        return False

    object_key = _object_key_from(key_or_url)
    if not object_key:
        return False

    try:
        r2_client.delete_object(Bucket=BUCKET_NAME, Key=object_key)
        return True
    except (BotoCoreError, ClientError) as exc:
        print(f"R2 delete failed: {exc}")
        return False


def _object_key_from(key_or_url: str) -> Optional[str]:
    """Extract the R2 object key from either a key string or a public URL."""
    if not key_or_url:
        return None
    if "://" not in key_or_url:
        return key_or_url.lstrip("/")

    base = (PUBLIC_BASE_URL or "").rstrip("/")
    if base and key_or_url.startswith(base + "/"):
        return key_or_url[len(base) + 1:]

    # Fallback: take everything after the host
    try:
        without_scheme = key_or_url.split("://", 1)[1]
        path = without_scheme.split("/", 1)[1] if "/" in without_scheme else ""
        if path.startswith(f"{BUCKET_NAME}/"):
            path = path[len(BUCKET_NAME) + 1:]
        return path or None
    except (IndexError, AttributeError):
        return None
