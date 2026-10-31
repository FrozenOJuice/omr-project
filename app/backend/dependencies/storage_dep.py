import os

import boto3
from botocore.config import Config

from repositories.storage import StorageRepository

# Garage's S3 API only recognizes bucket names in the request path, not in a
# virtual-hosted-style Host header, so boto3's default "auto" addressing
# style (which prefers virtual-hosted style for DNS-valid bucket names) must
# be overridden here.
_PATH_STYLE_CONFIG = Config(s3={"addressing_style": "path"})


def get_storage_repo() -> StorageRepository:
    endpoint_url = os.getenv("GARAGE_ENDPOINT_URL", "http://localhost:3900")
    access_key_id = os.getenv("GARAGE_ACCESS_KEY_ID")
    secret_access_key = os.getenv("GARAGE_SECRET_ACCESS_KEY")
    region_name = os.getenv("GARAGE_REGION", "garage")

    s3_client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region_name,
        config=_PATH_STYLE_CONFIG,
    )

    # Presigned URLs are followed directly by the browser, so they must use an
    # endpoint the browser can resolve, which may differ from the internal
    # endpoint backend services use to reach Garage (e.g. a Docker service name).
    public_endpoint_url = os.getenv("GARAGE_PUBLIC_ENDPOINT_URL", endpoint_url)
    if public_endpoint_url == endpoint_url:
        presign_client = s3_client
    else:
        presign_client = boto3.client(
            "s3",
            endpoint_url=public_endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region_name,
            config=_PATH_STYLE_CONFIG,
        )

    bucket_name = os.getenv("GARAGE_BUCKET_NAME", "capstone-storage")
    return StorageRepository(s3_client=s3_client, bucket=bucket_name, presign_client=presign_client)
