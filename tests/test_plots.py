"""Saved-estimate semantics and faithful plotting, independent of fitting."""
from copy import deepcopy
from pathlib import Path
import struct
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pathlab_spss.plots import PlotError, prepare_interactions, prepare_johnson_neyman, render_plots


def saved_result(conditions=1, categorical_x=False, logistic=False):
    nodes = [{"id": i, "column": column, "role": role} for i, column, role in
             [("X", "Training", "independent"), ("Y", "Performance", "dependent"),
              ("W", "Support", "moderator"), ("Z", "Experience", "moderator")]]
    points, jn = [], []
    xs = ["Treatment", "Control"] if categorical_x else [-1., 0., 1.]
    for condition in range(conditions):
        other = {"Z": float(condition)} if conditions > 1 else {}
        for w in [0., 1.]:
            for j, x in enumerate(xs):
                value = .2 + .1*j + .1*w + .02*condition
                points.append({"x": x, "moderator": w, "other_conditions": other,
                               "predicted": value, "lower": value-.1, "upper": value+.1})
        entry = {"path_id": "p_X_Y", "moderator_id": "W", "other_conditions": other,
                 "boundaries": [1.], "observed_range": [-2., 2.], "status": "computed",
                 "regions": [{"lower": -2., "upper": 1., "significant": False},
                             {"lower": 1., "upper": 2., "significant": True}],
                 "grid": [{"moderator": x, "estimate": value, "lower": low, "upper": high}
                          for x, value, low, high in [(-2., -.4, -1., .3), (0., .1, -.4, .6),
                                                      (1., .5, 0., 1.), (2., .75, .2, 1.3)]]}
        if categorical_x:
            entry["focal_contrast"] = {"node_id": "X", "level": "Treatment", "reference": "Control"}
        jn.append(entry)
    return {"graph": {"nodes": nodes, "edges": [{"id": "p_X_Y", "source": "X", "target": "Y"}], "moderations": []},
            "coding": [{"node_id": "X", "levels": ["Treatment", "Control"], "reference": "Control"}] if categorical_x else [],
            "equations": [{"target_id": "Y", "family": "logistic" if logistic else "linear"}],
            "bootstrap": {"confidence_level": .95},
            "plots": [{"path_id": "p_X_Y", "source_id": "X", "target_id": "Y", "moderator_id": "W",
                       "family": "logistic" if logistic else "linear", "scale": "probability" if logistic else "outcome_mean",
                       "note": "Other quantitative predictors held at complete-case means.", "points": points}],
            "johnson_neyman": jn}


def test_interactions_keep_exact_means_intervals_and_fixed_conditions():
    process = saved_result(conditions=3)
    original = deepcopy(process)
    prepared = prepare_interactions(process)
    assert len(prepared) == 1 and len(prepared[0]["panels"]) == 3
    for index, panel in enumerate(prepared[0]["panels"]):
        assert panel["condition"] == {"Z": float(index)}
        assert len(panel["lines"]) == 2
        assert panel["lines"][0]["x"] == [-1., 0., 1.]
        assert panel["lines"][0]["predicted"] == pytest.approx([.2+.02*index, .3+.02*index, .4+.02*index])
        assert panel["lines"][1]["lower"] == pytest.approx([.2+.02*index, .3+.02*index, .4+.02*index])
        assert panel["lines"][1]["label"] == "Support = 1"
    assert process == original


def test_category_positions_preserve_declared_raw_order_and_contrast():
    process = saved_result(categorical_x=True)
    plot = prepare_interactions(process)[0]
    assert plot["category_values"] == ["Treatment", "Control"]
    assert plot["panels"][0]["lines"][0]["x"] == [0, 1]
    jn, notices = prepare_johnson_neyman(process)
    assert not notices
    assert jn[0]["focal_contrast"] == {"node_id": "X", "level": "Treatment", "reference": "Control"}


def test_johnson_neyman_uses_analytic_regions_without_grid_threshold_estimation():
    process = saved_result()
    process["johnson_neyman"][0]["grid"] = list(reversed(process["johnson_neyman"][0]["grid"]))
    original = deepcopy(process)
    groups, notices = prepare_johnson_neyman(process)
    assert not notices
    panel = groups[0]["panels"][0]
    assert panel["x"] == [-2., 0., 1., 2.]
    assert panel["boundaries"] == [1.]
    assert panel["regions"] == [{"lower": -2., "upper": 1., "significant": False},
                                {"lower": 1., "upper": 2., "significant": True}]
    assert panel["lower"] == [-1., -.4, 0., .2]
    assert process == original


def test_categorical_moderator_retains_interaction_and_explains_jn_inapplicability(tmp_path):
    process = saved_result()
    process["johnson_neyman"] = [{"path_id": "p_X_Y", "moderator_id": "W", "status": "not_applicable",
                                  "reason": "Categorical moderators use level comparisons, not numerical Johnson–Neyman regions.", "grid": []}]
    result = render_plots(process, tmp_path)
    assert [chart["kind"] for chart in result["charts"]] == ["interaction"]
    assert "Categorical moderators" in result["notices"][0]


def test_logistic_scales_remain_probability_for_means_and_log_odds_for_path_effect(tmp_path):
    result = render_plots(saved_result(logistic=True), tmp_path)
    assert [chart["scale"] for chart in result["charts"]] == ["probability", "log-odds"]
    assert "not an indirect-effect region" in result["charts"][1]["note"]


def test_pages_preserve_all_conditions_without_overlaying_fixed_moderators(tmp_path):
    result = render_plots(saved_result(conditions=5), tmp_path)
    assert len(result["charts"]) == 4
    assert [chart["panels"] for chart in result["charts"]] == [4, 1, 4, 1]
    assert [chart["conditions"] for chart in result["charts"][:2]] == [
        [{"Z": 0.}, {"Z": 1.}, {"Z": 2.}, {"Z": 3.}], [{"Z": 4.}]]
    for chart in result["charts"]:
        path = Path(chart["path"])
        content = path.read_bytes()
        assert path.is_absolute() and content[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", content[16:24])
        assert width >= 1200 and height >= 800


def test_unknown_path_and_malformed_saved_limits_do_not_produce_misleading_charts(tmp_path):
    with pytest.raises(PlotError, match="existing model path"):
        render_plots(saved_result(), tmp_path, path="no_such_path")
    process = saved_result()
    process["johnson_neyman"][0]["observed_range"] = [0., 2.]
    with pytest.raises(PlotError, match="outside"):
        render_plots(process, tmp_path)
    assert not list(tmp_path.glob("*.png"))


def test_no_moderation_or_nonmatching_stage_explains_missing_plots(tmp_path):
    result = render_plots(saved_result(), tmp_path, path="SERIAL")
    assert not result["charts"] and "No moderated path matches" in result["notices"][0]
    result = render_plots(saved_result(), tmp_path, interaction=False, johnson_neyman=False)
    assert result == {"charts": [], "notices": []}


def test_no_threshold_inside_observed_range_still_renders_jn_chart(tmp_path):
    process = saved_result()
    entry = process["johnson_neyman"][0]
    entry["boundaries"] = []
    entry["regions"] = [{"lower": -2., "upper": 2., "significant": False}]
    result = render_plots(process, tmp_path, interaction=False)
    assert len(result["charts"]) == 1
    assert result["charts"][0]["boundaries"] == [[]]


def test_old_saved_results_without_jn_grid_explain_diagram_regeneration(tmp_path):
    process = saved_result()
    process["johnson_neyman"][0]["grid"] = []
    result = render_plots(process, tmp_path, interaction=False)
    assert not result["charts"]
    assert "Rerun the analysis" in result["notices"][0]
