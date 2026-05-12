#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path


TEXT_EXTENSIONS = {
    ".swift",
    ".h",
    ".m",
    ".mm",
    ".cpp",
    ".c",
    ".hpp",
    ".kt",
    ".kts",
    ".java",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".xml",
    ".plist",
    ".gradle",
    ".toml",
    ".properties",
    ".entitlements",
    ".xcscheme",
    ".xcworkspacedata",
    ".resolved",
    ".sh",
    ".rb",
    ".py",
    ".html",
    ".css",
}

IMPORTANT_FILENAMES = {
    "Package.swift",
    "project.pbxproj",
    "Podfile",
    "Cartfile",
    "Info.plist",
    "README",
    "README.md",
    "SPEC.md",
    "CODEX_CONTEXT.md",
}

IGNORED_PARTS = {
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
    "xcuserdata",
}


def should_ignore(relative: Path) -> bool:
    return any(part in IGNORED_PARTS for part in relative.parts)


def is_text_like(path: Path) -> bool:
    return path.suffix in TEXT_EXTENSIONS or path.name in IMPORTANT_FILENAMES


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_output(source: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=source,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            return f"[Forgis warning: git {' '.join(args)} failed: {result.stderr.strip()}]"
        return result.stdout.strip()
    except Exception as exc:
        return f"[Forgis warning: git {' '.join(args)} failed: {exc}]"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect a full source repository manifest and text bundle for migration context"
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest-output", required=True)
    args = parser.parse_args()

    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    manifest_output = Path(args.manifest_output).resolve()

    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"Source repository directory not found: {source}")

    all_files: list[Path] = []

    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue

        relative = path.relative_to(source)

        if should_ignore(relative):
            continue

        all_files.append(path)

    commit_sha = git_output(source, ["rev-parse", "HEAD"])
    branch_name = git_output(source, ["rev-parse", "--abbrev-ref", "HEAD"])
    status = git_output(source, ["status", "--short"])

    manifest_lines: list[str] = []
    manifest_lines.append("# Forgis Source Manifest")
    manifest_lines.append("")
    manifest_lines.append(f"Source path: `{source}`")
    manifest_lines.append(f"Git branch: `{branch_name}`")
    manifest_lines.append(f"Git commit: `{commit_sha}`")
    manifest_lines.append("")
    manifest_lines.append("## Git status")
    manifest_lines.append("")
    manifest_lines.append("```text")
    manifest_lines.append(status if status else "Clean working tree.")
    manifest_lines.append("```")
    manifest_lines.append("")
    manifest_lines.append("## Files")
    manifest_lines.append("")
    manifest_lines.append("| Path | Size bytes | SHA256 | Included in source bundle |")
    manifest_lines.append("|---|---:|---|---|")

    bundle_lines: list[str] = []
    bundle_lines.append("# Forgis Source Bundle")
    bundle_lines.append("")
    bundle_lines.append(f"Source path: `{source}`")
    bundle_lines.append(f"Git branch: `{branch_name}`")
    bundle_lines.append(f"Git commit: `{commit_sha}`")
    bundle_lines.append("")
    bundle_lines.append("This bundle is regenerated from the selected source repository on every Forgis run.")
    bundle_lines.append("")
    bundle_lines.append("The target repository must not be treated as the source of truth.")
    bundle_lines.append("")
    bundle_lines.append("## Full source manifest")
    bundle_lines.append("")
    bundle_lines.append("See `source_manifest.md` for the full file list, size, and SHA256 hash.")
    bundle_lines.append("")

    text_count = 0
    binary_count = 0

    for path in all_files:
        relative = path.relative_to(source)
        size = path.stat().st_size
        digest = sha256_file(path)
        included = is_text_like(path)

        manifest_lines.append(
            f"| `{relative}` | {size} | `{digest}` | {'yes' if included else 'no'} |"
        )

        if not included:
            binary_count += 1
            continue

        text_count += 1

        bundle_lines.append("---")
        bundle_lines.append("")
        bundle_lines.append(f"## File: `{relative}`")
        bundle_lines.append("")
        bundle_lines.append(f"- Size bytes: {size}")
        bundle_lines.append(f"- SHA256: `{digest}`")
        bundle_lines.append("")
        bundle_lines.append("```text")
        try:
            bundle_lines.append(read_text(path))
        except Exception as exc:
            bundle_lines.append(f"[Forgis warning: failed to read file: {exc}]")
        bundle_lines.append("```")
        bundle_lines.append("")

    if not all_files:
        manifest_lines.append("")
        manifest_lines.append("[Forgis warning: no files found.]")
        bundle_lines.append("[Forgis warning: no source files found.]")
        bundle_lines.append("")

    bundle_lines.append("---")
    bundle_lines.append("")
    bundle_lines.append("## Collection summary")
    bundle_lines.append("")
    bundle_lines.append(f"- Total scanned files: {len(all_files)}")
    bundle_lines.append(f"- Text files included in source bundle: {text_count}")
    bundle_lines.append(f"- Non-text or binary files recorded in manifest only: {binary_count}")
    bundle_lines.append("")
    bundle_lines.append("Forgis must use this freshly collected source bundle as the current source of truth.")

    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_output.parent.mkdir(parents=True, exist_ok=True)

    output.write_text("\n".join(bundle_lines), encoding="utf-8")
    manifest_output.write_text("\n".join(manifest_lines), encoding="utf-8")

    print(f"Forgis source bundle written to: {output}")
    print(f"Forgis source manifest written to: {manifest_output}")
    print(f"Total scanned files: {len(all_files)}")
    print(f"Text files included: {text_count}")
    print(f"Manifest-only files: {binary_count}")


if __name__ == "__main__":
    main()
