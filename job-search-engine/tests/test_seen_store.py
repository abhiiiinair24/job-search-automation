import json

from jobsearch.seen_store import InMemorySeenJobStore, JsonFileSeenJobStore


# --- InMemorySeenJobStore --------------------------------------------------


def test_in_memory_store_starts_empty():
    store = InMemorySeenJobStore()
    assert store.get_seen_ids() == set()


def test_in_memory_store_can_be_seeded_with_initial_ids():
    store = InMemorySeenJobStore(initial_seen=["a", "b"])
    assert store.get_seen_ids() == {"a", "b"}


def test_in_memory_store_mark_seen_adds_ids():
    store = InMemorySeenJobStore()
    store.mark_seen(["job-1", "job-2"])
    assert store.get_seen_ids() == {"job-1", "job-2"}


def test_in_memory_store_mark_seen_is_additive():
    store = InMemorySeenJobStore(initial_seen=["job-1"])
    store.mark_seen(["job-2"])
    assert store.get_seen_ids() == {"job-1", "job-2"}


def test_in_memory_store_filter_new_excludes_seen_ids():
    store = InMemorySeenJobStore(initial_seen=["job-1"])
    new_ids = store.filter_new(["job-1", "job-2", "job-3"])
    assert new_ids == ["job-2", "job-3"]


def test_in_memory_store_get_seen_ids_returns_a_copy():
    store = InMemorySeenJobStore(initial_seen=["job-1"])
    seen = store.get_seen_ids()
    seen.add("job-2")
    # Mutating the returned set should not affect the store's internal state.
    assert store.get_seen_ids() == {"job-1"}


# --- JsonFileSeenJobStore ---------------------------------------------------


def test_json_store_returns_empty_set_when_file_does_not_exist(tmp_path):
    store = JsonFileSeenJobStore(path=tmp_path / "seen.json")
    assert store.get_seen_ids() == set()


def test_json_store_mark_seen_persists_to_disk(tmp_path):
    path = tmp_path / "seen.json"
    store = JsonFileSeenJobStore(path=path)
    store.mark_seen(["job-1", "job-2"])

    assert path.exists()
    with path.open() as f:
        data = json.load(f)
    assert set(data) == {"job-1", "job-2"}


def test_json_store_reads_back_previously_marked_ids(tmp_path):
    path = tmp_path / "seen.json"
    store_a = JsonFileSeenJobStore(path=path)
    store_a.mark_seen(["job-1"])

    # A fresh instance pointed at the same path should see the same data -
    # this is what makes "seen" survive across separate process runs.
    store_b = JsonFileSeenJobStore(path=path)
    assert store_b.get_seen_ids() == {"job-1"}


def test_json_store_mark_seen_is_additive_across_instances(tmp_path):
    path = tmp_path / "seen.json"
    JsonFileSeenJobStore(path=path).mark_seen(["job-1"])
    JsonFileSeenJobStore(path=path).mark_seen(["job-2"])

    assert JsonFileSeenJobStore(path=path).get_seen_ids() == {"job-1", "job-2"}


def test_json_store_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "seen.json"
    store = JsonFileSeenJobStore(path=path)
    store.mark_seen(["job-1"])
    assert path.exists()


def test_json_store_handles_corrupt_file_gracefully(tmp_path):
    path = tmp_path / "seen.json"
    path.write_text("not valid json {{{")

    store = JsonFileSeenJobStore(path=path)
    assert store.get_seen_ids() == set()


def test_json_store_handles_non_list_json_gracefully(tmp_path):
    path = tmp_path / "seen.json"
    path.write_text(json.dumps({"not": "a list"}))

    store = JsonFileSeenJobStore(path=path)
    assert store.get_seen_ids() == set()


def test_json_store_filter_new_excludes_seen_ids(tmp_path):
    path = tmp_path / "seen.json"
    store = JsonFileSeenJobStore(path=path)
    store.mark_seen(["job-1"])

    new_ids = store.filter_new(["job-1", "job-2"])
    assert new_ids == ["job-2"]


def test_json_store_accepts_string_path(tmp_path):
    path_str = str(tmp_path / "seen.json")
    store = JsonFileSeenJobStore(path=path_str)
    store.mark_seen(["job-1"])
    assert store.get_seen_ids() == {"job-1"}
