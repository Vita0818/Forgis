from __future__ import annotations

import dataclasses
import json
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from forgis_config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_MAX_TOOL_RESULT_CHARS,
    DEFAULT_TASK_PROMPT_PATH,
    resolve_inside_root,
    resolve_target_subdir,
)


READ_TOOLS = {"list_dir", "tree", "read_file", "file_exists"}
WRITE_TOOLS = {"mkdir", "write_file", "append_file", "delete_file"}
ALL_TOOLS = READ_TOOLS | WRITE_TOOLS

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
            lowered = part.casefold()
            if lowered in SECRET_NAMES or lowered.endswith(SECRET_SUFFIXES):
                raise ToolError(f"{label} points at a secret-like path: {text}")
            if any(word in lowered for word in SECRET_WORDS):
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
        if tool_name == "mkdir":
            return self.mkdir(str(arguments.get("path", "")))
        if tool_name == "write_file":
            return self.write_file(str(arguments.get("path", "")), str(arguments.get("content", "")))
        if tool_name == "append_file":
            return self.append_file(str(arguments.get("path", "")), str(arguments.get("content", "")))
        if tool_name == "delete_file":
            return self.delete_file(str(arguments.get("path", "")))
        raise ToolError(f"Unsupported tool: {tool_name}")

    def operation_log(self) -> list[dict[str, Any]]:
        return [operation.as_dict() for operation in self.operations]
