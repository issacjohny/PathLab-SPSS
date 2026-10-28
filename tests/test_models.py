"""User-facing model selections must produce the intended validated graph."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pathlab_spss.core import validate_process
from pathlab_spss.models import DialogError, build_model, check_options


def validated(model):
    settings = deepcopy(model["settings"])
    settings["categorical"] = [{"node_id": node_id, "levels": [0, 1], "reference": 0}
                               for node_id in model["dialog"]["categorical_ids"]]
    return validate_process(model["graph"], settings,
                            [node["column"] for node in model["graph"]["nodes"]])


@pytest.mark.parametrize("structure,expected", [
    ("PARALLEL", {("X", "M1"), ("X", "M2"), ("M1", "Y"), ("M2", "Y"), ("X", "Y")}),
    ("SERIAL", {("X", "M1"), ("M1", "M2"), ("M2", "Y"), ("X", "Y")}),
    ("COMBINED", {("X", "M1"), ("X", "M2"), ("M1", "M2"),
                  ("M1", "Y"), ("M2", "Y"), ("X", "Y")}),
])
def test_presets_preserve_named_columns_and_explicit_direct_path(structure, expected):
    model = build_model("predictor", "outcome", ["first_mediator", "second_mediator"], structure)
    assert {(edge["source"], edge["target"]) for edge in model["graph"]["edges"]} == expected
    assert {node["id"]: node["column"] for node in model["graph"]["nodes"]} == {
        "X": "predictor", "Y": "outcome", "M1": "first_mediator", "M2": "second_mediator"}
    _, _, routes = validated(model)
    assert [(["p_X_Y"], ["X", "Y"])] == [r for r in routes if len(r[0]) == 1]
    assert len(routes) == {"PARALLEL": 3, "SERIAL": 2, "COMBINED": 4}[structure]


def test_combined_six_mediators_pass_route_budget_seven_rejected_early():
    model = build_model("x", "y", ["m%d" % i for i in range(6)], "COMBINED")
    assert len(validated(model)[2]) == 64
    with pytest.raises(DialogError, match="100-route"):
        build_model("x", "y", ["m%d" % i for i in range(7)], "COMBINED")
    # Long serial and parallel models remain within the route budget.
    assert len(validated(build_model("x", "y", ["m%d" % i for i in range(10)], "SERIAL"))[2]) == 2
    assert len(validated(build_model("x", "y", ["m%d" % i for i in range(10)], "PARALLEL"))[2]) == 11


def test_joint_pair_adds_hierarchy_complete_interactions_and_moderator_main_effects():
    model = build_model("x", "y", ["m"], w="w", z="z", moderate_first="WZ", moderate_second="WZ")
    validated(model)
    graph = model["graph"]
    edges = {edge["id"]: edge for edge in graph["edges"]}
    signatures = {(edges[mod["path_id"]]["target"],
                   frozenset([edges[mod["path_id"]]["source"], *mod["moderator_ids"]]))
                  for mod in graph["moderations"]}
    assert signatures == {
        ("M1", frozenset(["X", "W"])), ("M1", frozenset(["X", "Z"])),
        ("M1", frozenset(["W", "Z"])), ("M1", frozenset(["X", "W", "Z"])),
        ("Y", frozenset(["M1", "W"])), ("Y", frozenset(["M1", "Z"])),
        ("Y", frozenset(["W", "Z"])), ("Y", frozenset(["M1", "W", "Z"])),
    }
    assert {("W", "M1"), ("Z", "M1"), ("W", "Y"), ("Z", "Y")} <= {
        (edge["source"], edge["target"]) for edge in graph["edges"]}


def test_repeated_joint_pair_at_same_equation_deduplicates_wz_lower_order_term():
    model = build_model("x", "y", ["m"], w="w", z="z", moderate_second="WZ", moderate_direct="WZ")
    validated(model)
    edges = {edge["id"]: edge for edge in model["graph"]["edges"]}
    signatures = [(edges[mod["path_id"]]["target"],
                   tuple(sorted([edges[mod["path_id"]]["source"], *mod["moderator_ids"]])))
                  for mod in model["graph"]["moderations"]]
    assert len(signatures) == len(set(signatures)) == 7


def test_three_moderators_use_eight_automatic_conditions_and_all_stages_validate():
    model = build_model("x", "y", ["a", "b"], "SERIAL", w="w", z="z", q="q",
                        moderate_first="W", moderate_serial="Z", moderate_second="Q")
    validated(model)
    assert model["settings"]["automatic_probes"]["probabilities"] == [.16, .84]
    assert len(model["settings"]["automatic_probes"]["probabilities"])**3 == 8
    model = build_model("x", "y", ["m"], w="w", z="z", moderate_first="W", moderate_second="Z")
    assert model["settings"]["automatic_probes"]["probabilities"] == [.16, .5, .84]


def test_moderation_without_mediator_and_logistic_outcome_validate():
    model = build_model("x", "binary_y", w="w", z="z", moderate_direct="WZ", family="LOGISTIC")
    canonical, _, routes = validated(model)
    assert len(routes) == 1
    assert next(node for node in canonical["nodes"] if node["id"] == "Y")["measurement_scale"] == "nominal"
    assert model["settings"]["outcome_family"] == "logistic"


def test_categorical_ids_and_reference_policy_preserve_raw_variable_mapping():
    model = build_model("Treatment", "y", ["m"], w="Group", covariates=["Region", "Age"],
                        moderate_first="W", categorical=["treatment", "GROUP", "region"], reference="LAST")
    validated(model)
    assert model["dialog"]["categorical_ids"] == ["C1", "W", "X"]
    assert model["dialog"]["reference"] == "LAST"
    assert {node["column"] for node in model["graph"]["nodes"] if node["measurement_scale"] == "nominal"} == {
        "Treatment", "Group", "Region"}
    assert {("C1", "M1"), ("C1", "Y"), ("C2", "M1"), ("C2", "Y")} <= {
        (edge["source"], edge["target"]) for edge in model["graph"]["edges"]}


@pytest.mark.parametrize("kwargs,match", [
    ({"x": "x X"}, "exactly one"),
    ({"y": "X"}, "different variables"),
    ({"mediators": ["m", "M"]}, "different variables"),
    ({"mediators": ["m"], "w": "W", "covariates": ["w"]}, "different variables"),
    ({"mediators": ["m"], "w": "w"}, "Assign every"),
    ({"mediators": ["m"], "moderate_first": "W"}, "box is empty"),
    ({"mediators": ["m"], "w": "w z"}, "exactly one"),
    ({"mediators": [], "w": "w", "moderate_first": "W"}, "no first-stage"),
    ({"mediators": ["m1", "m2"], "w": "w", "moderate_serial": "W"}, "no serial-stage"),
    ({"mediators": ["m"], "w": "w", "moderate_first": "WZQ"}, "listed moderator"),
    ({"mediators": ["m"], "categorical": ["m"]}, "Only X"),
    ({"mediators": ["m"], "categorical": ["y"]}, "Only X"),
    ({"mediators": ["m"], "categorical": ["not_selected"]}, "unique selected"),
    ({"mediators": ["m"], "categorical": ["x", "X"]}, "unique selected"),
    ({"mediators": ["m"], "categorical": [4]}, "valid SPSS name"),
    ({"mediators": 4}, "variable names"),
    ({"mediators": ["m"]*11}, "at most 10"),
    ({"mediators": ["m"], "covariates": ["c"]*21}, "at most 10"),
    ({"mediators": ["m"], "structure": "UNKNOWN"}, "parallel, serial"),
    ({"mediators": ["m"], "family": "BINARY"}, "valid outcome"),
    ({"mediators": ["m"], "reference": "MIDDLE"}, "valid outcome"),
    ({"mediators": []}, "mediator or moderate"),
])
def test_invalid_selections_report_dialog_errors(kwargs, match):
    with pytest.raises(DialogError, match=match):
        build_model(**{"x": "x", "y": "y", "mediators": ["m"], **kwargs})


@pytest.mark.parametrize("bootstrap", [True, False, 199, 50001, 200.0, "200"])
def test_bootstrap_scalar_validation(bootstrap):
    with pytest.raises(DialogError, match="Bootstrap"):
        check_options(bootstrap=bootstrap)


@pytest.mark.parametrize("confidence", [True, False, 49.9, 100, float("nan"), float("inf"), "95"])
def test_confidence_scalar_validation(confidence):
    with pytest.raises(DialogError, match="Confidence"):
        check_options(confidence=confidence)


@pytest.mark.parametrize("seed", [True, False, -1, 2147483648, 12.0, "12"])
def test_seed_scalar_validation(seed):
    with pytest.raises(DialogError, match="Random seed"):
        check_options(seed=seed)


def test_options_return_explicit_estimator_and_alpha():
    assert check_options(bootstrap=200, confidence=90, seed=0, robust="CLASSICAL") == (
        {"bootstrap": 200, "alpha": pytest.approx(.1), "robust": False}, 0)
    assert check_options(bootstrap=50000, confidence=99.9, seed=2147483647, robust=True)[0]["robust"] is True
    with pytest.raises(DialogError, match="HC3 or classical"):
        check_options(robust="HC1")
