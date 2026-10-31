import uuid
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


class ScanBase(BaseModel):
    exam_id: uuid.UUID
    exam_template_id: uuid.UUID | None = None
    page_count: Optional[int] = None


class ScanCreate(ScanBase):
    pass


class ScanResponse(ScanBase):
    id: uuid.UUID
    uploader_user_id: uuid.UUID
    path: str
    status: str
    omr_scan_id: Optional[str] = None
    failure_code: Optional[str] = None
    failure_detail: Optional[str] = None
    batch_id: Optional[uuid.UUID] = None
    batch_index: Optional[int] = None
    model_config = ConfigDict(from_attributes=True) #allows for sqlalchemy dicts to be parsed

# 1. Frontend requests an upload session
class InitiateMultipartRequest(BaseModel):
    exam_id: uuid.UUID
    exam_template_id: uuid.UUID
    filename: str
    total_chunks: int
    page_count: Optional[int] = None

# 2. Backend returns URLs to Frontend
class ChunkUrlInfo(BaseModel):
    part_number: int
    url: str

class InitiateMultipartResponse(BaseModel):
    upload_id: str
    storage_path: str
    urls: List[ChunkUrlInfo]

# 3. Frontend finishes
class PartETag(BaseModel):
    PartNumber: int
    ETag: str  # Given by Garage after uploading each chunk

class CompleteMultipartRequest(BaseModel):
    upload_id: str
    storage_path: str
    exam_id: uuid.UUID
    exam_template_id: uuid.UUID
    parts: List[PartETag]
    page_count: Optional[int] = None


class ScanJobStatusResponse(BaseModel):
    """Live OMR progress for a scan's in-flight batch upload job."""

    progress: float
    finished: bool
    success: Optional[bool] = None
    # OMR's free-text status note (e.g. "rendering 4 pages"), so the frontend
    # can surface what the job is actually doing instead of just a percent.
    notes: str = ""
