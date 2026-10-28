"""Publication-friendly plots of saved PathLab estimates and uncertainty.

The renderer does not refit equations, select probes, or estimate thresholds.
Interaction curves use the engine's conditional fitted means. Johnson–Neyman
charts use its conditional path-slope grid and analytic observed-range regions.
"""
from __future__ import annotations

from collections import OrderedDict
import json
import math
from pathlib import Path
import re
import textwrap

from .branding import CREDIT, TITLE, AFFILIATION


class PlotError(ValueError):
    """A chart request cannot be represented faithfully."""


def _key(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _number(value):
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return str(value)
    return format(float(value), ".5g")


def _condition(values, labels):
    return "; ".join("%s = %s" % (labels.get(key, key), _number(value))
                     for key, value in sorted(values.items())) or "No other moderators"


def _numbers(rows, field):
    result = [float(row[field]) for row in rows]
    if not all(math.isfinite(value) for value in result):
        raise PlotError("A saved plot contains a non-finite %s value." % field)
    return result


def _selected_paths(process, path):
    graph = process["graph"]
    ids = {edge["id"] for edge in graph["edges"]}
    selected = str(path or "ALL").upper()
    if selected == "ALL":
        return ids
    roles = {node["id"]: node["role"] for node in graph["nodes"]}
    selectors = {
        "DIRECT": lambda source, target: source == "independent" and target == "dependent",
        "FIRST": lambda source, target: source == "independent" and target == "mediator",
        "FINAL": lambda source, target: source == "mediator" and target == "dependent",
        "SECOND": lambda source, target: source == "mediator" and target == "dependent",
        "SERIAL": lambda source, target: source == target == "mediator",
    }
    if selected in selectors:
        matches = {edge["id"] for edge in graph["edges"]
                   if selectors[selected](roles[edge["source"]], roles[edge["target"]])}
        return matches
    if path in ids:
        return {path}
    raise PlotError("Choose all paths, a listed mediation stage, or an existing model path.")


def prepare_interactions(process, path="ALL"):
    """Map saved fitted values into separate fixed-condition panels.

    Category positions are ordinal display positions only. Actual category
    labels retain the declared raw-value order, including numeric categories.
    """
    selected = _selected_paths(process, path)
    labels = {node["id"]: node["column"] for node in process["graph"]["nodes"]}
    coding = {row["node_id"]: row for row in process.get("coding", [])}
    prepared = []
    for plot in process.get("plots", []):
        if plot["path_id"] not in selected:
            continue
        panels = OrderedDict()
        for point in plot["points"]:
            condition = point.get("other_conditions", {})
            signature = _key(condition)
            panel = panels.setdefault(signature, {"condition": dict(condition), "lines": OrderedDict()})
            panel["lines"].setdefault(_key(point["moderator"]), {"moderator": point["moderator"], "rows": []})["rows"].append(point)
        source_coding = coding.get(plot["source_id"])
        category_values = source_coding["levels"] if source_coding else None
        for panel in panels.values():
            lines = []
            for line in panel["lines"].values():
                rows = line.pop("rows")
                if category_values is not None:
                    order = {_key(value): index for index, value in enumerate(category_values)}
                    if any(_key(row["x"]) not in order for row in rows):
                        raise PlotError("A saved category is absent from its coding declaration.")
                    rows = sorted(rows, key=lambda row: order[_key(row["x"])])
                    positions = [order[_key(row["x"])] for row in rows]
                else:
                    rows = sorted(rows, key=lambda row: float(row["x"]))
                    positions = _numbers(rows, "x")
                lower, upper = _numbers(rows, "lower"), _numbers(rows, "upper")
                if any(a > b for a, b in zip(lower, upper)):
                    raise PlotError("A saved fitted-mean confidence interval is reversed.")
                lines.append({"moderator": line["moderator"], "x": positions,
                              "predicted": _numbers(rows, "predicted"), "lower": lower, "upper": upper,
                              "label": "%s = %s" % (labels[plot["moderator_id"]], _number(line["moderator"]))})
            panel["lines"] = lines
            panel["label"] = _condition(panel["condition"], labels)
        prepared.append({"path_id": plot["path_id"], "source_id": plot["source_id"],
                         "target_id": plot["target_id"], "source": labels[plot["source_id"]],
                         "target": labels[plot["target_id"]], "moderator_id": plot["moderator_id"],
                         "moderator": labels[plot["moderator_id"]], "scale": plot["scale"],
                         "family": plot["family"], "note": plot["note"],
                         "category_values": category_values, "panels": list(panels.values())})
    return prepared


def prepare_johnson_neyman(process, path="ALL"):
    """Retain analytic regions and source-category contrasts without inference."""
    selected = _selected_paths(process, path)
    labels = {node["id"]: node["column"] for node in process["graph"]["nodes"]}
    edges = {edge["id"]: edge for edge in process["graph"]["edges"]}
    families = {row["target_id"]: row["family"] for row in process.get("equations", [])}
    groups, notices = OrderedDict(), []
    seen_notices = set()
    for entry in process.get("johnson_neyman", []):
        if entry["path_id"] not in selected:
            continue
        edge = edges[entry["path_id"]]
        contrast = entry.get("focal_contrast")
        signature = (entry["path_id"], entry["moderator_id"], _key(contrast))
        title = "%s → %s; moderator %s" % (labels[edge["source"]], labels[edge["target"]], labels[entry["moderator_id"]])
        if entry.get("status") != "computed" or not entry.get("grid"):
            reason = ("The saved result has no conditional-slope grid. Rerun the analysis to generate its diagram."
                      if entry.get("status") == "computed" else entry.get("reason") or "No numerical slope grid is available.")
            notice = "Johnson–Neyman unavailable for %s: %s" % (title, reason)
            if notice not in seen_notices:
                seen_notices.add(notice)
                notices.append(notice)
            continue
        limits = entry.get("observed_range")
        if not isinstance(limits, list) or len(limits) != 2 or not all(math.isfinite(float(value)) for value in limits) or limits[0] >= limits[1]:
            raise PlotError("A saved Johnson–Neyman result has no valid observed moderator range.")
        rows = sorted(entry["grid"], key=lambda row: float(row["moderator"]))
        x, lower, upper = _numbers(rows, "moderator"), _numbers(rows, "lower"), _numbers(rows, "upper")
        if any(a > b for a, b in zip(lower, upper)) or x[0] < limits[0] or x[-1] > limits[1]:
            raise PlotError("A saved Johnson–Neyman grid is outside its valid bounds.")
        regions = []
        for region in entry["regions"]:
            a, b = float(region["lower"]), float(region["upper"])
            if not limits[0] <= a < b <= limits[1] or not isinstance(region["significant"], bool):
                raise PlotError("A saved Johnson–Neyman region is invalid.")
            regions.append({"lower": a, "upper": b, "significant": region["significant"]})
        boundaries = [float(value) for value in entry.get("boundaries", [])]
        if not all(math.isfinite(value) and limits[0] < value < limits[1] for value in boundaries):
            raise PlotError("A Johnson–Neyman boundary lies outside the observed range.")
        group = groups.setdefault(signature, {"path_id": entry["path_id"], "source": labels[edge["source"]],
            "target": labels[edge["target"]], "moderator_id": entry["moderator_id"],
            "moderator": labels[entry["moderator_id"]], "focal_contrast": contrast,
            "family": families.get(edge["target"], "linear"), "panels": []})
        group["panels"].append({"condition": dict(entry.get("other_conditions", {})),
            "label": _condition(entry.get("other_conditions", {}), labels), "x": x,
            "estimate": _numbers(rows, "estimate"), "lower": lower, "upper": upper,
            "observed_range": list(limits), "regions": regions, "boundaries": boundaries,
            "boundary_details": entry.get("boundary_details", []), "assumptions": entry.get("assumptions", [])})
    return list(groups.values()), notices


def _axes(count, title, subtitle, footer):
    # An explicit Agg canvas avoids changing an existing extension's pyplot
    # backend or closing any figures it may have left open in this interpreter.
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    columns = 1 if count == 1 else 2
    rows = int(math.ceil(count / columns))
    figure = Figure(figsize=(8.4 if columns == 1 else 10.8, 5.9 if rows == 1 else 8.0))
    FigureCanvasAgg(figure)
    axes = figure.subplots(rows, columns, squeeze=False)
    figure.set_facecolor("white")
    figure.suptitle(title, x=.08, y=.97, ha="left", fontsize=15, fontweight="bold", color="#18354b")
    figure.text(.08, .92, subtitle, ha="left", va="top", fontsize=10, color="#455866")
    figure.text(.08, .065, textwrap.fill(footer, width=125 if columns == 2 else 102), ha="left", va="bottom", fontsize=8, color="#455866")
    figure.text(.08, .018, "PathLab | %s\n%s | %s" % (CREDIT, TITLE, AFFILIATION),
                ha="left", va="bottom", fontsize=7, color="#455866")
    figure.subplots_adjust(left=.095, right=.97, top=.82 if rows == 1 else .85, bottom=.20 if rows == 1 else .17, hspace=.48, wspace=.32)
    flat = list(axes.flat)
    for axis in flat[:count]:
        axis.set_facecolor("white")
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.spines["left"].set_color("#a5b3bc")
        axis.spines["bottom"].set_color("#a5b3bc")
        axis.tick_params(labelsize=9, colors="#304654")
        axis.grid(axis="y", color="#e4eaf0", linewidth=.7, zorder=0)
    for axis in flat[count:]:
        axis.set_visible(False)
    return figure, flat[:count]


def render_plots(process, output_dir, interaction=True, johnson_neyman=True, path="ALL"):
    """Return PNG metadata and notices; never modify the source result.

    ``path`` accepts ALL, DIRECT, FIRST, FINAL/SECOND, SERIAL, or an exact path
    ID. Every fixed other-moderator combination is retained, up to four panels
    per page. PNGs are ordinary files for the caller to insert in the Viewer.
    """
    charts, notices = [], []
    if not interaction and not johnson_neyman:
        return {"charts": charts, "notices": notices}
    interactions = prepare_interactions(process, path) if interaction else []
    jn, inapplicable = prepare_johnson_neyman(process, path) if johnson_neyman else ([], [])
    notices.extend(inapplicable)
    if not interactions and not jn:
        if not notices:
            notices.append("No moderated path matches this plot selection. Select a moderator and a moderation stage to create interaction or Johnson–Neyman diagrams.")
        return {"charts": charts, "notices": notices}
    import matplotlib
    from matplotlib.patches import Patch
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    confidence = 100 * float(process["bootstrap"]["confidence_level"])
    colors = ["#17629b", "#d4801c", "#198367", "#9b4c9b", "#5e6973", "#a44a3f", "#6c8d28", "#3c79a1", "#826b9e", "#c08a4e"]

    def save(figure, metadata):
        filename = "%03d_%s_%s.png" % (len(charts) + 1, metadata["kind"], re.sub(r"[^A-Za-z0-9_]+", "_", metadata["path_id"]))
        target = destination / filename
        try:
            figure.savefig(str(target), dpi=160, facecolor="white")
        finally:
            figure.clear()
        charts.append({**metadata, "path": str(target)})

    with matplotlib.rc_context({"font.family": "DejaVu Sans", "font.size": 10, "axes.labelcolor": "#304654", "lines.linewidth": 2.0}):
        for plot in interactions:
            for start in range(0, len(plot["panels"]), 4):
                panels = plot["panels"][start:start + 4]
                title = "Interaction: %s → %s" % (plot["source"], plot["target"])
                footer = "%g%% pointwise confidence bands for fitted means. %s" % (confidence, plot["note"])
                figure, axes = _axes(len(panels), title, "Lines show observed/probed values of %s" % plot["moderator"], footer)
                for axis, panel in zip(axes, panels):
                    for index, line in enumerate(panel["lines"]):
                        color = colors[index % len(colors)]
                        categorical = plot["category_values"] is not None
                        axis.plot(line["x"], line["predicted"], color=color, marker="o" if categorical else None, markersize=4, label=line["label"], zorder=3)
                        if categorical:
                            axis.vlines(line["x"], line["lower"], line["upper"], color=color, alpha=.55, linewidth=1.1)
                        else:
                            axis.fill_between(line["x"], line["lower"], line["upper"], color=color, alpha=.10, linewidth=0, zorder=2)
                    if plot["category_values"] is not None:
                        axis.set_xticks(range(len(plot["category_values"])))
                        axis.set_xticklabels([str(value) for value in plot["category_values"]], rotation=20 if len(plot["category_values"]) > 4 else 0, ha="right" if len(plot["category_values"]) > 4 else "center")
                    axis.set_xlabel(plot["source"])
                    axis.set_ylabel("Predicted probability of %s = 1" % plot["target"] if plot["scale"] == "probability" else "Predicted %s" % plot["target"])
                    if plot["scale"] == "probability":
                        axis.set_ylim(0, 1)
                    axis.set_title(textwrap.fill(panel["label"], 48), fontsize=9, loc="left", pad=10)
                    axis.legend(frameon=False, fontsize=8, loc="best")
                viewer_title = "%s by %s" % (title, plot["moderator"])
                if len(plot["panels"]) > 4:
                    viewer_title += " (page %d)" % (start // 4 + 1)
                save(figure, {"title": viewer_title, "kind": "interaction", "path_id": plot["path_id"],
                    "moderator_id": plot["moderator_id"], "conditions": [panel["condition"] for panel in panels],
                    "page": start // 4 + 1, "panels": len(panels), "scale": plot["scale"], "note": footer})
        for plot in jn:
            for start in range(0, len(plot["panels"]), 4):
                panels = plot["panels"][start:start + 4]
                title = "Johnson–Neyman: %s → %s" % (plot["source"], plot["target"])
                contrast = plot["focal_contrast"]
                contrast_text = " Contrast: %s versus %s." % (_number(contrast["level"]), _number(contrast["reference"])) if contrast else ""
                scale = "log-odds" if plot["family"] == "logistic" else "outcome units"
                footer = "%g%% pointwise confidence band; no multiplicity adjustment. Green regions use analytic path-slope boundaries within the observed moderator range. This is a conditional path effect, not an indirect-effect region." % confidence
                figure, axes = _axes(len(panels), title, "Conditional path effect across %s (%s).%s" % (plot["moderator"], scale, contrast_text), footer)
                for axis, panel in zip(axes, panels):
                    for region in panel["regions"]:
                        if region["significant"]:
                            axis.axvspan(region["lower"], region["upper"], color="#dcefe5", zorder=0)
                    axis.fill_between(panel["x"], panel["lower"], panel["upper"], color="#17629b", alpha=.16, linewidth=0, zorder=2)
                    slope_line, = axis.plot(panel["x"], panel["estimate"], color="#17629b", label="Conditional path effect", zorder=3)
                    axis.axhline(0, color="#687986", linestyle="--", linewidth=1, zorder=4)
                    for value in panel["boundaries"]:
                        axis.axvline(value, color="#8d6e40", linestyle=":", linewidth=1.2, zorder=4)
                        axis.text(value, .98, " %s = %s" % (plot["moderator"], _number(value)), transform=axis.get_xaxis_transform(), va="top", ha="right", rotation=90, fontsize=8, color="#73572c")
                    axis.set_xlim(panel["observed_range"])
                    axis.set_xlabel(plot["moderator"])
                    axis.set_ylabel("Conditional contrast (%s)" % scale if contrast else "Conditional slope (%s)" % scale)
                    axis.set_title(textwrap.fill(panel["label"], 48), fontsize=9, loc="left", pad=10)
                    handles = [slope_line, Patch(facecolor="#17629b", alpha=.16, label="%g%% pointwise CI" % confidence)]
                    if any(region["significant"] for region in panel["regions"]):
                        handles.append(Patch(facecolor="#dcefe5", label="CI excludes zero"))
                    axis.legend(handles=handles, frameon=False, fontsize=8, loc="best")
                    if not panel["boundaries"]:
                        axis.text(.02, .02, "No threshold inside the observed range", transform=axis.transAxes, fontsize=8, color="#455866")
                viewer_title = "%s across %s%s" % (title, plot["moderator"], contrast_text)
                if len(plot["panels"]) > 4:
                    viewer_title += " (page %d)" % (start // 4 + 1)
                save(figure, {"title": viewer_title, "kind": "johnson_neyman", "path_id": plot["path_id"],
                    "moderator_id": plot["moderator_id"], "conditions": [panel["condition"] for panel in panels],
                    "page": start // 4 + 1, "panels": len(panels), "scale": scale, "focal_contrast": contrast,
                    "boundaries": [panel["boundaries"] for panel in panels], "note": footer})
    return {"charts": charts, "notices": notices}
