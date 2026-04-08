"""Tests for hex_game.py — move cap, skip turn, and tiebreak mechanics."""

import pytest
from hex_game import HexGame, shortest_path_distance


class TestMoveCap:
    def test_classic_default_max_moves(self):
        g = HexGame(size=11, variant="classic")
        assert g.max_moves == 122

    def test_dark_default_max_moves(self):
        g = HexGame(size=11, variant="dark")
        assert g.max_moves == 363

    def test_custom_max_moves(self):
        g = HexGame(size=5, variant="classic", max_moves=10)
        assert g.max_moves == 10

    def test_game_ends_at_move_cap(self):
        g = HexGame(size=3, variant="classic", max_moves=5)
        moves = [(0, 0), (1, 1), (0, 1), (2, 0), (0, 2)]
        for i, (r, c) in enumerate(moves):
            if g.is_over:
                break
            g.play(r, c)
        assert g.is_over
        assert g.winner != 0  # tiebreak should pick a winner

    def test_is_over_includes_move_cap(self):
        g = HexGame(size=3, variant="classic", max_moves=2)
        assert not g.is_over
        g.play(0, 0)
        assert not g.is_over
        g.play(1, 1)
        assert g.is_over


class TestSkipTurn:
    def test_skip_increments_move_count(self):
        g = HexGame(size=5, variant="classic", max_moves=100)
        assert g.move_count == 0
        g.skip_turn()
        assert g.move_count == 1

    def test_skip_swaps_player(self):
        g = HexGame(size=5, variant="classic", max_moves=100)
        assert g.current_player == 1
        g.skip_turn()
        assert g.current_player == 2
        g.skip_turn()
        assert g.current_player == 1

    def test_skip_tracks_count(self):
        g = HexGame(size=5, variant="classic", max_moves=100)
        g.skip_turn()  # player 1 skipped
        g.skip_turn()  # player 2 skipped
        g.skip_turn()  # player 1 skipped again
        assert g.skip_count == {1: 2, 2: 1}

    def test_skip_triggers_move_cap(self):
        g = HexGame(size=3, variant="classic", max_moves=3)
        g.play(0, 0)  # move 1
        g.play(1, 1)  # move 2
        w = g.skip_turn()  # move 3 = cap
        assert g.is_over
        assert w != 0

    def test_skip_after_game_over_raises(self):
        g = HexGame(size=3, variant="classic", max_moves=2)
        g.play(0, 0)
        g.play(1, 1)
        assert g.is_over
        with pytest.raises(RuntimeError, match="already over"):
            g.skip_turn()


class TestTiebreak:
    def test_shorter_distance_wins(self):
        # Player 1 has stones closer to connecting top-bottom
        g = HexGame(size=3, variant="classic", max_moves=4)
        g.play(0, 0)  # P1 at top
        g.play(2, 2)  # P2 at bottom-right (far from left edge)
        g.play(1, 0)  # P1 at middle — distance 1 to connect
        g.play(0, 2)  # P2 — still needs col 0 side
        # P1 distance: 1, P2 distance: 2
        assert g.is_over
        assert g.winner == 1

    def test_equal_distance_last_mover_loses(self):
        # Set up equal distances, last mover should lose
        g = HexGame(size=3, variant="classic", max_moves=2)
        g.play(1, 1)  # P1 center
        g.play(1, 0)  # P2 center-left — both have distance ~1
        # Move cap hit. Both have similar distance.
        # If equal, last_player (P2) loses → P1 wins
        assert g.is_over
        d1 = shortest_path_distance(
            [[0, 0, 0], [0, 1, 0], [0, 0, 0]], 3, 1
        )
        d2 = shortest_path_distance(
            [[0, 0, 0], [2, 0, 0], [0, 0, 0]], 3, 2
        )
        if d1 == d2:
            assert g.winner == 1  # P2 moved last, P2 loses
        else:
            assert g.winner == (1 if d1 < d2 else 2)


class TestDarkModeMoveCap:
    def test_dark_collision_counts_toward_cap(self):
        g = HexGame(size=3, variant="dark", max_moves=3)
        g.play(0, 0)  # P1 places
        g.play(1, 1)  # P2 places
        # P1 tries to play where P2 is — collision, move 3 = cap
        winner, collision = g.play(1, 1)
        assert collision
        assert g.is_over
