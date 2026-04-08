"""Tests for count-based grading (4 + N models beaten)."""

from tournament import compute_grades, CombinedEntry


def _make_combined(entries: list[tuple[str, int]]) -> list[CombinedEntry]:
    """Helper: create CombinedEntry list from (name, total_pts) pairs."""
    return [
        CombinedEntry(strategy=name, total_pts=pts)
        for name, pts in entries
    ]


class TestCountBasedGrading:
    def test_beat_one_model(self):
        combined = _make_combined([
            ("MCTS_Tier_1", 20),
            ("StudentA", 8),
            ("Random", 5),
        ])
        grades = compute_grades(combined)
        assert len(grades) == 1
        # Beat 1 model (Random) → grade = 4 + 1 = 5
        assert grades[0]["score"] == 5

    def test_beat_two_models(self):
        combined = _make_combined([
            ("MCTS_Tier_2", 30),
            ("StudentA", 22),
            ("MCTS_Tier_1", 20),
            ("Random", 5),
        ])
        grades = compute_grades(combined)
        # Beat 2 models (Random, T1) → grade = 4 + 2 = 6
        assert grades[0]["score"] == 6

    def test_beat_five_models(self):
        combined = _make_combined([
            ("MCTS_Tier_5", 50),
            ("StudentA", 35),
            ("MCTS_Tier_4", 30),
            ("MCTS_Tier_3", 25),
            ("MCTS_Tier_2", 20),
            ("MCTS_Tier_1", 10),
            ("Random", 5),
        ])
        grades = compute_grades(combined)
        # Beat 5 models (Random, T1, T2, T3, T4) → grade = 4 + 5 = 9
        assert grades[0]["score"] == 9

    def test_beat_all_six_models(self):
        combined = _make_combined([
            ("StudentA", 60),
            ("MCTS_Tier_5", 50),
            ("MCTS_Tier_4", 40),
            ("MCTS_Tier_3", 30),
            ("MCTS_Tier_2", 20),
            ("MCTS_Tier_1", 10),
            ("Random", 5),
        ])
        grades = compute_grades(combined)
        # Beat 6 models → grade = 4 + 6 = 10
        assert grades[0]["score"] == 10

    def test_beat_zero_models(self):
        combined = _make_combined([
            ("Random", 10),
            ("StudentA", 3),
        ])
        grades = compute_grades(combined)
        # Beat 0 models → grade = 0 (not 4)
        assert grades[0]["score"] == 0

    def test_tie_counts_as_beaten(self):
        combined = _make_combined([
            ("MCTS_Tier_2", 20),
            ("StudentA", 20),
            ("Random", 5),
        ])
        grades = compute_grades(combined)
        # Tied with T2 (20 >= 20) → beaten. Also beats Random.
        # Beat 2 models → grade = 4 + 2 = 6
        assert grades[0]["score"] == 6

    def test_models_not_graded(self):
        combined = _make_combined([
            ("MCTS_Tier_1", 20),
            ("Random", 10),
            ("StudentA", 15),
        ])
        grades = compute_grades(combined)
        assert len(grades) == 1
        assert grades[0]["strategy"] == "StudentA"

    def test_top3_auto_10(self):
        combined = _make_combined([
            ("StudentA", 50),
            ("StudentB", 45),
            ("StudentC", 40),
            ("MCTS_Tier_2", 35),
            ("StudentD", 10),
            ("Random", 5),
        ])
        grades = compute_grades(combined)
        a = next(g for g in grades if g["strategy"] == "StudentA")
        b = next(g for g in grades if g["strategy"] == "StudentB")
        c = next(g for g in grades if g["strategy"] == "StudentC")
        d = next(g for g in grades if g["strategy"] == "StudentD")
        assert a["score"] == 10
        assert b["score"] == 10
        assert c["score"] == 10
        # D only beat Random → 4 + 1 = 5 (not in top 3)
        assert d["score"] == 5

    def test_beaten_list(self):
        combined = _make_combined([
            ("MCTS_Tier_3", 30),
            ("StudentA", 25),
            ("MCTS_Tier_2", 20),
            ("MCTS_Tier_1", 10),
            ("Random", 5),
        ])
        grades = compute_grades(combined)
        assert set(grades[0]["beaten"]) == {"Random", "MCTS_Tier_1", "MCTS_Tier_2"}
        # Beat 3 models → grade = 4 + 3 = 7
        assert grades[0]["score"] == 7

    def test_model_flip_still_counts(self):
        """If T4 outperforms T5, both still count as 1 model each."""
        combined = _make_combined([
            ("MCTS_Tier_4", 50),   # T4 above T5 — unusual
            ("StudentA", 45),
            ("MCTS_Tier_5", 40),
            ("Random", 5),
        ])
        grades = compute_grades(combined)
        # StudentA (45) >= T5 (40) and >= Random (5), but < T4 (50)
        # Beat 2 models → grade = 4 + 2 = 6
        assert grades[0]["score"] == 6
        assert set(grades[0]["beaten"]) == {"MCTS_Tier_5", "Random"}

    def test_multiple_students(self):
        combined = _make_combined([
            ("MCTS_Tier_3", 30),
            ("StudentA", 25),
            ("StudentB", 12),
            ("MCTS_Tier_2", 20),
            ("MCTS_Tier_1", 10),
            ("Random", 5),
        ])
        grades = compute_grades(combined)
        a = next(g for g in grades if g["strategy"] == "StudentA")
        b = next(g for g in grades if g["strategy"] == "StudentB")
        # A beats Random, T1, T2 → 4 + 3 = 7
        assert a["score"] == 7
        # B beats Random, T1 → 4 + 2 = 6
        assert b["score"] == 6
