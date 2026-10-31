import io
import os
import pytest
from unittest.mock import patch, MagicMock, ANY
from dependencies.storage_dep import get_storage_repo
from repositories.storage import StorageRepository
import uuid


def test_get_storage_repo_config_from_env(monkeypatch):
    monkeypatch.setenv("GARAGE_ENDPOINT_URL", "http://garage-container:3900")
    monkeypatch.delenv("GARAGE_PUBLIC_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("GARAGE_ACCESS_KEY_ID", "key-12345")
    monkeypatch.setenv("GARAGE_SECRET_ACCESS_KEY", "secret-67890")
    monkeypatch.setenv("GARAGE_REGION", "us-west-custom")
    monkeypatch.setenv("GARAGE_BUCKET_NAME", "production-scans")

    with patch("boto3.client") as mock_boto_client:
        repo = get_storage_repo()

        mock_boto_client.assert_called_once_with(
            "s3",
            endpoint_url="http://garage-container:3900",
            aws_access_key_id="key-12345",
            aws_secret_access_key="secret-67890",
            region_name="us-west-custom",
            config=ANY,
        )
        assert repo.bucket == "production-scans"
        assert repo.presign_client is repo.s3


def test_get_storage_repo_uses_public_endpoint_for_presigning(monkeypatch):
    monkeypatch.setenv("GARAGE_ENDPOINT_URL", "http://garage-store:3900")
    monkeypatch.setenv("GARAGE_PUBLIC_ENDPOINT_URL", "http://localhost:3900")
    monkeypatch.setenv("GARAGE_ACCESS_KEY_ID", "key-12345")
    monkeypatch.setenv("GARAGE_SECRET_ACCESS_KEY", "secret-67890")
    monkeypatch.setenv("GARAGE_REGION", "garage")
    monkeypatch.setenv("GARAGE_BUCKET_NAME", "production-scans")

    with patch("boto3.client", side_effect=[MagicMock(), MagicMock()]) as mock_boto_client:
        repo = get_storage_repo()

        assert mock_boto_client.call_count == 2
        mock_boto_client.assert_any_call(
            "s3",
            endpoint_url="http://garage-store:3900",
            aws_access_key_id="key-12345",
            aws_secret_access_key="secret-67890",
            region_name="garage",
            config=ANY,
        )
        mock_boto_client.assert_any_call(
            "s3",
            endpoint_url="http://localhost:3900",
            aws_access_key_id="key-12345",
            aws_secret_access_key="secret-67890",
            region_name="garage",
            config=ANY,
        )
        assert repo.presign_client is not repo.s3


def test_storage_repository_implements_upload_fileobj():
    mock_s3 = MagicMock()
    repo = StorageRepository(s3_client=mock_s3, bucket="test-bucket")
    
    assert hasattr(repo, "upload_fileobj")
    assert callable(getattr(repo, "upload_fileobj"))


def test_storage_repository_upload_fileobj_behavior():
    mock_s3 = MagicMock()
    target_bucket = "test-scan-bucket"
    repo = StorageRepository(s3_client=mock_s3, bucket=target_bucket)
    
    dummy_file = io.BytesIO(b"mock binary test string payload")
    filename = "exams/scan_001.pdf"

    result = repo.upload_fileobj(dummy_file, filename)

    mock_s3.upload_fileobj.assert_called_once_with(
        Fileobj=dummy_file,
        Bucket=target_bucket,
        Key=filename
    )
    assert result == {
        "status": "uploaded",
        "filename": filename
    }

#verify actual system works
@pytest.mark.asyncio
async def test_storage_real_integration_upload():
    repo = get_storage_repo()
    
    filename = f"integration_tests/test_{uuid.uuid4().hex}.txt"
    payload = b"Live integration test payload verifying network transport works."
    file_stream = io.BytesIO(payload)
    
    try:
        upload_res = repo.upload_fileobj(file_stream, filename)
        assert upload_res["status"] == "uploaded"

        downloaded_bytes = repo.download_file(filename)
        assert downloaded_bytes == payload
        
    finally:
        try:
            repo.delete_file(filename)
        except Exception:
            pass