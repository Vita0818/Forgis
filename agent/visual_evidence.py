from __future__ import annotations

import dataclasses
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


REFERENCE_AND_ACTUAL = "REFERENCE_AND_ACTUAL"
REFERENCE_ONLY = "REFERENCE_ONLY"
ACTUAL_ONLY = "ACTUAL_ONLY"
NO_VISUAL_EVIDENCE = "NO"

VISUAL_EVIDENCE_STATES = frozenset(
    {
        REFERENCE_AND_ACTUAL,
        REFERENCE_ONLY,
        ACTUAL_ONLY,
        NO_VISUAL_EVIDENCE,
    }
)

QWEN_PERMISSION_GATED = "QWEN_PERMISSION_GATED"
QWEN_UNAVAILABLE_IN_SESSION = "QWEN_UNAVAILABLE_IN_SESSION"
BLOCKED_BY_NO_EMULATOR = "BLOCKED_BY_NO_EMULATOR"
BLOCKED_BY_DEVECO_OR_DEVICE = "BLOCKED_BY_DEVECO_OR_DEVICE"
SCREENSHOT_BLOCKED_BY_SCREEN_RECORDING = "SCREENSHOT_BLOCKED_BY_SCREEN_RECORDING"
HOST_ENV_BLOCKED = "HOST_ENV_BLOCKED"
WINDOWS_HOST_VALIDATION_PENDING = "WINDOWS_HOST_VALIDATION_PENDING"
VISUAL_VALIDATION_DISABLED = "VISUAL_VALIDATION_DISABLED"
VISUAL_REPORT_INCOMPLETE = "VISUAL_REPORT_INCOMPLETE"
NO_REFERENCE_SCREENSHOTS_FOUND = "NO_REFERENCE_SCREENSHOTS_FOUND"

VISUAL_BLOCKER_REASONS = frozenset(
    {
        QWEN_PERMISSION_GATED,
        QWEN_UNAVAILABLE_IN_SESSION,
        BLOCKED_BY_NO_EMULATOR,
        BLOCKED_BY_DEVECO_OR_DEVICE,
        SCREENSHOT_BLOCKED_BY_SCREEN_RECORDING,
        HOST_ENV_BLOCKED,
        WINDOWS_HOST_VALIDATION_PENDING,
        VISUAL_VALIDATION_DISABLED,
        VISUAL_REPORT_INCOMPLETE,
        NO_REFERENCE_SCREENSHOTS_FOUND,
    }
)

ALLOWED_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
FORBIDDEN_IMAGE_SUFFIXES = frozenset(
    {
        ".env",
        ".pem",
        ".key",
        ".p12",
        ".pfx",
        ".mobileprovision",
        ".cer",
        ".crt",
    }
)
SOURCE_TEXT_SUFFIXES = frozenset(
    {
        ".py",
        ".swift",
        ".kt",
        ".java",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".yml",
        ".yaml",
        ".json",
        ".md",
        ".txt",
    }
)

SECRET_PART_RE = re.compile(
    r"(secret|token|credential|password|api[_-]?key|private|\.env|\.ssh|\.npmrc|\.pypirc|\.netrc)",
    re.IGNORECASE,
)
SECRET_VALUE_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|CREDENTIAL|API[_-]?KEY|PRIVATE)[A-Z0-9_]*)\s*[:=]\s*([^\s,;]+)"
)
WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
SAFE_SLUG_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


@dataclasses.dataclass(frozen=True)
class VisualEvidencePaths:
    root: Path
    reference_dir: Path
    actual_dir: Path
    qwen_dir: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "root": self.root.as_posix(),
            "reference_dir": self.reference_dir.as_posix(),
            "actual_dir": self.actual_dir.as_posix(),
            "qwen_dir": self.qwen_dir.as_posix(),
        }


@dataclasses.dataclass(frozen=True)
class VisualEvidenceSummary:
    required: bool
    provider: str
    state: str
    reference_screenshots_used: tuple[str, ...]
    actual_screenshots: tuple[str, ...]
    compare_screenshots_completed: bool
    blocker: str | None = None
    limitations: str | None = None

    def __post_init__(self) -> None:
        state = str(self.state or NO_VISUAL_EVIDENCE).strip()
        if state not in VISUAL_EVIDENCE_STATES:
            raise ValueError(f"Unsupported visual evidence state: {state}")
        blocker = None if self.blocker in {None, ""} else str(self.blocker).strip()
        if blocker is not None and blocker not in VISUAL_BLOCKER_REASONS:
            raise ValueError(f"Unsupported visual evidence blocker: {blocker}")
        object.__setattr__(self, "provider", sanitize_visual_text(self.provider, limit=80) or "qwen")
        object.__setattr__(
            self,
            "reference_screenshots_used",
            tuple(sanitize_visual_path_label(path) for path in self.reference_screenshots_used),
        )
        object.__setattr__(
            self,
            "actual_screenshots",
            tuple(sanitize_visual_path_label(path) for path in self.actual_screenshots),
        )
        object.__setattr__(self, "blocker", blocker)
        object.__setattr__(self, "limitations", sanitize_visual_text(self.limitations, limit=500) or None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "required": bool(self.required),
            "provider": self.provider,
            "state": self.state,
            "reference_screenshots_used": list(self.reference_screenshots_used),
            "actual_screenshots": list(self.actual_screenshots),
            "compare_screenshots_completed": bool(self.compare_screenshots_completed),
            "blocker": self.blocker,
            "limitations": self.limitations,
        }


def sanitize_visual_text(value: Any, *, limit: int = 500) -> str:
    text = str(value if value is not None else "")
    text = text.replace("\x00", "").replace("\r", " ").replace("\n", " ").strip()
    text = SECRET_VALUE_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    text = SECRET_PART_RE.sub("[redacted]", text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def sanitize_visual_path_label(value: Any, *, limit: int = 220) -> str:
    text = str(value if value is not None else "").replace("\\", "/")
    text = text.replace("\x00", "").replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return ""
    if text.startswith("/") or WINDOWS_ABSOLUTE_RE.match(text):
        name = PurePosixPath(text).name
        text = name if name else "[path-redacted]"
    parts: list[str] = []
    for part in PurePosixPath(text.strip("/")).parts:
        if part in {"", ".", "..", ".git"}:
            continue
        parts.append("[redacted]" if _is_secret_like_part(part) else part)
    cleaned = "/".join(parts) or "[path-redacted]"
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:120] + ".../" + cleaned[-80:]


def _is_secret_like_part(part: str) -> bool:
    lowered = part.casefold()
    return (
        lowered in {"id_rsa", "id_ed25519", ".ssh"}
        or lowered.endswith(tuple(FORBIDDEN_IMAGE_SUFFIXES))
        or bool(SECRET_PART_RE.search(part))
    )


def _is_safe_system_private_part(parts: tuple[str, ...], index: int) -> bool:
    return index == 1 and len(parts) > 1 and parts[0] == "/" and parts[index].casefold() == "private"


def _is_unsafe_path_part(parts: tuple[str, ...], index: int) -> bool:
    part = parts[index]
    if _is_safe_system_private_part(parts, index):
        return False
    return part in {"", ".", "..", ".git"} or _is_secret_like_part(part)


def _is_forbidden_home_path(path: Path) -> bool:
    try:
        home = Path.home().resolve()
    except OSError:
        return False
    forbidden = [home / "Desktop", home / "Downloads", home / "Documents"]
    return any(path == item or path.is_relative_to(item) for item in forbidden)


def _safe_slug_part(value: str, label: str) -> str:
    part = value.strip()
    if not part:
        raise ValueError(f"{label} contains an empty segment.")
    if part in {".", "..", ".git"}:
        raise ValueError(f"{label} contains an unsafe segment: {part}")
    if _is_secret_like_part(part):
        raise ValueError(f"{label} must not contain secret-like segments.")
    if not SAFE_SLUG_PART_RE.fullmatch(part):
        raise ValueError(f"{label} contains an unsafe segment: {part}")
    return part


def safe_target_repo_slug(target_repo: Any) -> str:
    text = str(target_repo if target_repo is not None else "").strip()
    if not text:
        raise ValueError("target_repo slug is required.")
    if "\x00" in text or "\n" in text or "\r" in text or "\\" in text:
        raise ValueError("target_repo slug contains an unsafe character.")
    if text.startswith("/") or text.startswith("~") or WINDOWS_ABSOLUTE_RE.match(text):
        raise ValueError("target_repo slug must not be an absolute path.")
    parts = [_safe_slug_part(part, "target_repo slug") for part in text.split("/")]
    slug = "__".join(parts)
    if not slug:
        raise ValueError("target_repo slug is empty.")
    return slug


def safe_run_id_slug(run_id: Any) -> str:
    text = str(run_id if run_id is not None else "").strip()
    if not text:
        raise ValueError("visual evidence run_id is required.")
    if "\x00" in text or "\n" in text or "\r" in text or "/" in text or "\\" in text:
        raise ValueError("visual evidence run_id must be a safe slug.")
    if text.startswith("/") or text.startswith("~") or WINDOWS_ABSOLUTE_RE.match(text):
        raise ValueError("visual evidence run_id must not be an absolute path.")
    return _safe_slug_part(text, "visual evidence run_id")


def _reject_if_inside(candidate: Path, forbidden_root: Path | None, label: str) -> None:
    if forbidden_root is None:
        return
    root = forbidden_root.resolve()
    if candidate == root or candidate.is_relative_to(root):
        raise ValueError(f"visual evidence root must not be inside the {label}.")


def _validate_evidence_root(candidate: Path, *, source_root: Path | None, target_root: Path | None) -> None:
    if _is_forbidden_home_path(candidate):
        raise ValueError("visual evidence root must not be Desktop, Downloads, or Documents.")
    if any(_is_unsafe_path_part(candidate.parts, index) for index, _part in enumerate(candidate.parts)):
        raise ValueError("visual evidence root contains an unsafe or secret-like path segment.")
    _reject_if_inside(candidate, source_root, "source repository")
    _reject_if_inside(candidate, target_root, "target repository")


def create_visual_evidence_paths(
    *,
    runtime_root: str | Path,
    run_id: str,
    target_repo: str,
    source_root: str | Path | None = None,
    target_root: str | Path | None = None,
    create: bool = True,
) -> VisualEvidencePaths:
    runtime = Path(runtime_root).expanduser().resolve()
    run_slug = safe_run_id_slug(run_id)
    repo_slug = safe_target_repo_slug(target_repo)
    root = (runtime / "visual-evidence" / run_slug / repo_slug).resolve()
    if not root.is_relative_to(runtime):
        raise ValueError("visual evidence root must stay inside runtime_root.")
    _validate_evidence_root(
        root,
        source_root=None if source_root is None else Path(source_root),
        target_root=None if target_root is None else Path(target_root),
    )
    paths = VisualEvidencePaths(
        root=root,
        reference_dir=root / "reference",
        actual_dir=root / "actual",
        qwen_dir=root / "qwen",
    )
    if create:
        for directory in (paths.reference_dir, paths.actual_dir, paths.qwen_dir):
            directory.mkdir(parents=True, exist_ok=True)
    return paths


def classify_visual_evidence(reference_paths: Iterable[Any], actual_paths: Iterable[Any]) -> str:
    has_reference = bool(tuple(reference_paths or ()))
    has_actual = bool(tuple(actual_paths or ()))
    if has_reference and has_actual:
        return REFERENCE_AND_ACTUAL
    if has_reference:
        return REFERENCE_ONLY
    if has_actual:
        return ACTUAL_ONLY
    return NO_VISUAL_EVIDENCE


def validate_visual_image_path(
    image_path: str | Path,
    *,
    allowed_root: str | Path | None = None,
    must_exist: bool = False,
) -> Path:
    raw_text = str(image_path if image_path is not None else "").strip()
    if not raw_text:
        raise ValueError("visual image path is required.")
    if "\x00" in raw_text or "\n" in raw_text or "\r" in raw_text:
        raise ValueError("visual image path contains an unsafe character.")
    path = Path(raw_text).expanduser()
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise ValueError("visual image path could not be resolved.") from exc
    if allowed_root is not None:
        root = Path(allowed_root).expanduser().resolve()
        if resolved != root and not resolved.is_relative_to(root):
            raise ValueError("visual image path must stay inside the visual evidence root.")
    if _is_forbidden_home_path(resolved):
        raise ValueError("visual image path must not be under Desktop, Downloads, or Documents.")
    for index, _part in enumerate(resolved.parts):
        if _is_unsafe_path_part(resolved.parts, index):
            raise ValueError("visual image path contains an unsafe or secret-like path segment.")
    suffix = resolved.suffix.casefold()
    if suffix in FORBIDDEN_IMAGE_SUFFIXES:
        raise ValueError("visual image path points at a forbidden secret/certificate file type.")
    if suffix in SOURCE_TEXT_SUFFIXES:
        raise ValueError("visual image path must not point at source, config, text, or markdown files.")
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise ValueError("visual image path must be .png, .jpg, .jpeg, or .webp.")
    if must_exist:
        if not resolved.exists():
            raise ValueError("visual image path does not exist.")
        if not resolved.is_file():
            raise ValueError("visual image path must be a file.")
    return resolved
