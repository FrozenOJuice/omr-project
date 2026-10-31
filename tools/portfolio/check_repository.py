"""Offline syntax, portfolio link, and basic publication-hygiene checks.

This does not import the application, connect to a service, or execute its tests.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[2]


def source_files() -> list[Path]:
    if (ROOT / ".git").exists():
        names = subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
        ).decode().split("\0")
        return sorted({ROOT / name for name in names if name and (ROOT / name).is_file()})
    return sorted(path for path in ROOT.rglob("*") if path.is_file() and ".git" not in path.relative_to(ROOT).parts)


def check() -> tuple[list[str], dict[str, int]]:
    errors: list[str] = []
    totals = {"Python": 0, "shell": 0, "JSON": 0, "local links": 0}
    for path in source_files():
        relative = path.relative_to(ROOT).as_posix()
        try:
            if path.suffix == ".py":
                ast.parse(path.read_bytes(), filename=relative)
                totals["Python"] += 1
            elif path.suffix == ".sh":
                result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
                if result.returncode:
                    errors.append(f"Shell syntax: {relative}")
                totals["shell"] += 1
            elif path.suffix == ".json" and not path.name.startswith("tsconfig"):
                json.loads(path.read_text())
                totals["JSON"] += 1
        except (SyntaxError, ValueError, UnicodeError) as exc:
            errors.append(f"Syntax: {relative}: {type(exc).__name__}")
        if path.suffix not in (".md", ".py", ".rb", ".sh", ".yml", ".toml", ".env"):
            continue
        text = path.read_text(errors="replace")
        # Ordinary fixture addresses under tests are deliberately not treated as
        # evidence of a real mailbox. Published operational defaults use example.com.
        is_test = "/tests/" in relative or path.name.endswith((".spec.ts", "_test.go"))
        if not is_test and re.search(r"[\w.+-]+@(?:gmail|hotmail|yahoo|outlook)\.com", text, re.I):
            errors.append(f"Personal-provider email needs review: {relative}")
        if re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", text):
            errors.append(f"Private-key block needs review: {relative}")

    documents = [ROOT / "README.md", ROOT / "CONTRIBUTORS.md", ROOT / "docs/TOC.md"]
    documents += sorted((ROOT / "docs/portfolio").rglob("*.md"))
    for path in documents:
        for match in re.finditer(r"!?\[[^\]]*\]\(([^)]+)\)", path.read_text()):
            target = match.group(1).strip().strip("<>")
            if target.startswith(("https://", "http://", "mailto:", "#")):
                continue
            target = unquote(target.split("#", 1)[0])
            if not target:
                continue
            totals["local links"] += 1
            if not (path.parent / target).exists():
                errors.append(f"Broken local link in {path.relative_to(ROOT)}: {target}")
    for filename in ("template-editor", "answer-key-editor", "scan-upload", "exam-review", "grade-release", "canvas-course-import"):
        if not (ROOT / f"docs/portfolio/screenshots/{filename}.png").is_file():
            errors.append(f"Missing portfolio screenshot: {filename}")
    return errors, totals


def main() -> int:
    errors, totals = check()
    for error in errors:
        print(error, file=sys.stderr)
    print("Offline repository checks:", ", ".join(f"{count} {kind}" for kind, count in totals.items()))
    print("No application services or test databases were accessed.")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
