"""Native SPSS Viewer inference tables and readable diagnostic summaries."""
from __future__ import annotations

import json
import textwrap

from .branding import CREDIT_BLOCK


def _text(spss, title, content):
    """SPSS text blocks retain literal line breaks rather than wrapping prose."""
    lines = [textwrap.fill(line, width=100, break_long_words=False, break_on_hyphens=False)
             if line else "" for line in str(content).splitlines()]
    spss.TextBlock(title, "\n".join(lines))


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return value


def _table(spss, title, columns, rows):
    if not rows:
        return
    # Chunk long tables to keep the Viewer usable without dropping any rows.
    for start in range(0, len(rows), 250):
        chunk = rows[start:start + 250]
        suffix = " (rows %d-%d)" % (start + 1, start + len(chunk)) if len(rows) > 250 else ""
        table = spss.BasePivotTable(title + suffix, "PathLab")
        table.SimplePivotTable(rowdim="Rows", coldim="Statistics",
                               rowlabels=[str(start + i + 1) for i in range(len(chunk))],
                               collabels=[label for _, label in columns],
                               cells=[[_cell(row.get(key)) for key, _ in columns] for row in chunk])


def display_error(message):
    import spss
    spss.StartProcedure("PathLab")
    try:
        _text(spss, "PathLab: analysis stopped", message)
    finally:
        spss.EndProcedure()


def display_appendix(result):
    import spss
    process = result["process"]
    nodes = {n["id"]: n["column"] for n in process["graph"]["nodes"]}
    edges = {e["id"]: "%s → %s" % (nodes[e["source"]], nodes[e["target"]]) for e in process["graph"]["edges"]}

    def condition(value):
        return "; ".join("%s = %s" % (nodes.get(key, key), _cell(item)) for key, item in sorted(value.items())) or "Unconditional"

    def decorate(row):
        row = dict(row)
        for key in ("condition", "condition_a", "condition_b", "other_conditions"):
            if isinstance(row.get(key), dict):
                row[key] = condition(row[key])
        if "node_ids" in row:
            row["route"] = " → ".join(nodes.get(i, i) for i in row["node_ids"])
        if "path_ids" in row:
            row["paths"] = "; ".join(edges.get(i, i) for i in row["path_ids"])
        if "path_id" in row:
            row["path"] = edges.get(row["path_id"], row["path_id"])
        if "target_id" in row:
            row["outcome"] = nodes.get(row["target_id"], row["target_id"])
        return row

    ci = [("estimate", "Estimate"), ("bootstrap_se", "Bootstrap SE"), ("lower", "Lower CI"), ("upper", "Upper CI")]
    inference = [("estimate", "B"), ("se", "SE"), ("statistic", "t / z"), ("p", "p"), ("lower", "Lower CI"), ("upper", "Upper CI")]
    spss.StartProcedure("PathLab")
    try:
        _text(spss, "PathLab — full technical appendix", "Version %s. This appendix contains equation diagnostics, paired contrasts, coding and reproduction details. The main results and diagrams appear above." % result["version"])
        source = result["source"]
        sample = process["sample"]
        _table(spss, "Analysis sample", [("dataset_n", "Dataset cases"), ("filtered_n", "Excluded by filter"),
                ("source_n", "Selected cases"), ("n", "Complete cases"), ("excluded", "Excluded: missing")], [{**source, **sample}])
        _table(spss, "Bootstrap and inference", [("requested", "Requested"), ("successful", "Successful"), ("failed", "Failed"),
                ("seed", "Seed"), ("ci_method", "CI method"), ("confidence_level", "Confidence"), ("failure_reasons", "Failure reasons")], [process["bootstrap"]])
        policy = process.get("probe_policy", {})
        _text(spss, "Moderator probe policy", "Numerical moderator probes are resolved once on the common sample at percentiles %s. Categorical moderators use their declared levels. Actual values are shown in every conditional effect table." % ", ".join(str(100 * p) for p in policy.get("probabilities", [])))
        _table(spss, "Variable roles and columns", [("id", "ID"), ("column", "Variable"), ("role", "Role"), ("measurement_scale", "Analysis scale")], process["graph"]["nodes"])
        _table(spss, "Categorical indicator coding", [("column", "Variable"), ("reference", "Reference"), ("levels", "Levels"), ("counts", "Category counts")], process["coding"])
        for equation in process["equations"]:
            _text(spss, "Equation: " + equation["column"], equation["formula"] + "\nStandard errors: " + equation["standard_errors"])
            _table(spss, "Coefficients: " + equation["column"], [("term", "Term"), *inference, ("reference", "Reference distribution")], equation["coefficients"])
            fit_keys = [("n", "N"), ("df_model", "Model df"), ("df_resid", "Residual df"), ("R2", "R²"),
                        ("adjustedR2", "Adjusted R²"), ("RMSE", "RMSE"), ("pseudo_R2", "Pseudo R²"), ("AIC", "AIC"), ("BIC", "BIC"), ("overall_test", "Overall test")]
            _table(spss, "Model fit: " + equation["column"], [(key, label) for key, label in fit_keys if key in equation], [equation])
            diagnostics = equation.get("diagnostics", {})
            _table(spss, "Diagnostics: " + equation["column"], [(key, key.replace("_", " ")) for key in diagnostics], [diagnostics] if diagnostics else [])
            evidence = equation.get("diagnostic_evidence", {})
            design = evidence.get("design", {})
            _table(spss, "Design diagnostics: " + equation["column"], [("columns", "Columns"), ("rank", "Rank"), ("condition_number", "Condition number")], [design] if design else [])
            term_names = {row["term_id"]: row["term"] for row in equation["coefficients"]}
            vif_rows = [{**row, "term": term_names.get(row["term_id"], row["term_id"])} for row in design.get("vif", [])]
            _table(spss, "Variance inflation: " + equation["column"], [("term", "Term"), ("value", "VIF"), ("unavailable_reason", "Reason if unavailable")], vif_rows)
            linear = evidence.get("linear", {})
            summary = linear.get("full_sample", {})
            _table(spss, "Influence screening: " + equation["column"], [(key, key.replace("_", " ")) for key in summary], [summary] if summary else [])
            if linear.get("reason"):
                _text(spss, "Diagnostic applicability", linear["reason"])
            if design.get("condition_number_note"):
                _text(spss, "Design diagnostic interpretation", design["condition_number_note"])
            if linear.get("notes"):
                _text(spss, "Influence diagnostic interpretation", "\n".join(linear["notes"]))
            _table(spss, "Odds ratios: " + equation["column"], [("term_id", "Term ID"), ("estimate", "Odds ratio"), ("lower", "Lower CI"), ("upper", "Upper CI")], equation.get("odds_ratios", []))
        _table(spss, "Conditional direct, indirect and total associations", [("id", "Effect ID"), ("kind", "Effect"), ("route", "Route"), ("paths", "Paths"),
                ("condition", "Moderator condition"), ("focal_contrast", "X contrast"), *ci, ("scale", "Scale")], [decorate(row) for row in process["effects"]])
        _table(spss, "Paired bootstrap effect contrasts", [("kind", "Contrast"), ("effect_a", "Effect A ID"), ("effect_b", "Effect B ID"),
                ("condition_a", "Condition A"), ("condition_b", "Condition B"), *ci], [decorate(row) for row in process["effect_contrasts"]])
        _table(spss, "Indices and conditional derivatives", [("id", "Index ID"), ("kind", "Type"), ("definition", "Definition"), ("paths", "Paths"),
                ("condition", "Moderator condition"), ("focal_contrast", "X contrast"), *ci], [decorate(row) for row in process["indices"]])
        _table(spss, "Paired bootstrap index contrasts", [("kind", "Type"), ("index_a", "Index A ID"), ("index_b", "Index B ID"),
                ("condition", "Moderator condition"), *ci], [decorate(row) for row in process["index_contrasts"]])
        _table(spss, "Conditional path slopes", [("path", "Path"), ("condition", "Moderator condition"), ("focal_contrast", "X contrast"), *inference,
                ("reference", "Reference distribution"), ("scale", "Scale"), ("conditioning_note", "Conditioning note")], [decorate(row) for row in process["slopes"]])
        _table(spss, "Interaction block tests", [("outcome", "Equation"), ("statistic", "Statistic"), ("reference", "Test"), ("df_num", "Numerator df"),
                ("df_den", "Denominator df"), ("p", "p"), ("deltaR2", "ΔR²"), ("status", "Status"), ("reason", "Reason")], [decorate(row) for row in process["interaction_tests"]])
        jn_rows = [{key: value for key, value in decorate(row).items() if key != "grid"} for row in process["johnson_neyman"]]
        jn_keys = list(dict.fromkeys(key for row in jn_rows for key in row))
        _table(spss, "Johnson–Neyman path-slope regions", [(key, key.replace("_", " ")) for key in jn_keys if key not in ("path_id",)], jn_rows)
        _text(spss, "Residual correlation diagnostics", str(_cell(process.get("residual_correlations"))))
        for text in [*process["assumptions"], *process["warnings"]]:
            _text(spss, "Interpretation and checks", text)
        compiler = process.get("compiler_plan", {})
        _text(spss, "Reproduction", str(_cell({"runtime": result["runtime"],
            "model_sha256": compiler.get("semantic_sha256"), "sample_mask_sha256": compiler.get("sample_mask_sha256")})))
    finally:
        spss.EndProcedure()


def _overview(process):
    nodes = {node["id"]: node["column"] for node in process["graph"]["nodes"]}
    edges = {edge["id"]: "%s → %s" % (nodes[edge["source"]], nodes[edge["target"]]) for edge in process["graph"]["edges"]}

    def describe(row):
        output = dict(row)
        for key in ("condition", "other_conditions"):
            values = row.get(key, {})
            output[key] = "; ".join("%s = %s" % (nodes.get(k, k), "%.4g" % v if isinstance(v, (int, float)) else v)
                                    for k, v in sorted(values.items())) or "Unconditional"
        if not row.get("other_conditions"):
            output["other_conditions"] = "None"
        output["route"] = " → ".join(nodes.get(key, key) for key in row.get("node_ids", []))
        output["path"] = edges.get(row.get("path_id"), row.get("path_id", ""))
        output["outcome"] = nodes.get(row.get("target_id"), row.get("target_id", ""))
        output["moderator"] = nodes.get(row.get("moderator_id"), row.get("moderator_id", ""))
        output["kind"] = str(row.get("kind", "")).replace("_", " ").capitalize()
        if isinstance(row.get("focal_contrast"), dict):
            contrast = row["focal_contrast"]
            output["focal_contrast"] = "%s vs %s" % (contrast["level"], contrast["reference"])
        if "regions" in row:
            output["regions"] = "; ".join("%.5g to %.5g: CI %s zero" % (region["lower"], region["upper"],
                "excludes" if region["significant"] else "includes") for region in row["regions"]) or "No eligible regions"
        if "boundaries" in row:
            output["boundaries"] = ", ".join("%.5g" % boundary for boundary in row["boundaries"]) or "No threshold within observed range"
        if row.get("observed_range"):
            output["observed_range"] = "%.5g to %.5g" % tuple(row["observed_range"])
        if "estimate" in row and "lower" in row and "upper" in row:
            output["excludes_zero"] = row["lower"] > 0 or row["upper"] < 0
        return output
    return nodes, edges, describe


def display_result(result):
    """A focused first reading; full diagnostics are an explicit appendix."""
    import spss
    process, source = result["process"], result["source"]
    presentation = result.get("presentation", {})
    nodes, edges, describe = _overview(process)
    inference = [("estimate", "B"), ("se", "SE"), ("statistic", "t / z"), ("p", "p"), ("lower", "Lower CI"), ("upper", "Upper CI")]
    intervals = [("estimate", "Estimate"), ("bootstrap_se", "Bootstrap SE"), ("lower", "Lower CI"), ("upper", "Upper CI"), ("excludes_zero", "CI excludes zero")]
    spss.StartProcedure("PathLab")
    try:
        title = {"MEDIATION": "Mediation", "MODERATION": "Moderation", "CONDITIONAL": "Conditional process: mediation with moderation"}.get(presentation.get("analysis"), "Mediation and moderation")
        _text(spss, "PathLab — " + title, "Version %s.\n%s\n\nStart with the model summary and confidence intervals below. Requested interaction and Johnson–Neyman diagrams follow these main tables." % (result["version"], CREDIT_BLOCK))
        roles = {role: [node["column"] for node in process["graph"]["nodes"] if node["role"] == role]
                 for role in ("independent", "dependent", "mediator", "moderator", "covariate")}
        model_rows = [{"item": label, "value": ", ".join(roles[role]) or "None"} for role, label in
                      (("independent", "Predictor X"), ("dependent", "Outcome Y"), ("mediator", "Mediators (in model order)"),
                       ("moderator", "Moderators"), ("covariate", "Covariates"))]
        # The compiled graph is canonically sorted by ID; use the explicit role
        # order from the request, or natural M1..M10 order for preset models.
        mediator_nodes = [node for node in process["graph"]["nodes"] if node["role"] == "mediator"]
        if all(node["id"].startswith("M") and node["id"][1:].isdigit() for node in mediator_nodes):
            model_rows[2]["value"] = ", ".join(node["column"] for node in sorted(mediator_nodes, key=lambda node: int(node["id"][1:]))) or "None"
        if presentation.get("structure") and roles["mediator"]:
            model_rows.append({"item": "Mediation structure", "value": presentation["structure"].capitalize()})
        else:
            model_rows[2]["item"] = "Mediators"
        model_rows.append({"item": "Outcome equation", "value": process["settings"]["outcome_family"].capitalize()})
        _table(spss, "1. Your model", [("item", "Setting"), ("value", "Selection")], model_rows)
        attachments = [{"path": edges[mod["path_id"]], "moderator": ", ".join(nodes[key] for key in mod["moderator_ids"])} for mod in process["graph"]["moderations"]]
        _table(spss, "Moderated paths (including required lower-order terms)", [("path", "Path"), ("moderator", "Moderator(s)")], attachments)
        _table(spss, "2. Cases used", [("dataset_n", "Dataset cases"), ("filtered_n", "Excluded by filter"), ("source_n", "Selected cases"),
                ("n", "Complete cases used"), ("excluded", "Excluded: missing")], [{**source, **process["sample"]}])
        bootstrap = dict(process["bootstrap"])
        bootstrap["confidence_percent"] = bootstrap["confidence_level"] * 100
        _table(spss, "Inference settings", [("confidence_percent", "Confidence (%)"), ("requested", "Bootstrap requested"), ("successful", "Successful"),
                ("failed", "Failed"), ("seed", "Random seed"), ("ci_method", "Interval method")], [bootstrap])
        _table(spss, "Categorical reference groups", [("column", "Variable"), ("reference", "Reference"), ("levels", "Observed levels")], process.get("coding", []))
        for equation in process["equations"]:
            _text(spss, "Equation: " + equation["column"], equation["formula"] + "\nStandard errors: " + equation["standard_errors"])
            _table(spss, "Coefficients: " + equation["column"], [("term", "Term"), *inference], equation["coefficients"])
        main_effects = process["effects"] if roles["mediator"] else [row for row in process["effects"] if row["kind"] == "direct"]
        _table(spss, "3. Direct and indirect associations (paired bootstrap)" if roles["mediator"] else "3. Conditional direct associations (paired bootstrap)",
                [("kind", "Effect"), ("route", "Route"), ("condition", "Moderator values"), ("focal_contrast", "X contrast"),
                 *intervals, ("scale", "Scale")], [describe(row) for row in main_effects])
        _table(spss, "Moderated mediation: indices and conditional derivatives", [("kind", "Type"), ("definition", "Meaning"),
                ("condition", "Moderator values"), *intervals], [describe(row) for row in process["indices"]])
        _table(spss, "Simple slopes (coefficient covariance intervals)", [("path", "Path"), ("condition", "Moderator values"),
                ("focal_contrast", "X contrast"), *inference, ("scale", "Scale")], [describe(row) for row in process["slopes"]])
        _table(spss, "Interaction tests", [("outcome", "Equation"), ("statistic", "Statistic"), ("reference", "Test"),
                ("p", "p"), ("deltaR2", "Change in R²"), ("reason", "Reason if unavailable")], [describe(row) for row in process["interaction_tests"]])
        _table(spss, "Johnson–Neyman thresholds within the observed range", [("path", "Path"), ("moderator", "Moderator"),
                ("other_conditions", "Other moderator values"), ("observed_range", "Observed range"), ("boundaries", "Thresholds"),
                ("regions", "Pointwise regions")], [describe(row) for row in process["johnson_neyman"] if row.get("status") == "computed"])
        for row in process["johnson_neyman"]:
            if row.get("status") != "computed":
                _text(spss, "Johnson–Neyman applicability", "%s: %s" % (edges.get(row["path_id"], row["path_id"]), row.get("reason", "No eligible continuous moderator region.")))
        if presentation.get("charts"):
            _text(spss, "4. Read your diagrams", "Interaction diagrams show the fitted outcome at the stated moderator values. Bands are pointwise confidence intervals for fitted means. Johnson–Neyman diagrams show a conditional path slope and where its interval excludes zero within the observed moderator range. Thresholds describe path slopes; indirect effects use the bootstrap tables above. Other moderator conditions are labeled in every panel.")
            _text(spss, "Diagram files", "%d diagram page(s). PNG copies: %s" % (len(presentation["charts"]), presentation["directory"]))
        for message in presentation.get("notices", []):
            _text(spss, "Diagram availability", str(message))
        for message in [*process["assumptions"], *process["warnings"]]:
            _text(spss, "Interpretation and checks", message)
        if presentation.get("detail", "STANDARD") == "STANDARD":
            _text(spss, "More detail", "Choose Full technical output under Options for paired effect contrasts, complete diagnostics, coding and reproduction details. Diagram and numerical settings use the same fitted model.")
    finally:
        spss.EndProcedure()


def display_plot_notices(presentation):
    import spss
    spss.StartProcedure("PathLab diagrams")
    try:
        for message in presentation.get("viewer_notices", []):
            _text(spss, "Diagram display", str(message))
        if presentation.get("directory"):
            _text(spss, "Open the PNG diagrams", presentation["directory"])
    finally:
        spss.EndProcedure()
