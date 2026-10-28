"""Independent equation and paired-bootstrap checks for the frozen SPSS engine.

References use explicit matrices, NumPy QR, and Newton score iterations.  They
do not use the engine's compiler, fitting, effect or resampling functions.
"""
from copy import deepcopy
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest
from scipy.special import expit

EXTENSION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXTENSION))
from pathlab_spss import core
from pathlab_spss.errors import LabError

SEED = 10317
DRAWS = 60
PROBES = {"W": [-.6, .7], "Z": [-.5, .8], "Q": [-.4, .9]}


def graph(roles, pairs, moderations=(), nominal=()):
    return {
        "schema_version": 1,
        "nodes": [{"id": key, "column": key, "role": role,
                   "measurement_scale": "nominal" if key in nominal else "interval"}
                  for key, role in roles.items()],
        "edges": [{"id": f"p_{a}_{b}", "source": a, "target": b} for a, b in pairs],
        "moderations": [{"id": f"mod_{i}", "path_id": f"p_{a}_{b}", "moderator_ids": mods}
                        for i, (a, b, mods) in enumerate(moderations)],
    }


def settings(probes=None, categorical=None, logistic=False):
    return {
        "schema_version": 3,
        "outcome_family": "logistic" if logistic else "linear",
        "categorical": categorical or [],
        "probes": [{"node_id": key, "values": values} for key, values in (probes or {}).items()],
        "automatic_probes": {"probabilities": [.16, .5, .84], "quantile_method": "linear",
                             "sample": "fixed_complete_case_sample", "resolve_before_bootstrap": True},
        "bootstrap_interval_quantile_method": "linear",
    }


def run(frame, spec, request, robust=True):
    return core.compute(frame, {"process": spec, "process_settings": request,
                               "bootstrap": DRAWS, "alpha": .05, "robust": robust}, SEED)[2]["process"]


def qr(y, design, robust=False):
    q, r = np.linalg.qr(design, mode="reduced")
    beta = np.linalg.solve(r, q.T @ y)
    inverse_r = np.linalg.solve(r, np.eye(r.shape[0]))
    bread = inverse_r @ inverse_r.T
    residual = y - design @ beta
    if robust:
        leverage = np.sum(q*q, axis=1)
        scores = residual/(1-leverage)
        covariance = bread @ (design.T @ (design*scores[:, None]**2)) @ bread
    else:
        covariance = bread*(residual @ residual)/(len(y)-design.shape[1])
    return beta, covariance


def newton(y, design, robust=False):
    beta = np.zeros(design.shape[1])
    for _ in range(100):
        p = expit(design @ beta)
        information = design.T @ (design*(p*(1-p))[:, None])
        step = np.linalg.solve(information, design.T @ (y-p))
        beta += step
        if np.max(np.abs(step)) < 1e-12:
            break
    else:
        raise AssertionError("Independent logistic reference did not converge")
    p = expit(design @ beta)
    bread = np.linalg.inv(design.T @ (design*(p*(1-p))[:, None]))
    covariance = bread
    if robust:
        leverage = p*(1-p)*np.sum((design @ bread)*design, axis=1)
        scores = (y-p)/(1-leverage)
        covariance = bread @ (design.T @ (design*scores[:, None]**2)) @ bread
    return beta, covariance


def interval(row, estimate, distribution, tolerance=1e-10):
    assert row["estimate"] == pytest.approx(estimate, abs=tolerance)
    assert row["bootstrap_se"] == pytest.approx(np.std(distribution, ddof=1), abs=tolerance)
    assert [row["lower"], row["upper"]] == pytest.approx(
        np.quantile(distribution, [.025, .975], method="linear"), abs=tolerance)


def check_equation(equation, beta, covariance, explicit_terms, tolerance=1e-10):
    order = [explicit_terms.index(tuple(f["node_id"] for f in row["factors"]))
             for row in equation["coefficients"]]
    assert [r["estimate"] for r in equation["coefficients"]] == pytest.approx(beta[order], abs=tolerance)
    assert np.asarray(equation["covariance"]["values"]) == pytest.approx(
        covariance[np.ix_(order, order)], abs=tolerance)


def serial_fixture(categorical=False, logistic=False):
    rng = np.random.Generator(np.random.PCG64(3197))
    n = 240
    x, w, z, q = rng.normal(size=(4, n))
    if categorical:
        q = np.where(q > 0, "high", "low")
    q_score = (q == "high").astype(float) if categorical else q
    m1 = .1 + .6*x + .2*w + .25*x*w + rng.normal(size=n)
    m2 = -.1 + .55*m1 + .15*z + .2*m1*z + rng.normal(size=n)
    y = .2 + .15*x + .65*m2 + .1*q_score + .18*m2*q_score + rng.normal(size=n)
    if logistic:
        y = rng.binomial(1, expit(-.1 + .15*x + .25*m2 + .15*q_score + .12*m2*q_score))
    frame = pd.DataFrame(dict(X=x, W=w, Z=z, Q=q, M1=m1, M2=m2, Y=y))
    frame.loc[1, "M1"] = np.nan
    frame.loc[3, "Y"] = np.nan
    spec = graph(
        {"X": "independent", "M1": "mediator", "M2": "mediator", "Y": "dependent",
         "W": "moderator", "Z": "moderator", "Q": "moderator"},
        [("X", "M1"), ("M1", "M2"), ("M2", "Y"), ("X", "Y"),
         ("W", "M1"), ("Z", "M2"), ("Q", "Y")],
        [("X", "M1", ["W"]), ("M1", "M2", ["Z"]), ("M2", "Y", ["Q"])],
        nominal=["Q"] if categorical else [],
    )
    probes = {**PROBES, "Q": ["low", "high"]} if categorical else deepcopy(PROBES)
    coding = [{"node_id": "Q", "levels": ["low", "high"], "reference": "low"}] if categorical else []
    return frame, spec, settings(probes, coding, logistic)


def serial_reference(frame, robust, categorical=False, logistic=False):
    fixed = frame.dropna()
    one = np.ones(len(fixed))
    q = fixed.Q.eq("high").to_numpy(float) if categorical else fixed.Q.to_numpy(float)
    matrices = {
        "M1": np.column_stack([one, fixed.X, fixed.W, fixed.X*fixed.W]),
        "M2": np.column_stack([one, fixed.M1, fixed.Z, fixed.M1*fixed.Z]),
        "Y": np.column_stack([one, fixed.X, fixed.M2, q, fixed.M2.to_numpy()*q]),
    }
    fits = {target: (newton if logistic and target == "Y" else qr)(
        fixed[target].to_numpy(), design, robust) for target, design in matrices.items()}
    boot = {target: [] for target in matrices}
    rng = np.random.Generator(np.random.PCG64(SEED))
    for _ in range(DRAWS):
        indices = rng.integers(0, len(fixed), len(fixed))
        for target, design in matrices.items():
            fit = newton if logistic and target == "Y" else qr
            boot[target].append(fit(fixed[target].to_numpy()[indices], design[indices])[0])
    return fits, {target: np.asarray(rows) for target, rows in boot.items()}


def serial_polynomial(betas, condition, derivative=(), categorical=False):
    w, z = condition["W"], condition["Z"]
    q = float(condition["Q"] == "high") if categorical else condition["Q"]
    a, d, b = betas["M1"], betas["M2"], betas["Y"]
    parts = {"W": a[..., 1]+a[..., 3]*w, "Z": d[..., 1]+d[..., 3]*z,
             "Q": b[..., 2]+b[..., 4]*q}
    derivatives = {"W": a[..., 3], "Z": d[..., 3], "Q": b[..., 4]}
    return math.prod(derivatives[key] if key in derivative else parts[key] for key in ("W", "Z", "Q"))


@pytest.mark.parametrize("robust", [False, True])
@pytest.mark.parametrize("categorical,logistic", [(False, False), (True, False), (False, True)])
def test_serial_three_moderators_equations_products_derivatives_and_paired_intervals(robust, categorical, logistic):
    frame, spec, request = serial_fixture(categorical, logistic)
    before, request_before = frame.copy(deep=True), deepcopy(request)
    output = run(frame, spec, request, robust)
    pd.testing.assert_frame_equal(frame, before)
    assert request == request_before
    assert output["sample"] == {"source_n": 240, "n": 238, "excluded": 2,
                                "rule": "One fixed listwise sample across all graph nodes and equations"}
    assert output["bootstrap"]["failed"] == 0
    fits, boot = serial_reference(frame, robust, categorical, logistic)
    betas = {target: pair[0] for target, pair in fits.items()}
    terms = {"M1": [(), ("X",), ("W",), ("W", "X")],
             "M2": [(), ("M1",), ("Z",), ("M1", "Z")],
             "Y": [(), ("X",), ("M2",), ("Q",), ("M2", "Q")]}
    tolerance = 1e-8 if logistic else 1e-10
    for equation in output["equations"]:
        target = equation["target_id"]
        check_equation(equation, *fits[target], terms[target], tolerance)
    distributions = {}
    for row in output["effects"]:
        indirect = serial_polynomial(betas, row["condition"], categorical=categorical)
        indirect_boot = serial_polynomial(boot, row["condition"], categorical=categorical)
        direct, direct_boot = betas["Y"][1], boot["Y"][:, 1]
        value, draws = {"specific_indirect": (indirect, indirect_boot),
                        "total_indirect": (indirect, indirect_boot),
                        "direct": (direct, direct_boot),
                        "total": (direct+indirect, direct_boot+indirect_boot)}[row["kind"]]
        interval(row, value, draws, tolerance)
        distributions[row["id"]] = draws
        if logistic:
            assert row["scale"] == "log_odds_statistical_path_product"
    numerical = ["W", "Z"] if categorical else ["W", "Z", "Q"]
    assert set(tuple(sorted(r["moderator_ids"])) for r in output["indices"]) == {
        tuple(sorted(group)) for order in range(1, len(numerical)+1)
        for group in itertools.combinations(numerical, order)}
    for row in output["indices"]:
        condition = row["condition"] or {key: values[0] for key, values in PROBES.items()}
        interval(row, serial_polynomial(betas, condition, row["moderator_ids"], categorical),
                 serial_polynomial(boot, condition, row["moderator_ids"], categorical), tolerance)
    effects = {row["id"]: row for row in output["effects"]}
    for row in output["effect_contrasts"]:
        a, b = row["effect_a"], row["effect_b"]
        interval(row, effects[a]["estimate"]-effects[b]["estimate"],
                 distributions[a]-distributions[b], tolerance)


def test_parallel_routes_difference_uses_same_case_draws():
    rng = np.random.Generator(np.random.PCG64(819))
    x = rng.normal(size=160)
    m1 = .6*x + rng.normal(size=160)
    m2 = .4*x + .5*m1 + rng.normal(size=160)
    y = .2*x + .5*m1 + .35*m2 + rng.normal(size=160)
    frame = pd.DataFrame(dict(X=x, M1=m1, M2=m2, Y=y))
    spec = graph({"X": "independent", "M1": "mediator", "M2": "mediator", "Y": "dependent"},
                 [("X", "M1"), ("X", "M2"), ("X", "Y"), ("M1", "Y"), ("M2", "Y")])
    output = run(frame, spec, settings())
    matrices = {"M1": np.column_stack([np.ones(len(x)), x]),
                "M2": np.column_stack([np.ones(len(x)), x]),
                "Y": np.column_stack([np.ones(len(x)), x, m1, m2])}
    betas = {target: qr(frame[target].to_numpy(), design)[0] for target, design in matrices.items()}
    boot = {target: [] for target in matrices}
    draw_rng = np.random.Generator(np.random.PCG64(SEED))
    for _ in range(DRAWS):
        indices = draw_rng.integers(0, len(x), len(x))
        for target, design in matrices.items():
            boot[target].append(qr(frame[target].to_numpy()[indices], design[indices])[0])
    boot = {target: np.asarray(values) for target, values in boot.items()}
    by_route = {("p_X_M1", "p_M1_Y"): (betas["M1"][1]*betas["Y"][2], boot["M1"][:, 1]*boot["Y"][:, 2]),
                ("p_X_M2", "p_M2_Y"): (betas["M2"][1]*betas["Y"][3], boot["M2"][:, 1]*boot["Y"][:, 3])}
    rows = {row["id"]: row for row in output["effects"]}
    contrast = next(row for row in output["effect_contrasts"] if row["kind"] == "specific_indirect_route_difference")
    a = by_route[tuple(rows[contrast["effect_a"]]["path_ids"])]
    b = by_route[tuple(rows[contrast["effect_b"]]["path_ids"])]
    interval(contrast, a[0]-b[0], a[1]-b[1])


def test_quadratic_moderated_mediation_is_conditional_derivative():
    rng = np.random.Generator(np.random.PCG64(24))
    x, w = rng.normal(size=(2, 180))
    m = .5*x + .2*w + .3*x*w + rng.normal(size=180)
    y = .1*x + .6*m + .2*w + .25*m*w + rng.normal(size=180)
    frame = pd.DataFrame(dict(X=x, W=w, M=m, Y=y))
    spec = graph({"X": "independent", "W": "moderator", "M": "mediator", "Y": "dependent"},
                 [("X", "M"), ("W", "M"), ("M", "Y"), ("W", "Y"), ("X", "Y")],
                 [("X", "M", ["W"]), ("M", "Y", ["W"])])
    output = run(frame, spec, settings({"W": [-.5, .8]}))
    a = qr(m, np.column_stack([np.ones(len(x)), x, w, x*w]))[0]
    b = qr(y, np.column_stack([np.ones(len(x)), x, m, w, m*w]))[0]
    assert output["indices"]
    for row in output["indices"]:
        assert row["kind"] == "conditional_derivative"
        value = row["condition"]["W"]
        expected = a[3]*b[2] + a[1]*b[4] + 2*a[3]*b[4]*value
        assert row["estimate"] == pytest.approx(expected, abs=1e-10)


def test_invalid_cycle_and_missing_category_declaration_are_rejected():
    frame, spec, request = serial_fixture()
    spec["edges"].append({"id": "cycle", "source": "M2", "target": "M1"})
    with pytest.raises(LabError, match="INVALID_MODEL"):
        run(frame, spec, request)
    frame, spec, request = serial_fixture(categorical=True)
    request["categorical"] = []
    with pytest.raises(LabError, match="INVALID_OPTIONS"):
        run(frame, spec, request)


def test_joint_three_way_moderation_includes_all_lower_order_terms():
    rng = np.random.Generator(np.random.PCG64(553))
    x, w, z = rng.normal(size=(3, 210))
    design = np.column_stack([np.ones(len(x)), x, w, z, x*w, x*z, w*z, x*w*z])
    y = design @ np.array([.1, .5, .2, -.1, .3, .25, -.2, .15]) + rng.normal(size=len(x))
    frame = pd.DataFrame(dict(X=x, W=w, Z=z, Y=y))
    spec = graph({"X": "independent", "W": "moderator", "Z": "moderator", "Y": "dependent"},
                 [("X", "Y"), ("W", "Y"), ("Z", "Y")],
                 [("X", "Y", ["W"]), ("X", "Y", ["Z"]),
                  ("W", "Y", ["Z"]), ("X", "Y", ["W", "Z"])])
    output = run(frame, spec, settings({"W": [-.5, .6], "Z": [-.4, .8]}))
    beta, covariance = qr(y, design, robust=True)
    check_equation(output["equations"][0], beta, covariance,
                   [(), ("X",), ("W",), ("Z",), ("W", "X"),
                    ("X", "Z"), ("W", "Z"), ("W", "X", "Z")])
    direct = [row for row in output["effects"] if row["kind"] == "direct"]
    assert len(direct) == 4
    for row in direct:
        w_value, z_value = row["condition"]["W"], row["condition"]["Z"]
        expected = beta[1] + beta[4]*w_value + beta[5]*z_value + beta[7]*w_value*z_value
        assert row["estimate"] == pytest.approx(expected, abs=1e-10)
    incomplete = deepcopy(spec)
    incomplete["moderations"] = incomplete["moderations"][1:]
    with pytest.raises(LabError, match="INVALID_MODEL"):
        run(frame, incomplete, settings({"W": [-.5, .6], "Z": [-.4, .8]}))


def test_vendor_hash_and_only_exception_import_adapted():
    provenance = json.loads((EXTENSION / "source-provenance.json").read_text(encoding="utf-8"))
    vendored = (EXTENSION / provenance["vendored_path"]).read_bytes()
    assert hashlib.sha256(vendored).hexdigest() == provenance["vendored_sha256"]
    restored = vendored.replace(b"from .errors import LabError", b"from engine import LabError")
    assert hashlib.sha256(restored).hexdigest() == provenance["source_sha256"]
    assert b"from engine import LabError" not in vendored
