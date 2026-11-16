#!/usr/bin/env python3
"""EnvContract — find environment-variable drift without installing anything.

A local, read-only-by-default CLI that maps environment lookups in source and
configuration files against an explicit example file such as .env.example.
Only variable NAMES from the selected example are read; live .env files are
never opened automatically.

Python 3.8+ · Standard library only · MIT
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

__version__ = "1.1.0"

KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ENV_ASSIGNMENT_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")

IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", "node_modules", "vendor",
    "dist", "build", "coverage", "target", "__pycache__", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", ".next", ".nuxt", ".turbo",
}

SOURCE_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue",
    ".svelte", ".go", ".rs", ".java", ".kt", ".kts", ".php", ".rb",
    ".sh", ".bash", ".zsh", ".yaml", ".yml", ".toml", ".tf", ".hcl",
    ".properties", ".dockerfile",
}
SOURCE_NAMES = {"dockerfile", "containerfile", "makefile"}
CONFIG_SUFFIXES = {".yaml", ".yml", ".toml", ".tf", ".hcl", ".properties"}
SHELL_SUFFIXES = {".sh", ".bash", ".zsh"}

# Exact, intentionally conservative access patterns. The engine reports names
# and locations only; it never echoes matched source text or values.
REFERENCE_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r"\b(?:os\.)?(?:getenv|Getenv)\s*\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    re.compile(r"\b(?:os\.)?environ(?:\.get)?\s*(?:\[\s*|\(\s*)['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    re.compile(r"\b(?:process\.env|import\.meta\.env)\.([A-Za-z_][A-Za-z0-9_]*)\b"),
    re.compile(r"\b(?:process\.env|import\.meta\.env)\s*\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]"),
    re.compile(r"\bSystem\.getenv\s*\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    re.compile(r"\b(?:std::)?env::var\s*\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    re.compile(r"\bgetenv\s*\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    re.compile(r"\b\$_(?:ENV|SERVER)\s*\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]"),
    re.compile(r"\bENV\s*\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]"),
)
INTERPOLATION_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
SHELL_VARIABLE_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)\b")

# Common process/shell variables are not application configuration contracts.
BUILTIN_NAMES = {
    "HOME", "PATH", "PWD", "OLDPWD", "USER", "LOGNAME", "SHELL", "TERM",
    "TMP", "TMPDIR", "TEMP", "HOSTNAME", "CI", "LANG", "LC_ALL", "RANDOM",
    "SECONDS", "UID", "EUID", "IFS", "PS1", "SHLVL", "GITHUB_WORKSPACE",
}


@dataclass
class Reference:
    path: str
    line: int


@dataclass
class AuditReport:
    root: str
    example_file: Optional[str]
    used: List[str]
    declared: List[str]
    missing: List[str]
    unused: List[str]
    references: Dict[str, List[Reference]] = field(default_factory=dict)
    duplicate_declarations: List[str] = field(default_factory=list)
    scanned_files: int = 0

    @property
    def clean(self) -> bool:
        return not self.missing and not self.unused and not self.duplicate_declarations

    def as_json(self) -> Dict[str, object]:
        data = asdict(self)
        data["clean"] = self.clean
        return data


class EnvContract:
    """Collect references and compare them with a safe example contract."""

    EXAMPLE_NAMES = (".env.example", ".env.sample", ".env.template", ".env.defaults")

    def __init__(self, root: Path, example: Optional[str] = None, ignores: Optional[List[str]] = None):
        self.root = root.resolve()
        self.example_arg = example
        self.ignore_patterns = list(ignores or [])
        ignore_file = self.root / ".envcontractignore"
        if ignore_file.is_file():
            try:
                self.ignore_patterns.extend(
                    line.strip() for line in ignore_file.read_text(encoding="utf-8", errors="replace").splitlines()
                    if line.strip() and not line.lstrip().startswith("#")
                )
            except OSError:
                pass

    def _is_ignored(self, path: Path) -> bool:
        rel = path.relative_to(self.root).as_posix()
        return any(
            fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(path.name, pattern)
            for pattern in self.ignore_patterns
        )

    def _example_path(self) -> Optional[Path]:
        if self.example_arg:
            path = Path(self.example_arg)
            return path if path.is_absolute() else self.root / path
        for name in self.EXAMPLE_NAMES:
            candidate = self.root / name
            if candidate.is_file():
                return candidate
        return None

    def _source_files(self) -> Iterable[Path]:
        for current, dirs, files in os.walk(self.root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
            for filename in sorted(files):
                path = Path(current) / filename
                if filename.lower() in SOURCE_NAMES or path.suffix.lower() in SOURCE_SUFFIXES:
                    try:
                        if not path.is_symlink() and path.is_file() and path.stat().st_size <= 1024 * 1024:
                            yield path
                    except OSError:
                        continue

    @staticmethod
    def _is_reference_context(path: Path) -> bool:
        suffix = path.suffix.lower()
        return suffix in SHELL_SUFFIXES | CONFIG_SUFFIXES or path.name.lower() in SOURCE_NAMES

    def _read_example_keys(self, path: Optional[Path]) -> Tuple[Set[str], List[str]]:
        if path is None or not path.is_file():
            return set(), []
        keys: Set[str] = set()
        duplicates: List[str] = []
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return set(), []
        for line in lines:
            # Strip comments after the assignment only for parsing the key. Values
            # are intentionally ignored, never stored or included in reports.
            candidate = line.split("#", 1)[0]
            match = ENV_ASSIGNMENT_RE.match(candidate)
            if not match:
                continue
            key = match.group(1)
            if key in keys:
                duplicates.append(key)
            keys.add(key)
        return keys, sorted(set(duplicates))

    def _find_references(self) -> Tuple[Dict[str, List[Reference]], int]:
        found: Dict[str, List[Reference]] = {}
        scanned = 0
        for path in self._source_files():
            if self._is_ignored(path):
                continue
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            scanned += 1
            rel = path.relative_to(self.root).as_posix()
            use_interpolation = self._is_reference_context(path)
            for number, line in enumerate(source.splitlines(), 1):
                names: Set[str] = set()
                for pattern in REFERENCE_PATTERNS:
                    names.update(pattern.findall(line))
                if use_interpolation:
                    names.update(INTERPOLATION_RE.findall(line))
                    if path.suffix.lower() in SHELL_SUFFIXES or path.name.lower() in SOURCE_NAMES:
                        names.update(SHELL_VARIABLE_RE.findall(line))
                for name in names - BUILTIN_NAMES:
                    if not KEY_RE.match(name):
                        continue
                    found.setdefault(name, []).append(Reference(path=rel, line=number))
        return found, scanned

    def audit(self) -> AuditReport:
        example_path = self._example_path()
        declared_set, duplicates = self._read_example_keys(example_path)
        references, scanned = self._find_references()
        used_set = set(references)
        declared = sorted(declared_set)
        used = sorted(used_set)
        example_display = None
        if example_path is not None:
            try:
                example_display = example_path.relative_to(self.root).as_posix()
            except ValueError:
                example_display = str(example_path)
        return AuditReport(
            root=str(self.root),
            example_file=example_display,
            used=used,
            declared=declared,
            missing=sorted(used_set - declared_set),
            unused=sorted(declared_set - used_set),
            references={key: references[key] for key in sorted(references)},
            duplicate_declarations=duplicates,
            scanned_files=scanned,
        )

    def write_example(self, destination: str, force: bool = False) -> Path:
        path = Path(destination)
        if not path.is_absolute():
            path = self.root / path
        if path.exists() and not force:
            raise FileExistsError("refusing to overwrite existing file; pass --force to replace it")
        references, _ = self._find_references()
        lines = ["# Generated by EnvContract. Fill in values locally; do not commit real secrets."]
        lines.extend(f"{key}=" for key in sorted(references))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path


def format_text(report: AuditReport) -> str:
    lines = ["EnvContract · environment contract audit", "─" * 48]
    lines.append(f"Root: {report.root}")
    lines.append(f"Example: {report.example_file or '(not found)'}")
    lines.append(f"Source/config files scanned: {report.scanned_files}")
    lines.append(f"Variables referenced: {len(report.used)} · declared: {len(report.declared)}")
    if report.missing:
        lines.extend(["", "MISSING FROM EXAMPLE"])
        for name in report.missing:
            refs = report.references.get(name, [])
            locations = ", ".join(f"{ref.path}:{ref.line}" for ref in refs[:4])
            suffix = f" (+{len(refs) - 4} more)" if len(refs) > 4 else ""
            lines.append(f"  + {name:<28} {locations}{suffix}")
    if report.unused:
        lines.extend(["", "DECLARED BUT UNUSED"])
        lines.extend(f"  - {name}" for name in report.unused)
    if report.duplicate_declarations:
        lines.extend(["", "DUPLICATE DECLARATIONS"])
        lines.extend(f"  ! {name}" for name in report.duplicate_declarations)
    if report.clean:
        lines.extend(["", "✓ Contract is in sync."])
    else:
        lines.extend(["", "Run `envcontract --write-example` to generate a blank template."])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="EnvContract — detect environment-variable drift; no dependencies, no secret values read.",
        epilog="Examples:\n  envcontract . --check\n  envcontract . --example deploy/.env.example --format json\n  envcontract . --write-example .env.example",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("path", nargs="?", default=".", help="Repository root (default: current directory)")
    parser.add_argument("--example", help="Explicit example file to compare (default: auto-detect .env.example/.env.sample/.env.template)")
    parser.add_argument("--ignore", action="append", default=[], metavar="GLOB", help="Skip a source path glob (repeatable; .envcontractignore is also read)")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="Report format")
    parser.add_argument("--check", action="store_true", help="Return exit code 1 if contract drift is detected")
    parser.add_argument("--write-example", metavar="PATH", help="Write a blank template containing discovered variable names")
    parser.add_argument("--force", action="store_true", help="Allow --write-example to replace an existing file")
    parser.add_argument("--version", action="version", version=f"EnvContract {__version__}")
    args = parser.parse_args(argv)

    root = Path(args.path).resolve()
    if not root.is_dir():
        parser.error(f"repository root is not a directory: {root}")
    tool = EnvContract(root, args.example, args.ignore)
    if args.write_example:
        try:
            target = tool.write_example(args.write_example, force=args.force)
            print(f"Wrote blank environment template: {target}", file=sys.stderr)
        except (OSError, FileExistsError) as exc:
            parser.error(str(exc))
        # Use the newly written template as the contract for the report.
        tool = EnvContract(root, str(target), args.ignore)

    report = tool.audit()
    if args.format == "json":
        print(json.dumps(report.as_json(), indent=2, ensure_ascii=False))
    else:
        print(format_text(report))
    return 1 if args.check and not report.clean else 0


if __name__ == "__main__":
    raise SystemExit(main())
