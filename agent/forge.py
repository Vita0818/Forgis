#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime
from pathlib import Path


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")


def ensure_directory(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"{label} is not a directory: {path}")


def collect_basic_tree(root: Path, max_files: int = 120) -> list[str]:
    ignored_dirs = {
        ".git",
        ".github",
        ".build",
        "build",
        "DerivedData",
        "node_modules",
        ".gradle",
        ".idea",
        ".vscode",
        "__pycache__",
    }

    results: list[str] = []

    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)

        if any(part in ignored_dirs for part in relative.parts):
            continue

        if path.is_file():
            results.append(str(relative))

        if len(results) >= max_files:
            break

    return results


def write_report(
    target: Path,
    source: Path,
    rules: Path,
    platform: str,
    target_branch: str,
    dry_run: bool,
    source_files: list[str],
) -> Path:
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    report_path = target / "MIGRATION_REPORT.md"

    file_list = "\n".join(f"- {item}" for item in source_files)
    if not file_list:
        file_list = "- No source files were collected."

    report = f"""# Forgis Migration Report

Generated at: {now}

## Configuration

- Source repository path: {source}
- Target repository path: {target}
- Rules path: {rules}
- Target platform: {platform}
- Target branch: {target_branch}
- Dry run: {dry_run}

## Status

Forgis scaffold check completed successfully.

No AI migration has been performed in this initialization run.

## Source repository sample

{file_list}

## Next step

After the GitHub Actions workflow is added, Forgis will be able to run this controller in the cloud.
"""

    report_path.write_text(report, encoding="utf-8")
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Forgis migration controller")

    parser.add_argument("--source", required=True, help="Path to the checked-out Apple source repository")
    parser.add_argument("--target", required=True, help="Path to the checked-out target output repository")
    parser.add_argument("--rules", required=True, help="Path to the Forgis rules directory")
    parser.add_argument("--platform", required=True, choices=["android", "windows"], help="Target platform")
    parser.add_argument("--target-branch", required=True, help="Target migration branch")
    parser.add_argument("--dry-run", required=True, type=parse_bool, help="Whether to avoid pushing changes")

    args = parser.parse_args()

    source = Path(args.source).resolve()
    target = Path(args.target).resolve()
    rules = Path(args.rules).resolve()

    ensure_directory(source, "Source repository")
    ensure_directory(target, "Target repository")
    ensure_directory(rules, "Rules directory")

    source_files = collect_basic_tree(source)
    report_path = write_report(
        target=target,
        source=source,
        rules=rules,
        platform=args.platform,
        target_branch=args.target_branch,
        dry_run=args.dry_run,
        source_files=source_files,
    )

    print("Forgis scaffold check completed.")
    print(f"Migration report written to: {report_path}")


if __name__ == "__main__":
    main()
