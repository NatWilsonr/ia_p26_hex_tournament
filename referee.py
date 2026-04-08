"""Separate-process referee for secure Hex matches.

Architecture: 3 processes per match
  - Referee process: holds HexGame, enforces rules
  - Strategy worker 1 (Black): runs strategy in isolated subprocess
  - Strategy worker 2 (White): runs strategy in isolated subprocess

Communication: JSON lines over stdin/stdout pipes.
Timeout: select() on stdout with timeout + SIGKILL (uncatchable).
"""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from hex_game import HexGame

WORKER_SCRIPT = str(Path(__file__).resolve().parent / "strategy_worker.py")


@dataclass
class MoveRecord:
    """Record of a single move in a game."""
    move_number: int
    player: int
    cell: tuple[int, int] | None
    time_s: float
    result: str  # "placed", "collision", "skip_timeout", "skip_invalid", "skip_crash", "skip_dead"


@dataclass
class MatchRecord:
    """Full record of a completed match."""
    black_strategy: str
    white_strategy: str
    winner_strategy: str
    winner_color: int
    variant: str
    board_size: int
    num_moves: int
    num_skips: dict[int, int] = field(default_factory=lambda: {1: 0, 2: 0})
    num_timeouts: dict[int, int] = field(default_factory=lambda: {1: 0, 2: 0})
    num_collisions: dict[int, int] = field(default_factory=lambda: {1: 0, 2: 0})
    duration_s: float = 0.0
    seed: int = 0
    move_log: list[MoveRecord] = field(default_factory=list)


class StrategyProcess:
    """Manages a strategy subprocess lifecycle."""

    def __init__(
        self,
        source: str,
        cls_name: str,
        memory_limit_mb: int = 8192,
    ) -> None:
        self.source = source
        self.cls_name = cls_name
        self.memory_limit_mb = memory_limit_mb
        self._proc: subprocess.Popen | None = None
        self._alive = False
        self.name: str = cls_name  # Updated after init

    def start(self, timeout: float = 30.0) -> bool:
        """Spawn the worker process and wait for ready signal."""
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        self._proc = subprocess.Popen(
            [sys.executable, WORKER_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            # Each strategy gets its own process group for clean kill
            preexec_fn=os.setsid,
        )

        # Send init message
        self._send({"source": self.source, "cls_name": self.cls_name})

        # Wait for ready
        response = self._recv(timeout=timeout)
        if response is None:
            self.kill()
            return False

        if response.get("status") == "ready":
            self.name = response.get("name", self.cls_name)
            self._alive = True
            return True

        self.kill()
        return False

    @property
    def alive(self) -> bool:
        if not self._alive or self._proc is None:
            return False
        if self._proc.poll() is not None:
            self._alive = False
        return self._alive

    def _send(self, msg: dict) -> bool:
        """Send a JSON line to the worker. Returns False if pipe is broken."""
        if self._proc is None or self._proc.stdin is None:
            return False
        try:
            data = json.dumps(msg) + "\n"
            self._proc.stdin.write(data.encode())
            self._proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            self._alive = False
            return False

    def _recv(self, timeout: float = 10.0) -> dict | None:
        """Read a JSON line from the worker with timeout.

        Returns None on timeout, broken pipe, or invalid JSON.
        """
        if self._proc is None or self._proc.stdout is None:
            return None

        fd = self._proc.stdout.fileno()
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return None  # Timeout

        try:
            line = self._proc.stdout.readline()
            if not line:
                self._alive = False
                return None
            return json.loads(line.decode())
        except (json.JSONDecodeError, OSError):
            return None

    def send_begin(self, config: dict, timeout: float = 10.0) -> bool:
        """Send begin command and wait for acknowledgment."""
        if not self._send({"cmd": "begin", "config": config}):
            return False
        response = self._recv(timeout=timeout)
        return response is not None and response.get("status") == "ok"

    def send_play(
        self,
        board: list[list[int]],
        last_move: tuple[int, int] | None,
        timeout: float = 10.0,
    ) -> tuple[int, int] | None:
        """Send play command and wait for move response.

        Returns (row, col) or None on timeout/error.
        """
        msg = {
            "cmd": "play",
            "board": board,
            "last_move": list(last_move) if last_move is not None else None,
        }
        if not self._send(msg):
            return None

        response = self._recv(timeout=timeout)
        if response is None:
            return None

        if "move" in response:
            m = response["move"]
            if isinstance(m, list) and len(m) == 2:
                return (int(m[0]), int(m[1]))
        return None

    def send_result(self, move: tuple[int, int], success: bool) -> None:
        """Send move result (non-blocking, no response expected)."""
        self._send({"cmd": "result", "move": list(move), "success": success})

    def send_end(self, board: list[list[int]], winner: int, your_player: int) -> None:
        """Send end-of-game notification."""
        self._send({
            "cmd": "end",
            "board": board,
            "winner": winner,
            "your_player": your_player,
        })

    def kill(self) -> None:
        """Kill the worker process with SIGKILL (uncatchable)."""
        if self._proc is not None:
            try:
                # Kill the entire process group
                os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._alive = False


def run_match_referee(
    black_info: tuple[str, str],
    white_info: tuple[str, str],
    board_size: int = 11,
    variant: str = "classic",
    seed: int = 42,
    move_timeout: float = 10.0,
    memory_limit_mb: int = 8192,
) -> MatchRecord:
    """Run a single match using the referee pattern.

    Parameters
    ----------
    black_info, white_info : (source, cls_name)
        Strategy loading info.
    """
    game = HexGame(size=board_size, variant=variant, seed=seed)
    is_dark = variant == "dark"

    # Spawn strategy processes
    procs = {
        1: StrategyProcess(black_info[0], black_info[1], memory_limit_mb),
        2: StrategyProcess(white_info[0], white_info[1], memory_limit_mb),
    }

    t_start = time.monotonic()
    move_log: list[MoveRecord] = []
    num_skips = {1: 0, 2: 0}
    num_timeouts = {1: 0, 2: 0}
    num_collisions = {1: 0, 2: 0}

    try:
        # Start both processes
        for player_num, proc in procs.items():
            if not proc.start(timeout=30.0):
                # Process failed to start — treat as dead for entire game
                proc._alive = False

        # Send begin to both
        for player_num, proc in procs.items():
            if proc.alive:
                config = {
                    "board_size": board_size,
                    "variant": variant,
                    "initial_board": [list(row) for row in game.get_view(player_num)],
                    "player": player_num,
                    "opponent": 3 - player_num,
                    "time_limit": move_timeout,
                }
                if not proc.send_begin(config, timeout=30.0):
                    proc._alive = False

        # Track last successful move per player (for classic last_move)
        last_successful: dict[int, tuple[int, int] | None] = {1: None, 2: None}

        # Main game loop
        while not game.is_over:
            current = game.current_player
            opponent_num = 3 - current
            proc = procs[current]
            move_num = game.move_count + 1

            if not proc.alive:
                # Dead process — skip turn
                t0 = time.monotonic()
                winner = game.skip_turn()
                move_log.append(MoveRecord(
                    move_number=move_num,
                    player=current,
                    cell=None,
                    time_s=time.monotonic() - t0,
                    result="skip_dead",
                ))
                num_skips[current] += 1
                if winner != 0:
                    break
                continue

            # Build board view
            if is_dark:
                board_view = [list(row) for row in game.get_view(current)]
                last_move = None
            else:
                board_view = [list(row) for row in game.board]
                last_move = last_successful.get(opponent_num)

            # Request move
            t0 = time.monotonic()
            move = proc.send_play(board_view, last_move, timeout=move_timeout)
            elapsed = time.monotonic() - t0

            if move is None:
                # Timeout or crash — kill process, skip turn
                proc.kill()
                winner = game.skip_turn()
                move_log.append(MoveRecord(
                    move_number=move_num,
                    player=current,
                    cell=None,
                    time_s=elapsed,
                    result="skip_timeout",
                ))
                num_skips[current] += 1
                num_timeouts[current] += 1
                if winner != 0:
                    break
                continue

            # Validate move
            row, col = move
            if not (0 <= row < board_size and 0 <= col < board_size):
                # Out of bounds — skip turn
                winner = game.skip_turn()
                move_log.append(MoveRecord(
                    move_number=move_num,
                    player=current,
                    cell=(row, col),
                    time_s=elapsed,
                    result="skip_invalid",
                ))
                num_skips[current] += 1
                if winner != 0:
                    break
                continue

            # Try to play the move
            try:
                winner_result, collision = game.play(row, col)
            except ValueError:
                # Invalid move (e.g., occupied cell in classic, own stone in dark)
                winner = game.skip_turn()
                move_log.append(MoveRecord(
                    move_number=move_num,
                    player=current,
                    cell=(row, col),
                    time_s=elapsed,
                    result="skip_invalid",
                ))
                num_skips[current] += 1
                if winner != 0:
                    break
                continue

            # Successful play or collision
            if collision:
                proc.send_result(move, success=False)
                move_log.append(MoveRecord(
                    move_number=move_num,
                    player=current,
                    cell=(row, col),
                    time_s=elapsed,
                    result="collision",
                ))
                num_collisions[current] += 1
            else:
                proc.send_result(move, success=True)
                last_successful[current] = (row, col)
                move_log.append(MoveRecord(
                    move_number=move_num,
                    player=current,
                    cell=(row, col),
                    time_s=elapsed,
                    result="placed",
                ))

            if winner_result != 0:
                break

        # Game over — determine winner
        winner_color = game.winner
        if winner_color == 0:
            # Should not happen with move cap, but fallback
            winner_color = 1

        winner_name = procs[winner_color].name
        duration = time.monotonic() - t_start

        # Notify strategies of game end
        final_board = [list(row) for row in game.board]
        for player_num, proc in procs.items():
            if proc.alive:
                proc.send_end(final_board, winner_color, player_num)

        return MatchRecord(
            black_strategy=procs[1].name,
            white_strategy=procs[2].name,
            winner_strategy=winner_name,
            winner_color=winner_color,
            variant=variant,
            board_size=board_size,
            num_moves=game.move_count,
            num_skips=num_skips,
            num_timeouts=num_timeouts,
            num_collisions=num_collisions,
            duration_s=duration,
            seed=seed,
            move_log=move_log,
        )

    finally:
        # Always clean up processes
        for proc in procs.values():
            proc.kill()
