"""
Tests for database operations using a temporary in-memory (or temp-file) DB.
"""
import pytest
# tmp_db fixture is provided by conftest.py


class TestUpsertPlayer:
    def test_creates_new_player(self, tmp_db):
        tmp_db.upsert_player("model-a", "Model A", "lmstudio", 1200.0)
        lb = tmp_db.get_leaderboard()
        assert any(p["model_id"] == "model-a" for p in lb)

    def test_updates_existing_player_elo(self, tmp_db):
        tmp_db.upsert_player("model-a", "Model A", "lmstudio", 1200.0)
        tmp_db.upsert_player("model-a", "Model A", "lmstudio", 1250.0)
        lb = tmp_db.get_leaderboard()
        model = next(p for p in lb if p["model_id"] == "model-a")
        assert model["elo"] == pytest.approx(1250.0)

    def test_multiple_players(self, tmp_db):
        tmp_db.upsert_player("model-a", "Model A", "lmstudio", 1200.0)
        tmp_db.upsert_player("model-b", "Model B", "lmstudio", 1300.0)
        lb = tmp_db.get_leaderboard()
        ids = {p["model_id"] for p in lb}
        assert "model-a" in ids
        assert "model-b" in ids


class TestRecordGame:
    def _setup_players(self, db):
        db.upsert_player("white-model", "White", "lmstudio", 1200.0)
        db.upsert_player("black-model", "Black", "lmstudio", 1200.0)

    def test_records_game_returns_id(self, tmp_db):
        self._setup_players(tmp_db)
        game_id = tmp_db.record_game(
            white_model_id="white-model",
            black_model_id="black-model",
            result="1-0",
            termination="checkmate",
            total_moves=20,
            pgn="1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0",
            white_elo_before=1200.0,
            black_elo_before=1200.0,
            white_elo_after=1216.0,
            black_elo_after=1184.0,
        )
        assert isinstance(game_id, int)
        assert game_id > 0

    def test_game_appears_in_recent_games(self, tmp_db):
        self._setup_players(tmp_db)
        tmp_db.record_game(
            white_model_id="white-model",
            black_model_id="black-model",
            result="1-0",
            termination="checkmate",
            total_moves=4,
            pgn="1. e4 *",
            white_elo_before=1200.0,
            black_elo_before=1200.0,
            white_elo_after=1216.0,
            black_elo_after=1184.0,
        )
        games = tmp_db.get_recent_games(10)
        assert len(games) >= 1


class TestRecordMove:
    def _setup(self, db):
        db.upsert_player("white-model", "White", "lmstudio", 1200.0)
        db.upsert_player("black-model", "Black", "lmstudio", 1200.0)
        game_id = db.record_game(
            white_model_id="white-model",
            black_model_id="black-model",
            result="*",
            termination="ongoing",
            total_moves=1,
            pgn="1. e4 *",
            white_elo_before=1200.0,
            black_elo_before=1200.0,
            white_elo_after=1200.0,
            black_elo_after=1200.0,
        )
        return game_id

    def test_records_move(self, tmp_db):
        game_id = self._setup(tmp_db)
        tmp_db.record_move(
            game_id=game_id,
            move_number=1,
            player_model_id="white-model",
            move_uci="e2e4",
            move_san="e4",
            candidate_rank=1,
            quality="best",
            score_cp=30,
            reasoning="Controls center.",
            fen_after="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        )
        moves = tmp_db.get_game_moves(game_id)
        assert len(moves) == 1
        assert moves[0]["move_uci"] == "e2e4"

    def test_thinking_content_stored(self, tmp_db):
        game_id = self._setup(tmp_db)
        tmp_db.record_move(
            game_id=game_id,
            move_number=1,
            player_model_id="white-model",
            move_uci="e2e4",
            move_san="e4",
            candidate_rank=1,
            quality="best",
            score_cp=30,
            reasoning="Center control.",
            fen_after="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            thinking_content="I considered e4 because it controls d5 and f5.",
        )
        moves = tmp_db.get_game_moves(game_id)
        assert moves[0].get("thinking_content") == "I considered e4 because it controls d5 and f5."

    def test_thinking_content_defaults_empty(self, tmp_db):
        game_id = self._setup(tmp_db)
        tmp_db.record_move(
            game_id=game_id,
            move_number=1,
            player_model_id="white-model",
            move_uci="e2e4",
            move_san="e4",
            candidate_rank=1,
            quality="best",
            score_cp=30,
            reasoning="Center.",
            fen_after="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        )
        moves = tmp_db.get_game_moves(game_id)
        tc = moves[0].get("thinking_content")
        assert tc is None or tc == ""


class TestEloHistory:
    def test_elo_history_recorded(self, tmp_db):
        tmp_db.upsert_player("model-a", "Model A", "lmstudio", 1200.0)
        tmp_db.upsert_player("model-b", "Model B", "lmstudio", 1200.0)
        tmp_db.record_game(
            white_model_id="model-a",
            black_model_id="model-b",
            result="1-0",
            termination="checkmate",
            total_moves=20,
            pgn="",
            white_elo_before=1200.0,
            black_elo_before=1200.0,
            white_elo_after=1216.0,
            black_elo_after=1184.0,
        )
        history = tmp_db.get_elo_history("model-a")
        assert len(history) >= 1

    def test_game_count_increments(self, tmp_db):
        tmp_db.upsert_player("model-a", "Model A", "lmstudio", 1200.0)
        tmp_db.upsert_player("model-b", "Model B", "lmstudio", 1200.0)
        assert tmp_db.get_player_game_count("model-a") == 0
        tmp_db.record_game(
            white_model_id="model-a",
            black_model_id="model-b",
            result="1-0",
            termination="checkmate",
            total_moves=20,
            pgn="",
            white_elo_before=1200.0,
            black_elo_before=1200.0,
            white_elo_after=1216.0,
            black_elo_after=1184.0,
        )
        assert tmp_db.get_player_game_count("model-a") == 1


class TestLeaderboard:
    def test_leaderboard_includes_players(self, tmp_db):
        tmp_db.upsert_player("model-a", "Model A", "lmstudio", 1300.0)
        tmp_db.upsert_player("model-b", "Model B", "lmstudio", 1100.0)
        lb = tmp_db.get_leaderboard()
        ids = [row["model_id"] for row in lb]
        assert "model-a" in ids
        assert "model-b" in ids

    def test_leaderboard_sorted_by_elo_desc(self, tmp_db):
        tmp_db.upsert_player("model-low", "Low", "lmstudio", 1000.0)
        tmp_db.upsert_player("model-high", "High", "lmstudio", 1500.0)
        lb = tmp_db.get_leaderboard()
        elos = [row["elo"] for row in lb]
        assert elos == sorted(elos, reverse=True)
