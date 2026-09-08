import json

from jobsearch.config import Config


def _clear_board_env(monkeypatch):
    monkeypatch.delenv("GREENHOUSE_BOARDS", raising=False)
    monkeypatch.delenv("LEVER_COMPANIES", raising=False)
    monkeypatch.delenv("BOARDS_CONFIG_PATH", raising=False)


def test_from_env_uses_env_vars_when_set(monkeypatch):
    monkeypatch.setenv("GREENHOUSE_BOARDS", "stripe,airbnb")
    monkeypatch.setenv("LEVER_COMPANIES", "netflix")
    config = Config.from_env()
    assert config.greenhouse_boards == ["stripe", "airbnb"]
    assert config.lever_companies == ["netflix"]


def test_from_env_falls_back_to_boards_file_when_env_vars_unset(monkeypatch, tmp_path):
    _clear_board_env(monkeypatch)
    boards_file = tmp_path / "boards.json"
    boards_file.write_text(json.dumps({"greenhouse_boards": ["acme"], "lever_companies": ["other"]}))
    monkeypatch.setenv("BOARDS_CONFIG_PATH", str(boards_file))

    config = Config.from_env()

    assert config.greenhouse_boards == ["acme"]
    assert config.lever_companies == ["other"]


def test_from_env_vars_take_precedence_over_boards_file(monkeypatch, tmp_path):
    boards_file = tmp_path / "boards.json"
    boards_file.write_text(json.dumps({"greenhouse_boards": ["from-file"], "lever_companies": []}))
    monkeypatch.setenv("BOARDS_CONFIG_PATH", str(boards_file))
    monkeypatch.setenv("GREENHOUSE_BOARDS", "from-env")
    monkeypatch.delenv("LEVER_COMPANIES", raising=False)

    config = Config.from_env()

    assert config.greenhouse_boards == ["from-env"]


def test_from_env_with_no_env_vars_and_no_boards_file_is_empty(monkeypatch, tmp_path):
    _clear_board_env(monkeypatch)
    monkeypatch.setenv("BOARDS_CONFIG_PATH", str(tmp_path / "nonexistent.json"))

    config = Config.from_env()

    assert config.greenhouse_boards == []
    assert config.lever_companies == []


def test_from_env_other_settings_unaffected_by_boards_source(monkeypatch, tmp_path):
    _clear_board_env(monkeypatch)
    monkeypatch.setenv("BOARDS_CONFIG_PATH", str(tmp_path / "nonexistent.json"))
    monkeypatch.setenv("RECENCY_DAYS", "7")
    monkeypatch.setenv("CANDIDATE_EXPERIENCE_YEARS", "5")

    config = Config.from_env()

    assert config.recency_days == 7
    assert config.candidate_experience_years == 5.0
