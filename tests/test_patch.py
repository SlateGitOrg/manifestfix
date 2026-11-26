from manifestfix.patch import covers, merge_frozen, parse_path

PATH = "containers[1].container_no"


def test_path_parsing_and_coverage():
    assert parse_path(PATH) == ["containers", 1, "container_no"]
    assert parse_path("$") == []
    assert covers("containers", PATH)
    assert covers(PATH, PATH)
    assert not covers(PATH, "containers[1]")
    assert not covers(PATH, "containers[1].seal_no")
    assert not covers("containers[1]", "containers[2].seal_no")


def test_patch_for_asked_path_leaves_vessel_frozen(clean):
    response = {
        "patch": [
            {"op": "replace", "path": PATH, "value": "TGHU9876542"},
            {"op": "replace", "path": "vessel", "value": "MV SOMETHING ELSE"},
        ]
    }
    merged = merge_frozen(clean, response, {PATH})
    assert merged.data["containers"][1]["container_no"] == "TGHU9876542"
    assert merged.data["vessel"] == clean["vessel"]
    assert merged.applied == [PATH]
    assert merged.rejected == ["vessel"]
    assert clean["containers"][1]["container_no"] == "MSCU1234566"  # input untouched


def test_full_object_response_only_contributes_asked_paths(clean):
    rewritten = {**clean, "vessel": "CHANGED", "shipper": "CHANGED"}
    rewritten["containers"] = [dict(c) for c in clean["containers"]]
    rewritten["containers"][1]["container_no"] = "TGHU9876542"
    rewritten["containers"][0]["seal_no"] = "CHANGED"
    merged = merge_frozen(clean, rewritten, {PATH})
    assert merged.data["containers"][1]["container_no"] == "TGHU9876542"
    assert merged.data["vessel"] == clean["vessel"]
    assert merged.data["containers"][0]["seal_no"] == clean["containers"][0]["seal_no"]


def test_parent_path_edit_is_rejected_when_only_a_child_was_asked(clean):
    response = {"patch": [{"op": "replace", "path": "containers[1]", "value": {}}]}
    merged = merge_frozen(clean, response, {PATH})
    assert merged.data == clean
    assert merged.rejected == ["containers[1]"]


def test_remove_op_and_bad_index(clean):
    clean["notes"] = "x"
    merged = merge_frozen(clean, {"patch": [{"op": "remove", "path": "notes"}]}, {"notes"})
    assert "notes" not in merged.data
    bad = {"patch": [{"op": "replace", "path": "containers[9].seal_no", "value": "x"}]}
    assert merge_frozen(clean, bad, {"containers"}).rejected == ["containers[9].seal_no"]


def test_root_allowed_replaces_whole_document(clean):
    merged = merge_frozen(None, {"vessel": "NEW"}, {"$"})
    assert merged.data == {"vessel": "NEW"}
