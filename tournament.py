#!/usr/bin/env python3
"""Run head-to-head Hex tournament with league scoring.

Features:
  - Separate-process referee (unhackable isolation via JSON pipes).
  - Two leagues: classic + dark, combined standings.
  - 4 games per pair per variant (2 as Black, 2 as White).
  - Win=1, Loss=0 scoring. Top 3 students by total pts → auto 10.
  - Count-based grading: grade = 4 + N models beaten (0 if none).
  - JSONL persistence, config, grades CSV/JSON.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time as _time_mod
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from referee import run_match_referee, MatchRecord

RESULTS_DIR = Path(__file__).resolve().parent / "results"

# Default baselines in difficulty order
DEFAULT_TIERS = [
    "Random",
    "MCTS_Tier_1",
    "MCTS_Tier_2",
    "MCTS_Tier_3",
    "MCTS_Tier_4",
    "MCTS_Tier_5",
]

# ------------------------------------------------------------------
# League table computation
# ------------------------------------------------------------------

@dataclass
class LeagueEntry:
    strategy: str
    wins: int = 0
    losses: int = 0
    points: int = 0
    rank: int = 0


def compute_league_table(
    matches: list[MatchRecord],
    variant: str,
) -> list[LeagueEntry]:
    """Compute league standings for a single variant."""
    wins: dict[str, int] = defaultdict(int)
    losses: dict[str, int] = defaultdict(int)
    strategies: set[str] = set()

    for m in matches:
        if m.variant != variant:
            continue
        strategies.add(m.black_strategy)
        strategies.add(m.white_strategy)
        wins[m.winner_strategy] += 1
        loser = m.white_strategy if m.winner_strategy == m.black_strategy else m.black_strategy
        losses[loser] += 1

    entries = []
    for s in sorted(strategies):
        entries.append(LeagueEntry(
            strategy=s,
            wins=wins[s],
            losses=losses[s],
            points=wins[s],
        ))

    # Sort by points descending
    entries.sort(key=lambda e: -e.points)
    for i, e in enumerate(entries):
        e.rank = i + 1

    return entries


@dataclass
class CombinedEntry:
    strategy: str
    classic_pts: int = 0
    dark_pts: int = 0
    total_pts: int = 0
    classic_rank: int = 0
    dark_rank: int = 0
    avg_rank: float = 0.0


def compute_combined_standings(
    classic_table: list[LeagueEntry],
    dark_table: list[LeagueEntry],
) -> list[CombinedEntry]:
    """Merge classic and dark leagues into combined standings."""
    classic_map = {e.strategy: e for e in classic_table}
    dark_map = {e.strategy: e for e in dark_table}
    all_strats = set(classic_map.keys()) | set(dark_map.keys())

    entries = []
    for s in all_strats:
        c = classic_map.get(s)
        d = dark_map.get(s)
        c_pts = c.points if c else 0
        d_pts = d.points if d else 0
        c_rank = c.rank if c else len(classic_table) + 1
        d_rank = d.rank if d else len(dark_table) + 1
        entries.append(CombinedEntry(
            strategy=s,
            classic_pts=c_pts,
            dark_pts=d_pts,
            total_pts=c_pts + d_pts,
            classic_rank=c_rank,
            dark_rank=d_rank,
            avg_rank=(c_rank + d_rank) / 2.0,
        ))

    # Sort: total_pts desc, avg_rank asc
    entries.sort(key=lambda e: (-e.total_pts, e.avg_rank))
    return entries


# ------------------------------------------------------------------
# Grades: count-based + top-3 auto-10
# ------------------------------------------------------------------

def compute_grades(
    combined: list[CombinedEntry],
) -> list[dict]:
    """Compute grades from league position.

    A student "beats" a model when their total_pts >= the model's total_pts
    (tie = student gets the credit).  Grade = 5 for the first model beaten,
    +1 for each additional model beaten (max 10 with 6 models).
    Top 3 students by total pts → auto 10.
    """
    defaults_set = set(DEFAULT_TIERS)

    # Get each model's total_pts from the combined standings
    model_pts: dict[str, int] = {}
    for e in combined:
        if e.strategy in defaults_set:
            model_pts[e.strategy] = e.total_pts

    grades = []
    for e in combined:
        if e.strategy in defaults_set:
            continue  # Only grade students

        beaten = []
        for tier in DEFAULT_TIERS:
            tier_pts = model_pts.get(tier)
            if tier_pts is not None and e.total_pts >= tier_pts:
                beaten.append(tier)

        n_beaten = len(beaten)
        score = (4 + n_beaten) if n_beaten > 0 else 0

        grades.append({
            "strategy": e.strategy,
            "score": score,
            "beaten": beaten,
            "total_wins": e.total_pts,
            "league_rank": next(
                (i + 1 for i, x in enumerate(combined) if x.strategy == e.strategy),
                0,
            ),
        })

    grades.sort(key=lambda x: (-x["score"], -x["total_wins"]))

    # Auto-10: top 3 students by total pts (requires ≥3 students)
    if len(grades) >= 3:
        pts_values = sorted({g["total_wins"] for g in grades}, reverse=True)
        top3_threshold = pts_values[min(2, len(pts_values) - 1)]
        if top3_threshold > 0:
            for g in grades:
                if g["total_wins"] >= top3_threshold and g["score"] < 10:
                    g["score"] = 10
                    g["auto_10"] = True

    grades.sort(key=lambda x: (-x["score"], -x["total_wins"]))
    return grades


# ------------------------------------------------------------------
# Printing
# ------------------------------------------------------------------

def print_league_table(table: list[LeagueEntry], variant: str) -> None:
    print(f"\n{'='*55}")
    print(f"  {variant.upper()} LEAGUE")
    print(f"{'='*55}")
    print(f"  {'Rank':>4}  {'Strategy':<25} {'Wins':>5} {'Losses':>6} {'Pts':>5}")
    print(f"  {'-'*50}")
    for e in table:
        print(f"  {e.rank:>4}  {e.strategy:<25} {e.wins:>5} {e.losses:>6} {e.points:>5}")
    print()


def print_combined_standings(entries: list[CombinedEntry]) -> None:
    print(f"\n{'='*80}")
    print(f"  COMBINED STANDINGS")
    print(f"{'='*80}")
    print(f"  {'Strategy':<25} {'Classic':>7} {'Dark':>5} {'Total':>6} "
          f"{'C.Rank':>7} {'D.Rank':>7} {'AvgRnk':>7}")
    print(f"  {'-'*70}")
    for e in entries:
        print(f"  {e.strategy:<25} {e.classic_pts:>7} {e.dark_pts:>5} {e.total_pts:>6} "
              f"{e.classic_rank:>7} {e.dark_rank:>7} {e.avg_rank:>7.1f}")
    print()


def print_grades(grades: list[dict]) -> None:
    print(f"\n{'='*72}")
    print(f"  GRADES (models beaten)")
    print(f"{'='*72}")
    print(f"  {'Strategy':<25}{'Score':>7}{'League Pts':>11}  Models beaten")
    print(f"  {'-'*65}")
    for g in grades:
        beaten = ", ".join(g["beaten"]) if g["beaten"] else "none"
        auto = " (auto-10: top 3)" if g.get("auto_10") else ""
        print(f"  {g['strategy']:<25}{g['score']:>7}{g['total_wins']:>11}  {beaten}{auto}")
    print()

    top3 = [g for g in grades if g.get("auto_10")]
    if top3:
        print("  TOP 3 (auto-10):")
        for i, g in enumerate(top3[:3]):
            medal = ["#1", "#2", "#3"][i]
            print(f"    {medal} {g['strategy']} — score: {g['score']}, "
                  f"league pts: {g['total_wins']}")
        print()


def print_matchup_table(matches: list[MatchRecord], variant: str | None = None) -> None:
    """Print head-to-head results."""
    w: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    g: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for m in matches:
        if variant and m.variant != variant:
            continue
        a, b = m.black_strategy, m.white_strategy
        g[a][b] += 1
        g[b][a] += 1
        winner = m.winner_strategy
        loser = b if winner == a else a
        w[winner][loser] += 1

    strats = sorted(set(s for pair in g.values() for s in pair) | set(g.keys()))
    label = f" ({variant})" if variant else ""

    print(f"\n{'MATCHUP TABLE' + label + ' (wins / games)':^60}")
    header = f"{'':20}" + "".join(f"{s[:12]:>14}" for s in strats)
    print(header)
    print("-" * len(header))
    for a in strats:
        row = f"{a[:19]:<20}"
        for b in strats:
            if a == b:
                row += f"{'---':>14}"
            else:
                total = g[a].get(b, 0)
                won = w[a].get(b, 0)
                row += f"{f'{won}/{total}':>14}" if total > 0 else f"{'':>14}"
        print(row)
    print()


# ------------------------------------------------------------------
# Match runner wrapper (for ProcessPoolExecutor)
# ------------------------------------------------------------------

def _run_referee_match(
    black_info: tuple[str, str],
    white_info: tuple[str, str],
    board_size: int,
    variant: str,
    seed: int,
    move_timeout: float,
    memory_limit_mb: int,
) -> MatchRecord:
    """Wrapper for run_match_referee to use with ProcessPoolExecutor."""
    return run_match_referee(
        black_info=black_info,
        white_info=white_info,
        board_size=board_size,
        variant=variant,
        seed=seed,
        move_timeout=move_timeout,
        memory_limit_mb=memory_limit_mb,
    )


# ------------------------------------------------------------------
# Tournament runner
# ------------------------------------------------------------------

def run_tournament(
    strategies_info: list[tuple[tuple[str, str], str]],
    board_size: int = 11,
    variant: str = "classic",
    num_games: int = 4,
    seed: int = 42,
    max_workers: int | None = None,
    move_timeout: float = 15.0,
    memory_limit_mb: int = 8192,
    eval_mode: bool = False,
) -> list[MatchRecord]:
    """Run a tournament for a single variant.

    Parameters
    ----------
    strategies_info : list
        Each element is ((source, class_name), display_name).
    num_games : int
        Games per pair (must be even for color balance).
    eval_mode : bool
        If True, only student strategies play against defaults.
    """
    if num_games % 2 != 0:
        num_games += 1
        print(f"  [Note] num_games adjusted to {num_games} (must be even for color balance)")

    rng = random.Random(seed)

    if max_workers is None:
        max_workers = min(8, os.cpu_count() or 4)

    strat_by_name = {name: info for info, name in strategies_info}

    if eval_mode:
        defaults = {name for name in strat_by_name if name in DEFAULT_TIERS}
        students = {name for name in strat_by_name if name not in defaults}
        pairs = [(s, d) for s in students for d in defaults]
    else:
        names = list(strat_by_name.keys())
        pairs = [(names[i], names[j]) for i in range(len(names)) for j in range(i + 1, len(names))]

    # Build match schedule: 2 as Black + 2 as White per pair
    matches_to_run = []
    for a_name, b_name in pairs:
        for game_idx in range(num_games):
            game_seed = rng.randint(0, 2**31)
            half = num_games // 2
            if game_idx < half:
                black_name, white_name = a_name, b_name
            else:
                black_name, white_name = b_name, a_name
            matches_to_run.append((
                strat_by_name[black_name], black_name,
                strat_by_name[white_name], white_name,
                game_seed,
            ))

    total_matches = len(matches_to_run)
    print(f"Running {total_matches} games "
          f"({len(pairs)} pairs × {num_games} games, "
          f"variant: {variant}, "
          f"board: {board_size}×{board_size}, "
          f"workers: {max_workers}, "
          f"timeout: {move_timeout}s/move) ...", flush=True)

    results: list[MatchRecord] = []

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for black_info, black_name, white_info, white_name, game_seed in matches_to_run:
            fut = executor.submit(
                _run_referee_match,
                black_info,
                white_info,
                board_size,
                variant,
                game_seed,
                move_timeout,
                memory_limit_mb,
            )
            futures[fut] = (black_name, white_name)

        completed = 0
        for fut in as_completed(futures):
            black_name, white_name = futures[fut]
            completed += 1
            try:
                match_result = fut.result()
                results.append(match_result)
                if completed % 10 == 0 or completed == total_matches:
                    print(f"  [{completed}/{total_matches}] "
                          f"{match_result.black_strategy} vs {match_result.white_strategy} → "
                          f"{match_result.winner_strategy} wins "
                          f"({match_result.num_moves} moves, "
                          f"{match_result.duration_s:.1f}s)", flush=True)
            except Exception as exc:
                print(f"  [{completed}/{total_matches}] "
                      f"{black_name} vs {white_name} FAILED: {exc}", file=sys.stderr)

    return results


# ------------------------------------------------------------------
# Persistence
# ------------------------------------------------------------------

def _match_record_to_dict(m: MatchRecord) -> dict:
    """Convert MatchRecord to JSON-serializable dict."""
    d = asdict(m)
    # Convert move_log MoveRecord dataclasses
    d["move_log"] = [
        {
            "move_number": ml["move_number"],
            "player": ml["player"],
            "cell": ml["cell"],
            "time_s": ml["time_s"],
            "result": ml["result"],
        }
        for ml in d["move_log"]
    ]
    return d


def save_results(
    run_dir: Path,
    all_matches: list[MatchRecord],
    classic_table: list[LeagueEntry],
    dark_table: list[LeagueEntry],
    combined: list[CombinedEntry],
    grades: list[dict],
    config: dict,
) -> None:
    """Save all tournament results to the run directory."""
    run_dir.mkdir(parents=True, exist_ok=True)

    # config.json
    (run_dir / "config.json").write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # games.jsonl (streamed, crash-safe)
    with (run_dir / "games.jsonl").open("w", encoding="utf-8") as f:
        for i, m in enumerate(all_matches):
            record = _match_record_to_dict(m)
            record["game_id"] = i + 1
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # League tables
    (run_dir / "classic_league.json").write_text(
        json.dumps([asdict(e) for e in classic_table], indent=2), encoding="utf-8"
    )
    (run_dir / "dark_league.json").write_text(
        json.dumps([asdict(e) for e in dark_table], indent=2), encoding="utf-8"
    )

    # Combined standings
    (run_dir / "combined_standings.json").write_text(
        json.dumps([asdict(e) for e in combined], indent=2), encoding="utf-8"
    )

    # Grades
    (run_dir / "grades.json").write_text(
        json.dumps(grades, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Grades CSV
    with (run_dir / "grades.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "grade", "tier_beaten", "total_wins", "league_rank"])
        for g in grades:
            tier = g["beaten"][-1] if g["beaten"] else "none"
            writer.writerow([g["strategy"], g["score"], tier, g["total_wins"], ""])

    # Summary
    with (run_dir / "summary.txt").open("w", encoding="utf-8") as f:
        f.write(f"Tournament: {config.get('timestamp', '')}\n")
        f.write(f"Board: {config.get('board_size', 11)}×{config.get('board_size', 11)}\n")
        f.write(f"Games/pair/variant: {config.get('games_per_pair', 4)}\n")
        f.write(f"Timeout: {config.get('move_timeout', 10.0)}s/move\n")
        f.write(f"Strategies: {config.get('num_strategies', '?')}\n")
        f.write(f"Total games: {len(all_matches)}\n\n")
        f.write("Combined Standings:\n")
        for e in combined:
            f.write(f"  {e.strategy}: {e.total_pts} pts "
                    f"(classic={e.classic_pts}, dark={e.dark_pts}, "
                    f"avg_rank={e.avg_rank:.1f})\n")
        f.write("\nGrades:\n")
        for g in grades:
            f.write(f"  {g['strategy']}: {g['score']}\n")

    # Latest symlink
    results_dir = run_dir.parent.parent
    latest = results_dir / "latest"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(run_dir)
    except OSError:
        pass

    # History append
    history_path = results_dir / "history.jsonl"
    top3 = [g["strategy"] for g in grades[:3]]
    history_entry = {
        "timestamp": config.get("timestamp", ""),
        "num_strategies": config.get("num_strategies", 0),
        "num_games": len(all_matches),
        "top_3": top3,
        "path": str(run_dir),
    }
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(history_entry, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hex strategy tournament (league format)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  python tournament.py                                    # quick: classic only, 4 games/pair
  python tournament.py --variant dark                     # dark hex only
  python tournament.py --official                         # both variants (classic + dark)
  python tournament.py --official --num-games 4           # 4 games per pair per variant
  python tournament.py --team my_team                     # your team vs defaults
  python tournament.py --eval                             # students vs defaults only
""",
    )
    parser.add_argument("--board-size", type=int, default=11)
    parser.add_argument("--variant", choices=["classic", "dark"], default="classic")
    parser.add_argument("--num-games", type=int, default=4,
                        help="Games per pair per variant (must be even, default: 4)")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--move-timeout", type=float, default=15.0,
                        help="Max seconds per move (default: 15.0)")
    parser.add_argument("--memory", type=int, default=8192)
    parser.add_argument("--official", action="store_true",
                        help="Run both variants (classic + dark)")
    parser.add_argument("--team", type=str, default=None)
    parser.add_argument("--eval", action="store_true",
                        help="Students vs defaults only")
    parser.add_argument("--name", type=str, default=None)
    args = parser.parse_args()

    from strategies import _discover_builtin, _discover_students

    # Discover strategies
    strat_infos: list[tuple[tuple[str, str], str]] = []

    for cls in _discover_builtin():
        inst = cls()
        strat_infos.append((("__builtin__", cls.__name__), inst.name))

    for cls in _discover_students(team_filter=args.team):
        inst = cls()
        src_file = sys.modules.get(cls.__module__)
        if src_file and hasattr(src_file, "__file__") and src_file.__file__:
            strat_infos.append(((src_file.__file__, cls.__name__), inst.name))
        else:
            strat_infos.append((("__builtin__", cls.__name__), inst.name))

    if not strat_infos:
        print("No strategies found.", file=sys.stderr)
        return

    master_seed = args.seed if args.seed is not None else random.randint(0, 2**31)
    rng = random.Random(master_seed)

    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")

    if args.official:
        _run_official(args, strat_infos, rng, timestamp)
    else:
        _run_single(args, strat_infos, rng, timestamp)


def _run_single(args, strat_infos, rng, timestamp) -> None:
    """Run a single-variant tournament."""
    seed = rng.randint(0, 2**31)

    print(f"\n{'='*60}")
    print(f"  VARIANT: {args.variant}  |  BOARD: {args.board_size}×{args.board_size}")
    print(f"{'='*60}\n")

    matches = run_tournament(
        strategies_info=strat_infos,
        board_size=args.board_size,
        variant=args.variant,
        num_games=args.num_games,
        seed=seed,
        max_workers=args.workers,
        move_timeout=args.move_timeout,
        memory_limit_mb=args.memory,
        eval_mode=args.eval or bool(args.team),
    )

    table = compute_league_table(matches, args.variant)
    print_league_table(table, args.variant)
    print_matchup_table(matches, args.variant)

    # Build combined entries from single league for grading
    single_combined = [
        CombinedEntry(
            strategy=e.strategy,
            classic_pts=e.points if args.variant == "classic" else 0,
            dark_pts=e.points if args.variant == "dark" else 0,
            total_pts=e.points,
            classic_rank=e.rank if args.variant == "classic" else 0,
            dark_rank=e.rank if args.variant == "dark" else 0,
            avg_rank=float(e.rank),
        )
        for e in table
    ]
    grades = compute_grades(single_combined)
    print_grades(grades)


def _run_official(args, strat_infos, rng, timestamp) -> None:
    """Run the official tournament: both variants with league scoring."""
    all_matches: list[MatchRecord] = []

    print(f"\n{'#'*60}")
    print(f"  OFFICIAL TOURNAMENT (League Format)")
    print(f"  Board: {args.board_size}×{args.board_size}")
    print(f"  Games per pair per variant: {args.num_games}")
    print(f"  Timeout: {args.move_timeout}s/move | Memory: {args.memory}MB")
    print(f"{'#'*60}")

    for variant in ["classic", "dark"]:
        round_seed = rng.randint(0, 2**31)

        print(f"\n{'='*60}")
        print(f"  LEAGUE: {variant.upper()}"
              + (" (fog of war)" if variant == "dark" else ""))
        print(f"{'='*60}\n")

        t0 = _time_mod.time()
        matches = run_tournament(
            strategies_info=strat_infos,
            board_size=args.board_size,
            variant=variant,
            num_games=args.num_games,
            seed=round_seed,
            max_workers=args.workers,
            move_timeout=args.move_timeout,
            memory_limit_mb=args.memory,
            eval_mode=args.eval or bool(args.team),
        )
        elapsed = _time_mod.time() - t0

        table = compute_league_table(matches, variant)
        print_league_table(table, variant)
        print_matchup_table(matches, variant)
        print(f"  Elapsed: {elapsed:.1f}s")

        all_matches.extend(matches)

    # Combined standings
    classic_table = compute_league_table(all_matches, "classic")
    dark_table = compute_league_table(all_matches, "dark")
    combined = compute_combined_standings(classic_table, dark_table)
    print_combined_standings(combined)

    # Grades (from league position)
    grades = compute_grades(combined)
    print_grades(grades)

    # Get git commit hash
    git_hash = ""
    try:
        import subprocess
        git_hash = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        pass

    # Persistence
    config = {
        "timestamp": timestamp,
        "name": args.name,
        "board_size": args.board_size,
        "games_per_pair": args.num_games,
        "move_timeout": args.move_timeout,
        "memory_limit_mb": args.memory,
        "variants": ["classic", "dark"],
        "num_strategies": len(strat_infos),
        "strategies": [
            {"name": name, "source": info[0], "cls": info[1]}
            for info, name in strat_infos
        ],
        "git_commit": git_hash,
    }

    run_dir = RESULTS_DIR / "runs" / timestamp
    save_results(run_dir, all_matches, classic_table, dark_table, combined, grades, config)
    print(f"Results saved to {run_dir}")


if __name__ == "__main__":
    main()
