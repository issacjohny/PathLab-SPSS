"""Read-only runtime preflight, with an opt-in isolated synthetic engine test.

Run with SPSS's Python executable. --smoke-engine refuses an already running
backend so it cannot replace a dataset in a live GUI session.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import random
import sys
import tempfile


def preflight(inspect_only=False):
    result = {"python": platform.python_version(), "executable": sys.executable,
              "libraries": {}, "ready": True}
    for name in ("spss", "spssdata", "extension", "numpy", "pandas", "scipy", "statsmodels", "matplotlib"):
        try:
            # Some IBM utility imports start the backend while checking its
            # version. A preflight must not start SPSS or open a dataset.
            if name in ("spssdata", "extension") or (inspect_only and name != "spss"):
                if importlib.util.find_spec(name) is None:
                    raise ImportError("Module not installed: " + name)
                result["libraries"][name] = "available"
                continue
            module = importlib.import_module(name)
            result["libraries"][name] = getattr(module, "__version__", "available")
        except Exception as error:
            result["libraries"][name] = {"error": type(error).__name__, "message": str(error)}
            result["ready"] = False
    return result


def synthetic_syntax():
    rng = random.Random(2738)
    rows = []
    for i in range(90):
        x, w = rng.gauss(0, 1), rng.gauss(0, 1)
        m = .6*x + .2*w + .3*x*w + rng.gauss(0, 1)
        y = .2*x + .7*m + rng.gauss(0, 1)
        rows.append([x, m, y, w, int(i % 5 != 0)])
    # Isolated synthetic data only; missing sentinel tests user-missing conversion.
    rows[1][1] = -999
    syntax = ["DATA LIST FREE /x m y w selected.", "BEGIN DATA"]
    syntax += [" ".join(format(v, ".17g") for v in row) for row in rows]
    syntax += ["END DATA.", "VARIABLE LEVEL x m y w (SCALE).",
               "VARIABLE LABELS selected 'Sample inclusion flag'.",
               "MISSING VALUES m (-999).", "FILTER BY selected."]
    return syntax


def smoke_engine(extension_path=None):
    import spss
    if spss.IsBackendReady():
        raise RuntimeError("Use a fresh external SPSS Python process; an existing backend is never replaced.")
    # Disable only the external console echo, while still constructing native
    # Viewer output. Older Windows consoles cannot encode all variable labels.
    spss.SetOutput("off")
    spss.Submit(synthetic_syntax())
    try:
        original_tvars = spss.GetSetting("TVARS")
        if extension_path:
            extension_path = Path(extension_path).resolve()
            spec = str(extension_path / "PATHLAB.xml").replace("\\", "/").replace("'", "''")
            spss.Submit("EXTENSION /SPECIFICATION COMMAND='%s'." % spec)
            with tempfile.TemporaryDirectory(prefix="pathlab-command-", dir=str(extension_path)) as folder:
                saved = Path(folder) / "result.json"
                target = str(saved).replace("\\", "/").replace("'", "''")
                spss.Submit("PATHLAB X=x Y=y MEDIATORS=m W=w "
                            "/MODEL STRUCTURE=PARALLEL FAMILY=LINEAR REFERENCE=FIRST "
                            "/MODERATION FIRST=W SECOND=NONE SERIAL=NONE DIRECT=NONE "
                            "/OPTIONS BOOTSTRAP=200 CONFIDENCE=95 SEED=2738 ROBUST=HC3 "
                            "/OUTPUT JSON='%s'." % target)
                if not saved.is_file():
                    raise AssertionError("The native PATHLAB command did not save a completed result.")
                result = json.loads(saved.read_text(encoding="utf-8"))
            metadata = result["source"]
        else:
            from pathlab_spss.adapter import analyze, read_active_frame
            from pathlab_spss.models import build_model
            model = build_model("x", "y", ["m"], w="w", moderate_first="W")
            frame, metadata = read_active_frame(model["graph"])
            assert len(frame) == 72, "SPSS active filter did not select exactly 72 cases"
            assert frame["m"].isna().sum() == 1, "SPSS user missing value was not converted"
            result = analyze(model, bootstrap=200, confidence=95, seed=2738,
                             plots="NONE", output_detail="FULL")
        assert spss.GetSetting("TVARS").lower() == original_tvars.lower(), "Output preference was changed"
        assert result["process"]["sample"]["n"] == 71
        assert result["process"]["bootstrap"]["successful"] == 200
        assert result["process"]["indices"], "Moderated mediation index missing"
        assert all(math.isfinite(row["estimate"]) for row in result["process"]["effects"])
        runtime_location = sys.modules["pathlab_spss"].__file__
        if extension_path:
            assert ".zip" in runtime_location.lower(), "Native command bypassed packaged zip runtime"
        return {"status": "passed", "dispatch": "native_command" if extension_path else "direct_adapter",
                "runtime_location": runtime_location, "source": metadata,
                "sample": result["process"]["sample"],
                "bootstrap": result["process"]["bootstrap"],
                "effect_rows": len(result["process"]["effects"]),
                "index_rows": len(result["process"]["indices"]),
                "output_detail": result.get("presentation", {}).get("detail"),
                "runtime": result["runtime"]}
    finally:
        spss.StopSPSS()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dependency-path", type=Path)
    parser.add_argument("--smoke-engine", action="store_true")
    parser.add_argument("--extension-path", type=Path,
                        help="Test registered command and zip runtime in an extracted bundle layout")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.extension_path.resolve() if args.extension_path else Path(__file__).resolve().parents[1]))
    if args.dependency_path:
        sys.path.insert(0, str(args.dependency_path.resolve()))
    # Native callbacks initialize a separate embedded Python context. NumPy
    # must first load there, rather than in this external driver interpreter.
    result = preflight(inspect_only=bool(args.extension_path))
    if args.smoke_engine and result["ready"]:
        result["engine_smoke"] = smoke_engine(args.extension_path)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
