import json

from jobsearch.boards_config import BoardsConfig


def test_from_file_loads_valid_config(tmp_path):
    path = tmp_path / "boards.json"
    path.write_text(json.dumps({"greenhouse_boards": ["stripe", "airbnb"], "lever_companies": ["netflix"]}))

    config = BoardsConfig.from_file(path)

    assert config.greenhouse_boards == ["stripe", "airbnb"]
    assert config.lever_companies == ["netflix"]


def test_from_file_missing_file_returns_empty_config(tmp_path):
    config = BoardsConfig.from_file(tmp_path / "does_not_exist.json")
    assert config.greenhouse_boards == []
    assert config.lever_companies == []


def test_from_file_malformed_json_returns_empty_config(tmp_path):
    path = tmp_path / "boards.json"
    path.write_text("not valid json {{{")
    config = BoardsConfig.from_file(path)
    assert config.greenhouse_boards == []
    assert config.lever_companies == []


def test_from_file_non_object_json_returns_empty_config(tmp_path):
    path = tmp_path / "boards.json"
    path.write_text(json.dumps(["stripe", "airbnb"]))  # a list, not an object
    config = BoardsConfig.from_file(path)
    assert config.greenhouse_boards == []
    assert config.lever_companies == []


def test_from_file_non_list_fields_return_empty_config(tmp_path):
    path = tmp_path / "boards.json"
    path.write_text(json.dumps({"greenhouse_boards": "stripe", "lever_companies": []}))
    config = BoardsConfig.from_file(path)
    assert config.greenhouse_boards == []
    assert config.lever_companies == []


def test_from_file_strips_whitespace_and_drops_empty_entries(tmp_path):
    path = tmp_path / "boards.json"
    path.write_text(json.dumps({"greenhouse_boards": ["  stripe  ", "", "   "], "lever_companies": []}))
    config = BoardsConfig.from_file(path)
    assert config.greenhouse_boards == ["stripe"]


def test_from_file_missing_keys_default_to_empty_lists(tmp_path):
    path = tmp_path / "boards.json"
    path.write_text(json.dumps({}))
    config = BoardsConfig.from_file(path)
    assert config.greenhouse_boards == []
    assert config.lever_companies == []


def test_from_file_accepts_string_or_path(tmp_path):
    path = tmp_path / "boards.json"
    path.write_text(json.dumps({"greenhouse_boards": ["stripe"], "lever_companies": []}))
    config = BoardsConfig.from_file(str(path))
    assert config.greenhouse_boards == ["stripe"]
