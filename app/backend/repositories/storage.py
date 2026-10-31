import os
import logging

logger = logging.getLogger(__name__)

class StorageRepository:
    def __init__(self, s3_client, bucket: str | None = None, presign_client=None):
        self.s3 = s3_client
        self.presign_client = presign_client or s3_client
        self.bucket = bucket or os.getenv(
            "GARAGE_BUCKET_NAME",
            "capstone-storage-test",
        )

    def upload_file(self, file_bytes: bytes, filename: str) -> dict:
        self.s3.put_object(Bucket=self.bucket, Key=filename, Body=file_bytes)
        return {"status": "uploaded", "filename": filename}

    def upload_fileobj(self, fileobj, filename: str) -> dict:
        """Streams a file-like object directly to Garage without loading it all into memory. For large files"""
        self.s3.upload_fileobj(Fileobj=fileobj, Bucket=self.bucket, Key=filename)
        return {"status": "uploaded", "filename": filename}

    def delete_file(self, filename: str) -> dict:
        self.s3.delete_object(Bucket=self.bucket, Key=filename)
        return {"status": "deleted", "filename": filename}

    def list_files(self) -> list:
        response = self.s3.list_objects_v2(Bucket=self.bucket)
        if "Contents" in response:
            return [
                {"filename": obj["Key"], "size": obj["Size"]}
                for obj in response["Contents"]
            ]
        return []

    def download_file(self, filename: str) -> bytes:
        obj = self.s3.get_object(Bucket=self.bucket, Key=filename)
        return obj["Body"].read()

    def open_file(self, filename: str):
        """Return the object body's streaming reader without buffering it."""
        return self.s3.get_object(Bucket=self.bucket, Key=filename)["Body"]

    def configure_cors(self, allowed_origin: str) -> None:
        """Allows the browser to follow presigned URLs directly (e.g. to render a PDF), since
        those requests go straight to Garage rather than through the backend."""
        self.s3.put_bucket_cors(
            Bucket=self.bucket,
            CORSConfiguration={
                "CORSRules": [
                    {
                        "AllowedOrigins": [allowed_origin],
                        "AllowedMethods": ["GET", "PUT"],
                        "AllowedHeaders": ["*"],
                        "ExposeHeaders": ["ETag"],
                    }
                ]
            },
        )

    def get_presigned_url(self, filename: str, expires_in: int = 3600) -> str:
        return self.presign_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": filename},
            ExpiresIn=expires_in,
        )

    # Chunked upload functions
    def initiate_multipart_upload(self, filename: str) -> str:
        response = self.s3.create_multipart_upload(Bucket=self.bucket, Key=filename)
        return response["UploadId"]

    def generate_presigned_part_url(self, filename: str, upload_id: str, part_number: int) -> str:
        return self.presign_client.generate_presigned_url(
            ClientMethod="upload_part",
            Params={
                "Bucket": self.bucket,
                "Key": filename,
                "UploadId": upload_id,
                "PartNumber": part_number,
            },
            ExpiresIn=7200,
        )

    def complete_multipart_upload(self, filename: str, upload_id: str, parts: list) -> None:
        self.s3.complete_multipart_upload(
            Bucket=self.bucket,
            Key=filename,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts}
        )

    def abort_multipart_upload(self, filename: str, upload_id: str) -> None:
        try:
            self.s3.abort_multipart_upload(Bucket=self.bucket, Key=filename, UploadId=upload_id)
        except Exception:
            pass

    def download_to_file(self, filename: str, dest_path: str) -> None:
        """Streams to local file to avoid memory costs"""
        self.s3.download_file(Bucket=self.bucket, Key=filename, Filename=dest_path)

    def delete_directory(self, prefix: str) -> dict:
        paginator = self.s3.get_paginator("list_objects_v2")
        deleted = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            contents = page.get("Contents", [])
            if not contents:
                continue
            objects = [{"Key": obj["Key"]} for obj in contents]

            response = self.s3.delete_objects(Bucket=self.bucket, Delete={"Objects": objects})
            errors = response.get("Errors", [])
            if errors:
                for error in errors:
                    key = error.get("Key", "Unknown Key")
                    code = error.get("Code", "Unknown Code")
                    message = error.get("Message", "No message provided")
                    
                    logger.error(f"Failed to delete object from {self.bucket}. Key: {key}, Code: {code}, Message: {message}")

            actually_deleted = [d["Key"] for d in response.get("Deleted", [])]
            deleted.extend(actually_deleted)

        return {"status": "deleted", "prefix": prefix, "deleted_count": len(deleted)}
