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


# --- Adzuna discovery settings ------------------------------------------------


def test_from_env_adzuna_credentials_default_to_none(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    config = Config.from_env()
    assert config.adzuna_app_id is None
    assert config.adzuna_app_key is None


def test_from_env_adzuna_credentials_picked_up(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "my-app-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "my-app-key")
    config = Config.from_env()
    assert config.adzuna_app_id == "my-app-id"
    assert config.adzuna_app_key == "my-app-key"


def test_from_env_adzuna_search_terms_empty_by_default(monkeypatch):
    monkeypatch.delenv("ADZUNA_SEARCH_TERMS", raising=False)
    config = Config.from_env()
    assert config.adzuna_search_terms == []


def test_from_env_adzuna_search_terms_parsed_from_csv(monkeypatch):
    monkeypatch.setenv("ADZUNA_SEARCH_TERMS", "ai/ml engineer, backend engineer")
    config = Config.from_env()
    assert config.adzuna_search_terms == ["ai/ml engineer", "backend engineer"]


def test_from_env_adzuna_tunables_have_sane_defaults(monkeypatch):
    for var in [
        "ADZUNA_MAX_DAYS_OLD", "ADZUNA_RESULTS_PER_PAGE",
        "ADZUNA_ENRICH", "ADZUNA_ENRICHMENT_MAX_COMPANIES",
    ]:
        monkeypatch.delenv(var, raising=False)
    config = Config.from_env()
    assert config.adzuna_max_days_old == 4
    assert config.adzuna_results_per_page == 25
    assert config.adzuna_enrich is True
    assert config.adzuna_enrichment_max_companies == 20


def test_from_env_adzuna_enrich_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ADZUNA_ENRICH", "false")
    config = Config.from_env()
    assert config.adzuna_enrich is False
