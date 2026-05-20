from __future__ import annotations

import dataclasses
import json
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from build_runner import run_build as run_configured_build, run_tests as run_configured_tests
from command_runner import CommandRunnerError, safe_run_command
from forgis_config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_MAX_TOOL_RESULT_CHARS,
    DEFAULT_TASK_PROMPT_PATH,
    resolve_inside_root,
    resolve_target_subdir,
)
from git_tools import GitToolError, git_diff as target_git_diff, git_status as target_git_status


READ_TOOLS = {"list_dir", "tree", "read_file", "file_exists", "search_text", "git_status", "git_diff"}
WRITE_TOOLS = {"mkdir", "write_file", "append_file", "delete_file", "edit_file", "apply_patch"}
COMMAND_TOOLS = {"run_command", "run_build", "run_tests"}
OBSERVATION_TOOLS = READ_TOOLS | COMMAND_TOOLS
ALL_TOOLS = READ_TOOLS | WRITE_TOOLS | COMMAND_TOOLS

SECRET_NAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
SECRET_WORDS = ("secret", "credential", "private-key", "private_key")
WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
UNIFIED_HUNK_RE = re.compile(r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@")


class ToolError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class ToolOperation:
    tool: str
    path: str
    bytes_written: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "path": self.path,
            "bytes_written": self.bytes_written,
        }


@dataclasses.dataclass(frozen=True)
class ResolvedToolPath:
    absolute: Path
    virtual: str
    root_name: str


def path_kind_no_follow(path: Path) -> str:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return "missing"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISDIR(mode):
        return "dir"
    if stat.S_ISREG(mode):
        return "file"
    return "other"


def is_secret_like_part(part: str) -> bool:
    lowered = part.casefold()
    return (
        lowered in SECRET_NAMES
        or lowered.endswith(SECRET_SUFFIXES)
        or any(word in lowered for word in SECRET_WORDS)
    )


class FileToolSandbox:
    def __init__(
        self,
        *,
        source_root: Path,
        target_root: Path,
        target_subdir: str,
        config_path: str = DEFAULT_CONFIG_PATH,
        task_path: str = DEFAULT_TASK_PROMPT_PATH,
        max_result_chars: int = DEFAULT_MAX_TOOL_RESULT_CHARS,
        build_command: tuple[str, ...] = (),
        test_command: tuple[str, ...] = (),
        build_timeout_seconds: int = 60,
        test_timeout_seconds: int = 60,
        max_command_output_chars: int | None = None,
    ) -> None:
        self.source_root = source_root.resolve()
        self.target_root = target_root.resolve()
        if not self.source_root.is_dir():
            raise FileNotFoundError(f"Source repository directory not found: {self.source_root}")
        if not self.target_root.is_dir():
            raise FileNotFoundError(f"Target repository directory not found: {self.target_root}")

        self.target_subdir_path, self.target_subdir = resolve_target_subdir(
            self.target_root,
            target_subdir,
        )
        self.config_path, self.config_relative = resolve_inside_root(
            self.target_root,
            config_path,
            "config_path",
        )
        self.task_path, self.task_relative = resolve_inside_root(
            self.target_root,
            task_path,
            "task_prompt_path",
        )
        self.max_result_chars = max_result_chars
        self.build_command = tuple(build_command)
        self.test_command = tuple(test_command)
        self.build_timeout_seconds = build_timeout_seconds
        self.test_timeout_seconds = test_timeout_seconds
        self.max_command_output_chars = max_result_chars if max_command_output_chars is None else max_command_output_chars
        self.operations: list[ToolOperation] = []
        self.read_count = 0
        self.write_count = 0

    def _clean_path_text(self, path: Any, label: str) -> str:
        text = str(path if path is not None else "").strip().replace("\\", "/")
        if not text:
            raise ToolError(f"{label} is required.")
        if "\x00" in text or "\n" in text or "\r" in text:
            raise ToolError(f"{label} contains an unsafe character.")
        if text.startswith("/") or WINDOWS_ABSOLUTE_RE.match(text) or text.startswith("~"):
            raise ToolError(f"{label} must use a Forgis virtual relative path, not an absolute path.")

        parts = PurePosixPath(text).parts
        if any(part in {"", ".", "..", ".git"} for part in parts):
            raise ToolError(f"{label} contains an unsafe path segment: {text}")
        for part in parts:
            if is_secret_like_part(part):
                raise ToolError(f"{label} points at a secret-like path: {text}")
        return text.rstrip("/")

    def _virtual_parts(self, path: str) -> tuple[str, str, str]:
        text = self._clean_path_text(path, "path")
        if text == "source":
            return "source", "", "source"
        if text.startswith("source/"):
            return "source", text[len("source/") :], text
        if text == "target":
            return "target", "", "target"
        if text.startswith("target/"):
            return "target", text[len("target/") :], text
        if text == "config":
            return "target", self.config_relative, f"target/{self.config_relative}"
        if text == "task":
            return "target", self.task_relative, f"target/{self.task_relative}"
        if text == "target_subdir":
            return "target_subdir", "", f"target/{self.target_subdir}"
        if text.startswith("target_subdir/"):
            relative = text[len("target_subdir/") :]
            return "target_subdir", relative, f"target/{self.target_subdir}/{relative}"
        return "target", text, f"target/{text}"

    def _resolve_against(self, root: Path, relative: str, label: str) -> Path:
        root_resolved = root.resolve()
        parts = PurePosixPath(relative).parts
        current = root_resolved
        for part in parts[:-1]:
            current = current / part
            kind = path_kind_no_follow(current)
            if kind == "symlink":
                raise ToolError(f"{label} contains a symlink directory segment.")
            if kind not in {"missing", "dir"}:
                raise ToolError(f"{label} contains a non-directory path segment.")

        candidate = current / parts[-1] if parts else current
        if candidate != root_resolved and not candidate.is_relative_to(root_resolved):
            raise ToolError(f"{label} escapes its allowed root.")
        return candidate

    def resolve_read_path(self, path: str) -> ResolvedToolPath:
        root_name, relative, virtual = self._virtual_parts(path)
        if root_name == "source":
            root = self.source_root
        elif root_name == "target":
            root = self.target_root
        else:
            root = self.target_subdir_path
        absolute = self._resolve_against(root, relative, "read path")
        return ResolvedToolPath(absolute=absolute, virtual=virtual, root_name=root_name)

    def resolve_write_path(self, path: str, *, allow_subdir_root: bool = False) -> ResolvedToolPath:
        root_name, relative, virtual = self._virtual_parts(path)
        if root_name == "source":
            raise ToolError("Write tools cannot modify the source repository.")

        base = self.target_subdir_path if root_name == "target_subdir" else self.target_root
        absolute = self._resolve_against(base, relative, "write path")
        if absolute == self.target_subdir_path and not allow_subdir_root:
            raise ToolError("Write tools require a path inside target_subdir, not target_subdir itself.")
        if absolute != self.target_subdir_path and not absolute.is_relative_to(self.target_subdir_path):
            raise ToolError("Write tools can only modify files inside target_subdir.")
        if path_kind_no_follow(absolute) == "symlink":
            raise ToolError("Write tools cannot modify paths through symlinks.")
        if absolute in {self.config_path, self.task_path}:
            raise ToolError("Write tools cannot modify the config or task file.")

        relative_to_target = absolute.relative_to(self.target_root).as_posix()
        parts = PurePosixPath(relative_to_target).parts
        if ".github" in parts and "workflows" in parts:
            raise ToolError("Write tools cannot modify workflow files.")

        return ResolvedToolPath(absolute=absolute, virtual=f"target/{relative_to_target}", root_name="target")

    def _truncate_text(self, text: str) -> tuple[str, bool]:
        if len(text) <= self.max_result_chars:
            return text, False
        note = f"\n\n[Forgis tool result truncated after {self.max_result_chars} characters. Continue with pagination.]\n"
        keep = max(0, self.max_result_chars - len(note))
        return text[:keep] + note, True

    def _limited_result(self, result: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True)
        if len(encoded) <= self.max_result_chars:
            return result
        limited = dict(result)
        limited["truncated"] = True
        limited["truncation_note"] = (
            f"Result exceeded {self.max_result_chars} characters. "
            "Use a narrower path or read_file pagination."
        )
        for key in ("entries", "tree"):
            if isinstance(limited.get(key), list):
                items = list(limited[key])
                while items and len(json.dumps({**limited, key: items}, ensure_ascii=False)) > self.max_result_chars:
                    items.pop()
                limited[key] = items
        return limited

    def list_dir(self, path: str) -> dict[str, Any]:
        resolved = self.resolve_read_path(path)
        kind = path_kind_no_follow(resolved.absolute)
        if kind == "missing":
            raise ToolError(f"Directory does not exist: {resolved.virtual}")
        if kind != "dir":
            raise ToolError(f"Path is not a directory: {resolved.virtual}")
        entries: list[dict[str, str]] = []
        for entry in sorted(resolved.absolute.iterdir(), key=lambda item: item.name.casefold()):
            entries.append({"name": entry.name, "type": path_kind_no_follow(entry)})
        self.read_count += 1
        return self._limited_result({"ok": True, "path": resolved.virtual, "entries": entries, "truncated": False})

    def tree(self, path: str, max_depth: int | None = None) -> dict[str, Any]:
        resolved = self.resolve_read_path(path)
        root_kind = path_kind_no_follow(resolved.absolute)
        if root_kind == "missing":
            raise ToolError(f"Tree root does not exist: {resolved.virtual}")
        if root_kind != "dir":
            raise ToolError(f"Tree root is not a directory: {resolved.virtual}")
        depth_limit = 3 if max_depth is None else int(max_depth)
        if depth_limit < 0:
            raise ToolError("max_depth must not be negative.")

        lines: list[str] = []

        def visit(directory: Path, prefix: str, depth: int) -> None:
            if depth > depth_limit:
                return
            for entry in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
                kind = path_kind_no_follow(entry)
                marker = "/" if kind == "dir" else "@" if kind == "symlink" else ""
                lines.append(f"{prefix}{entry.name}{marker}")
                if kind == "dir" and depth < depth_limit:
                    visit(entry, prefix + "  ", depth + 1)

        visit(resolved.absolute, "", 0)
        self.read_count += 1
        return self._limited_result({"ok": True, "path": resolved.virtual, "tree": lines, "truncated": False})

    def read_file(
        self,
        path: str,
        start_line: int | None = None,
        max_lines: int | None = None,
    ) -> dict[str, Any]:
        resolved = self.resolve_read_path(path)
        kind = path_kind_no_follow(resolved.absolute)
        if kind == "missing":
            raise ToolError(f"File does not exist: {resolved.virtual}")
        if kind == "symlink":
            raise ToolError(f"Refusing to read symlink file: {resolved.virtual}")
        if kind != "file":
            raise ToolError(f"Path is not a file: {resolved.virtual}")

        start = 1 if start_line is None else int(start_line)
        if start < 1:
            raise ToolError("start_line must be at least 1.")
        limit = None if max_lines is None else int(max_lines)
        if limit is not None and limit < 1:
            raise ToolError("max_lines must be at least 1.")

        text = resolved.absolute.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        total_lines = len(lines)
        start_index = min(start - 1, total_lines)
        end_index = total_lines if limit is None else min(total_lines, start_index + limit)
        selected = lines[start_index:end_index]
        content, truncated_by_chars = self._truncate_text("".join(selected))
        has_more_lines = end_index < total_lines
        self.read_count += 1
        return {
            "ok": True,
            "path": resolved.virtual,
            "start_line": start,
            "returned_lines": len(selected),
            "total_lines": total_lines,
            "next_start_line": end_index + 1 if has_more_lines else None,
            "truncated": has_more_lines or truncated_by_chars,
            "content": content,
        }

    def file_exists(self, path: str) -> dict[str, Any]:
        resolved = self.resolve_read_path(path)
        kind = path_kind_no_follow(resolved.absolute)
        self.read_count += 1
        return {
            "ok": True,
            "path": resolved.virtual,
            "exists": kind != "missing",
            "type": kind,
            "is_symlink": kind == "symlink",
        }

    def _walk_search_files(self, root: Path) -> list[Path]:
        files: list[Path] = []
        stack = [root]
        while stack:
            directory = stack.pop()
            for entry in sorted(directory.iterdir(), key=lambda item: item.name.casefold(), reverse=True):
                if entry.name == ".git" or is_secret_like_part(entry.name):
                    continue
                kind = path_kind_no_follow(entry)
                if kind == "dir":
                    stack.append(entry)
                elif kind == "file":
                    files.append(entry)
        return sorted(files, key=lambda item: item.as_posix().casefold())

    def _search_candidate_files(self, resolved: ResolvedToolPath) -> list[tuple[Path, str]]:
        kind = path_kind_no_follow(resolved.absolute)
        if kind == "missing":
            raise ToolError(f"Search root does not exist: {resolved.virtual}")
        if kind == "symlink":
            raise ToolError(f"Refusing to search symlink path: {resolved.virtual}")
        if kind == "file":
            return [(resolved.absolute, resolved.virtual)]
        if kind != "dir":
            raise ToolError(f"Search root is not a file or directory: {resolved.virtual}")

        pairs: list[tuple[Path, str]] = []
        for path in self._walk_search_files(resolved.absolute):
            relative = path.relative_to(resolved.absolute).as_posix()
            virtual = f"{resolved.virtual.rstrip('/')}/{relative}" if relative else resolved.virtual
            pairs.append((path, virtual))
        return pairs

    def _line_snippet(self, line: str, match_start: int | None = None, *, max_chars: int = 240) -> str:
        clean = line.rstrip("\r\n")
        if len(clean) <= max_chars:
            return clean
        if match_start is None:
            return clean[: max_chars - 3] + "..."
        start = max(0, min(match_start - 80, len(clean) - max_chars + 3))
        end = min(len(clean), start + max_chars - 3)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(clean) else ""
        return prefix + clean[start:end] + suffix

    def search_text(
        self,
        query: str,
        root: str = "target",
        *,
        regex: bool = False,
        case_sensitive: bool = False,
        max_results: int = 50,
    ) -> dict[str, Any]:
        needle = str(query)
        if not needle:
            raise ToolError("query is required.")
        limit = max(1, min(int(max_results), 200))
        resolved = self.resolve_read_path(root or "target")
        candidates = self._search_candidate_files(resolved)
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = None
        if regex:
            try:
                pattern = re.compile(needle, flags)
            except re.error as exc:
                raise ToolError(f"query is not a valid regular expression: {exc}") from exc
        else:
            needle_cmp = needle if case_sensitive else needle.casefold()

        matches: list[dict[str, Any]] = []
        files_scanned = 0
        for path, virtual in candidates:
            try:
                with path.open("rb") as file:
                    if b"\x00" in file.read(4096):
                        continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            files_scanned += 1
            for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
                if pattern is not None:
                    match = pattern.search(line)
                    if not match:
                        continue
                    match_start = match.start()
                else:
                    haystack = line if case_sensitive else line.casefold()
                    match_start = haystack.find(needle_cmp)
                    if match_start < 0:
                        continue
                matches.append(
                    {
                        "path": virtual,
                        "line": line_number,
                        "snippet": self._line_snippet(line, match_start),
                    }
                )
                if len(matches) >= limit:
                    self.read_count += 1
                    return {
                        "ok": True,
                        "root": resolved.virtual,
                        "query": "[redacted]",
                        "regex": bool(regex),
                        "case_sensitive": bool(case_sensitive),
                        "matches": matches,
                        "match_count": len(matches),
                        "files_scanned": files_scanned,
                        "truncated": True,
                    }

        self.read_count += 1
        return {
            "ok": True,
            "root": resolved.virtual,
            "query": "[redacted]",
            "regex": bool(regex),
            "case_sensitive": bool(case_sensitive),
            "matches": matches,
            "match_count": len(matches),
            "files_scanned": files_scanned,
            "truncated": False,
        }

    def git_status(self, max_entries: int | None = None) -> dict[str, Any]:
        try:
            result = target_git_status(self.target_root, max_entries=200 if max_entries is None else int(max_entries))
        except GitToolError as exc:
            raise ToolError(str(exc)) from exc
        self.read_count += 1
        return result

    def git_diff(self, max_chars: int | None = None) -> dict[str, Any]:
        try:
            result = target_git_diff(self.target_root, max_chars=self.max_result_chars if max_chars is None else int(max_chars))
        except GitToolError as exc:
            raise ToolError(str(exc)) from exc
        self.read_count += 1
        return result

    def mkdir(self, path: str) -> dict[str, Any]:
        resolved = self.resolve_write_path(path, allow_subdir_root=True)
        resolved.absolute.mkdir(parents=True, exist_ok=True)
        self.operations.append(ToolOperation(tool="mkdir", path=resolved.virtual))
        self.write_count += 1
        return {"ok": True, "path": resolved.virtual}

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        resolved = self.resolve_write_path(path)
        resolved.absolute.parent.mkdir(parents=True, exist_ok=True)
        text = str(content)
        resolved.absolute.write_text(text, encoding="utf-8")
        self.operations.append(ToolOperation(tool="write_file", path=resolved.virtual, bytes_written=len(text.encode("utf-8"))))
        self.write_count += 1
        return {"ok": True, "path": resolved.virtual, "bytes_written": len(text.encode("utf-8"))}

    def append_file(self, path: str, content: str) -> dict[str, Any]:
        resolved = self.resolve_write_path(path)
        resolved.absolute.parent.mkdir(parents=True, exist_ok=True)
        text = str(content)
        with resolved.absolute.open("a", encoding="utf-8") as file:
            file.write(text)
        self.operations.append(ToolOperation(tool="append_file", path=resolved.virtual, bytes_written=len(text.encode("utf-8"))))
        self.write_count += 1
        return {"ok": True, "path": resolved.virtual, "bytes_written": len(text.encode("utf-8"))}

    def edit_file(
        self,
        path: str,
        old_text: str,
        new_text: str,
        expected_replacements: int | None = 1,
    ) -> dict[str, Any]:
        resolved = self.resolve_write_path(path)
        kind = path_kind_no_follow(resolved.absolute)
        if kind == "missing":
            raise ToolError(f"File does not exist: {resolved.virtual}")
        if kind != "file":
            raise ToolError(f"Path is not a regular file: {resolved.virtual}")
        old = str(old_text)
        if old == "":
            raise ToolError("old_text must be non-empty.")
        new = str(new_text)
        expected = 1 if expected_replacements is None else int(expected_replacements)
        if expected < 1:
            raise ToolError("expected_replacements must be at least 1.")

        text = resolved.absolute.read_text(encoding="utf-8", errors="replace")
        count = text.count(old)
        if count != expected:
            raise ToolError(
                f"edit_file expected {expected} replacement(s), found {count} in {resolved.virtual}."
            )
        updated = text.replace(old, new, expected)
        resolved.absolute.write_text(updated, encoding="utf-8")
        bytes_written = len(updated.encode("utf-8"))
        self.operations.append(ToolOperation(tool="edit_file", path=resolved.virtual, bytes_written=bytes_written))
        self.write_count += 1
        return {
            "ok": True,
            "path": resolved.virtual,
            "replacements": expected,
            "bytes_written": bytes_written,
        }

    def _parse_unified_patch(self, patch: str) -> list[tuple[int, list[str]]]:
        lines = patch.splitlines(keepends=True)
        hunks: list[tuple[int, list[str]]] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if line.startswith(("--- ", "+++ ")):
                index += 1
                continue
            match = UNIFIED_HUNK_RE.match(line.rstrip("\r\n"))
            if not match:
                raise ToolError("apply_patch requires a unified diff hunk header.")
            old_start = int(match.group("old_start"))
            index += 1
            hunk_lines: list[str] = []
            while index < len(lines) and not lines[index].startswith("@@ "):
                current = lines[index]
                if current.startswith("\\ No newline at end of file"):
                    index += 1
                    continue
                if not current or current[0] not in {" ", "+", "-"}:
                    raise ToolError("apply_patch contains an invalid hunk line.")
                hunk_lines.append(current)
                index += 1
            hunks.append((old_start, hunk_lines))
        if not hunks:
            raise ToolError("apply_patch requires at least one unified diff hunk.")
        return hunks

    def apply_patch(self, path: str, patch: str) -> dict[str, Any]:
        resolved = self.resolve_write_path(path)
        kind = path_kind_no_follow(resolved.absolute)
        if kind == "missing":
            raise ToolError(f"File does not exist: {resolved.virtual}")
        if kind != "file":
            raise ToolError(f"Path is not a regular file: {resolved.virtual}")

        original = resolved.absolute.read_text(encoding="utf-8", errors="replace")
        original_lines = original.splitlines(keepends=True)
        output: list[str] = []
        source_index = 0
        for old_start, hunk_lines in self._parse_unified_patch(str(patch)):
            target_index = old_start - 1
            if target_index < source_index or target_index > len(original_lines):
                raise ToolError("apply_patch hunk location is invalid for the current file.")
            output.extend(original_lines[source_index:target_index])
            index = target_index
            for hunk_line in hunk_lines:
                marker = hunk_line[0]
                value = hunk_line[1:]
                if marker == " ":
                    if index >= len(original_lines) or original_lines[index] != value:
                        raise ToolError("apply_patch context does not match the current file.")
                    output.append(original_lines[index])
                    index += 1
                elif marker == "-":
                    if index >= len(original_lines) or original_lines[index] != value:
                        raise ToolError("apply_patch removal does not match the current file.")
                    index += 1
                elif marker == "+":
                    output.append(value)
            source_index = index
        output.extend(original_lines[source_index:])
        updated = "".join(output)
        if updated == original:
            raise ToolError("apply_patch made no changes.")
        resolved.absolute.write_text(updated, encoding="utf-8")
        bytes_written = len(updated.encode("utf-8"))
        self.operations.append(ToolOperation(tool="apply_patch", path=resolved.virtual, bytes_written=bytes_written))
        self.write_count += 1
        return {"ok": True, "path": resolved.virtual, "bytes_written": bytes_written}

    def delete_file(self, path: str) -> dict[str, Any]:
        resolved = self.resolve_write_path(path)
        kind = path_kind_no_follow(resolved.absolute)
        if kind == "missing":
            raise ToolError(f"File does not exist: {resolved.virtual}")
        if kind == "dir":
            raise ToolError(f"delete_file refuses to delete directories: {resolved.virtual}")
        resolved.absolute.unlink()
        self.operations.append(ToolOperation(tool="delete_file", path=resolved.virtual))
        self.write_count += 1
        return {"ok": True, "path": resolved.virtual}

    def run_command(
        self,
        command: Any,
        cwd: str | None = None,
        *,
        timeout_seconds: int | None = None,
        max_output_chars: int | None = None,
    ) -> dict[str, Any]:
        resolved = self.resolve_read_path(cwd or "target_subdir")
        if resolved.root_name == "source":
            raise ToolError("run_command cannot run in the source repository.")
        kind = path_kind_no_follow(resolved.absolute)
        if kind == "symlink":
            raise ToolError("run_command cannot use a symlink working directory.")
        if kind != "dir":
            raise ToolError(f"run_command cwd is not a directory: {resolved.virtual}")
        if resolved.absolute != self.target_subdir_path and not resolved.absolute.is_relative_to(self.target_subdir_path):
            raise ToolError("run_command cwd must be inside target_subdir.")
        try:
            result = safe_run_command(
                cwd=resolved.absolute,
                command=command,
                timeout_seconds=10 if timeout_seconds is None else int(timeout_seconds),
                max_output_chars=self.max_result_chars if max_output_chars is None else int(max_output_chars),
            )
        except CommandRunnerError as exc:
            raise ToolError(str(exc)) from exc
        result["cwd"] = resolved.virtual
        return result

    def run_build(self) -> dict[str, Any]:
        return run_configured_build(
            command=self.build_command,
            cwd=self.target_subdir_path,
            timeout_seconds=self.build_timeout_seconds,
            max_output_chars=self.max_command_output_chars,
        )

    def run_tests(self) -> dict[str, Any]:
        return run_configured_tests(
            command=self.test_command,
            cwd=self.target_subdir_path,
            timeout_seconds=self.test_timeout_seconds,
            max_output_chars=self.max_command_output_chars,
        )

    def invoke(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name not in ALL_TOOLS:
            raise ToolError(f"Unsupported tool: {tool_name}")
        if not isinstance(arguments, dict):
            raise ToolError("Tool arguments must be a JSON object.")
        if tool_name == "list_dir":
            return self.list_dir(str(arguments.get("path", "")))
        if tool_name == "tree":
            max_depth = arguments.get("max_depth")
            return self.tree(str(arguments.get("path", "")), None if max_depth is None else int(max_depth))
        if tool_name == "read_file":
            return self.read_file(
                str(arguments.get("path", "")),
                arguments.get("start_line"),
                arguments.get("max_lines"),
            )
        if tool_name == "file_exists":
            return self.file_exists(str(arguments.get("path", "")))
        if tool_name == "search_text":
            return self.search_text(
                str(arguments.get("query", "")),
                str(arguments.get("root", "target")),
                regex=bool(arguments.get("regex", False)),
                case_sensitive=bool(arguments.get("case_sensitive", False)),
                max_results=int(arguments.get("max_results", 50)),
            )
        if tool_name == "git_status":
            return self.git_status(arguments.get("max_entries"))
        if tool_name == "git_diff":
            return self.git_diff(arguments.get("max_chars"))
        if tool_name == "mkdir":
            return self.mkdir(str(arguments.get("path", "")))
        if tool_name == "write_file":
            return self.write_file(str(arguments.get("path", "")), str(arguments.get("content", "")))
        if tool_name == "append_file":
            return self.append_file(str(arguments.get("path", "")), str(arguments.get("content", "")))
        if tool_name == "edit_file":
            return self.edit_file(
                str(arguments.get("path", "")),
                str(arguments.get("old_text", "")),
                str(arguments.get("new_text", "")),
                arguments.get("expected_replacements", 1),
            )
        if tool_name == "apply_patch":
            return self.apply_patch(str(arguments.get("path", "")), str(arguments.get("patch", "")))
        if tool_name == "delete_file":
            return self.delete_file(str(arguments.get("path", "")))
        if tool_name == "run_command":
            return self.run_command(
                arguments.get("command"),
                None if arguments.get("cwd") is None else str(arguments.get("cwd", "")),
                timeout_seconds=arguments.get("timeout_seconds"),
                max_output_chars=arguments.get("max_output_chars"),
            )
        if tool_name == "run_build":
            return self.run_build()
        if tool_name == "run_tests":
            return self.run_tests()
        raise ToolError(f"Unsupported tool: {tool_name}")

    def operation_log(self) -> list[dict[str, Any]]:
        return [operation.as_dict() for operation in self.operations]
