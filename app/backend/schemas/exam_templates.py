from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class QuestionConfigItem(BaseModel):
    choices: list[str]

    @field_validator("choices")
    @classmethod
    def validate_choices_length(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError("A question must have at least 2 choice options.")
        return v


SectionType = Literal["multiple_choice", "true_false"]


class TemplateSection(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    type: SectionType = "multiple_choice"
    question_ids: list[str] = Field(min_length=1)

    @field_validator("id", "name")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Section id and name cannot be blank.")
        return value

    @field_validator("question_ids")
    @classmethod
    def validate_question_ids(cls, value: list[str]) -> list[str]:
        if any(not question_id.strip() for question_id in value):
            raise ValueError("Section question ids cannot be blank.")
        if len(value) != len(set(value)):
            raise ValueError("A question cannot appear more than once in a section.")
        return value


def default_template_sections(
    question_config: dict[str, QuestionConfigItem] | dict[str, dict],
) -> list[TemplateSection]:
    question_ids = sorted(
        question_config,
        key=lambda question_id: (
            0,
            int(question_id),
        ) if question_id.isdigit() else (1, question_id),
    )
    return [
        TemplateSection(
            id="section-1",
            name="Section 1",
            question_ids=question_ids,
        )
    ]


def validate_template_sections(
    question_config: dict[str, QuestionConfigItem] | dict[str, dict],
    sections: list[TemplateSection],
) -> None:
    if not sections:
        raise ValueError("A template must have at least one section.")

    section_ids = [section.id for section in sections]
    if len(section_ids) != len(set(section_ids)):
        raise ValueError("Section ids must be unique within a template.")

    normalized_names = [section.name.casefold() for section in sections]
    if len(normalized_names) != len(set(normalized_names)):
        raise ValueError("Section names must be unique within a template.")

    assigned_question_ids = [
        question_id
        for section in sections
        for question_id in section.question_ids
    ]
    if len(assigned_question_ids) != len(set(assigned_question_ids)):
        raise ValueError("A question cannot belong to more than one section.")

    configured_question_ids = set(question_config)
    assigned = set(assigned_question_ids)
    missing = sorted(configured_question_ids - assigned)
    unknown = sorted(assigned - configured_question_ids)
    if missing or unknown:
        problems = []
        if missing:
            problems.append(f"unassigned questions: {', '.join(missing)}")
        if unknown:
            problems.append(f"unknown questions: {', '.join(unknown)}")
        raise ValueError("Invalid section question membership (" + "; ".join(problems) + ").")

    for section in sections:
        if section.type != "true_false":
            continue
        for question_id in section.question_ids:
            config = question_config[question_id]
            choices = (
                config.choices
                if isinstance(config, QuestionConfigItem)
                else config["choices"]
            )
            if choices != ["T", "F"]:
                raise ValueError(
                    f"True/False section questions must use T and F (question {question_id})."
                )


class CreateExamTemplateRequest(BaseModel):
    name: str
    question_config: dict[str, QuestionConfigItem] = Field(min_length=1, max_length=200)
    version: int | None = None
    n_versions: int = Field(default=4, ge=1, le=26)
    sections: list[TemplateSection] | None = None

    @model_validator(mode="after")
    def validate_sections(self) -> "CreateExamTemplateRequest":
        if self.sections is None:
            self.sections = default_template_sections(self.question_config)
        validate_template_sections(self.question_config, self.sections)
        return self


class UpdateExamTemplateRequest(BaseModel):
    name: str | None = None
    question_config: dict[str, QuestionConfigItem] | None = Field(
        default=None, min_length=1, max_length=200
    )
    n_versions: int | None = Field(default=None, ge=1, le=26)
    sections: list[TemplateSection] | None = None


class ExamTemplateResponse(BaseModel):
    id: UUID
    name: str
    created_by: UUID | None = None
    question_config: dict[str, QuestionConfigItem]
    total_questions: int
    version: int
    n_versions: int
    blueprint: str | None = None
    version_from_q1: bool = False
    omr_template_id: UUID | None = None
    generated_pdf_path: str | None = None
    archived_at: datetime | None = None
    sections: list[TemplateSection]

    model_config = {"from_attributes": True}


class ExamTemplateUsageExam(BaseModel):
    id: UUID
    name: str
    course_id: UUID
    answer_key_count: int = 0
    scan_count: int = 0


class ExamTemplateUsageResponse(BaseModel):
    template_id: UUID
    exam_count: int
    answer_key_count: int
    scan_count: int
    exams: list[ExamTemplateUsageExam]

    @property
    def has_usage(self) -> bool:
        return (
            self.exam_count > 0
            or self.answer_key_count > 0
            or self.scan_count > 0
        )
