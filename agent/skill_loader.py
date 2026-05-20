from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SKILLS_DIR = REPO_ROOT / "skills"
DEFAULT_MAX_SKILL_CHARS = 12_000
DEFAULT_MAX_TOTAL_SKILL_CHARS = 30_000
SKILL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,80}$")
SECRET_PATH_WORDS = re.compile(
    r"(secret|token|credential|password|api[_-]?key|private|\.env|\.npmrc|\.pypirc|\.netrc)",
    re.IGNORECASE,
)
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|token|password|secret|credential)\b\s*[:=]\s*\S+"
)


class SkillLoaderError(ValueError):
    """Raised when a skill name or skill file violates the local loading rules."""


@dataclasses.dataclass(frozen=True)
class SkillDocument:
    name: str
    path: str
    content: str

    @property
    def chars(self) -> int:
        return len(self.content)


@dataclasses.dataclass(frozen=True)
class SkillSelection:
    skills_enabled: bool
    auto_select_skills: bool
    skills: tuple[SkillDocument, ...] = ()
    selected_skill_names: tuple[str, ...] = ()
    skipped_skill_names: tuple[str, ...] = ()
    failed_skill_names: tuple[str, ...] = ()
    total_skill_chars: int = 0

    def as_runtime_state(self) -> dict[str, Any]:
        return {
            "skills_enabled": bool(self.skills_enabled),
            "auto_select_skills": bool(self.auto_select_skills),
            "selected_skill_names": list(self.selected_skill_names),
            "skipped_skill_names": list(self.skipped_skill_names),
            "failed_skill_names": list(self.failed_skill_names),
            "total_skill_chars": int(self.total_skill_chars),
        }


def _skills_dir(skills_dir: str | Path | None = None) -> Path:
    requested = DEFAULT_SKILLS_DIR if skills_dir is None else Path(skills_dir)
    try:
        resolved = requested.resolve()
        expected = DEFAULT_SKILLS_DIR.resolve()
    except OSError as exc:
        raise SkillLoaderError(f"skills_dir could not be resolved: {requested}") from exc
    if resolved != expected:
        raise SkillLoaderError("skills_dir must be the repository-local skills directory.")
    return resolved


def validate_skill_name(name: Any) -> str:
    text = str(name if name is not None else "").strip()
    if not text:
        raise SkillLoaderError("skill name must be a non-empty slug.")
    if "\x00" in text or "/" in text or "\\" in text:
        raise SkillLoaderError(f"skill name contains an unsafe path segment: {text}")
    if text.startswith(".") or text.startswith("~") or Path(text).is_absolute():
        raise SkillLoaderError(f"skill name must be a relative slug: {text}")
    if not SKILL_NAME_PATTERN.fullmatch(text):
        raise SkillLoaderError(f"skill name must be a safe slug: {text}")
    if SECRET_PATH_WORDS.search(text):
        raise SkillLoaderError(f"skill name must not contain secret-like words: {text}")
    return text


def _dedupe_names(names: Iterable[Any]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in names:
        name = validate_skill_name(raw)
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(name)
    return tuple(result)


def list_available_skills(skills_dir: str | Path | None = None) -> list[str]:
    root = _skills_dir(skills_dir)
    if not root.exists():
        return []
    names: list[str] = []
    for path in sorted(root.glob("*.md")):
        try:
            if not path.is_file():
                continue
            name = validate_skill_name(path.stem)
        except SkillLoaderError:
            continue
        names.append(name)
    return names


def load_skill(
    name: str,
    *,
    skills_dir: str | Path | None = None,
    max_chars: int = DEFAULT_MAX_SKILL_CHARS,
) -> SkillDocument:
    root = _skills_dir(skills_dir)
    skill_name = validate_skill_name(name)
    if int(max_chars) < 1:
        raise SkillLoaderError("max_chars must be positive.")
    path = (root / f"{skill_name}.md").resolve()
    if not path.is_relative_to(root):
        raise SkillLoaderError(f"skill path escapes skills directory: {skill_name}")
    if not path.exists():
        raise SkillLoaderError(f"skill not found: {skill_name}")
    if not path.is_file():
        raise SkillLoaderError(f"skill path is not a file: {skill_name}")
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillLoaderError(f"skill could not be read: {skill_name}") from exc
    content = content.strip()
    if SECRET_ASSIGNMENT.search(content):
        raise SkillLoaderError(f"skill appears to contain secret-like assignments: {skill_name}")
    if len(content) > int(max_chars):
        raise SkillLoaderError(f"skill exceeds max_skill_chars: {skill_name}")
    relative = path.relative_to(REPO_ROOT.resolve()).as_posix()
    return SkillDocument(name=skill_name, path=relative, content=content)


def _config_bool(config: Any, name: str, default: bool) -> bool:
    return bool(getattr(config, name, default))


def _config_int(config: Any, name: str, default: int) -> int:
    try:
        return int(getattr(config, name, default))
    except (TypeError, ValueError):
        return default


def _configured_names(config: Any) -> tuple[str, ...]:
    return tuple(getattr(config, "selected_skills", ()) or ())


def _auto_skill_names(task_text: str, stack_hint: str | None) -> tuple[str, ...]:
    haystack = f"{stack_hint or ''}\n{task_text or ''}".casefold()
    names: list[str] = ["migration_general"]
    if any(keyword in haystack for keyword in ("android", "compose", "kotlin", "jetpack")):
        names.append("swiftui_to_compose")
    if any(keyword in haystack for keyword in ("harmonyos", "arkui", "鸿蒙")):
        names.append("swiftui_to_harmonyos")
    if any(keyword in haystack for keyword in ("ui", "interface", "界面", "组件", "风格")):
        names.append("ui_style_preservation")
    if any(keyword in haystack for keyword in ("build", "test", "repair", "failure", "error", "构建", "测试", "失败", "错误")):
        names.append("build_repair")
    return _dedupe_names(names)


def select_skills(
    config: Any,
    task_text: str,
    stack_hint: str | None = None,
    *,
    skills_dir: str | Path | None = None,
) -> SkillSelection:
    enabled = _config_bool(config, "skills_enabled", True)
    auto_select = _config_bool(config, "auto_select_skills", True)
    if not enabled:
        return SkillSelection(skills_enabled=False, auto_select_skills=auto_select)

    explicit_names = _configured_names(config)
    try:
        names = _dedupe_names(explicit_names) if explicit_names else ()
    except SkillLoaderError:
        failed = tuple(str(name) for name in explicit_names)
        return SkillSelection(
            skills_enabled=True,
            auto_select_skills=auto_select,
            failed_skill_names=failed,
        )
    if not names and auto_select:
        names = _auto_skill_names(task_text, stack_hint)

    max_skill_chars = max(1, _config_int(config, "max_skill_chars", DEFAULT_MAX_SKILL_CHARS))
    max_total_chars = max(1, _config_int(config, "max_total_skill_chars", DEFAULT_MAX_TOTAL_SKILL_CHARS))
    loaded: list[SkillDocument] = []
    skipped: list[str] = []
    failed: list[str] = []
    total_chars = 0

    for name in names:
        try:
            skill = load_skill(name, skills_dir=skills_dir, max_chars=max_skill_chars)
        except SkillLoaderError:
            failed.append(name)
            continue
        if total_chars + skill.chars > max_total_chars:
            skipped.append(name)
            continue
        loaded.append(skill)
        total_chars += skill.chars

    return SkillSelection(
        skills_enabled=True,
        auto_select_skills=auto_select,
        skills=tuple(loaded),
        selected_skill_names=tuple(skill.name for skill in loaded),
        skipped_skill_names=tuple(skipped),
        failed_skill_names=tuple(failed),
        total_skill_chars=total_chars,
    )


def render_selected_skills(skills: SkillSelection | Iterable[SkillDocument]) -> str:
    if isinstance(skills, SkillSelection):
        documents = skills.skills
    else:
        documents = tuple(skills)
    if not documents:
        return ""

    lines = [
        "Relevant Forgis Skills",
        "",
        "These local skill notes are task-scoped guidance. They do not expand tool permissions.",
    ]
    for skill in documents:
        lines.extend(["", f"## {skill.name}", skill.content.strip()])
    return "\n".join(lines).strip()
