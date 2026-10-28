"""Translate explicit dialog selections into the versioned graph contract."""
from __future__ import annotations

from itertools import combinations


class DialogError(ValueError):
    """An actionable input error suitable for the SPSS Viewer."""


def names(value):
    if value is None:
        return []
    if isinstance(value, str):
        return value.split()
    try:
        result = list(value)
    except TypeError as error:
        raise DialogError("Select SPSS variable names from the variable list.") from error
    if any(not isinstance(name, str) or not name.strip() for name in result):
        raise DialogError("Every selected variable must have a valid SPSS name.")
    return result


def build_model(x, y, mediators=(), structure="PARALLEL", w=None, z=None, q=None,
                covariates=(), moderate_first="NONE", moderate_second="NONE",
                moderate_serial="NONE", moderate_direct="NONE", family="LINEAR",
                categorical=(), reference="FIRST"):
    """Use safe role IDs, preserving actual SPSS variable names as column mappings.

    Serial: X -> M1 -> ... -> Mk -> Y, plus X -> Y.
    Combined: all forward mediator links plus X -> every M and every M -> Y.
    Covariates enter every mediator/outcome equation. Stage selections apply to
    every arrow at that stage; the dialog labels describe this explicitly.
    """
    x, y = names(x), names(y)
    if len(x) != 1 or len(y) != 1:
        raise DialogError("Select exactly one predictor X and one outcome Y.")
    mediators, covariates, categorical = names(mediators), names(covariates), names(categorical)
    if len(mediators) > 10 or len(covariates) > 20:
        raise DialogError("Select at most 10 mediators and 20 covariates.")
    structure, family, reference = structure.upper(), family.upper(), reference.upper()
    if structure not in ("PARALLEL", "SERIAL", "COMBINED"):
        raise DialogError("Choose parallel, serial, or combined mediation.")
    # Every nonempty forward subsequence is an indirect route, plus X -> Y.
    # The computation contract caps the total at 100 routes.
    if structure == "COMBINED" and len(mediators) > 6:
        raise DialogError("Combined mediation supports at most 6 mediators (100-route computation limit).")
    if family not in ("LINEAR", "LOGISTIC") or reference not in ("FIRST", "LAST"):
        raise DialogError("Choose a valid outcome family and categorical reference rule.")
    roles = [("X", x[0], "independent"), ("Y", y[0], "dependent")]
    mids = ["M%d" % (i + 1) for i in range(len(mediators))]
    roles += [(i, column, "mediator") for i, column in zip(mids, mediators)]
    for node_id, selected in (("W", w), ("Z", z), ("Q", q)):
        selected = names(selected)
        if len(selected) > 1:
            raise DialogError("Each moderator box accepts exactly one variable.")
        if selected:
            roles.append((node_id, selected[0], "moderator"))
    roles += [("C%d" % (i + 1), column, "covariate") for i, column in enumerate(covariates)]
    columns = [row[1] for row in roles]
    if any(not isinstance(column, str) or not column for column in columns):
        raise DialogError("Every selected variable must have a valid SPSS name.")
    if len(set(column.casefold() for column in columns)) != len(columns):
        raise DialogError("Use different variables for X, Y, mediators, moderators, and covariates.")
    by_column = {column.casefold(): node_id for node_id, column, _ in roles}
    categorical_ids = {by_column.get(column.casefold()) for column in categorical}
    if None in categorical_ids or len(categorical_ids) != len(categorical):
        raise DialogError("Categorical variables must be unique selected model variables.")
    allowed_categorical = {i for i, _, role in roles if role in ("independent", "moderator", "covariate")}
    if not categorical_ids <= allowed_categorical:
        raise DialogError("Only X, moderators, and covariates can use categorical indicator coding.")
    pairs = {("X", "Y")}
    stages = {"first": [], "second": [], "serial": [], "direct": [("X", "Y")]}
    if mids:
        stages["first"] = [("X", i) for i in (mids if structure != "SERIAL" else mids[:1])]
        stages["second"] = [(i, "Y") for i in (mids if structure != "SERIAL" else mids[-1:])]
        stages["serial"] = list(zip(mids, mids[1:])) if structure == "SERIAL" else list(combinations(mids, 2)) if structure == "COMBINED" else []
        pairs.update(pair for stage in ("first", "second", "serial") for pair in stages[stage])
    for node_id, _, role in roles:
        if role == "covariate":
            pairs.update((node_id, target) for target in [*mids, "Y"])
    mods, interaction_keys = [], set()
    available = {i for i, _, role in roles if role == "moderator"}

    def attach(source, target, moderators):
        signature = (target, tuple(sorted([source, *moderators])))
        if signature in interaction_keys:
            return
        interaction_keys.add(signature)
        pairs.add((source, target))
        pairs.update((moderator, target) for moderator in moderators)
        mods.append({"id": "mod%d" % (len(mods) + 1), "path_id": "p_%s_%s" % (source, target), "moderator_ids": list(moderators)})

    for stage, choice in (("first", moderate_first), ("second", moderate_second),
                          ("serial", moderate_serial), ("direct", moderate_direct)):
        choice = (choice or "NONE").upper()
        if choice == "NONE":
            continue
        if choice not in ("W", "Z", "Q", "WZ", "WQ", "ZQ"):
            raise DialogError("Select a listed moderator or joint moderator pair.")
        selected = list(choice)
        if not set(selected) <= available:
            raise DialogError("A stage uses a moderator whose variable box is empty.")
        if not stages[stage]:
            raise DialogError("The selected model has no %s-stage arrows to moderate." % stage)
        for source, target in stages[stage]:
            for moderator in selected:
                attach(source, target, [moderator])
            if len(selected) == 2:
                attach(selected[0], target, [selected[1]])
                attach(source, target, selected)
    used = {i for mod in mods for i in mod["moderator_ids"]}
    if available != used:
        raise DialogError("Assign every selected moderator to at least one moderation stage.")
    if not mediators and not mods:
        raise DialogError("Select a mediator or moderate the direct X-to-Y path.")
    nodes = [{"id": i, "column": column, "role": role,
              "measurement_scale": "nominal" if i in categorical_ids or (i == "Y" and family == "LOGISTIC") else "interval"}
             for i, column, role in roles]
    settings = {"schema_version": 3, "outcome_family": family.lower(), "categorical": [], "probes": [],
                "automatic_probes": {"probabilities": [.16, .84] if len(available) == 3 else [.16, .5, .84],
                                     "quantile_method": "linear", "sample": "fixed_complete_case_sample",
                                     "resolve_before_bootstrap": True}, "bootstrap_interval_quantile_method": "linear"}
    return {"schema_version": 1, "graph": {"schema_version": 1, "nodes": nodes,
            "edges": [{"id": "p_%s_%s" % pair, "source": pair[0], "target": pair[1]} for pair in sorted(pairs)],
            "moderations": mods}, "settings": settings,
            "dialog": {"structure": structure, "categorical_ids": sorted(categorical_ids), "reference": reference}}


def check_options(bootstrap=5000, confidence=95, seed=20261028, robust="HC3"):
    if isinstance(bootstrap, bool) or not isinstance(bootstrap, int) or not 200 <= bootstrap <= 50000:
        raise DialogError("Bootstrap samples must be an integer from 200 to 50,000.")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 50 <= confidence <= 99.9:
        raise DialogError("Confidence level must be between 50 and 99.9 percent.")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2147483647:
        raise DialogError("Random seed must be an integer from 0 to 2,147,483,647.")
    if isinstance(robust, bool):
        robust = "HC3" if robust else "CLASSICAL"
    if str(robust).upper() not in ("HC3", "CLASSICAL"):
        raise DialogError("Choose HC3 or classical standard errors.")
    return {"bootstrap": bootstrap, "alpha": 1 - confidence / 100, "robust": str(robust).upper() == "HC3"}, seed


def validate_analysis(analysis, model):
    """An explicit guided task must agree with the selected variable roles."""
    choice = str(analysis or "AUTO").upper()
    roles = [node["role"] for node in model["graph"]["nodes"]]
    has_mediators, has_moderators = "mediator" in roles, "moderator" in roles
    actual = "CONDITIONAL" if has_mediators and has_moderators else "MEDIATION" if has_mediators else "MODERATION"
    if choice not in ("AUTO", "MEDIATION", "MODERATION", "CONDITIONAL"):
        raise DialogError("Choose Mediation, Moderation, Conditional process, or Automatic.")
    if choice != "AUTO" and choice != actual:
        instructions = {"MEDIATION": "For Mediation, select at least one mediator and leave moderator boxes empty.",
                        "MODERATION": "For Moderation, leave mediators empty, choose a moderator, and assign it to the direct X-to-Y path under Moderation.",
                        "CONDITIONAL": "For Conditional process, select at least one mediator and one moderator, then choose the moderated stages."}
        raise DialogError(instructions[choice])
    return actual
