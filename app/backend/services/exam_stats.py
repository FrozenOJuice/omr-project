from collections import Counter, defaultdict
from math import ceil
from string import ascii_uppercase
from statistics import mean, median, multimode, pstdev
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from errors.exceptions import ForbiddenError, NotFoundError
from models.user import User, UserRole
from repositories.courses import get_by_id as get_course_by_id
from repositories.exam_grades import student_has_grade_for_exam
from repositories.exam_stats import list_exam_grade_rows
from repositories.exam_templates import get_exam_template_by_id
from repositories.exams import get_exam_by_id
from repositories.users import get_by_id as get_user_by_id
from schemas.exam_stats import (
    AnswerChoiceStats,
    ExamScoreDistributionResponse,
    ExamStatsResponse,
    ExamVersionStats,
    QuestionStats,
    ScoreDistributionBucket,
)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _question_sort_key(question_number: str) -> tuple[int, int | str]:
    return (0, int(question_number)) if question_number.isdigit() else (1, question_number)


def _discrimination_groups(
    attempts: list[dict],
) -> tuple[list[dict], list[dict]] | None:
    """Return non-overlapping upper/lower 27% groups for item analysis.

    Four graded attempts is the minimum that can form two meaningful,
    non-overlapping groups. Smaller samples report the index as unavailable.
    """
    ranked = sorted(
        (attempt for attempt in attempts if attempt["overall_percentage"] is not None),
        key=lambda attempt: attempt["overall_percentage"],
        reverse=True,
    )
    if len(ranked) < 4:
        return None
    group_size = min(ceil(len(ranked) * 0.27), len(ranked) // 2)
    return ranked[:group_size], ranked[-group_size:]


def _selected_answers(result: dict) -> list[str]:
    return [str(answer) for answer in (result.get("student_answers") or [])]


def _group_selection_percentage(group: list[dict], answer: str) -> float:
    if not group:
        return 0.0
    selected = sum(answer in _selected_answers(attempt["result"]) for attempt in group)
    return _round((selected / len(group)) * 100) or 0.0


def _answer_choice_stats(
    *,
    data: dict,
    configured_choices: list[str],
    groups: tuple[list[dict], list[dict]] | None,
) -> tuple[list[AnswerChoiceStats], float | None]:
    graded_count = data["graded_count"]
    correct_answers = data["correct_answers"]
    all_answers = set(configured_choices) | set(correct_answers) | set(data["choice_counts"])
    all_answers.discard("blank")

    high_group, low_group = groups or ([], [])
    choices: list[AnswerChoiceStats] = []
    effective_distractors = 0
    distractor_count = 0

    for answer in sorted(all_answers):
        selected_count = data["choice_counts"].get(answer, 0)
        selected_percentage = _round((selected_count / graded_count) * 100) or 0.0
        is_correct = answer in correct_answers
        high_percentage = _group_selection_percentage(high_group, answer) if groups else None
        low_percentage = _group_selection_percentage(low_group, answer) if groups else None

        if is_correct:
            effectiveness = "correct"
        else:
            distractor_count += 1
            if selected_count == 0:
                effectiveness = "not_selected"
            elif selected_percentage < 5:
                effectiveness = "weak"
            elif groups and (low_percentage or 0.0) <= (high_percentage or 0.0):
                effectiveness = "weak"
            else:
                effectiveness = "effective"
                effective_distractors += 1

        choices.append(
            AnswerChoiceStats(
                answer=answer,
                selected_count=selected_count,
                selected_percentage=selected_percentage,
                is_correct=is_correct,
                high_group_percentage=high_percentage,
                low_group_percentage=low_percentage,
                effectiveness=effectiveness,
            )
        )

    blank_count = data["choice_counts"].get("blank", 0)
    if blank_count:
        choices.append(
            AnswerChoiceStats(
                answer="blank",
                selected_count=blank_count,
                selected_percentage=_round((blank_count / graded_count) * 100) or 0.0,
                is_correct=False,
                high_group_percentage=None,
                low_group_percentage=None,
                effectiveness="blank",
            )
        )

    efficiency = (
        _round(effective_distractors / distractor_count)
        if distractor_count
        else None
    )
    return choices, efficiency


def _score_percentage(total_score: float, max_score: float) -> float | None:
    resolved_max_score = float(max_score)
    if resolved_max_score <= 0:
        return None
    return (float(total_score) / resolved_max_score) * 100


def _build_question_stats(
    rows: list,
    configured_choices: dict[str, list[str]],
) -> list[QuestionStats]:
    per_question = defaultdict(
        lambda: {
            "graded_count": 0,
            "correct_count": 0,
            "scores": [],
            "max_score": 0.0,
            "selected_distribution": Counter(),
            "choice_counts": Counter(),
            "correct_answers": set(),
            "attempts": [],
        }
    )

    for total_score, max_score, question_results, _exam_version in rows:
        overall_percentage = _score_percentage(total_score, max_score)
        for question_number, result in (question_results or {}).items():
            bucket = per_question[str(question_number)]
            bucket["graded_count"] += 1
            bucket["correct_count"] += 1 if result.get("correct") else 0
            bucket["scores"].append(float(result.get("score", 0.0)))
            bucket["max_score"] = max(
                bucket["max_score"], float(result.get("max_score", 0.0))
            )
            bucket["correct_answers"].update(
                str(answer) for answer in (result.get("correct_answers") or [])
            )
            bucket["attempts"].append(
                {"overall_percentage": overall_percentage, "result": result}
            )

            selected = _selected_answers(result)
            label = ",".join(selected) if selected else "blank"
            bucket["selected_distribution"][label] += 1
            if selected:
                bucket["choice_counts"].update(selected)
            else:
                bucket["choice_counts"]["blank"] += 1

    question_stats: list[QuestionStats] = []
    for question_number, data in per_question.items():
        graded_count = data["graded_count"]
        groups = _discrimination_groups(data["attempts"])
        if groups:
            high_group, low_group = groups
            high_correct = sum(
                bool(attempt["result"].get("correct")) for attempt in high_group
            )
            low_correct = sum(
                bool(attempt["result"].get("correct")) for attempt in low_group
            )
            discrimination_index = _round(
                (high_correct / len(high_group)) - (low_correct / len(low_group))
            )
        else:
            discrimination_index = None

        answer_choices, distractor_efficiency = _answer_choice_stats(
            data=data,
            configured_choices=configured_choices.get(question_number, []),
            groups=groups,
        )
        correct_percentage = (
            _round((data["correct_count"] / graded_count) * 100) or 0.0
        )
        incorrect_count = graded_count - data["correct_count"]
        question_stats.append(
            QuestionStats(
                question_number=question_number,
                graded_count=graded_count,
                correct_count=data["correct_count"],
                correct_percentage=correct_percentage,
                incorrect_count=incorrect_count,
                incorrect_percentage=(
                    _round((incorrect_count / graded_count) * 100) or 0.0
                ),
                average_score=_round(mean(data["scores"])) or 0.0,
                max_score=data["max_score"],
                selected_distribution=dict(data["selected_distribution"]),
                answer_choices=answer_choices,
                item_difficulty=(
                    _round(data["correct_count"] / graded_count) or 0.0
                ),
                discrimination_index=discrimination_index,
                distractor_efficiency=distractor_efficiency,
            )
        )

    question_stats.sort(key=lambda question: _question_sort_key(question.question_number))
    return question_stats


def _average_metric(values: list[float]) -> float | None:
    return _round(mean(values)) if values else None


def _build_score_distribution(percentages: list[float]) -> list[ScoreDistributionBucket]:
    if not percentages:
        return []

    counts = [0] * 10
    for percentage in percentages:
        bucket_index = min(max(int(percentage // 10), 0), 9)
        counts[bucket_index] += 1

    total = len(percentages)
    return [
        ScoreDistributionBucket(
            label=f"{index * 10}-{100 if index == 9 else index * 10 + 9}%",
            lower_bound=index * 10,
            upper_bound=100 if index == 9 else index * 10 + 9,
            count=count,
            percentage=_round((count / total) * 100) or 0.0,
        )
        for index, count in enumerate(counts)
    ]


def _build_version_stats(
    rows: list,
    configured_choices: dict[str, list[str]],
    configured_versions: list[str | None],
) -> list[ExamVersionStats]:
    rows_by_version: dict[str | None, list] = defaultdict(list)
    for row in rows:
        rows_by_version[row[3]].append(row)

    versions = set(configured_versions) | set(rows_by_version)
    version_stats: list[ExamVersionStats] = []
    for exam_version in sorted(
        versions,
        key=lambda version: (version is not None, version or ""),
    ):
        version_rows = rows_by_version.get(exam_version, [])
        questions = _build_question_stats(version_rows, configured_choices)
        percentages = [
            percentage
            for total_score, max_score, _question_results, _version in version_rows
            if (percentage := _score_percentage(total_score, max_score)) is not None
        ]
        discrimination_values = [
            question.discrimination_index
            for question in questions
            if question.discrimination_index is not None
        ]
        distractor_values = [
            question.distractor_efficiency
            for question in questions
            if question.distractor_efficiency is not None
        ]
        version_stats.append(
            ExamVersionStats(
                exam_version=exam_version,
                graded_count=len(version_rows),
                mean_percentage=_average_metric(percentages),
                average_item_difficulty=_average_metric(
                    [question.item_difficulty for question in questions]
                ),
                average_discrimination_index=_average_metric(discrimination_values),
                average_distractor_efficiency=_average_metric(distractor_values),
                difficult_question_count=sum(
                    question.item_difficulty < 0.3 for question in questions
                ),
                low_discrimination_question_count=sum(
                    question.discrimination_index is not None
                    and question.discrimination_index < 0.2
                    for question in questions
                ),
                weak_distractor_question_count=sum(
                    question.distractor_efficiency is not None
                    and question.distractor_efficiency < 0.5
                    for question in questions
                ),
                question_stats=questions,
            )
        )
    return version_stats


def _quantile(sorted_values: list[float], q: float) -> float:
    pos = (len(sorted_values) - 1) * q
    base = int(pos)
    rest = pos - base
    value = (
        sorted_values[base] + rest * (sorted_values[base + 1] - sorted_values[base])
        if base + 1 < len(sorted_values)
        else sorted_values[base]
    )
    return round(value, 1)


async def get_exam_stats(
    db: AsyncSession,
    exam_id: UUID,
    requesting_user_id: UUID,
) -> ExamStatsResponse:
    exam = await get_exam_by_id(db, exam_id)
    if not exam:
        raise NotFoundError("Exam not found", code="exam_not_found")

    course = await get_course_by_id(db, exam.course_id)
    user = await get_user_by_id(db, requesting_user_id)

    if not course:
        raise NotFoundError("Course not found", code="course_not_found")
    if user.role != "admin" and course.created_by != requesting_user_id:
        raise ForbiddenError(
            "You do not have permission to view this exam's stats",
            code="exam_stats_forbidden",
        )

    configured_choices: dict[str, list[str]] = {}
    configured_versions: list[str | None] = [None]
    exam_template_id = getattr(exam, "exam_template_id", None)
    if exam_template_id:
        template = await get_exam_template_by_id(db, exam_template_id)
        if template:
            configured_choices = {
                str(question_number): [str(choice) for choice in config.get("choices", [])]
                for question_number, config in (template.question_config or {}).items()
            }
            version_count = getattr(template, "n_versions", 1)
            if version_count > 1:
                configured_versions = list(ascii_uppercase[:version_count])

    rows = await list_exam_grade_rows(db, exam_id)
    raw_scores = [float(total_score) for total_score, _max, _questions, _version in rows]
    percentages = [
        percentage
        for total_score, max_score, _questions, _version in rows
        if (percentage := _score_percentage(total_score, max_score)) is not None
    ]
    sorted_percentages = sorted(percentages)
    question_stats = _build_question_stats(rows, configured_choices)
    version_stats = _build_version_stats(
        rows,
        configured_choices,
        configured_versions,
    )

    return ExamStatsResponse(
        exam_id=exam_id,
        graded_count=len(rows),
        mean_score=_round(mean(raw_scores)) if raw_scores else None,
        standard_deviation_score=_round(pstdev(raw_scores)) if raw_scores else None,
        median_score=_round(median(raw_scores)) if raw_scores else None,
        mode_scores=[_round(v) for v in multimode(raw_scores)] if raw_scores else [],
        highest_score=_round(max(raw_scores)) if raw_scores else None,
        lowest_score=_round(min(raw_scores)) if raw_scores else None,
        mean_percentage=_round(mean(percentages)) if percentages else None,
        standard_deviation_percentage=_round(pstdev(percentages)) if percentages else None,
        min_percentage=_round(sorted_percentages[0]) if sorted_percentages else None,
        q1_percentage=_quantile(sorted_percentages, 0.25) if sorted_percentages else None,
        median_percentage=_quantile(sorted_percentages, 0.5) if sorted_percentages else None,
        q3_percentage=_quantile(sorted_percentages, 0.75) if sorted_percentages else None,
        max_percentage=_round(sorted_percentages[-1]) if sorted_percentages else None,
        score_distribution=_build_score_distribution(percentages),
        question_stats=question_stats,
        version_stats=version_stats,
    )


async def get_exam_score_distribution(
    db: AsyncSession, exam_id: UUID, current_user: User
) -> ExamScoreDistributionResponse:
    exam = await get_exam_by_id(db, exam_id)
    if not exam:
        raise NotFoundError("Exam not found", code="exam_not_found")

    is_staff = current_user.role_enum in {UserRole.PROFESSOR, UserRole.ADMIN}
    if not is_staff:
        # A student only sees the class spread once results are released,
        # and only for an exam they actually have a grade in.
        has_access = exam.released and await student_has_grade_for_exam(db, exam_id, current_user.id)
        if not has_access:
            raise ForbiddenError("Insufficient permissions", code="insufficient_permissions")

    rows = await list_exam_grade_rows(db, exam_id)
    percentages = sorted(
        (float(total_score) / float(max_score)) * 100
        for total_score, max_score, _questions, _version in rows
        if max_score
    )

    if not percentages:
        return ExamScoreDistributionResponse(
            count=0,
            min_percentage=None,
            q1_percentage=None,
            median_percentage=None,
            q3_percentage=None,
            max_percentage=None,
        )

    return ExamScoreDistributionResponse(
        count=len(percentages),
        min_percentage=round(percentages[0], 1),
        q1_percentage=_quantile(percentages, 0.25),
        median_percentage=_quantile(percentages, 0.5),
        q3_percentage=_quantile(percentages, 0.75),
        max_percentage=round(percentages[-1], 1),
    )
