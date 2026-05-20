# Build Repair

- Start from the structured build or test failure summary.
- Locate the smallest relevant file or symbol before editing.
- Prefer a narrow fix over broad rewrites or speculative cleanup.
- After an edit, inspect `git_diff` before running another configured check.
- If the same area keeps failing, stop blind repairs and report the blocker.
- Do not expand command permissions or invent unconfigured build/test steps.
