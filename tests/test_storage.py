from shipbook.storage import Storage


def test_push_and_pop_all(storage):
    storage.push_array_obj("q", {"a": 1})
    storage.push_array_obj("q", {"a": 2})
    items = storage.pop_all_array_obj("q")
    assert items == [{"a": 1}, {"a": 2}]
    # Draining is destructive.
    assert storage.pop_all_array_obj("q") == []


def test_pop_all_empty_queue(storage):
    assert storage.pop_all_array_obj("missing") == []


def test_push_after_drain_starts_fresh(storage):
    storage.push_array_obj("q", {"n": 1})
    storage.pop_all_array_obj("q")
    storage.push_array_obj("q", {"n": 2})
    assert storage.pop_all_array_obj("q") == [{"n": 2}]


def test_get_set_item_and_obj(storage):
    assert storage.get_item("k") is None
    storage.set_item("k", "value")
    assert storage.get_item("k") == "value"
    storage.set_obj("cfg", {"x": [1, 2]})
    assert storage.get_obj("cfg") == {"x": [1, 2]}


def test_in_memory_fallback(monkeypatch):
    s = Storage(directory="/does/not/exist/and/cannot/be/made")
    # makedirs may still succeed on some systems; force the memory path.
    s._enabled = False
    s.push_array_obj("q", {"a": 1})
    s.set_item("k", "v")
    assert s.get_item("k") == "v"
    assert s.pop_all_array_obj("q") == [{"a": 1}]
