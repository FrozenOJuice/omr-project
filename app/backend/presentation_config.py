"""Shared configuration for seeded and generated presentation fixtures."""

import re
from itertools import chain


def presentation_email(first_name: str, last_name: str) -> str:
    """Return a readable, deterministic address for a synthetic student."""

    def slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", ".", value.lower()).strip(".")

    return f"{slug(first_name)}.{slug(last_name)}@example.com"


def unique_names(
    source: list[str] | tuple[str, ...],
    count: int,
    excluded: set[str],
    separator: str,
) -> list[str]:
    """Select deterministic unique names, combining source values if needed."""
    values: list[str] = []
    seen = set(excluded)
    combinations = (
        f"{left}{separator}{right}"
        for left in source
        for right in source
        if left != right
    )
    for candidate in chain(source, combinations):
        if candidate in seen:
            continue
        seen.add(candidate)
        values.append(candidate)
        if len(values) == count:
            return values
    raise ValueError(f"Unable to generate {count} unique names")


CANVAS_LINKED_STUDENTS = (
    ("Maya", "Chen", "maya.chen@example.com", "10000001"),
    ("Liam", "Wilson", "liam.wilson@example.com", "10000002"),
    ("Ava", "Patel", "ava.patel@example.com", "10000003"),
    ("Noah", "Kim", "noah.kim@example.com", "10000004"),
    ("Sofia", "Martinez", "sofia.martinez@example.com", "10000005"),
    ("Ethan", "Nguyen", "ethan.nguyen@example.com", "10000006"),
    ("Olivia", "Brown", "olivia.brown@example.com", "10000007"),
    ("Lucas", "Anderson", "lucas.anderson@example.com", "10000008"),
    ("Emma", "Thompson", "emma.thompson@example.com", "10000009"),
    ("Jackson", "Lee", "jackson.lee@example.com", "10000010"),
)


PRESENTATION_ADDITIONAL_FIRST_NAMES = (
    "Aaron", "Abigail", "Abraham", "Ada", "Aiden", "Alexandra", "Alexis",
    "Alyssa", "Andrea", "Angela", "Arthur", "Ashton", "Autumn", "Beau",
    "Bella", "Blake", "Brianna", "Caleb", "Calvin", "Cameron", "Cassandra",
    "Cecilia", "Connor", "Daisy", "Damian", "Delilah", "Derek", "Diana",
    "Edward", "Eleanor", "Elias", "Eliana", "Emily", "Eric", "Esther",
    "Finn", "Fiona", "Gavin", "Georgia", "Gianna", "Grant", "Hailey",
    "Ian", "Ivy", "Jade", "Jason", "Jasmine", "Jeremiah", "Jocelyn",
    "Jonah", "Julia", "Justin", "Katherine", "Kayla", "Kevin", "Lillian",
    "Logan", "Lydia", "Marcus", "Maria", "Melody", "Micah", "Morgan",
    "Oscar", "Paige", "Patrick", "Penelope", "Peter", "Rachel", "Rebecca",
    "Reese", "Riley", "Rose", "Samantha", "Simon", "Stella", "Steven",
    "Summer", "Sydney", "Timothy", "Tyler", "Vanessa", "Vivian", "Zachary",
)

PRESENTATION_ADDITIONAL_LAST_NAMES = (
    "Adams", "Allen", "Alvarez", "Anderson", "Andrews", "Arnold", "Barrett",
    "Beck", "Benson", "Berry", "Black", "Boyd", "Bradley", "Bryant",
    "Burke", "Burns", "Burton", "Carlson", "Carr", "Carroll", "Castillo",
    "Chapman", "Chavez", "Christensen", "Crawford", "Cunningham", "Daniels",
    "Davidson", "Dawson", "Dean", "Dixon", "Douglas", "Dunn", "Elliott",
    "Ellis", "Erickson", "Ferguson", "Fields", "Ford", "Fowler", "Fox",
    "Gardner", "George", "Gibson", "Gilbert", "Gordon", "Grant", "Greene",
    "Hanson", "Harper", "Hart", "Hawkins", "Hayes", "Henry", "Hicks",
    "Holland", "Holmes", "Howell", "Hudson", "Hunt", "Hunter", "Jackson",
    "Jacobs", "Johnston", "Jones", "Keller", "Kennedy", "Lane", "Larson",
    "Lawrence", "Marshall", "Mason", "Matthews", "McCarthy", "Medina",
    "Mendoza", "Meyer", "Mills", "Morrison", "Murray", "Newman", "Nichols",
    "Palmer", "Porter", "Ramos", "Ray", "Rice", "Riley", "Rose", "Ruiz",
    "Schmidt", "Shaw", "Spencer", "Stone", "Warren", "Washington", "Weaver",
    "Wheeler", "Williamson",
)

DEFAULT_PRESENTATION_TEMPLATE_NAME = "Default Exam (10 Questions A-E)"
DEFAULT_PRESENTATION_QUESTION_CONFIG = {
    str(question): {"choices": ["A", "B", "C", "D", "E"]}
    for question in range(1, 11)
}
DEFAULT_PRESENTATION_SECTIONS = [
    {
        "id": "section-1",
        "name": "Multiple Choice",
        "type": "multiple_choice",
        "question_ids": [str(question) for question in range(1, 11)],
    }
]

PRESENTATION_TEMPLATE_NAME = "Mixed-Format Exam (15 Questions A-K)"
PRESENTATION_QUESTION_CONFIG = {
    **{
        str(question): {"choices": list("ABCDEFGHIJK")}
        for question in range(1, 11)
    },
    **{str(question): {"choices": ["T", "F"]} for question in range(11, 16)},
}
PRESENTATION_SECTIONS = [
    {
        "id": "section-1",
        "name": "Multiple Choice",
        "type": "multiple_choice",
        "question_ids": [str(question) for question in range(1, 11)],
    },
    {
        "id": "section-2",
        "name": "True or False",
        "type": "true_false",
        "question_ids": [str(question) for question in range(11, 16)],
    },
]
