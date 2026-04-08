"""Hex game engine: board logic, move validation, and win detection.

Board coordinates use (row, col) with 0-indexing.
  - Player 1 (Black): connects top (row 0) to bottom (row N-1).
  - Player 2 (White): connects left (col 0) to right (col N-1).

Cell values: 0 = empty, 1 = Black, 2 = White.

Variants:
  - ``"classic"``: Standard Hex. Both players see the full board.
  - ``"dark"``: Hex Oscuro (fog of war). Each player only sees their
    own stones and opponent stones discovered via collisions. Placing
    a stone on a hidden opponent cell causes a **collision**: the turn
    is consumed (no stone placed), and that opponent cell is revealed.
"""

from __future__ import annotations

import random
from collections import deque
from typing import Sequence

# Six neighbours in hex offset coordinates
NEIGHBORS = [(-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0)]


def get_neighbors(r: int, c: int, size: int) -> list[tuple[int, int]]:
    """Return valid neighbour cells for (r, c) on a board of given size."""
    result = []
    for dr, dc in NEIGHBORS:
        nr, nc = r + dr, c + dc
        if 0 <= nr < size and 0 <= nc < size:
            result.append((nr, nc))
    return result


def check_winner(board: Sequence[Sequence[int]], size: int) -> int:
    """Return the winner (1 or 2) or 0 if no winner yet.

    Uses BFS from each player's starting edge to their goal edge.
    """
    if _bfs_connected(board, size, player=1):
        return 1
    if _bfs_connected(board, size, player=2):
        return 2
    return 0


def _bfs_connected(
    board: Sequence[Sequence[int]], size: int, player: int,
) -> bool:
    """BFS to check if *player* has connected their two edges."""
    visited: set[tuple[int, int]] = set()
    queue: deque[tuple[int, int]] = deque()

    if player == 1:
        for c in range(size):
            if board[0][c] == 1:
                queue.append((0, c))
                visited.add((0, c))
        goal_check = lambda r, c: r == size - 1
    else:
        for r in range(size):
            if board[r][0] == 2:
                queue.append((r, 0))
                visited.add((r, 0))
        goal_check = lambda r, c: c == size - 1

    while queue:
        r, c = queue.popleft()
        if goal_check(r, c):
            return True
        for nr, nc in get_neighbors(r, c, size):
            if (nr, nc) not in visited and board[nr][nc] == player:
                visited.add((nr, nc))
                queue.append((nr, nc))
    return False


def empty_cells(board: Sequence[Sequence[int]], size: int) -> list[tuple[int, int]]:
    """Return all empty cells on the board."""
    return [(r, c) for r in range(size) for c in range(size) if board[r][c] == 0]


def make_board(size: int) -> list[list[int]]:
    """Create an empty board."""
    return [[0] * size for _ in range(size)]


def board_to_tuple(board: list[list[int]]) -> tuple[tuple[int, ...], ...]:
    """Convert mutable board to immutable tuple-of-tuples."""
    return tuple(tuple(row) for row in board)


def tuple_to_board(t: tuple[tuple[int, ...], ...]) -> list[list[int]]:
    """Convert immutable board to mutable list-of-lists."""
    return [list(row) for row in t]


def shortest_path_distance(
    board: Sequence[Sequence[int]], size: int, player: int,
) -> int:
    """Compute shortest-path distance for *player* to connect their edges.

    Uses Dijkstra on a graph where:
      - Own stones have cost 0
      - Empty cells have cost 1
      - Opponent stones are walls (impassable)

    Returns 0 if already connected, or ``size*size+1`` if no path.
    """
    from heapq import heappush, heappop

    INF = size * size + 1
    dist: dict[tuple[int, int], int] = {}
    heap: list[tuple[int, int, int]] = []

    if player == 1:
        for c in range(size):
            if board[0][c] == 1:
                heappush(heap, (0, 0, c))
            elif board[0][c] == 0:
                heappush(heap, (1, 0, c))
        goal_check = lambda r, c: r == size - 1
    else:
        for r in range(size):
            if board[r][0] == 2:
                heappush(heap, (0, r, 0))
            elif board[r][0] == 0:
                heappush(heap, (1, r, 0))
        goal_check = lambda r, c: c == size - 1

    while heap:
        d, r, c = heappop(heap)
        if (r, c) in dist:
            continue
        dist[(r, c)] = d
        if goal_check(r, c):
            return d
        for nr, nc in get_neighbors(r, c, size):
            if (nr, nc) in dist:
                continue
            cell = board[nr][nc]
            if cell == player:
                heappush(heap, (d, nr, nc))
            elif cell == 0:
                heappush(heap, (d + 1, nr, nc))

    return INF


def render_board(
    board: Sequence[Sequence[int]],
    size: int,
    fog_player: int = 0,
) -> str:
    """Return a text rendering of the hex board.

    Parameters
    ----------
    fog_player : int
        If > 0, render from that player's perspective in dark mode:
        own stones shown, opponent stones shown as ``?`` unless
        revealed (present in the view board).  If 0 (default),
        render full board (classic mode).

    Symbols: ``·`` = empty, ``B`` = Black, ``W`` = White, ``?`` = hidden.
    """
    symbols = {0: "·", 1: "B", 2: "W"}
    lines = []
    header = "  " + " ".join(f"{c:>2}" for c in range(size))
    lines.append(header)

    for r in range(size):
        indent = " " * r
        cells = " ".join(f" {symbols.get(board[r][c], '?')}" for c in range(size))
        lines.append(f"{indent}{r:>2}{cells}")

    return "\n".join(lines)


class HexGame:
    """Manages a single Hex game between two players.

    Parameters
    ----------
    size : int
        Board side length (default 11).
    variant : str
        ``"classic"`` or ``"dark"`` (fog of war).
    seed : int or None
        Random seed (used for any variant-specific randomness).
    """

    # Default move caps per variant
    DEFAULT_MAX_MOVES = {"classic": 122, "dark": 363}

    def __init__(
        self,
        size: int = 11,
        variant: str = "classic",
        seed: int | None = None,
        max_moves: int | None = None,
    ) -> None:
        self._size = size
        self._variant = variant
        self._rng = random.Random(seed)
        self._max_moves = max_moves or self.DEFAULT_MAX_MOVES.get(variant, size * size + 1)

        self._board = make_board(size)
        self._initial_board = board_to_tuple(self._board)
        self._current_player = 1  # Black moves first
        self._winner = 0
        self._move_count = 0
        self._skip_count: dict[int, int] = {1: 0, 2: 0}
        self._last_move: tuple[int, int] | None = None
        self._last_collision: tuple[int, int] | None = None
        self._history: list[tuple[int, tuple[int, int], bool]] = []
        # history entry: (player, (row, col), collision)

        # Dark-mode state: per-player views
        if variant == "dark":
            self._views: dict[int, list[list[int]]] = {
                1: make_board(size),
                2: make_board(size),
            }
            self._collision_count: dict[int, int] = {1: 0, 2: 0}
            self._turn_count: dict[int, int] = {1: 0, 2: 0}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        return self._size

    @property
    def variant(self) -> str:
        return self._variant

    @property
    def initial_board(self) -> tuple[tuple[int, ...], ...]:
        return self._initial_board

    @property
    def board(self) -> tuple[tuple[int, ...], ...]:
        """The TRUE board state (full information)."""
        return board_to_tuple(self._board)

    @property
    def current_player(self) -> int:
        return self._current_player

    @property
    def winner(self) -> int:
        return self._winner

    @property
    def is_over(self) -> bool:
        return (
            self._winner != 0
            or self._move_count >= self._max_moves
            or len(empty_cells(self._board, self._size)) == 0
        )

    @property
    def last_move(self) -> tuple[int, int] | None:
        """Last successfully placed move (not collisions)."""
        return self._last_move

    @property
    def last_collision(self) -> tuple[int, int] | None:
        """Cell of the last collision, or None. Reset after each play()."""
        return self._last_collision

    @property
    def move_count(self) -> int:
        return self._move_count

    @property
    def max_moves(self) -> int:
        return self._max_moves

    @property
    def skip_count(self) -> dict[int, int]:
        """Number of skipped turns per player."""
        return dict(self._skip_count)

    @property
    def history(self) -> list[tuple[int, tuple[int, int], bool]]:
        """List of (player, (row, col), was_collision) for all actions."""
        return list(self._history)

    def get_view(self, player: int) -> tuple[tuple[int, ...], ...]:
        """Return the board from *player*'s perspective.

        In classic mode, this is the full board.
        In dark mode, only the player's own stones and opponent stones
        discovered via collisions are visible.  Everything else is 0.
        """
        if self._variant == "dark":
            return board_to_tuple(self._views[player])
        return self.board

    def get_opponent_turn_count(self, player: int) -> int:
        """Return how many turns the opponent of *player* has had.

        Only meaningful in dark mode. Helps strategies estimate how
        many hidden opponent stones exist.
        """
        if self._variant != "dark":
            return 0
        return self._turn_count[3 - player]

    def play(self, row: int, col: int) -> tuple[int, bool]:
        """Place a stone at (row, col) for the current player.

        Returns
        -------
        tuple[int, bool]
            ``(winner, collision)`` where:
            - ``winner``: 1 or 2 if the game is over, else 0.
            - ``collision``: True if the move hit a hidden opponent
              stone (dark mode only). In classic mode, always False.
              On collision the turn is consumed but no stone is placed.

        Raises
        ------
        RuntimeError
            If the game is already over.
        ValueError
            If the cell is out of bounds, or occupied by your own stone,
            or (in classic mode) occupied by any stone.
        """
        if self.is_over:
            raise RuntimeError("Game is already over")
        if not (0 <= row < self._size and 0 <= col < self._size):
            raise ValueError(
                f"Cell ({row}, {col}) out of bounds for size {self._size}"
            )

        player = self._current_player
        opponent = 3 - player
        self._last_collision = None

        if self._variant == "dark":
            return self._play_dark(row, col, player, opponent)
        else:
            return self._play_classic(row, col, player)

    def _tiebreak_winner(self, last_player: int) -> int:
        """Determine winner by shortest_path_distance when move cap is hit.

        The player with the shorter remaining distance wins.
        If equal, the player who moved last (*last_player*) loses.
        """
        d1 = shortest_path_distance(self._board, self._size, 1)
        d2 = shortest_path_distance(self._board, self._size, 2)
        if d1 < d2:
            return 1
        if d2 < d1:
            return 2
        # Equal distance: last mover loses
        return 3 - last_player

    def _play_classic(
        self, row: int, col: int, player: int,
    ) -> tuple[int, bool]:
        """Classic mode: full information, occupied = error."""
        if self._board[row][col] != 0:
            raise ValueError(f"Cell ({row}, {col}) is already occupied")

        self._board[row][col] = player
        self._history.append((player, (row, col), False))
        self._last_move = (row, col)
        self._move_count += 1

        self._winner = check_winner(self._board, self._size)
        if self._winner == 0 and self._move_count >= self._max_moves:
            self._winner = self._tiebreak_winner(player)
        if self._winner == 0:
            self._current_player = 3 - player
        return (self._winner, False)

    def _play_dark(
        self, row: int, col: int, player: int, opponent: int,
    ) -> tuple[int, bool]:
        """Dark mode: fog of war with collisions."""
        self._turn_count[player] += 1

        cell = self._board[row][col]

        if cell == player:
            # Playing on your own visible stone is always an error
            raise ValueError(
                f"Cell ({row}, {col}) is already your own stone"
            )

        if cell == opponent:
            # COLLISION: opponent stone is hidden here
            # Reveal it in the player's view, consume turn
            self._views[player][row][col] = opponent
            self._collision_count[player] += 1
            self._last_collision = (row, col)
            self._history.append((player, (row, col), True))
            self._move_count += 1
            if self._move_count >= self._max_moves:
                self._winner = self._tiebreak_winner(player)
                return (self._winner, True)
            self._current_player = opponent  # turn passes
            return (0, True)

        # cell == 0: empty, place stone normally
        self._board[row][col] = player
        self._views[player][row][col] = player
        # Note: opponent does NOT see this stone in their view
        self._history.append((player, (row, col), False))
        self._last_move = (row, col)
        self._move_count += 1

        self._winner = check_winner(self._board, self._size)
        if self._winner == 0 and self._move_count >= self._max_moves:
            self._winner = self._tiebreak_winner(player)
        if self._winner == 0:
            self._current_player = opponent
        return (self._winner, False)

    def skip_turn(self) -> int:
        """Skip the current player's turn without placing a stone.

        The move counter increments and the turn passes to the opponent.
        Used by the referee when a strategy times out, crashes, or
        returns an invalid move.

        Returns
        -------
        int
            The winner (1 or 2) if the move cap is reached, else 0.
        """
        if self.is_over:
            raise RuntimeError("Game is already over")

        player = self._current_player
        self._skip_count[player] += 1
        self._move_count += 1

        if self._move_count >= self._max_moves:
            self._winner = self._tiebreak_winner(player)
            return self._winner

        self._current_player = 3 - player
        return 0

    def legal_moves(self) -> list[tuple[int, int]]:
        """Return all truly legal moves (empty cells on real board)."""
        return empty_cells(self._board, self._size)

    def apparent_moves(self, player: int) -> list[tuple[int, int]]:
        """Return cells that appear empty to *player*.

        In classic mode, same as ``legal_moves()``.
        In dark mode, includes cells that are actually occupied by the
        opponent but not yet discovered (player thinks they're empty).
        """
        if self._variant == "dark":
            return empty_cells(self._views[player], self._size)
        return self.legal_moves()

    def render(self, perspective: int = 0) -> str:
        """Render the board.

        Parameters
        ----------
        perspective : int
            0 = full board (god view), 1 or 2 = that player's view
            (dark mode only; in classic mode, always full).
        """
        if perspective > 0 and self._variant == "dark":
            return render_board(self._views[perspective], self._size)
        return render_board(self._board, self._size)
