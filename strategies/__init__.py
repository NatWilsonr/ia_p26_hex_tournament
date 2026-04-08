"""Auto-discovery of Strategy subclasses.

Scans two locations:
  1. Built-in strategies in this ``strategies/`` package.
  2. Student submissions under ``estudiantes/<team>/strategy.py``.
"""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import sys
from pathlib import Path

from strategy import Strategy

_PKG_DIR = Path(__file__).resolve().parent
# strategies/ -> repo root
_REPO_ROOT = _PKG_DIR.parent
_STUDENTS_DIR = _REPO_ROOT / "estudiantes"


def _subclasses_in_module(mod) -> list[type[Strategy]]:
    found: list[type[Strategy]] = []
    for attr_name in dir(mod):
        obj = getattr(mod, attr_name)
        if (
            isinstance(obj, type)
            and issubclass(obj, Strategy)
            and obj is not Strategy
        ):
            found.append(obj)
    return found


def _discover_builtin() -> list[type[Strategy]]:
    """Import all modules (.py and .so) in this package."""
    found: list[type[Strategy]] = []
    for info in pkgutil.iter_modules([str(_PKG_DIR)]):
        try:
            mod = importlib.import_module(f"strategies.{info.name}")
            found.extend(_subclasses_in_module(mod))
        except ImportError:
            print(f"  [info] {info.name} requires Docker — skipped")
    return found


def _discover_students(
    team_filter: str | None = None,
) -> list[type[Strategy]]:
    """Scan ``estudiantes/<team>/strategy.py`` for Strategy subclasses.

    Parameters
    ----------
    team_filter : str or None
        If provided, only load from ``estudiantes/<team_filter>/``.
        Otherwise load from all team directories.
    """
    found: list[type[Strategy]] = []
    if not _STUDENTS_DIR.is_dir():
        return found

    for team_dir in sorted(_STUDENTS_DIR.iterdir()):
        if not team_dir.is_dir():
            continue
        # Skip template and hidden directories
        if team_dir.name.startswith("_") or team_dir.name.startswith("."):
            continue
        # Apply team filter
        if team_filter and team_dir.name != team_filter:
            continue

        # Prefer compiled .so over .py
        so_files = list(team_dir.glob("strategy.cpython-*.so")) + list(team_dir.glob("strategy.*.so"))
        strategy_file = so_files[0] if so_files else team_dir / "strategy.py"
        if not strategy_file.exists():
            continue

        mod_name = f"student_{team_dir.name}_strategy"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, strategy_file)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
            found.extend(_subclasses_in_module(mod))
        except Exception as exc:
            print(f"  [warn] failed to load {strategy_file}: {exc}")

    return found


def discover_strategies(
    team_filter: str | None = None,
) -> list[type[Strategy]]:
    """Return all Strategy subclasses (built-in + student submissions)."""
    return _discover_builtin() + _discover_students(team_filter=team_filter)
