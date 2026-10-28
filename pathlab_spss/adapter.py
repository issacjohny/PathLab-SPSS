"""Read the active SPSS dataset without changing data, and run PathLab locally."""
from __future__ import annotations

from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
import platform
import tempfile

from . import __version__
from .branding import developer_metadata
from .models import DialogError, build_model, check_options, validate_analysis


def dependencies():
    modules = {}
    for name in ("numpy", "pandas", "scipy", "statsmodels"):
        try:
            modules[name] = importlib.import_module(name)
        except ImportError as error:
            raise DialogError("PathLab's calculation libraries are not installed in this SPSS Python. "
                              "Run the supplied PathLab Setup application once, then restart SPSS. "
                              "Missing library: %s." % name) from error
    return modules


def _active_filter(spss, spssaux):
    # SHOW DIR otherwise returns labels under some SPSS output preferences.
    previous = spss.GetSetting("TVARS")
    try:
        spss.Submit("SET TVARS=NAMES.")
        return spssaux.getDatasetInfo("Filter") or None
    finally:
        if str(previous).upper() not in ("NAMES", "LABELS", "BOTH"):
            raise DialogError("SPSS returned an unrecognized variable-label preference.")
        spss.Submit("SET TVARS=%s." % str(previous).upper())


def read_active_frame(graph):
    """Respect filter and user missing values; refuse unsupported weighting/splits.

    The source frame retains missing rows so the engine records listwise losses.
    Filter losses are reported separately from listwise missing-data exclusions.
    """
    import pandas as pd
    import spss
    import spssaux
    import spssdata
    if spss.GetWeightVar():
        raise DialogError("PathLab currently requires unweighted cases. Turn Weight Cases off before running.")
    if spss.GetSplitVariableNames():
        raise DialogError("PathLab currently requires Split File off. Analyze selected groups separately.")
    dictionary = {spss.GetVariableName(i).casefold(): i for i in range(spss.GetVariableCount())}
    columns = [node["column"] for node in graph["nodes"]]
    if not dictionary:
        raise DialogError("Open a dataset before running PathLab.")
    metadata = []
    for node in graph["nodes"]:
        index = dictionary.get(node["column"].casefold())
        if index is None:
            raise DialogError("A selected model variable no longer exists in the active dataset.")
        level = spss.GetVariableMeasurementLevel(index)
        metadata.append({"node_id": node["id"], "column": node["column"],
                         "spss_name": spss.GetVariableName(index), "label": spss.GetVariableLabel(index),
                         "spss_measurement_level": level, "spss_type": spss.GetVariableType(index)})
        if str(level).lower() == "nominal" and node["measurement_scale"] != "nominal":
            raise DialogError("%s is marked Nominal in SPSS. Select it in Categorical variables, "
                              "or change its measurement level to Scale if it is a quantitative score." % node["column"])
    filter_name = _active_filter(spss, spssaux)
    if filter_name and filter_name.casefold() not in dictionary:
        raise DialogError("The active SPSS filter could not be resolved to a variable. Review Select Cases.")
    indexes = [dictionary[column.casefold()] for column in columns]
    filter_index = None
    if filter_name:
        filter_variable_index = dictionary[filter_name.casefold()]
        if filter_variable_index not in indexes:
            indexes.append(filter_variable_index)
        filter_index = indexes.index(filter_variable_index)
    raw_n = spss.GetCaseCount()
    rows, read_n, filtered_n = [], 0, 0
    cursor = spssdata.Spssdata(indexes=indexes, names=False, convertUserMissing=True, omitmissing=False)
    try:
        for row in cursor:
            read_n += 1
            if filter_index is not None and (row[filter_index] is None or row[filter_index] == 0):
                filtered_n += 1
                continue
            # SPSS strings are fixed-width padded. Remove trailing padding, while
            # retaining their actual values instead of substituting value labels.
            rows.append([value.rstrip() if isinstance(value, str) else value for value in row[:len(columns)]])
    finally:
        cursor.CClose()
    return pd.DataFrame(rows, columns=columns), {"dataset_n": raw_n, "read_n": read_n,
            "filtered_n": raw_n - len(rows), "selected_n": len(rows),
            "filter_variable": filter_name, "user_missing": "Converted to missing before common listwise selection",
            "weight": "off", "split_file": "off", "variables": metadata}


def resolve_categories(model, frame):
    """Resolve the explicitly selected FIRST/LAST rule once on the fixed sample."""
    resolved = deepcopy(model)
    dialog = resolved.pop("dialog", {})
    if not dialog:
        return resolved
    sample = frame[[node["column"] for node in resolved["graph"]["nodes"]]].dropna()
    if sample.empty:
        raise DialogError("No complete cases remain across the selected variables.")
    by_id = {node["id"]: node for node in resolved["graph"]["nodes"]}
    for node_id in dialog["categorical_ids"]:
        values = sample[by_id[node_id]["column"]].unique().tolist()
        if not 2 <= len(values) <= 10:
            raise DialogError("Each categorical variable needs 2 to 10 observed categories in the common sample.")
        try:
            levels = sorted(values)
        except TypeError as error:
            raise DialogError("A categorical variable contains mixed text and numeric values.") from error
        resolved["settings"]["categorical"].append({"node_id": node_id, "levels": levels,
                    "reference": levels[0] if dialog["reference"] == "FIRST" else levels[-1]})
    # Three categorical moderators can also exceed the joint-probe budget.
    count = 1
    categorical_map = {item["node_id"]: item for item in resolved["settings"]["categorical"]}
    for node in resolved["graph"]["nodes"]:
        if node["role"] == "moderator":
            count *= len(categorical_map[node["id"]]["levels"]) if node["id"] in categorical_map else len(resolved["settings"]["automatic_probes"]["probabilities"])
    if count > 25:
        raise DialogError("The selected moderator categories create more than 25 joint probe conditions. "
                          "Use fewer moderator categories or moderators.")
    return resolved


def _save_json(path, result):
    target = Path(path).expanduser().resolve()
    if not target.parent.is_dir():
        raise DialogError("Choose an existing output folder for the JSON results.")
    # Replace atomically only after a complete, finite result has serialized.
    payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    descriptor, temporary = tempfile.mkstemp(prefix=".pathlab-", suffix=".json", dir=str(target.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
        os.replace(temporary, str(target))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def presentation_options(plots="BOTH", output_detail="STANDARD", plot_directory=None):
    plots, detail = str(plots or "BOTH").upper(), str(output_detail or "STANDARD").upper()
    if plots not in ("BOTH", "INTERACTION", "JN", "NONE"):
        raise DialogError("Under Diagrams, choose both diagram types, interaction only, Johnson–Neyman only, or tables only.")
    if detail not in ("STANDARD", "FULL"):
        raise DialogError("Choose Standard results or Full technical output under Options.")
    folder = Path(plot_directory).expanduser().resolve() if plot_directory else None
    if folder is not None and not folder.is_dir():
        raise DialogError("Choose an existing folder for diagram exports under Diagrams.")
    return plots, detail, folder


def analyze(model, bootstrap=5000, confidence=95, seed=20261028, robust="HC3", output_json=None,
            plots="BOTH", plot_directory=None, output_detail="STANDARD", analysis="AUTO"):
    """Common execution for GUI and saved graph specifications."""
    options, seed = check_options(bootstrap, confidence, seed, robust)
    plots, output_detail, plot_directory = presentation_options(plots, output_detail, plot_directory)
    libraries = dependencies()
    from .core import compute, validate_process
    from .report import display_result
    import spss
    if not isinstance(model, dict) or model.get("schema_version") != 1:
        raise DialogError("Unsupported PathLab model specification version.")
    analysis = validate_analysis(analysis, model)
    frame, source = read_active_frame(model["graph"])
    resolved = resolve_categories(model, frame)
    graph, settings = resolved["graph"], resolved["settings"]
    metadata = {row["node_id"]: row for row in source["variables"]}
    for node in graph["nodes"]:
        if node["measurement_scale"] != "nominal" and str(metadata[node["id"]]["spss_measurement_level"]).lower() == "ordinal":
            node["measurement_scale"] = "ordinal"
    validate_process(graph, settings, list(frame.columns))
    process = compute(frame, {**options, "process": graph, "process_settings": settings}, seed)[2]["process"]
    result = {"extension": "PathLab for SPSS", "version": __version__,
              "developer": developer_metadata(), "request": resolved,
              "runtime": {"python": platform.python_version(), "spss": str(spss.GetDefaultPlugInVersion()),
                          **{name: module.__version__ for name, module in libraries.items()}},
              "source": source, "process": process,
              "presentation": {"analysis": analysis, "structure": model.get("dialog", {}).get("structure"),
                               "requested_plots": plots, "detail": output_detail,
                               "charts": [], "notices": [], "directory": None}}
    presentation = result["presentation"]
    if plots != "NONE" and graph["moderations"]:
        try:
            from .plots import render_plots
            folder = tempfile.mkdtemp(prefix="PathLab-diagrams-", dir=str(plot_directory) if plot_directory else None)
            presentation.update(directory=folder, exported=plot_directory is not None)
            rendered = render_plots(process, folder, interaction=plots in ("BOTH", "INTERACTION"),
                                    johnson_neyman=plots in ("BOTH", "JN"))
            presentation.update(rendered)
            presentation["status"] = "rendered" if presentation["charts"] else "not_applicable"
            import matplotlib
            result["runtime"]["matplotlib"] = matplotlib.__version__
        except ImportError:
            presentation["status"] = "unavailable"
            presentation["notices"].append("Diagrams need the additional plotting library. Run PathLab Setup again for this SPSS version and restart SPSS. The numerical analysis has completed.")
        except Exception as error:
            presentation["status"] = "failed"
            presentation["notices"].append("Diagram rendering did not complete (%s). The numerical analysis has completed." % type(error).__name__)
    elif plots != "NONE":
        presentation.update(status="not_applicable", notices=["Interaction and Johnson–Neyman diagrams apply to moderated paths. This mediation model has no moderator."])
    else:
        presentation["status"] = "not_requested"
    display_result(result)
    if presentation["charts"]:
        from .viewer import insert_charts
        presentation["viewer_notices"] = insert_charts(presentation["charts"])
        if presentation["viewer_notices"]:
            from .report import display_plot_notices
            display_plot_notices(presentation)
    if output_detail == "FULL":
        from .report import display_appendix
        display_appendix(result)
    if output_json:
        _save_json(output_json, result)
    return result


def _execute(function, *args, **kwargs):
    from .report import display_error
    try:
        return function(*args, **kwargs)
    except DialogError as error:
        display_error(str(error))
    except Exception as error:
        code = getattr(error, "code", None)
        messages = {"INSUFFICIENT_DATA": "At least 10 complete cases are required.",
                    "SINGULAR_DESIGN": "An equation is singular. Check collinearity, constant categories, and the sample size.",
                    "CONSTANT_VARIABLE": "A selected variable is constant in the common analysis sample.",
                    "BOOTSTRAP_FAILURE": "Fewer than 95% of bootstrap fits succeeded. Review sparse categories and model complexity.",
                    "SEPARATION": "The binary outcome has complete or quasi-complete separation.",
                    "NONCONVERGENCE": "A logistic equation did not converge.",
                    "RESOURCE_LIMIT": "This model exceeds a computation or output limit. Reduce model complexity, probes, or bootstrap count.",
                    "INVALID_OPTIONS": "Review categorical coding, binary 0/1 outcome coding, and probe settings.",
                    "INVALID_MODEL": "The selected paths do not form a supported mediation or moderation model.",
                    "NUMERIC_TYPE_MISMATCH": "Quantitative variables must be numeric. Declare text categories in Categorical variables."}
        if code:
            display_error(messages.get(code, "Calculation stopped: %s." % code))
        else:
            # Unexpected errors must remain visible; do not return plausible output.
            display_error("PathLab stopped before completing results (%s)." % type(error).__name__)
            raise
    return None


def run_dialog(x, y, mediators=(), structure="PARALLEL", w=None, z=None, q=None, covariates=(),
               moderate_first="NONE", moderate_second="NONE", moderate_serial="NONE", moderate_direct="NONE",
               bootstrap=5000, confidence=95, seed=20261028, robust="HC3", family="LINEAR",
               categorical=(), reference="FIRST", output_json=None, plots="BOTH", plot_directory=None,
               output_detail="STANDARD", analysis="AUTO"):
    def execute():
        model = build_model(x, y, mediators, structure, w, z, q, covariates, moderate_first,
                            moderate_second, moderate_serial, moderate_direct, family, categorical, reference)
        return analyze(model, bootstrap, confidence, seed, robust, output_json,
                       plots, plot_directory, output_detail, analysis)
    return _execute(execute)


def run(model_file, bootstrap=5000, confidence=95, seed=20261028, robust="HC3", output_json=None,
        plots="BOTH", plot_directory=None, output_detail="STANDARD"):
    def execute():
        with open(model_file, encoding="utf-8") as stream:
            model = json.load(stream)
        return analyze(model, bootstrap, confidence, seed, robust, output_json, plots, plot_directory, output_detail)
    return _execute(execute)
