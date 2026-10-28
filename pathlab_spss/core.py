"""Graph-based observed conditional process analysis; never evaluates user syntax.

Every term is compiled from an independently validated, immutable visual design.
Indirect effects are statistical path products. Inference resamples whole cases,
using the same resample in every equation, and never substitutes a normal test
for a bootstrap interval for an indirect effect.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import itertools
import json
import math
import re
import warnings
from types import SimpleNamespace

import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import expit
from scipy.optimize import linprog
import statsmodels.api as sm
from statsmodels.tools.sm_exceptions import ConvergenceWarning, PerfectSeparationWarning, PerfectSeparationError

from .errors import LabError

IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
ROLES = {"independent", "dependent", "mediator", "moderator", "covariate"}
SCALES = {"nominal", "ordinal", "interval", "ratio"}
# MAX_WORK bounds n * terms^2 * bootstrap replications. It admits at 5,000
# replications every model size that the earlier bound admitted at 1,000.
MAX_TERMS, MAX_ROWS, MAX_WORK = 80, 8000, 2_000_000_000
MAX_DERIVATIVE_WORK = 100_000_000
THREE_MODERATOR_CAPABILITIES = {
    "contract": "three_exogenous_moderators_v1", "max_moderators": 3,
    "max_moderators_per_attachment": 2, "max_joint_conditions": 25,
    "max_derivative_order": 3, "max_derivative_work": MAX_DERIVATIVE_WORK,
}


def finite(value):
    return float(value) if value is not None and np.isfinite(value) else None


def _scalar(value):
    return isinstance(value, str) and 0 < len(value) <= 120 or (
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    )


def _strict(value, keys):
    return isinstance(value, dict) and set(value) == set(keys)


def _key(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validate_settings_version(settings):
    """Historical contracts remain exact; three moderators require explicit v3."""
    legacy = ("outcome_family", "categorical", "probes")
    if _strict(settings, legacy):
        return 1
    if not _strict(settings, (*legacy, "schema_version", "automatic_probes", "bootstrap_interval_quantile_method")) or type(settings["schema_version"]) is not int or settings["schema_version"] not in (2, 3):
        raise LabError("INVALID_OPTIONS")
    policy = settings["automatic_probes"]
    if not _strict(policy, ("probabilities", "quantile_method", "sample", "resolve_before_bootstrap")):
        raise LabError("INVALID_OPTIONS")
    probabilities = policy["probabilities"]
    if not isinstance(probabilities, list) or not 1 <= len(probabilities) <= 5 or any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities) or any(a >= b for a, b in zip(probabilities, probabilities[1:])):
        raise LabError("INVALID_OPTIONS")
    if policy["quantile_method"] not in ("linear", "weibull") or policy["sample"] != "fixed_complete_case_sample" or policy["resolve_before_bootstrap"] is not True or settings["bootstrap_interval_quantile_method"] != "linear":
        raise LabError("INVALID_OPTIONS")
    return settings["schema_version"]


def validate_process(graph, settings, columns):
    """Validate independently of the web compiler and SQL binding gate."""
    # Determine only the prospective graph bound here; preserve historical
    # structural-error ordering and independently validate the full request below.
    max_moderators = 3 if isinstance(settings, dict) and type(settings.get("schema_version")) is int and settings.get("schema_version") == 3 else 2
    if not _strict(graph, ("schema_version", "nodes", "edges", "moderations")) or type(graph["schema_version"]) is not int or graph["schema_version"] != 1:
        raise LabError("INVALID_MODEL")
    nodes, edges, mods = graph["nodes"], graph["edges"], graph["moderations"]
    if not isinstance(nodes, list) or not 3 <= len(nodes) <= 32 + max_moderators or not isinstance(edges, list) or not 1 <= len(edges) <= 150 or not isinstance(mods, list) or len(mods) > 150:
        raise LabError("INVALID_MODEL")
    if any(not _strict(n, ("id", "column", "role", "measurement_scale")) for n in nodes):
        raise LabError("INVALID_MODEL")
    if any(not isinstance(n["id"], str) or not IDENTIFIER.fullmatch(n["id"]) or n["id"] == "STRAT_GROUP" or not isinstance(n["column"], str) or n["column"] not in columns or not isinstance(n["role"], str) or n["role"] not in ROLES or not isinstance(n["measurement_scale"], str) or n["measurement_scale"] not in SCALES for n in nodes):
        raise LabError("INVALID_MODEL")
    by_id = {n["id"]: n for n in nodes}
    counts = Counter(n["role"] for n in nodes)
    if len(by_id) != len(nodes) or len({n["column"] for n in nodes}) != len(nodes) or counts["independent"] != 1 or counts["dependent"] != 1 or counts["mediator"] > 10 or counts["moderator"] > max_moderators or counts["covariate"] > 20:
        raise LabError("INVALID_MODEL")
    if any(not _strict(e, ("id", "source", "target")) for e in edges):
        raise LabError("INVALID_MODEL")
    if any(not isinstance(e["id"], str) or not IDENTIFIER.fullmatch(e["id"]) or not isinstance(e["source"], str) or not isinstance(e["target"], str) or e["source"] not in by_id or e["target"] not in by_id or e["source"] == e["target"] or by_id[e["target"]]["role"] not in ("mediator", "dependent") for e in edges):
        raise LabError("INVALID_MODEL")
    if len({e["id"] for e in edges}) != len(edges) or len({(e["source"], e["target"]) for e in edges}) != len(edges):
        raise LabError("INVALID_MODEL")
    by_edge = {e["id"]: e for e in edges}
    pairs = {(e["source"], e["target"]) for e in edges}
    interaction_keys = set()
    moderation_ids = set()
    for mod in mods:
        if not _strict(mod, ("id", "path_id", "moderator_ids")) or not isinstance(mod["id"], str) or not IDENTIFIER.fullmatch(mod["id"]) or mod["id"] in moderation_ids or not isinstance(mod["path_id"], str) or mod["path_id"] not in by_edge or not isinstance(mod["moderator_ids"], list) or not 1 <= len(mod["moderator_ids"]) <= 2 or any(not isinstance(i, str) for i in mod["moderator_ids"]):
            raise LabError("INVALID_MODEL")
        moderation_ids.add(mod["id"])
        edge = by_edge[mod["path_id"]]
        ids = mod["moderator_ids"]
        if len(set(ids)) != len(ids) or any(i not in by_id or by_id[i]["role"] != "moderator" or i in (edge["source"], edge["target"]) for i in ids):
            raise LabError("INVALID_MODEL")
        signature = (edge["target"], tuple(sorted([edge["source"], *ids])))
        if signature in interaction_keys or any((i, edge["target"]) not in pairs for i in ids):
            raise LabError("INVALID_MODEL")
        interaction_keys.add(signature)
    for target, factors in interaction_keys:
        if len(factors) == 3 and any((target, tuple(pair)) not in interaction_keys for pair in itertools.combinations(factors, 2)):
            raise LabError("INVALID_MODEL")
    used_moderators = {i for mod in mods for i in mod["moderator_ids"]}
    if (counts["mediator"] == 0 and not mods) or used_moderators != {i for i, node in by_id.items() if node["role"] == "moderator"}:
        raise LabError("INVALID_MODEL")
    visiting, visited = set(), set()
    def visit(node):
        if node in visiting:
            raise LabError("INVALID_MODEL")
        if node in visited:
            return
        visiting.add(node)
        for edge in edges:
            if edge["source"] == node:
                visit(edge["target"])
        visiting.remove(node)
        visited.add(node)
    for node in by_id:
        visit(node)
    x = next(n["id"] for n in nodes if n["role"] == "independent")
    y = next(n["id"] for n in nodes if n["role"] == "dependent")
    routes = []
    def walk(current, path, route_nodes):
        if current == y:
            routes.append((path, route_nodes))
            if len(routes) > 100:
                raise LabError("RESOURCE_LIMIT")
            return
        for edge in sorted(edges, key=lambda e: e["id"]):
            if edge["source"] == current:
                walk(edge["target"], path + [edge["id"]], route_nodes + [edge["target"]])
    walk(x, [], [x])
    route_nodes = {i for _, path_nodes in routes for i in path_nodes}
    if not routes or any(n["role"] == "mediator" and n["id"] not in route_nodes for n in nodes):
        raise LabError("INVALID_MODEL")
    connected = {i for e in edges for i in (e["source"], e["target"])}
    if connected != set(by_id):
        raise LabError("INVALID_MODEL")
    _validate_settings_version(settings)
    if settings["outcome_family"] not in ("linear", "logistic") or not isinstance(settings["categorical"], list) or len(settings["categorical"]) > 21 + max_moderators or not isinstance(settings["probes"], list) or len(settings["probes"]) > max_moderators:
        raise LabError("INVALID_OPTIONS")
    coding = {}
    for entry in settings["categorical"]:
        if not _strict(entry, ("node_id", "levels", "reference")) or not isinstance(entry["node_id"], str) or entry["node_id"] not in by_id or entry["node_id"] in coding or by_id[entry["node_id"]]["role"] not in ("independent", "moderator", "covariate"):
            raise LabError("INVALID_OPTIONS")
        levels = entry["levels"]
        if not isinstance(levels, list) or not 2 <= len(levels) <= 10 or any(not _scalar(v) for v in levels) or len(set(levels)) != len(levels) or len({"text" if isinstance(v, str) else "number" for v in levels}) != 1 or not _scalar(entry["reference"]) or entry["reference"] not in levels or isinstance(entry["reference"], str) != isinstance(levels[0], str):
            raise LabError("INVALID_OPTIONS")
        coding[entry["node_id"]] = entry
    if any(n["measurement_scale"] == "nominal" and n["role"] in ("independent", "moderator", "covariate") and n["id"] not in coding for n in nodes):
        raise LabError("INVALID_OPTIONS")
    if any(n["measurement_scale"] == "nominal" and n["role"] == "mediator" for n in nodes) or (by_id[y]["measurement_scale"] == "nominal" and settings["outcome_family"] != "logistic"):
        raise LabError("INVALID_OPTIONS")
    seen_probes = set()
    for entry in settings["probes"]:
        if not _strict(entry, ("node_id", "values")) or not isinstance(entry["node_id"], str) or entry["node_id"] not in by_id or by_id[entry["node_id"]]["role"] != "moderator" or entry["node_id"] in seen_probes or not isinstance(entry["values"], list) or not 1 <= len(entry["values"]) <= 5 or any(not _scalar(v) for v in entry["values"]) or len(set(entry["values"])) != len(entry["values"]):
            raise LabError("INVALID_OPTIONS")
        seen_probes.add(entry["node_id"])
        if entry["node_id"] in coding:
            if any(v not in coding[entry["node_id"]]["levels"] or isinstance(v, str) != isinstance(coding[entry["node_id"]]["levels"][0], str) for v in entry["values"]):
                raise LabError("INVALID_OPTIONS")
        elif any(isinstance(v, str) for v in entry["values"]):
            raise LabError("INVALID_OPTIONS")
    canonical = {"schema_version": 1, "nodes": sorted(nodes, key=lambda n: n["id"]), "edges": sorted(edges, key=lambda e: e["id"]), "moderations": sorted([{**m, "moderator_ids": sorted(m["moderator_ids"])} for m in mods], key=lambda m: m["id"])}
    return canonical, coding, routes


def _fit(y, design, family, robust, bootstrap=False):
    n, p = design.shape
    if n <= p + 2 or np.linalg.matrix_rank(design) < p:
        raise LabError("SINGULAR_DESIGN")
    if family == "linear":
        if bootstrap:
            beta, _, rank, _ = np.linalg.lstsq(design, y, rcond=None)
            if rank != p or not np.isfinite(beta).all():
                raise LabError("SINGULAR_DESIGN")
            return beta
        result = sm.OLS(y, design).fit(cov_type="HC3" if robust else "nonrobust")
        return result, np.asarray(result.cov_params()), stats.norm if robust else stats.t(result.df_resid)
    if set(np.unique(y)) != {0., 1.}:
        raise LabError("INVALID_OPTIONS")
    # Fitting on a column-scaled matrix preserves the exact model and avoids
    # unit-dependent optimizer tolerances/information conditioning. Parameters
    # and covariance are converted back to the original, uncentered units.
    scales = np.max(np.abs(design), axis=0)
    scaled = design / scales
    if not bootstrap:
        signed = scaled * (2*y-1)[:, None]
        # A nonzero direction with all signed margins >=0 and a positive
        # average margin is complete or quasi-complete separation. The final
        # constraint excludes the trivial all-zero solution. Infeasibility
        # establishes overlap; numerical/iteration failure is not overlap.
        separation = linprog(np.zeros(p), A_ub=np.vstack([-signed, -signed.mean(axis=0)]), b_ub=np.r_[np.zeros(n), -1.], bounds=[(None, None)]*p, method="highs")
        if separation.success:
            margin = signed @ separation.x
            if np.min(margin) >= -1e-7 and np.mean(margin) >= 1-1e-7:
                raise LabError("SEPARATION")
            raise LabError("NONCONVERGENCE")
        if separation.status != 2:
            raise LabError("NONCONVERGENCE")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", PerfectSeparationWarning)
            warnings.simplefilter("error", ConvergenceWarning)
            result = sm.Logit(y, scaled).fit(disp=False, maxiter=100)
    except (PerfectSeparationWarning, PerfectSeparationError) as error:
        raise LabError("SEPARATION") from error
    except ConvergenceWarning as error:
        raise LabError("NONCONVERGENCE") from error
    if not result.mle_retvals["converged"]:
        raise LabError("NONCONVERGENCE")
    beta = np.asarray(result.params) / scales
    if not np.isfinite(beta).all():
        raise LabError("NUMERICAL_OVERFLOW")
    probability = result.predict()
    weight = probability * (1 - probability)
    information = scaled.T @ (scaled * weight[:, None])
    if not np.isfinite(information).all() or np.linalg.matrix_rank(information) < p:
        raise LabError("SINGULAR_DESIGN")
    if bootstrap:
        return beta
    covariance = np.asarray(result.cov_params())
    if robust:
        bread = np.linalg.inv(information)
        leverage = weight * np.sum((scaled @ bread) * scaled, axis=1)
        if np.any(leverage >= 1 - 1e-10):
            raise LabError("SINGULAR_DESIGN")
        score_residual = (y - probability) / (1 - leverage)
        covariance = bread @ (scaled.T @ (scaled * score_residual[:, None] ** 2)) @ bread
    covariance = covariance / np.outer(scales, scales)
    # Retain package likelihood/df diagnostics while exposing original units.
    fit = SimpleNamespace(params=beta, **{key: getattr(result, key) for key in ("df_model", "df_resid", "llf", "llnull", "prsquared", "aic", "bic", "llr", "llr_pvalue")})
    return fit, covariance, stats.norm


def _inference(beta, covariance, vector, reference, alpha):
    value = float(vector @ beta)
    variance = float(vector @ covariance @ vector)
    if variance < -1e-8 or not math.isfinite(variance):
        raise LabError("INVALID_RESULT")
    se = math.sqrt(max(0., variance))
    critical = float(reference.ppf(1 - alpha / 2))
    return {"estimate": value, "se": se, "statistic": value / se if se > 0 else None, "reference": "normal z" if reference is stats.norm else "residual-df t", "p": finite(2 * reference.sf(abs(value / se))) if se > 0 else None, "lower": value - critical * se, "upper": value + critical * se}


def _bootstrap_row(value, distribution, alpha):
    lower, upper = np.quantile(distribution, [alpha / 2, 1 - alpha / 2], method="linear")
    return {"estimate": float(value), "bootstrap_se": float(np.std(distribution, ddof=1)), "lower": float(lower), "upper": float(upper)}


def _odds_ratio(value):
    # A per-original-unit odds ratio can exceed floating-point range after an
    # innocent change of units. Preserve the coefficient and explicitly leave
    # the ratio unavailable rather than overflowing or inventing infinity/zero.
    return float(math.exp(value)) if -745 < value < 709 else None


def _wald(beta, covariance):
    """Normalize covariance before inversion so a change of units cannot drop terms."""
    diagonal = np.diag(covariance)
    if np.any(diagonal <= 0) or not np.isfinite(covariance).all():
        return None
    se = np.sqrt(diagonal)
    correlation = covariance / np.outer(se, se)
    if np.linalg.matrix_rank(correlation) < len(beta):
        return None
    standardized = beta / se
    return finite(standardized @ np.linalg.solve(correlation, standardized))


def _diagnostic_evidence(eq):
    """Save bounded display evidence without changing fitting or random draws.

    Plot positions are positions in the fixed complete-case sample, not source
    row identifiers. Full-sample diagnostics are calculated before deterministic
    thinning, and variance inflation is for individual compiled design columns.
    """
    design, fit = eq["design"], eq["fit"]
    n, p = design.shape
    vif = []
    # Centering unit-scaled predictors avoids overflow and makes VIF invariant
    # to an innocent change of numerical units. The intercept is excluded.
    predictors = design[:, 1:]
    if p > 1:
        scaled = predictors / np.max(np.abs(predictors), axis=0)
        centered = scaled - np.mean(scaled, axis=0)
        norm = np.sqrt(np.sum(centered ** 2, axis=0))
        standardized = centered / norm
        correlation = standardized.T @ standardized
        try:
            if np.linalg.matrix_rank(correlation) < p - 1:
                raise np.linalg.LinAlgError("Numerically singular predictor correlation")
            values = np.diag(np.linalg.inv(correlation))
        except np.linalg.LinAlgError:
            values = np.full(p - 1, np.nan)
        for term_id, value in zip(eq["term_ids"][1:], values):
            available = math.isfinite(value) and value >= 1 - 1e-8
            vif.append({"term_id": term_id, "value": float(max(1., value)) if available else None,
                        "unavailable_reason": None if available else "The predictor correlation is numerically singular or its inverse is unstable."})
    condition = finite(np.linalg.cond(design))
    evidence = {"schema_version": 1, "n": n,
                "design": {"columns": p, "rank": int(np.linalg.matrix_rank(design)),
                           "condition_number": condition,
                           "condition_number_note": "Condition number of the unscaled design, including the intercept; sensitive to measurement units and centering. VIF describes each non-intercept compiled term, not a generalized factor-level VIF.",
                           "vif": vif}}
    if eq["family"] != "linear":
        evidence["linear"] = {"status": "not_applicable", "reason": "OLS residual, normal-reference Q-Q, leverage and Cook diagnostics do not apply to this logistic equation. Review its saved likelihood, convergence and separation checks."}
        return evidence
    residual = np.asarray(fit.resid)
    fitted = np.asarray(fit.fittedvalues)
    raw_leverage = np.asarray(fit.get_influence().hat_matrix_diag)
    valid_leverage = np.isfinite(raw_leverage) & (raw_leverage >= -1e-10) & (raw_leverage <= 1 + 1e-10)
    # Numerical projection roundoff may put an endpoint a few ulps outside
    # [0, 1]. Only that tolerance is clipped; larger violations are unavailable.
    leverage = np.where(valid_leverage, np.clip(raw_leverage, 0., 1.), np.nan)
    residual_se = math.sqrt(float(fit.mse_resid))
    standardized_residual = np.full(n, np.nan)
    cooks = np.full(n, np.nan)
    usable = valid_leverage & (leverage < 1 - 1e-10)
    if residual_se > 0 and math.isfinite(residual_se):
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            standardized_residual[usable] = residual[usable] / (residual_se * np.sqrt(1 - leverage[usable]))
            cooks[usable] = standardized_residual[usable] ** 2 * leverage[usable] / (p * (1 - leverage[usable]))
            scaled_residual = residual / residual_se
    else:
        scaled_residual = np.full(n, np.nan)
    unavailable = None
    if not residual_se > 0 or not math.isfinite(residual_se):
        unavailable = "Residual standard error is zero or unavailable; scaled residuals and Cook distances are unavailable."
    elif not usable.all():
        unavailable = "Cases with leverage at or numerically near one, or outside its valid numerical range, have unavailable internally studentized residuals and Cook distances."
    elif not (np.isfinite(standardized_residual).all() and np.isfinite(cooks).all()):
        unavailable = "Some internally studentized residuals or Cook distances exceed finite numerical range."
    count = min(n, 200)
    positions = np.unique(np.linspace(0, n - 1, count, dtype=int))
    sampling = "all_cases" if n <= 200 else "deterministic_evenly_spaced"
    ordered = np.sort(scaled_residual)
    leverage_threshold, cooks_threshold = 2 * p / n, 4 / n
    evidence["linear"] = {
        "status": "computed", "scale": "internally_studentized_residual", "sampling": sampling,
        "total_cases": n, "plotted_cases": len(positions),
        "points": [{"case_position": int(i + 1), "fitted": float(fitted[i]), "residual": float(residual[i]),
                    "standardized_residual": finite(standardized_residual[i]),
                    "leverage": finite(leverage[i]), "cooks_distance": finite(cooks[i])} for i in positions],
        "qq": {"scale": "residual_over_residual_standard_error", "sampling": sampling,
               "total_cases": n, "plotted_cases": len(positions),
               "points": [{"rank": int(i + 1), "theoretical_quantile": float(stats.norm.ppf((i + .5) / n)),
                           "standardized_residual": finite(ordered[i])} for i in positions]},
        "full_sample": {"leverage_threshold": leverage_threshold, "high_leverage_cases": int(np.sum(leverage > leverage_threshold)),
                        "cooks_threshold": cooks_threshold, "influential_cases": int(np.sum(cooks > cooks_threshold)) if np.isfinite(cooks).any() else None,
                        "cooks_available_cases": int(np.isfinite(cooks).sum()),
                        "leverage_available_cases": int(np.isfinite(leverage).sum()),
                        "standardized_residual_available_cases": int(np.isfinite(standardized_residual).sum()),
                        "max_leverage": finite(np.max(leverage[np.isfinite(leverage)])) if np.isfinite(leverage).any() else None,
                        "max_cooks_distance": finite(np.max(cooks[np.isfinite(cooks)])) if np.isfinite(cooks).any() else None,
                        "residual_standard_error": finite(residual_se), "unavailable_standardized_reason": unavailable},
        "notes": ["Case positions refer to the fixed complete-case analysis sample, not original source row IDs. Plot thinning never changes the analysis sample or full-sample summaries.",
                  "Residual plot uses internally studentized residuals; Q-Q uses residual divided by residual standard error against normal quantiles at (rank - 0.5) / n.",
                  "Leverage > 2p/n and Cook distance > 4/n are screening heuristics, not deletion rules or hypothesis tests. No cases were removed.",
                  "Leverage roundoff within 1e-10 of [0, 1] is clipped to that range; values beyond it are unavailable. A leverage within 1e-10 of one cannot support finite studentization or Cook distance.",
                  "These OLS diagnostics describe the fitted mean model even when coefficient inference uses HC3. They do not establish normality, independent cases, correct causal ordering or absence of confounding."]}
    return evidence


def _residual_correlations(equations, by_id, n):
    """Full fixed-sample OLS residual associations; never use thinned plot cases."""
    targets = sorted(equations)
    output = {"status": "not_applicable", "target_ids": targets,
              "columns": [by_id[target]["column"] for target in targets],
              "n": n, "values": None}
    if any(equations[target]["family"] != "linear" for target in targets):
        return {**output, "reason": "Pearson OLS residual correlations are not defined for this mixed linear/logistic equation set; no logistic residual definition is substituted."}
    residuals = []
    for target in targets:
        equation = equations[target]
        residual = np.asarray(equation["fit"].resid, dtype=float)
        if residual.shape != (n,) or not np.isfinite(residual).all():
            raise LabError("INVALID_RESULT")
        centered = residual - residual.mean()
        response = np.asarray(equation["y"], dtype=float)
        tolerance = np.finfo(float).eps * max(float(np.linalg.norm(response)), np.finfo(float).tiny) * 32
        if np.linalg.norm(centered) <= tolerance:
            return {**output, "reason": "At least one equation has zero or numerically degenerate residual variance; its residual correlation is unavailable, not zero."}
        residuals.append(centered)
    matrix = np.corrcoef(np.stack(residuals), rowvar=True)
    matrix = np.atleast_2d(matrix)
    if matrix.shape != (len(targets), len(targets)) or not np.isfinite(matrix).all():
        raise LabError("INVALID_RESULT")
    return {**output, "status": "computed", "values": matrix.tolist()}


def compute(frame, options, seed):
    requested_settings = options.get("process_settings")
    graph, coding, routes = validate_process(options.get("process"), requested_settings, list(frame.columns))
    settings_version = _validate_settings_version(requested_settings)
    alpha, robust, requested = options.get("alpha", .05), options.get("robust", True), options.get("bootstrap", 1000)
    by_id = {n["id"]: n for n in graph["nodes"]}
    by_edge = {e["id"]: e for e in graph["edges"]}
    x_id = next(i for i, n in by_id.items() if n["role"] == "independent")
    y_id = next(i for i, n in by_id.items() if n["role"] == "dependent")
    moderator_ids = [i for i, n in by_id.items() if n["role"] == "moderator"]
    used_columns = [n["column"] for n in graph["nodes"]]
    sample_mask = frame[used_columns].notna().all(axis=1)
    data = frame[used_columns].loc[sample_mask]
    n = len(data)
    if n < 10:
        raise LabError("INSUFFICIENT_DATA")
    values, basis, basis_description, coding_rows = {}, {}, {}, []
    notices = ["Statistical associations do not establish causation. Temporal ordering and absence of unmeasured confounding require substantive justification.", "All equations use one fixed listwise sample. Whole-case bootstrap resampling assumes independent observations.", "No implicit centering, score construction, missing-value imputation or graph changes are performed."]
    for node_id, node in by_id.items():
        series = data[node["column"]]
        if node_id in coding:
            declaration = coding[node_id]
            levels, reference = declaration["levels"], declaration["reference"]
            if isinstance(levels[0], str):
                if not all(isinstance(v, str) for v in series):
                    raise LabError("INVALID_OPTIONS")
                observed = set(series)
            else:
                if not pd.api.types.is_numeric_dtype(series):
                    raise LabError("NUMERIC_TYPE_MISMATCH")
                observed = set(series.astype(float))
            if observed != set(levels):
                raise LabError("INVALID_OPTIONS")
            basis[node_id] = []
            for index, level in enumerate(levels):
                if level == reference:
                    continue
                factor = (node_id, index)
                basis[node_id].append(factor)
                values[factor] = series.eq(level).to_numpy(float)
                basis_description[factor] = {"node_id": node_id, "column": node["column"], "level": level, "reference": reference}
            coding_rows.append({"node_id": node_id, "column": node["column"], "levels": levels, "reference": reference, "method": "indicator", "counts": [{"level": level, "n": int(series.eq(level).sum())} for level in levels]})
        else:
            if not pd.api.types.is_numeric_dtype(series):
                raise LabError("NUMERIC_TYPE_MISMATCH")
            numeric = series.to_numpy(float)
            if not np.isfinite(numeric).all():
                raise LabError("INVALID_DATA")
            if np.unique(numeric).size < 2:
                raise LabError("CONSTANT_VARIABLE")
            factor = (node_id, -1)
            basis[node_id] = [factor]
            values[factor] = numeric
            basis_description[factor] = {"node_id": node_id, "column": node["column"]}
            if node["measurement_scale"] == "ordinal":
                notices.append(f"Ordinal numerical score {node_id} is modeled as a quantitative score; equal-spacing and linearity assumptions require review.")
    if requested_settings["outcome_family"] == "logistic":
        if set(values[(y_id, -1)]) != {0., 1.}:
            raise LabError("INVALID_OPTIONS")
        notices.append("Binary-outcome indirect and total values are statistical products on the log-odds equation scale, not natural causal, probability or marginal total effects. Logistic noncollapsibility prevents interpreting them as a reduced total log-odds coefficient.")
    explicit = {entry["node_id"]: entry["values"] for entry in requested_settings["probes"]}
    probe_policy = requested_settings["automatic_probes"] if settings_version >= 2 else {"probabilities": [.16, .5, .84], "quantile_method": "linear"}
    probes = {}
    extrapolation = []
    for node_id in moderator_ids:
        # Resolve once on the fixed sample. Explicit values bypass percentiles;
        # resampling never changes the estimand's conditioning values.
        probes[node_id] = explicit[node_id] if node_id in explicit else coding[node_id]["levels"] if node_id in coding else [float(v) for v in np.unique(np.quantile(values[(node_id, -1)], probe_policy["probabilities"], method=probe_policy["quantile_method"]))]
        if node_id not in coding:
            low, high = float(values[(node_id, -1)].min()), float(values[(node_id, -1)].max())
            if any(v < low or v > high for v in probes[node_id]):
                extrapolation.append(node_id)
    condition_count = math.prod(len(v) for v in probes.values())
    if condition_count > 25:
        raise LabError("RESOURCE_LIMIT")
    conditions = [dict(zip(moderator_ids, items)) for items in itertools.product(*(probes[i] for i in moderator_ids))]
    if extrapolation:
        notices.append("Explicit probe values extrapolate beyond the observed range for: " + ", ".join(extrapolation) + ".")
    if len(moderator_ids) >= 2:
        notices.append("Probe combinations use marginal moderator values; individual marginal ranges do not establish adequate joint data support.")
    equations = {}
    def add_term(target, factors):
        factors = tuple(sorted(factors))
        equations.setdefault(target, {"terms": {(): None}})["terms"][factors] = None
    for edge in graph["edges"]:
        for factor in basis[edge["source"]]:
            add_term(edge["target"], [factor])
    for mod in graph["moderations"]:
        edge = by_edge[mod["path_id"]]
        for factors in itertools.product(*(basis[i] for i in [edge["source"], *mod["moderator_ids"]])):
            add_term(edge["target"], factors)
    work = 0
    for target, eq in sorted(equations.items()):
        eq["terms"] = sorted(eq["terms"], key=lambda terms: (len(terms), terms))
        if len(eq["terms"]) > MAX_TERMS:
            raise LabError("RESOURCE_LIMIT")
        eq["term_ids"] = ["term_" + target + "_" + hashlib.sha256(_key(terms).encode()).hexdigest()[:16] for terms in eq["terms"]]
        eq["design"] = np.column_stack([np.prod([values[f] for f in terms], axis=0) if terms else np.ones(n) for terms in eq["terms"]])
        eq["family"] = requested_settings["outcome_family"] if target == y_id else "linear"
        eq["y"] = values[(target, -1)]
        work += n * len(eq["terms"]) ** 2 * requested * (10 if eq["family"] == "logistic" else 1)
    contrasts = basis[x_id]
    indirect_routes = [(path, route_nodes) for path, route_nodes in routes if len(path) > 1]
    numerical_moderators = [i for i in moderator_ids if i not in coding]
    if settings_version == 3:
        derivatives = [subset for order in range(1, len(numerical_moderators) + 1)
                       for subset in itertools.combinations(numerical_moderators, order)]
        # Each derivative of a route product assigns its k partials to L edges
        # (L**k assignments), evaluating L edge slopes for every bootstrap draw.
        # Counting every subset even for structurally zero derivatives is a
        # conservative bound, calculated before any original or bootstrap fit.
        derivative_work = requested * len(conditions) * len(contrasts) * sum(
            sum(math.comb(len(numerical_moderators), order) * len(path) ** (order + 1)
                for order in range(1, len(numerical_moderators) + 1))
            for path, _ in indirect_routes)
        if derivative_work > MAX_DERIVATIVE_WORK:
            raise LabError("RESOURCE_LIMIT")
    else:
        derivatives = [(i,) for i in numerical_moderators] + ([tuple(moderator_ids)] if len(moderator_ids) == 2 and not coding.keys() & set(moderator_ids) else [])
    estimated_rows = len(contrasts) * len(conditions) * (len(indirect_routes) + 3)
    estimated_contrasts = len(contrasts) * (len(conditions) * len(indirect_routes) * (len(indirect_routes) - 1) // 2 + (len(indirect_routes) + 3) * len(conditions) * (len(conditions) - 1) // 2)
    estimated_indices = len(contrasts) * len(conditions) * (len(indirect_routes) + 1 + len(indirect_routes)*(len(indirect_routes)-1)//2) * (len(derivatives) if settings_version == 3 else len(moderator_ids) + (1 if len(moderator_ids) == 2 else 0))
    estimated_points = sum((len(coding[edge["source"]]["levels"]) if edge["source"] in coding else 21) * len(conditions) * len({i for mod in graph["moderations"] if mod["path_id"] == edge["id"] for i in mod["moderator_ids"]}) for edge in graph["edges"])
    if work > MAX_WORK or sum(eq["design"].size for eq in equations.values()) > 5_000_000 or estimated_rows + estimated_contrasts + estimated_indices > MAX_ROWS or estimated_points > 12000:
        raise LabError("RESOURCE_LIMIT")
    for eq in equations.values():
        eq["fit"], eq["cov"], eq["reference"] = _fit(eq["y"], eq["design"], eq["family"], robust)
        eq["beta"] = np.asarray(eq["fit"].params)
    accepted = []
    failures = Counter()
    rng = np.random.Generator(np.random.PCG64(seed)) if settings_version >= 2 else np.random.default_rng(seed)
    for _ in range(requested):
        index = rng.integers(0, n, n)
        try:
            draw = {target: _fit(eq["y"][index], eq["design"][index], eq["family"], False, True) for target, eq in equations.items()}
            accepted.append(draw)
        except LabError as error:
            failures[error.code] += 1
        except (np.linalg.LinAlgError, ValueError, RuntimeWarning, PerfectSeparationWarning, ConvergenceWarning, OverflowError):
            failures["NUMERICAL_FAILURE"] += 1
    if len(accepted) < .95 * requested:
        raise LabError("BOOTSTRAP_FAILURE")
    for target, eq in equations.items():
        eq["boot"] = np.asarray([draw[target] for draw in accepted])
    successful = len(accepted)
    scale = "log_odds_statistical_path_product" if requested_settings["outcome_family"] == "logistic" else "outcome_units"
    output = {"schema_version": 1, "graph": graph, "requested_settings": requested_settings, "settings": {**requested_settings, "probes": [{"node_id": i, "values": probes[i]} for i in moderator_ids]}, "sample": {"source_n": len(frame), "n": n, "excluded": len(frame) - n, "rule": "One fixed listwise sample across all graph nodes and equations"}, "equations": [], "path_coefficients": [], "interaction_coefficients": [], "effects": [], "slopes": [], "indices": [], "index_contrasts": [], "effect_contrasts": [], "johnson_neyman": [], "interaction_tests": [], "plots": [], "coding": coding_rows, "assumptions": notices, "warnings": [], "bootstrap": {"requested": requested, "successful": successful, "failed": requested - successful, "seed": seed, "ci_method": "percentile", "confidence_level": 1 - alpha, "success_threshold": .95, "failure_reasons": dict(failures)}}
    if settings_version >= 2:
        canonical_settings = {**requested_settings, "categorical": sorted(requested_settings["categorical"], key=lambda entry: entry["node_id"]), "probes": sorted(requested_settings["probes"], key=lambda entry: entry["node_id"])}
        semantics = {"graph": graph, "settings": canonical_settings, "estimation": {"alpha": alpha, "robust": robust, "bootstrap": requested, "seed": seed}}
        output.update(schema_version=settings_version, probe_policy=probe_policy, compiler_plan={
            "schema_version": 1,
            "semantic_sha256": hashlib.sha256(_key(semantics).encode("utf-8")).hexdigest(),
            "sample_mask_sha256": hashlib.sha256(_key(sample_mask.tolist()).encode("utf-8")).hexdigest(),
            "equations": [{"target_id": target, "family": eq["family"], "term_ids": eq["term_ids"], "terms": [{"term_id": term_id, "factors": [basis_description[f] for f in terms]} for term_id, terms in zip(eq["term_ids"], eq["terms"])]} for target, eq in sorted(equations.items())],
            "routes": [{"path_ids": path, "node_ids": node_ids} for path, node_ids in routes],
            "work": {"estimated_fit_operations": work, "design_cells": sum(eq["design"].size for eq in equations.values()), "estimated_effect_rows": estimated_rows, "estimated_contrast_rows": estimated_contrasts, "estimated_index_rows": estimated_indices, "estimated_plot_points": estimated_points, "limits": {"fit_operations": MAX_WORK, "terms_per_equation": MAX_TERMS, "result_rows": MAX_ROWS, "design_cells": 5_000_000, "plot_points": 12000}},
        })
        output["bootstrap"].update(quantile_method="linear", rng="numpy.PCG64")
        if settings_version == 3:
            output["compiler_plan"]["capabilities"] = dict(THREE_MODERATOR_CAPABILITIES)
            output["compiler_plan"]["work"]["estimated_derivative_operations"] = derivative_work
    estimates = []
    def term_label(terms):
        if not terms:
            return "Intercept"
        return " × ".join(by_id[f[0]]["column"] + (f" [{basis_description[f]['level']} vs {basis_description[f]['reference']}]" if f[1] >= 0 else "") for f in terms)
    for target, eq in sorted(equations.items()):
        fit, covariance, reference = eq["fit"], eq["cov"], eq["reference"]
        coefficients = []
        for index, terms in enumerate(eq["terms"]):
            row = {"term_id": eq["term_ids"][index], "term": term_label(terms), "factors": [basis_description[f] for f in terms], **_inference(eq["beta"], covariance, np.eye(len(eq["terms"]))[index], reference, alpha)}
            coefficients.append(row)
            estimates.append({"term": row["term_id"], "estimate": row["estimate"], "se": row["se"], "p": row["p"], "lower": row["lower"], "upper": row["upper"]})
        eq["coefficients"] = coefficients
        summary = {"target_id": target, "column": by_id[target]["column"], "family": eq["family"], "formula": by_id[target]["column"] + " ~ " + " + ".join(term_label(terms) for terms in eq["terms"]), "n": n, "df_model": float(fit.df_model), "df_resid": float(fit.df_resid), "coefficients": coefficients, "covariance": {"term_ids": eq["term_ids"], "values": covariance.tolist()}, "standard_errors": ("generalized logistic HC3" if eq["family"] == "logistic" else "HC3") if robust else "model-based logistic" if eq["family"] == "logistic" else "classical OLS", "assumptions": ["Independent cases; correctly specified conditional mean/link; no unmeasured confounding is established by this fit."]}
        if eq["family"] == "linear":
            overall_wald = _wald(eq["beta"][1:], covariance[1:, 1:])
            overall_F = overall_wald / fit.df_model if overall_wald is not None else None
            summary.update(R=float(math.sqrt(max(0, fit.rsquared))), R2=float(fit.rsquared), adjustedR2=float(fit.rsquared_adj), MSE=float(fit.mse_resid), RMSE=float(math.sqrt(fit.mse_resid)), overall_test={"statistic": overall_F, "reference": "HC3 Wald F" if robust else "OLS F", "df_num": float(fit.df_model), "df_den": float(fit.df_resid), "p": finite(stats.f.sf(overall_F, fit.df_model, fit.df_resid)) if overall_F is not None else None})
            influence = fit.get_influence()
            summary["diagnostics"] = {"max_cooks_distance": finite(np.max(influence.cooks_distance[0])), "max_leverage": finite(np.max(influence.hat_matrix_diag)), "durbin_watson": finite(sm.stats.stattools.durbin_watson(fit.resid)), "breusch_pagan_p": finite(sm.stats.diagnostic.het_breuschpagan(fit.resid, eq["design"])[1])}
        else:
            summary.update(log_likelihood=float(fit.llf), null_log_likelihood=float(fit.llnull), pseudo_R2=float(fit.prsquared), AIC=float(fit.aic), BIC=float(fit.bic), overall_test={"statistic": float(fit.llr), "reference": "likelihood-ratio chi-square (model-based)", "df_num": float(fit.df_model), "df_den": None, "p": float(fit.llr_pvalue)})
            summary["separation_check"] = "Original sample checked for complete/quasi-complete separation using unit-scaled linear-program feasibility; each fit also checks convergence, finite parameters and full-rank weighted information."
            summary["odds_ratios"] = [{"term_id": row["term_id"], "estimate": _odds_ratio(row["estimate"]), "lower": _odds_ratio(row["lower"]), "upper": _odds_ratio(row["upper"]), "note": "An unavailable ratio exceeds numerical exponentiation range; the original-unit log-odds coefficient and its uncertainty remain available."} for row in coefficients]
        if settings_version >= 2:
            summary["diagnostic_evidence"] = _diagnostic_evidence(eq)
        output["equations"].append(summary)
    output["residual_correlations"] = _residual_correlations(equations, by_id, n)
    def link_row(eq, terms):
        return eq["coefficients"][eq["terms"].index(tuple(sorted(terms)))]
    for edge in graph["edges"]:
        eq = equations[edge["target"]]
        for factor in basis[edge["source"]]:
            row = link_row(eq, [factor])
            entry = {"path_id": edge["id"], "source_id": edge["source"], "target_id": edge["target"], "family": eq["family"], "scale": "log_odds" if eq["family"] == "logistic" else "outcome_units", **{k: row[k] for k in ("term_id", "estimate", "se", "statistic", "reference", "p", "lower", "upper")}}
            if factor[1] >= 0:
                entry["focal_contrast"] = basis_description[factor]
            output["path_coefficients"].append(entry)
    for mod in graph["moderations"]:
        edge = by_edge[mod["path_id"]]
        eq = equations[edge["target"]]
        for factors in itertools.product(*(basis[i] for i in [edge["source"], *mod["moderator_ids"]])):
            row = link_row(eq, factors)
            output["interaction_coefficients"].append({"moderation_id": mod["id"], "path_id": edge["id"], "target_id": edge["target"], "factors": [basis_description[f] for f in sorted(factors)], **{k: row[k] for k in ("term_id", "estimate", "se", "statistic", "reference", "p", "lower", "upper")}})
    def factor_at(factor, condition):
        node_id = factor[0]
        value = condition.get(node_id, coding[node_id]["reference"] if node_id in coding else float(values[(node_id, -1)].mean()))
        return float(value == basis_description[factor]["level"]) if factor[1] >= 0 else float(value)
    def path_vector(edge, source_factor, condition, derivative=()):
        eq = equations[edge["target"]]
        vector = np.zeros(len(eq["terms"]))
        for index, terms in enumerate(eq["terms"]):
            if source_factor not in terms:
                continue
            others = [f for f in terms if f != source_factor]
            differentiated = list(others)
            for node_id in derivative:
                factor = (node_id, -1)
                if factor not in differentiated:
                    break
                differentiated.remove(factor)
            else:
                vector[index] = math.prod(factor_at(f, condition) for f in differentiated)
        return vector
    def path_value(edge_id, focal_factor, condition, derivative=()):
        edge = by_edge[edge_id]
        factor = focal_factor if edge["source"] == x_id else basis[edge["source"]][0]
        vector = path_vector(edge, factor, condition, derivative)
        eq = equations[edge["target"]]
        return float(vector @ eq["beta"]), eq["boot"] @ vector
    def product(path, focal_factor, condition, derivative=()):
        if not derivative:
            rows = [path_value(e, focal_factor, condition) for e in path]
            return math.prod(row[0] for row in rows), np.prod([row[1] for row in rows], axis=0)
        result, distribution = 0., np.zeros(successful)
        # Product differentiation assigns each requested derivative to an edge.
        for assignment in itertools.product(range(len(path)), repeat=len(derivative)):
            rows = [path_value(e, focal_factor, condition, tuple(derivative[k] for k, edge_index in enumerate(assignment) if edge_index == i)) for i, e in enumerate(path)]
            result += math.prod(row[0] for row in rows)
            distribution += np.prod([row[1] for row in rows], axis=0)
        return result, distribution
    cached = []
    constant_indices = {}
    for contrast_index, focal_factor in enumerate(contrasts):
        contrast = basis_description[focal_factor] if focal_factor[1] >= 0 else None
        for condition_index, condition in enumerate(conditions):
            route_rows = []
            for route_index, (path, route_nodes) in enumerate(indirect_routes):
                value, distribution = product(path, focal_factor, condition)
                row = {"id": f"effect_{contrast_index}_{condition_index}_route_{route_index}", "kind": "specific_indirect", "path_ids": path, "node_ids": route_nodes, "condition": condition, "scale": scale, **_bootstrap_row(value, distribution, alpha)}
                if contrast:
                    row["focal_contrast"] = contrast
                output["effects"].append(row)
                route_rows.append((row, distribution))
            total_indirect = sum(row[0]["estimate"] for row in route_rows)
            indirect_distribution = sum((row[1] for row in route_rows), np.zeros(successful))
            direct_paths = [path for path, _ in routes if len(path) == 1]
            direct, direct_distribution = product(direct_paths[0], focal_factor, condition) if direct_paths else (0., np.zeros(successful))
            grouped = []
            for kind, value, distribution in [("total_indirect", total_indirect, indirect_distribution), ("direct", direct, direct_distribution), ("total", direct + total_indirect, direct_distribution + indirect_distribution)]:
                row = {"id": f"effect_{contrast_index}_{condition_index}_{kind}", "kind": kind, "path_ids": sorted({e for path, _ in (routes if kind == "total" else [(p, []) for p in direct_paths] if kind == "direct" else indirect_routes) for e in path}), "node_ids": [x_id, y_id], "condition": condition, "scale": scale, **_bootstrap_row(value, distribution, alpha)}
                if kind == "direct":
                    row["structurally_fixed_zero"] = not bool(direct_paths)
                if contrast:
                    row["focal_contrast"] = contrast
                output["effects"].append(row)
                grouped.append((row, distribution))
            cached.append((contrast_index, condition_index, route_rows + grouped, focal_factor))
            for derivative in derivatives:
                route_derivatives = []
                for route_index, (path, _) in enumerate(indirect_routes):
                    degrees = {i: sum(int(any(any(f[0] == i for f in terms) for terms in equations[by_edge[e]["target"]]["terms"] if (focal_factor if by_edge[e]["source"] == x_id else basis[by_edge[e]["source"]][0]) in terms)) for e in path) for i in moderator_ids}
                    value, distribution = product(path, focal_factor, condition, derivative)
                    route_derivatives.append((route_index, path, degrees, value, distribution))
                if not route_derivatives or not any(all(degrees[i] > 0 for i in derivative) for _, _, degrees, _, _ in route_derivatives):
                    continue
                grouped_derivatives = [*route_derivatives, ("total_indirect", sorted({e for path, _ in indirect_routes for e in path}), {i: max(row[2][i] for row in route_derivatives) for i in moderator_ids}, sum(row[3] for row in route_derivatives), sum((row[4] for row in route_derivatives), np.zeros(successful)))]
                route_index_rows = []
                for route_index, path, degrees, value, distribution in grouped_derivatives:
                    if len(derivative) == 1:
                        i = derivative[0]
                        kind = "linear_index" if degrees[i] <= 1 and all(degrees[j] == 0 for j in moderator_ids if j != i) else "conditional_index" if degrees[i] <= 1 else "conditional_derivative"
                    else:
                        constant = all(degrees[i] <= 1 for i in derivative) and (settings_version < 3 or all(degrees[i] == 0 for i in moderator_ids if i not in derivative))
                        kind = "mixed_index" if constant else "conditional_mixed_derivative"
                    effect_kind = "total_indirect" if route_index == "total_indirect" else "specific_indirect"
                    constant_key = (contrast_index, route_index, derivative)
                    # Constant indices appear once; conditional rows retain their values.
                    if kind in ("linear_index", "mixed_index") and condition_index > 0:
                        if effect_kind == "specific_indirect":
                            route_index_rows.append((constant_indices[constant_key], distribution))
                        continue
                    row = {"id": f"index_{contrast_index}_{condition_index}_{route_index}_" + "_".join(derivative), "kind": kind, "effect_kind": effect_kind, "definition": "Partial derivative of " + ("summed indirect path products" if effect_kind == "total_indirect" else "specific indirect path product") + " with respect to " + " and ".join(derivative) + ("; constant over moderator values" if kind in ("linear_index", "mixed_index") else "; conditional on stated values, not a global linear index"), "path_ids": path, "moderator_ids": list(derivative), "condition": {} if kind in ("linear_index", "mixed_index") else condition, "scale": scale, "structurally_fixed_zero": any(degrees[i] == 0 for i in derivative), **_bootstrap_row(value, distribution, alpha)}
                    if contrast:
                        row["focal_contrast"] = contrast
                    output["indices"].append(row)
                    if kind in ("linear_index", "mixed_index"):
                        constant_indices[constant_key] = row
                    if effect_kind == "specific_indirect":
                        route_index_rows.append((row, distribution))
                for (row_a, draw_a), (row_b, draw_b) in itertools.combinations(route_index_rows, 2):
                    if condition_index > 0 and not row_a["condition"] and not row_b["condition"]:
                        continue
                    output["index_contrasts"].append({"id": "index_contrast_" + row_a["id"] + "_minus_" + row_b["id"], "kind": "route_derivative_difference" if "derivative" in row_a["kind"] or "derivative" in row_b["kind"] else "route_index_difference", "index_a": row_a["id"], "index_b": row_b["id"], "definition": "Difference between the stated specific indirect route derivatives; paired bootstrap resamples preserve their covariance.", "condition": {} if not row_a["condition"] and not row_b["condition"] else condition, "moderator_ids": list(derivative), "scale": scale, **_bootstrap_row(row_a["estimate"]-row_b["estimate"], draw_a-draw_b, alpha)})
    def contrast_row(a, b, kind):
        row_a, distribution_a = a
        row_b, distribution_b = b
        output["effect_contrasts"].append({"id": "contrast_" + row_a["id"] + "_minus_" + row_b["id"], "kind": kind, "effect_a": row_a["id"], "effect_b": row_b["id"], "condition_a": row_a["condition"], "condition_b": row_b["condition"], "scale": scale, **_bootstrap_row(row_a["estimate"] - row_b["estimate"], distribution_a - distribution_b, alpha)})
    for _, _, rows, _ in cached:
        for a, b in itertools.combinations([row for row in rows if row[0]["kind"] == "specific_indirect"], 2):
            contrast_row(a, b, "specific_indirect_route_difference")
    for contrast_index in range(len(contrasts)):
        grouped = [rows for ci, _, rows, _ in cached if ci == contrast_index]
        for a, b in itertools.combinations(grouped, 2):
            for row_a, row_b in zip(a, b):
                contrast_row(row_a, row_b, "condition_difference")
    for edge in graph["edges"]:
        eq = equations[edge["target"]]
        relevant_mods = [m for m in graph["moderations"] if m["path_id"] == edge["id"]]
        if not relevant_mods:
            continue
        affected = sorted({i for m in relevant_mods for i in m["moderator_ids"]})
        edge_conditions = list({_key({i: v for i, v in condition.items() if i != edge["source"]}): {i: v for i, v in condition.items() if i != edge["source"]} for condition in conditions}.values())
        for factor in basis[edge["source"]]:
            for condition in edge_conditions:
                vector = path_vector(edge, factor, condition)
                row = {"path_id": edge["id"], "source_id": edge["source"], "target_id": edge["target"], "condition": condition, "conditioning_note": "Other numerical equation predictors are held at complete-case means; other categorical predictors at their declared reference. All equation terms involving the focal source are included.", "scale": "log_odds" if eq["family"] == "logistic" else "outcome_units", **_inference(eq["beta"], eq["cov"], vector, eq["reference"], alpha)}
                if factor[1] >= 0:
                    row["focal_contrast"] = basis_description[factor]
                output["slopes"].append(row)
            for moderator in affected:
                slices = {_key({i: v for i, v in c.items() if i != moderator}): {i: v for i, v in c.items() if i != moderator} for c in edge_conditions}
                for other in slices.values():
                    entry = {"path_id": edge["id"], "moderator_id": moderator, "other_conditions": other, "boundaries": [], "boundary_details": [], "grid": [], "regions": [], "observed_range": None, "status": "not_applicable", "reason": "Categorical moderators use level comparisons, not numerical Johnson–Neyman regions.", "assumptions": ["Pointwise intervals; no multiplicity adjustment. Other moderators are held at the stated values."]}
                    if factor[1] >= 0:
                        entry["focal_contrast"] = basis_description[factor]
                    if moderator not in coding:
                        low, high = float(values[(moderator, -1)].min()), float(values[(moderator, -1)].max())
                        v0 = path_vector(edge, factor, {**other, moderator: 0})
                        v1 = path_vector(edge, factor, {**other, moderator: 1}) - v0
                        b0, b1 = float(v0 @ eq["beta"]), float(v1 @ eq["beta"])
                        critical = float(eq["reference"].ppf(1 - alpha / 2))
                        polynomial = np.array([b1*b1-critical**2*(v1@eq["cov"]@v1), 2*(b0*b1-critical**2*(v0@eq["cov"]@v1)), b0*b0-critical**2*(v0@eq["cov"]@v0)])
                        tolerance = np.finfo(float).eps * float(np.max(np.abs(polynomial))) * 32
                        coefficients = np.trim_zeros(np.where(np.abs(polynomial) <= tolerance, 0, polynomial), "f")
                        roots = np.roots(coefficients) if len(coefficients) > 1 else []
                        boundaries = sorted({float(root.real) for root in roots if abs(root.imag) < 1e-8 and low < root.real < high})
                        cuts = [low, *boundaries, high]
                        entry.update(status="computed", reason="Analytic conditional-slope boundaries restricted to the observed moderator range.", observed_range=[low, high], boundaries=boundaries, regions=[{"lower": a, "upper": b, "significant": bool(np.polyval(polynomial, (a+b)/2) > tolerance)} for a, b in zip(cuts, cuts[1:])])
                        observed = values[(moderator, -1)]
                        entry["boundary_details"] = [{"value": boundary,
                            "percent_below": float(100 * np.count_nonzero(observed < boundary) / n),
                            "percent_above": float(100 * np.count_nonzero(observed > boundary) / n),
                            "percent_equal": float(100 * np.count_nonzero(observed == boundary) / n)}
                            for boundary in boundaries]
                        moderator_grid = sorted({*np.linspace(low, high, 21).tolist(), *boundaries})
                        entry["grid"] = [{"moderator": value,
                            **_inference(eq["beta"], eq["cov"], path_vector(edge, factor, {**other, moderator: value}), eq["reference"], alpha)}
                            for value in moderator_grid]
                    output["johnson_neyman"].append(entry)
                # The fitted-mean plot contains every source category; do not repeat
                # the whole plot for each separate indicator contrast.
                if factor != basis[edge["source"]][0]:
                    continue
                # Fitted means hold all remaining equation variables at means or reference categories.
                plot = {"path_id": edge["id"], "source_id": edge["source"], "target_id": edge["target"], "column": by_id[edge["target"]]["column"], "family": eq["family"], "moderator_id": moderator, "scale": "probability" if eq["family"] == "logistic" else "outcome_mean", "note": "Conditional fitted means, not individual prediction intervals or total pathway effects. Other numerical predictors are held at complete-case means and categorical predictors at their declared reference.", "points": []}
                source_grid = coding[edge["source"]]["levels"] if edge["source"] in coding else np.linspace(values[(edge["source"], -1)].min(), values[(edge["source"], -1)].max(), 21).tolist()
                for condition in edge_conditions:
                    for source in source_grid:
                        point_values = {i: coding[i]["reference"] if i in coding else float(values[(i, -1)].mean()) for i in by_id}
                        point_values.update(condition)
                        point_values[edge["source"]] = source
                        vector = np.array([math.prod(factor_at(f, point_values) for f in terms) for terms in eq["terms"]])
                        inferred = _inference(eq["beta"], eq["cov"], vector, eq["reference"], alpha)
                        point = {"x": source, "moderator": condition[moderator], "other_conditions": {i: v for i, v in condition.items() if i != moderator}, "predicted": inferred["estimate"], "lower": inferred["lower"], "upper": inferred["upper"]}
                        if eq["family"] == "logistic":
                            for key in ("predicted", "lower", "upper"):
                                point[key] = float(expit(point[key]))
                        plot["points"].append(point)
                output["plots"].append(plot)
    for target, eq in sorted(equations.items()):
        positions = [i for i, terms in enumerate(eq["terms"]) if len(terms) > 1]
        if not positions:
            continue
        beta = eq["beta"][positions]
        covariance = eq["cov"][np.ix_(positions, positions)]
        statistic = _wald(beta, covariance)
        delta = None
        if eq["family"] == "linear":
            keep = [i for i in range(len(eq["terms"])) if i not in positions]
            restricted = sm.OLS(eq["y"], eq["design"][:, keep]).fit()
            delta = float(eq["fit"].rsquared - restricted.rsquared)
        classical_linear = eq["family"] == "linear" and not robust
        if classical_linear and statistic is not None:
            statistic /= len(positions)
        output["interaction_tests"].append({"target_id": target, "moderation_ids": [m["id"] for m in graph["moderations"] if by_edge[m["path_id"]]["target"] == target], "term_ids": [eq["term_ids"][i] for i in positions], "statistic": statistic, "reference": "HC3 Wald chi-square" if robust else "model-based Wald chi-square" if eq["family"] == "logistic" else "OLS partial F", "df_num": len(positions), "df_den": float(eq["fit"].df_resid) if classical_linear else None, "p": None if statistic is None else float(stats.f.sf(statistic, len(positions), eq["fit"].df_resid)) if classical_linear else float(stats.chi2.sf(statistic, len(positions))), "deltaR2": delta, "status": "computed" if statistic is not None else "unavailable", "reason": None if statistic is not None else "The estimated interaction-block covariance is singular; no test statistic is invented."})
    if requested - successful:
        output["warnings"].append("Some complete-case bootstrap replicates failed; inspect the recorded counts and reasons.")
    if len(output["effects"]) + len(output["effect_contrasts"]) + len(output["indices"]) + len(output["index_contrasts"]) > MAX_ROWS or len(json.dumps(output, allow_nan=False)) > 3_500_000:
        raise LabError("RESOURCE_LIMIT")
    fit_summary = next(row for row in output["equations"] if row["target_id"] == y_id)
    fit = {"r_squared": fit_summary["R2"], "adjusted_r_squared": fit_summary["adjustedR2"], "df_resid": fit_summary["df_resid"]} if requested_settings["outcome_family"] == "linear" else {"pseudo_r_squared": fit_summary["pseudo_R2"], "log_likelihood": fit_summary["log_likelihood"], "aic": fit_summary["AIC"]}
    return estimates, fit, {"process": output}, notices + output["warnings"], n
