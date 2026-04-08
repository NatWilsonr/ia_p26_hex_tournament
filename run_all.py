#!/usr/bin/env python3
"""One-command launcher: tournament runner.

Usage:
    # Quick test (classic variant, 3 games per pair)
    python3 run_all.py

    # Full official tournament (both variants)
    python3 run_all.py --official

    # Real evaluation tournament (all students, more games)
    python3 run_all.py --real

    # Your team vs defaults
    python3 run_all.py --team mi_equipo
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent


def _run(cmd: list[str], check: bool = True) -> int:
    """Run a command, streaming output."""
    print(f"\n>>> {' '.join(cmd)}\n", flush=True)
    result = subprocess.run(cmd, cwd=str(_DIR))
    if check and result.returncode != 0:
        print(f"\nCommand failed with exit code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-command Hex tournament launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  python3 run_all.py                          # quick test (classic, 3 games)
  python3 run_all.py --official               # both variants, 5 games/pair
  python3 run_all.py --real                   # class evaluation (10 games/pair)
  python3 run_all.py --real --num-games 20    # class evaluation, 20 games/pair
  python3 run_all.py --team mi_equipo         # your team vs defaults
""",
    )
    parser.add_argument("--num-games", type=int, default=None,
                        help="Games per pair per variant (default: 4 quick/official, 10 real)")
    parser.add_argument("--real", action="store_true",
                        help="Real evaluation tournament: both variants, 10 games/pair, "
                             "eval mode (students vs defaults only)")
    parser.add_argument("--official", action="store_true",
                        help="Official tournament: both variants")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducibility")
    parser.add_argument("--team", type=str, default=None,
                        help="Only run this team + defaults")
    parser.add_argument("--board-size", type=int, default=11,
                        help="Board side length (default: 11)")
    parser.add_argument("--move-timeout", type=float, default=None,
                        help="Override seconds per move (default: 15)")
    args = parser.parse_args()

    # ── Run tournament ────────────────────────────────────
    print("\n" + "=" * 60)
    if args.real:
        print("  RUNNING REAL EVALUATION TOURNAMENT")
    elif args.official:
        print("  RUNNING OFFICIAL TOURNAMENT")
    else:
        print("  RUNNING QUICK TOURNAMENT")
    print("=" * 60, flush=True)

    cmd = [sys.executable, "tournament.py"]

    if args.real:
        cmd.append("--official")
        cmd.append("--eval")
        num_games = args.num_games or 10
        move_timeout = args.move_timeout or 15.0
    elif args.official:
        cmd.append("--official")
        num_games = args.num_games or 4
        move_timeout = args.move_timeout or 15.0
    else:
        num_games = args.num_games or 4
        move_timeout = args.move_timeout or 15.0

    cmd += ["--num-games", str(num_games)]
    cmd += ["--move-timeout", str(move_timeout)]
    cmd += ["--board-size", str(args.board_size)]

    if args.seed is not None:
        cmd += ["--seed", str(args.seed)]

    if args.team:
        cmd += ["--team", args.team]

    _run(cmd)

    # ── Summary ───────────────────────────────────────────
    print("\n" + "-" * 60)
    if args.team:
        print(f"  Results saved to: estudiantes/{args.team}/results/")
    else:
        print(f"  Results saved to: results/runs/ (+ results/latest.json)")
    print("-" * 60)


if __name__ == "__main__":
    main()
