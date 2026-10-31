from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


UBC_SCANNED_IMAGE_RETENTION_MONTHS = 12
UBC_EXAM_RECORD_RETENTION_MONTHS = 12
MAX_RETENTION_MONTHS = 72


class RetentionPolicyUpsertRequest(BaseModel):
    scanned_image_retention_months: int = Field(
        default=UBC_SCANNED_IMAGE_RETENTION_MONTHS,
        ge=UBC_SCANNED_IMAGE_RETENTION_MONTHS,
        le=MAX_RETENTION_MONTHS,
    )
    exam_record_retention_months: int = Field(
        default=UBC_EXAM_RECORD_RETENTION_MONTHS,
        ge=UBC_EXAM_RECORD_RETENTION_MONTHS,
        le=MAX_RETENTION_MONTHS,
    )
    retain_anonymized_analytics: bool = True


class RetentionPolicyResponse(BaseModel):
    id: UUID
    owner_user_id: UUID
    scanned_image_retention_months: int
    exam_record_retention_months: int
    retain_anonymized_analytics: bool
    source: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RecommendedRetentionPolicy(BaseModel):
    scanned_image_retention_months: int = UBC_SCANNED_IMAGE_RETENTION_MONTHS
    exam_record_retention_months: int = UBC_EXAM_RECORD_RETENTION_MONTHS
    retain_anonymized_analytics: bool = True
    maximum_retention_months: int = MAX_RETENTION_MONTHS
    basis: str = "UBC Records Schedules TL7300-15 and TL7100-25"
    source_urls: list[str] = [
        "https://recordsmanagement.ubc.ca/schedules/tl7300-teaching-and-learning-student-work-examinations-theses/",
        "https://recordsmanagement.ubc.ca/schedules/tl7100-teaching-and-learning-course-management/",
        "https://okanagan.calendar.ubc.ca/campus-wide-policies-and-regulations/viewing-marked-work-and-examinations/policy",
    ]


class RetentionPolicyStatusResponse(BaseModel):
    configured: bool
    policy: RetentionPolicyResponse | None
    recommended: RecommendedRetentionPolicy = Field(
        default_factory=RecommendedRetentionPolicy
    )
