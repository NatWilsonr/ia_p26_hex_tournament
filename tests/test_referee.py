"""Tests for referee.py — process isolation and security."""

import os
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

from referee import run_match_referee


@pytest.fixture
def malicious_strategy_dir(tmp_path):
    """Create a temporary directory with malicious strategy files."""
    return tmp_path


def _write_strategy(path: Path, name: str, code: str) -> str:
    """Write a strategy file and return its path."""
    path.write_text(code)
    return str(path)


class TestRefereeBasic:
    def test_random_vs_random_classic(self):
        result = run_match_referee(
            black_info=("__builtin__", "RandomStrategy"),
            white_info=("__builtin__", "RandomStrategy"),
            board_size=7,
            variant="classic",
            seed=42,
            move_timeout=5.0,
        )
        assert result.winner_color in (1, 2)
        assert result.num_moves > 0
        assert len(result.move_log) == result.num_moves

    def test_random_vs_random_dark(self):
        result = run_match_referee(
            black_info=("__builtin__", "RandomStrategy"),
            white_info=("__builtin__", "RandomStrategy"),
            board_size=7,
            variant="dark",
            seed=42,
            move_timeout=5.0,
        )
        assert result.winner_color in (1, 2)
        assert result.num_moves > 0


class TestMaliciousStrategies:
    def test_sigalrm_disable(self, malicious_strategy_dir):
        """Strategy that tries to disable SIGALRM — referee should be unaffected."""
        code = textwrap.dedent("""\
            import signal
            import time
            from strategy import Strategy, GameConfig

            class SigAlrmDisabler(Strategy):
                @property
                def name(self):
                    return "SigAlrmDisabler"

                def begin_game(self, config):
                    # Try to disable all signal handlers
                    signal.signal(signal.SIGALRM, signal.SIG_IGN)
                    signal.signal(signal.SIGTERM, signal.SIG_IGN)
                    self.player = config.player
                    self.size = config.board_size

                def play(self, board, last_move):
                    # Disable again just in case
                    signal.signal(signal.SIGALRM, signal.SIG_IGN)
                    # Find any empty cell
                    for r in range(self.size):
                        for c in range(self.size):
                            if board[r][c] == 0:
                                return (r, c)
                    return (0, 0)
        """)
        path = _write_strategy(
            malicious_strategy_dir / "strategy.py", "SigAlrmDisabler", code
        )
        result = run_match_referee(
            black_info=(path, "SigAlrmDisabler"),
            white_info=("__builtin__", "RandomStrategy"),
            board_size=7,
            variant="classic",
            seed=42,
            move_timeout=5.0,
        )
        # Game should complete normally despite SIGALRM disable
        assert result.winner_color in (1, 2)
        assert result.num_moves > 0

    def test_infinite_loop(self, malicious_strategy_dir):
        """Strategy that enters infinite loop — should be killed after timeout."""
        code = textwrap.dedent("""\
            import time
            from strategy import Strategy, GameConfig

            class InfiniteLooper(Strategy):
                @property
                def name(self):
                    return "InfiniteLooper"

                def begin_game(self, config):
                    self.player = config.player
                    self.size = config.board_size

                def play(self, board, last_move):
                    # Infinite loop
                    while True:
                        pass
        """)
        path = _write_strategy(
            malicious_strategy_dir / "strategy.py", "InfiniteLooper", code
        )
        result = run_match_referee(
            black_info=(path, "InfiniteLooper"),
            white_info=("__builtin__", "RandomStrategy"),
            board_size=5,
            variant="classic",
            seed=42,
            move_timeout=2.0,
        )
        # InfiniteLooper should timeout on first move, get killed,
        # then all remaining turns are skipped. Random wins.
        assert result.winner_strategy == "Random"
        assert result.num_timeouts[1] >= 1
        assert result.num_skips[1] >= 1

    def test_gc_get_objects(self, malicious_strategy_dir):
        """Strategy that tries gc.get_objects() — should find nothing useful."""
        code = textwrap.dedent("""\
            import gc
            from strategy import Strategy, GameConfig

            class GcSnooper(Strategy):
                @property
                def name(self):
                    return "GcSnooper"

                def begin_game(self, config):
                    self.player = config.player
                    self.size = config.board_size
                    # Try to find HexGame objects
                    self.found_hex = False
                    for obj in gc.get_objects():
                        if hasattr(obj, '__class__') and obj.__class__.__name__ == 'HexGame':
                            self.found_hex = True

                def play(self, board, last_move):
                    # Won't find HexGame since it's in a different process
                    for r in range(self.size):
                        for c in range(self.size):
                            if board[r][c] == 0:
                                return (r, c)
                    return (0, 0)
        """)
        path = _write_strategy(
            malicious_strategy_dir / "strategy.py", "GcSnooper", code
        )
        result = run_match_referee(
            black_info=(path, "GcSnooper"),
            white_info=("__builtin__", "RandomStrategy"),
            board_size=7,
            variant="classic",
            seed=42,
            move_timeout=5.0,
        )
        # Game should complete — gc.get_objects() finds nothing useful
        assert result.winner_color in (1, 2)
        assert result.num_moves > 0

    def test_crash_mid_game(self, malicious_strategy_dir):
        """Strategy that crashes after a few moves."""
        code = textwrap.dedent("""\
            from strategy import Strategy, GameConfig

            class Crasher(Strategy):
                def __init__(self):
                    self.move_count = 0

                @property
                def name(self):
                    return "Crasher"

                def begin_game(self, config):
                    self.player = config.player
                    self.size = config.board_size
                    self.move_count = 0

                def play(self, board, last_move):
                    self.move_count += 1
                    if self.move_count >= 3:
                        raise RuntimeError("I give up!")
                    for r in range(self.size):
                        for c in range(self.size):
                            if board[r][c] == 0:
                                return (r, c)
                    return (0, 0)
        """)
        path = _write_strategy(
            malicious_strategy_dir / "strategy.py", "Crasher", code
        )
        result = run_match_referee(
            black_info=(path, "Crasher"),
            white_info=("__builtin__", "RandomStrategy"),
            board_size=7,
            variant="classic",
            seed=42,
            move_timeout=5.0,
        )
        # Random should win after Crasher dies
        assert result.winner_strategy == "Random"
