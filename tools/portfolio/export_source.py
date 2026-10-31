"""Export current non-ignored source without Git history.

This creates a new directory; it never commits, pushes, initializes Git, or
changes repository visibility.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil

from check_repository import ROOT, check, source_files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="New directory outside the source repository")
    args = parser.parse_args()
    destination = args.destination.expanduser().resolve()
    if destination == ROOT or ROOT in destination.parents:
        parser.error("Choose a destination outside the source repository")
    if destination.exists():
        parser.error("Destination already exists; refusing to overwrite it")
    errors, _ = check()
    if errors:
        parser.error("Repository checks failed; run check_repository.py for details")
    files = source_files()
    for source in files:
        if source.is_symlink():
            parser.error(f"Review symlink before export: {source.relative_to(ROOT)}")
        relative = source.relative_to(ROOT)
        if ".git" in relative.parts:
            parser.error("Git internals must never be exported")
    destination.mkdir(parents=True)
    for source in files:
        target = destination / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (destination / "PORTFOLIO_EXPORT.md").write_text(
        "# Source-only portfolio export\n\n"
        "This is a snapshot of the current working source, including portfolio cleanup.\n"
        "Git history and ignored local environment files are excluded.\n"
        "The original repository and collaboration attribution are preserved separately.\n"
        "Team attribution and the existing license are included.\n"
        "See CONTRIBUTORS.md and docs/portfolio/publication.md for project provenance.\n"
    )
    print(f"Created private review snapshot: {destination} ({len(files)} files; no Git history)")


if __name__ == "__main__":
    main()
