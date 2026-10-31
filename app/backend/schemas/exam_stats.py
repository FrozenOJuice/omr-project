from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class AnswerChoiceStats(BaseModel):
    answer: str
    selected_count: int
    selected_percentage: float
    is_correct: bool
    high_group_percentage: float | None
    low_group_percentage: float | None
    effectiveness: Literal["correct", "effective", "weak", "not_selected", "blank"]


class QuestionStats(BaseModel):
    question_number: str
    graded_count: int
    correct_count: int
    correct_percentage: float
    incorrect_count: int
    incorrect_percentage: float
    average_score: float
    max_score: float
    selected_distribution: dict[str, int]
    answer_choices: list[AnswerChoiceStats]
    item_difficulty: float
    discrimination_index: float | None
    distractor_efficiency: float | None


class ExamVersionStats(BaseModel):
    exam_version: str | None
    graded_count: int
    mean_percentage: float | None
    average_item_difficulty: float | None
    average_discrimination_index: float | None
    average_distractor_efficiency: float | None
    difficult_question_count: int
    low_discrimination_question_count: int
    weak_distractor_question_count: int
    question_stats: list[QuestionStats]


class ScoreDistributionBucket(BaseModel):
    label: str
    lower_bound: int
    upper_bound: int
    count: int
    percentage: float


class ExamStatsResponse(BaseModel):
    exam_id: UUID
    graded_count: int
    mean_score: float | None
    standard_deviation_score: float | None
    median_score: float | None
    mode_scores: list[float]
    highest_score: float | None
    lowest_score: float | None
    mean_percentage: float | None
    standard_deviation_percentage: float | None
    min_percentage: float | None
    q1_percentage: float | None
    median_percentage: float | None
    q3_percentage: float | None
    max_percentage: float | None
    score_distribution: list[ScoreDistributionBucket]
    question_stats: list[QuestionStats]
    version_stats: list[ExamVersionStats]


# A trimmed, student-safe view of the class's score spread: just the
# five-number summary and a count, none of the per-question or per-student
# detail ExamStatsResponse carries.
class ExamScoreDistributionResponse(BaseModel):
    count: int
    min_percentage: float | None
    q1_percentage: float | None
    median_percentage: float | None
    q3_percentage: float | None
    max_percentage: float | None
