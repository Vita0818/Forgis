#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_feedback import redact_secrets


PR_BODY_MAX_CHARS = 30_000
PR_BODY_SHORT_MAX_CHARS = 3_000
PR_BODY_LOG_EXCERPT_CHARS = 4_000
TRUNCATION_NOTE = "\n\nTruncated. See forgis-reports artifact for the full report."
PR_VISUAL_FIELD_CHARS = 220


def _clean_value(value: str | None, fallback: str = "unknown") -> str:
    text = (value or "").strip()
    if not text:
        return fallback
    return redact_secrets(text.replace("\r", " ").replace("\n", " "))


def _actions_run_line(run_url: str | None) -> str:
    clean = _clean_value(run_url, "")
    if not clean:
        return "- GitHub Actions run: unavailable"
    return f"- GitHub Actions run: {clean}"


def _read_log_excerpt(path: str | None) -> str:
    if not path:
        return ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    clean = redact_secrets(text.strip())
    if not clean:
        return ""
    if len(clean) <= PR_BODY_LOG_EXCERPT_CHARS:
        return clean
    keep = max(0, PR_BODY_LOG_EXCERPT_CHARS - len(TRUNCATION_NOTE))
    return clean[-keep:] + TRUNCATION_NOTE


def _clean_visual_field(value: Any, fallback: str = "none") -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        return fallback
    clean = redact_secrets(text.replace("\r", " ").replace("\n", " "))
    if len(clean) <= PR_VISUAL_FIELD_CHARS:
        return clean
    return clean[: PR_VISUAL_FIELD_CHARS - 3].rstrip() + "..."


def _load_visual_validation(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        raw = Path(path)
        data = json.loads(raw.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    visual = data.get("visual_validation") if isinstance(data, dict) else None
    return visual if isinstance(visual, dict) else {}


def _visual_summary_lines(report_json_path: str | None) -> list[str]:
    visual = _load_visual_validation(report_json_path)
    if not visual:
        return [
            "## Visual Validation",
            "",
            "- Status: `not reported`",
            "- Full visual report fields were unavailable in the run report artifact.",
        ]
    evidence = _clean_visual_field(visual.get("valid_visual_evidence"), "NO")
    blocker = _clean_visual_field(visual.get("actual_screenshot_blocker"), "none")
    limitations = _clean_visual_field(visual.get("visual_validation_limitations"), "none")
    if evidence == "REFERENCE_ONLY" and limitations == "none":
        limitations = "reference-only; not full rendered visual validation."
    return [
        "## Visual Validation",
        "",
        f"- Required: `{str(bool(visual.get('required'))).lower()}`",
        f"- Provider: `{_clean_visual_field(visual.get('provider'), 'qwen')}`",
        f"- Called: `{str(bool(visual.get('called'))).lower()}`",
        f"- Evidence: `{evidence}`",
        f"- Compare completed: `{str(bool(visual.get('compare_screenshots_completed'))).lower()}`",
        f"- Blocker: `{blocker}`",
        f"- Limitations: `{limitations}`",
    ]


def truncate_body(text: str, limit: int) -> str:
    clean = redact_secrets(text).strip() + "\n"
    if len(clean) <= limit:
        return clean
    keep = max(0, limit - len(TRUNCATION_NOTE) - 1)
    return clean[:keep].rstrip() + TRUNCATION_NOTE + "\n"


def build_pr_body(
    *,
    target_branch: str,
    push_branch: str,
    target_base_branch: str,
    target_subdir: str,
    commit_sha: str = "",
    dry_run: str = "",
    confirm_real_run: str = "",
    remote_target_branch_exists: str = "",
    run_url: str = "",
    run_log_path: str = "",
    run_report_json_path: str = "",
    limit: int = PR_BODY_MAX_CHARS,
) -> str:
    run_log_excerpt = _read_log_excerpt(run_log_path)
    mode = "real run" if _clean_value(dry_run, "false").casefold() == "false" else "dry run"
    lines = [
        "# Forgis Task Output",
        "",
        "Forgis generated target output and pushed it to the branch shown below.",
        "",
        "## Run Summary",
        "",
        f"- Configured target branch: `{_clean_value(target_branch)}`",
        f"- PR head / pushed branch: `{_clean_value(push_branch)}`",
        f"- Target base branch: `{_clean_value(target_base_branch)}`",
        f"- Target subdir: `{_clean_value(target_subdir)}`",
        f"- Commit: `{_clean_value(commit_sha)}`",
        f"- Run mode: `{mode}`",
        f"- confirm_real_run: `{_clean_value(confirm_real_run)}`",
        f"- Remote target branch existed: `{_clean_value(remote_target_branch_exists)}`",
        _actions_run_line(run_url),
        "",
        "## Reports",
        "",
        "Download the `forgis-reports` artifact from the workflow run for the full safe report set:",
        "",
        "- `FORGIS_RUN_REPORT.md`",
        "- `FORGIS_RUN_REPORT.json`",
        "- `FORGIS_MIGRATION_PLAN.json`",
        "",
        "The PR body intentionally omits full reports, full diffs, full tool logs, full model summaries, and large build/test output.",
        "",
        *_visual_summary_lines(run_report_json_path),
    ]
    if run_log_excerpt:
        lines.extend(
            [
                "",
                "## Short Run Log Excerpt",
                "",
                "```text",
                run_log_excerpt,
                "```",
            ]
        )
    return truncate_body("\n".join(lines), limit)


def build_short_pr_body(
    *,
    target_branch: str,
    push_branch: str,
    target_base_branch: str,
    target_subdir: str,
    commit_sha: str = "",
    run_url: str = "",
    run_report_json_path: str = "",
    limit: int = PR_BODY_SHORT_MAX_CHARS,
) -> str:
    lines = [
        "# Forgis Task Output",
        "",
        "Forgis generated target output. The full report is in the `forgis-reports` artifact.",
        "",
        f"- Configured target branch: `{_clean_value(target_branch)}`",
        f"- PR head / pushed branch: `{_clean_value(push_branch)}`",
        f"- Target base branch: `{_clean_value(target_base_branch)}`",
        f"- Target subdir: `{_clean_value(target_subdir)}`",
        f"- Commit: `{_clean_value(commit_sha)}`",
        _actions_run_line(run_url),
        "",
        *_visual_summary_lines(run_report_json_path),
        "",
        "See `FORGIS_RUN_REPORT.md`, `FORGIS_RUN_REPORT.json`, and `FORGIS_MIGRATION_PLAN.json` in the artifact.",
    ]
    return truncate_body("\n".join(lines), limit)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a bounded Forgis pull request body.")
    parser.add_argument("--mode", choices=("standard", "short"), default="standard")
    parser.add_argument("--output", required=True)
    parser.add_argument("--target-branch", required=True)
    parser.add_argument("--push-branch", required=True)
    parser.add_argument("--target-base-branch", required=True)
    parser.add_argument("--target-subdir", required=True)
    parser.add_argument("--commit-sha", default="")
    parser.add_argument("--dry-run", default="")
    parser.add_argument("--confirm-real-run", default="")
    parser.add_argument("--remote-target-branch-exists", default="")
    parser.add_argument("--run-url", default="")
    parser.add_argument("--run-log-path", default="")
    parser.add_argument("--run-report-json-path", default="")
    args = parser.parse_args()

    if args.mode == "short":
        body = build_short_pr_body(
            target_branch=args.target_branch,
            push_branch=args.push_branch,
            target_base_branch=args.target_base_branch,
            target_subdir=args.target_subdir,
            commit_sha=args.commit_sha,
            run_url=args.run_url,
            run_report_json_path=args.run_report_json_path,
        )
    else:
        body = build_pr_body(
            target_branch=args.target_branch,
            push_branch=args.push_branch,
            target_base_branch=args.target_base_branch,
            target_subdir=args.target_subdir,
            commit_sha=args.commit_sha,
            dry_run=args.dry_run,
            confirm_real_run=args.confirm_real_run,
            remote_target_branch_exists=args.remote_target_branch_exists,
            run_url=args.run_url,
            run_log_path=args.run_log_path,
            run_report_json_path=args.run_report_json_path,
        )
    Path(args.output).write_text(body, encoding="utf-8")


if __name__ == "__main__":
    main()
