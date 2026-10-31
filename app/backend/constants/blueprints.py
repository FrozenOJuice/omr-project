#--- For templates such as ubco standard sheet ---

UBCO_100_BLUEPRINT = "ubco_100"

UBCO_100_QUESTION_CONFIG = {
    str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(1, 101)
}

# Same physical sheet, but the printed Q1 bubble row is treated as a version
# selector rather than a graded question — see ExamTemplate.version_from_q1.
UBCO_100_QUESTION_CONFIG_VERSIONED = {
    str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(2, 101)
}

UBCO_100_DEFAULT_SCORING = {
    "default_points_per_question": 1.0
}

# Default answer key values for the UBCO 100-question blueprint.
# All questions default to "A" (single choice) — instructors must update before grading.
UBCO_100_DEFAULT_ANSWER_KEY = {
    str(i): {
        "grading_type": "single",
        "correct_choices": ["A"],
        "points": None,
        "partial_weights": None,
    }
    for i in range(1, 101)
}
