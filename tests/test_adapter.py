"""SPSS data semantics and persistent result safety at the integration boundary."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pathlab_spss import adapter
from pathlab_spss.models import DialogError, build_model


@pytest.fixture
def spss_modules(monkeypatch):
    # Simulates the native cursor AFTER active SPSS filtering. The adapter must
    # not accidentally count these selected cases as the original dataset size.
    state = {"tvars": "Labels", "closed": False, "fail_filter": False,
             "weight": None, "splits": [], "filter": "include",
             "names": ["X", "m", "Y", "include"],
             "rows": [(1., 2., 3., 1.), (2., None, 5., 1.), (3., 4., 7., 1.)],
             "dataset_n": 5, "levels": ["scale", "scale", "scale", "nominal"]}

    def submit(command):
        assert command.startswith("SET TVARS=")
        state["tvars"] = command.split("=")[1].rstrip(".")

    def filter_info(key):
        assert key == "Filter" and state["tvars"] == "NAMES"
        if state["fail_filter"]:
            raise RuntimeError("SPSS filter inspection failed")
        return state["filter"]

    class Cursor:
        def __init__(self, indexes, names, convertUserMissing, omitmissing):
            assert names is False and convertUserMissing is True and omitmissing is False
            self.rows = [tuple(row[i] for i in indexes) for row in state["rows"]]

        def __iter__(self):
            return iter(self.rows)

        def CClose(self):
            state["closed"] = True

    fake = SimpleNamespace(GetWeightVar=lambda: state["weight"],
                          GetSplitVariableNames=lambda: state["splits"],
                          GetVariableCount=lambda: len(state["names"]),
                          GetVariableName=lambda index: state["names"][index],
                          GetVariableMeasurementLevel=lambda index: state["levels"][index],
                          GetVariableLabel=lambda index: "label for " + state["names"][index],
                          GetVariableType=lambda index: 0,
                          GetCaseCount=lambda: state["dataset_n"],
                          GetSetting=lambda key: state["tvars"], Submit=submit)
    monkeypatch.setitem(sys.modules, "spss", fake)
    monkeypatch.setitem(sys.modules, "spssaux", SimpleNamespace(getDatasetInfo=filter_info))
    monkeypatch.setitem(sys.modules, "spssdata", SimpleNamespace(Spssdata=Cursor))
    return state


def test_native_selected_cases_keep_user_missing_and_close_cursor(spss_modules):
    graph = build_model("x", "y", ["m"])["graph"]
    frame, source = adapter.read_active_frame(graph)
    assert list(frame.columns) == ["x", "y", "m"]
    assert frame["m"].isna().tolist() == [False, True, False]
    assert source["dataset_n"] == 5
    assert source["read_n"] == 3
    assert source["filtered_n"] == 2
    assert source["filter_variable"] == "include"
    assert spss_modules["closed"] is True
    assert spss_modules["tvars"] == "LABELS"
    assert source["variables"][0]["spss_name"] == "X"


@pytest.mark.parametrize("setting,value,error", [("weight", "wt", "Weight Cases"),
                                                  ("splits", ["group"], "Split File")])
def test_unsupported_weight_and_split_cannot_be_silently_ignored(spss_modules, setting, value, error):
    spss_modules[setting] = value
    with pytest.raises(DialogError, match=error):
        adapter.read_active_frame(build_model("x", "y", ["m"])["graph"])


def test_label_preference_restored_even_when_filter_lookup_fails(spss_modules):
    spss_modules["fail_filter"] = True
    with pytest.raises(RuntimeError, match="filter inspection"):
        adapter.read_active_frame(build_model("x", "y", ["m"])["graph"])
    assert spss_modules["tvars"] == "LABELS"


def test_filter_can_also_be_selected_as_model_variable_without_duplicate_projection(spss_modules):
    spss_modules["names"] = ["x", "m", "y"]
    spss_modules["rows"] = [(1., 2., 3.), (2., 4., 5.)]
    spss_modules["dataset_n"] = 3
    spss_modules["filter"] = "x"
    frame, source = adapter.read_active_frame(build_model("x", "y", ["m"])["graph"])
    assert len(frame) == 2 and source["filtered_n"] == 1
    assert frame["m"].tolist() == [2., 4.]


def test_nominal_score_requires_explicit_categorical_declaration(spss_modules):
    spss_modules["levels"][0] = "nominal"
    with pytest.raises(DialogError, match="Categorical variables"):
        adapter.read_active_frame(build_model("x", "y", ["m"])["graph"])


def test_categories_resolve_on_common_sample_only_and_without_mutating_request():
    model = build_model("x", "y", ["m"], categorical=["x"], reference="LAST")
    original = deepcopy(model)
    frame = pd.DataFrame({"x": ["A", "B", "C", "A"], "m": [1., 2., None, 4.], "y": [2., 3., 4., 5.]})
    resolved = adapter.resolve_categories(model, frame)
    assert resolved["settings"]["categorical"] == [{"node_id": "X", "levels": ["A", "B"], "reference": "B"}]
    assert "dialog" not in resolved and model == original


def test_joint_category_probe_budget_stops_excessive_conditions():
    model = build_model("x", "y", ["m"], w="w", z="z", q="q", moderate_first="WZ",
                        moderate_second="Q", categorical=["w", "z", "q"])
    rows = [{"x": float(i), "m": float(i + 1), "y": float(i + 2), "w": w, "z": z, "q": q}
            for i, (w, z, q) in enumerate(__import__("itertools").product(range(3), repeat=3))]
    with pytest.raises(DialogError, match="25 joint"):
        adapter.resolve_categories(model, pd.DataFrame(rows))


def test_invalid_json_cannot_replace_existing_results(tmp_path):
    target = tmp_path / "results.json"
    target.write_text('{"previous": true}', encoding="utf-8")
    with pytest.raises(ValueError):
        adapter._save_json(target, {"bad": float("nan")})
    assert json.loads(target.read_text(encoding="utf-8")) == {"previous": True}
    assert list(tmp_path.iterdir()) == [target]


def test_successful_json_write_is_complete_and_cleans_temporary_file(tmp_path):
    target = tmp_path / "results.json"
    adapter._save_json(target, {"estimate": .125, "name": "Médiation"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"estimate": .125, "name": "Médiation"}
    assert list(tmp_path.iterdir()) == [target]
