"""Guided choices reject contradictory models before reading research data."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pathlab_spss.adapter import presentation_options
from pathlab_spss.models import DialogError, build_model, validate_analysis
from pathlab_spss.report import _overview


@pytest.mark.parametrize("expected,kwargs", [
    ("MEDIATION", {"mediators": ["m"]}),
    ("MODERATION", {"w": "w", "moderate_direct": "W"}),
    ("CONDITIONAL", {"mediators": ["m"], "w": "w", "moderate_first": "W"}),
])
def test_automatic_goal_matches_selected_roles_and_explicit_goal(expected, kwargs):
    model = build_model("x", "y", **kwargs)
    assert validate_analysis("AUTO", model) == expected
    assert validate_analysis(expected.lower(), model) == expected
    for other in {"MEDIATION", "MODERATION", "CONDITIONAL"} - {expected}:
        with pytest.raises(DialogError, match="For "):
            validate_analysis(other, model)


def test_invalid_goal_is_actionable():
    with pytest.raises(DialogError, match="Choose Mediation"):
        validate_analysis("TYPO", build_model("x", "y", ["m"]))


def test_default_presentation_is_readable_with_both_diagrams():
    assert presentation_options() == ("BOTH", "STANDARD", None)


def test_export_folder_is_explicit_and_must_exist(tmp_path):
    assert presentation_options("jn", "full", tmp_path) == ("JN", "FULL", tmp_path.resolve())
    with pytest.raises(DialogError, match="existing folder"):
        presentation_options(plot_directory=tmp_path / "unavailable")


@pytest.mark.parametrize("kwargs,message", [({"plots": "UNKNOWN"}, "Under Diagrams"),
                                            ({"output_detail": "UNKNOWN"}, "under Options")])
def test_invalid_output_selections_cannot_silently_fall_back(kwargs, message):
    with pytest.raises(DialogError, match=message):
        presentation_options(**kwargs)


def test_overview_shows_research_variable_names_and_honest_region_labels():
    graph = build_model("Training", "Performance", w="Experience", moderate_direct="W")["graph"]
    _, _, describe = _overview({"graph": graph})
    row = describe({"path_id": "p_X_Y", "moderator_id": "W", "other_conditions": {},
                    "boundaries": [1.25], "regions": [{"lower": 0., "upper": 1.25, "significant": False},
                    {"lower": 1.25, "upper": 3., "significant": True}]})
    assert row["path"] == "Training → Performance"
    assert row["moderator"] == "Experience"
    assert row["boundaries"] == "1.25"
    assert "CI includes zero" in row["regions"] and "CI excludes zero" in row["regions"]
