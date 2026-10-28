"""Prepare a GUI-only synthetic diagram check, or collect its saved results.

No external SpssClient connection is used while SPSS executes the extension.
Run the prepared developer file with SPSS Run > All. Researchers use the menu.
"""
from pathlib import Path
import argparse
import hashlib
import io
import json
import re
import tempfile
import uuid
import zipfile
from check_runtime import synthetic_syntax


def q(path):
    return str(Path(path).resolve()).replace("\\", "/").replace("'", "''")


def png_fingerprint(data):
    # SPSS re-encodes imported PNGs; compare decoded pixels, not file bytes.
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        return image.size, hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--dependency-path", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--original-dataset")
    parser.add_argument("--detail", choices=("STANDARD", "FULL"), default="STANDARD")
    parser.add_argument("--plots", choices=("BOTH", "INTERACTION", "JN", "NONE"), default="BOTH")
    parser.add_argument("--clean-instance", action="store_true",
                        help="Use only a separate empty SPSS instance; leave its own named synthetic dataset open")
    parser.add_argument("--installed", action="store_true",
                        help="Test the installed command after restarting SPSS; do not change its import path or register XML")
    parser.add_argument("--collect", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.collect:
        if not args.output:
            parser.error("Collection needs --output.")
        context = json.loads(args.collect.read_text(encoding="utf-8"))
        marker = json.loads(Path(context["marker"]).read_text(encoding="utf-8"))
        if not Path(context["result"]).is_file():
            raise RuntimeError("PATHLAB did not export its result JSON. Inspect the test's saved SPSS Viewer output for the actual command error; an older installed PATHLAB command can override a temporary XML registration. Install the matching SPE bundle and restart SPSS before repeating an installed-command check.")
        assert marker["completed"] and (marker.get("isolated_clean_instance") or marker.get("original_active_restored"))
        result = json.loads(Path(context["result"]).read_text(encoding="utf-8"))
        if context.get("bundle_version") and result.get("version") != context["bundle_version"]:
            raise RuntimeError("The executed PATHLAB version (%s) differs from the requested bundle (%s). Install that SPE and restart SPSS; an older registered command may be shadowing it." %
                               (result.get("version"), context["bundle_version"]))
        assert result["process"]["sample"]["n"] == 71 and result["process"]["bootstrap"]["successful"] == 200
        charts = result["presentation"]["charts"]
        assert result["presentation"].get("viewer_notices", []) == []
        if context["plots"] == "BOTH":
            assert {chart["kind"] for chart in charts} == {"interaction", "johnson_neyman"}
        with zipfile.ZipFile(context["spv"]) as archive:
            image_data = [data for name in archive.namelist()
                          if (data := archive.read(name)).startswith(bytes.fromhex("89504e470d0a1a0a"))]
        embedded = [png_fingerprint(data) for data in image_data]
        matches = []
        for chart in charts:
            dimensions, pixels = png_fingerprint(Path(chart["path"]).read_bytes())
            assert (dimensions, pixels) in embedded, "The saved Viewer does not contain the rendered chart: %s" % chart["title"]
            matches.append({"title": chart["title"], "dimensions": dimensions, "rgba_sha256": pixels})
        pngs = len(image_data)
        summary = {"status": "passed", "dispatch": ("installed native command, " if context.get("installed_command") else "") + "GUI Run > All; no external RunSyntax client", "data": "synthetic only",
                   "version": result["version"], "runtime": result["runtime"], "sample": result["process"]["sample"], "bootstrap": result["process"]["bootstrap"],
                   "chart_count": len(charts), "chart_titles": [chart["title"] for chart in charts], "embedded_pngs": pngs,
                   "embedded_chart_pixel_matches": matches,
                   "effect_rows": len(result["process"]["effects"]), "index_rows": len(result["process"]["indices"]),
                   "johnson_neyman_boundaries": [chart.get("boundaries") for chart in charts if chart["kind"] == "johnson_neyman"],
                   "viewer_notices": [], "output_detail": result["presentation"]["detail"],
                   "original_active_dataset_restored": marker.get("original_active_restored"),
                   "isolated_clean_instance": bool(marker.get("isolated_clean_instance")), "requested_bundle_sha256": context["bundle_sha256"]}
        args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2))
        return 0
    if not all((args.bundle, args.destination, args.original_dataset)) or (not args.installed and not args.dependency_path):
        parser.error("Preparation needs --bundle, --destination and --original-dataset, plus --dependency-path unless --installed is used.")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", args.original_dataset):
        raise ValueError("Use the existing active SPSS dataset's valid name.")
    args.destination.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="pathlab-gui-", dir=str(args.destination.resolve())))
    digest = hashlib.sha256(args.bundle.read_bytes()).hexdigest()
    with zipfile.ZipFile(args.bundle) as archive:
        manifest = archive.read("META-INF/MANIFEST.MF").decode("utf-8")
        version = re.search(r"(?m)^Version:\s*([^\r\n]+)", manifest).group(1).strip()
    extension = folder / ("native-" + digest[:12])
    if not args.installed:
        (extension / "PATHLAB").mkdir(parents=True)
        with zipfile.ZipFile(args.bundle) as archive:
            for name in ("PATHLAB.py", "PATHLAB.xml"):
                (extension / name).write_bytes(archive.read(name))
            (extension / "PATHLAB/pathlab_spss.zip").write_bytes(archive.read("pathlab_spss.zip"))
    source, result, marker, spv = [folder / name for name in ("PathLab-diagram-check-%s.sps" % digest[:12], "result.json", "completed.json", "synthetic-output.spv")]
    token = uuid.uuid4().hex[:12]
    scratch, output, protected_original = "PathLabTest" + token, "PathLabOutput" + token, "PathLabOriginal" + token
    syntax = ["OUTPUT NEW NAME=%s." % output, "BEGIN PROGRAM Python3.", "import spss",
              "pathlab_original_name=spss.ActiveDataset()", "pathlab_original_count=spss.GetVariableCount()",
              "pathlab_original_unnamed=pathlab_original_name in (None, '', '*')",
              "if pathlab_original_unnamed:", "    spss.Submit('DATASET NAME %s.')" % protected_original,
              "pathlab_original_name=spss.ActiveDataset()", "END PROGRAM."] + synthetic_syntax()
    # DATA LIST opens a new working file while preserving a named original.
    # Name the populated synthetic file; activating an empty declaration fails.
    syntax += ["DATASET NAME %s." % scratch]
    bootstrap = ["BEGIN PROGRAM Python3.", "import os,sys", "for key in list(sys.modules):",
               "    if key == 'PATHLAB' or key == 'pathlab_spss' or key.startswith('pathlab_spss.'):", "        del sys.modules[key]",
               "sys.path.insert(0,%r)" % str(extension), "sys.path.insert(0,%r)" % str(args.dependency_path.resolve() if args.dependency_path else ""),
               "os.environ['SPSS_EXTENSIONS_RAISE']='true'", "END PROGRAM.",
               "EXTENSION /SPECIFICATION COMMAND='%s'." % q(extension / "PATHLAB.xml")]
    if not args.installed:
        syntax += bootstrap
    syntax += ["PATHLAB X=x Y=y MEDIATORS=m W=w",
               "/MODEL STRUCTURE=PARALLEL FAMILY=LINEAR REFERENCE=FIRST ANALYSIS=CONDITIONAL",
               "/MODERATION FIRST=W SECOND=NONE SERIAL=NONE DIRECT=NONE", "/OPTIONS BOOTSTRAP=200 CONFIDENCE=95 SEED=2738 ROBUST=HC3",
               "/PLOTS TYPE=%s DIRECTORY='%s'" % (args.plots, q(folder)), "/OUTPUT DETAIL=%s JSON='%s'." % (args.detail, q(result))]
    if not args.clean_instance:
        syntax += ["BEGIN PROGRAM Python3.", "spss.Submit('DATASET ACTIVATE %s.' % pathlab_original_name)",
                   "END PROGRAM.", "DATASET CLOSE %s." % scratch]
    syntax += ["OUTPUT SAVE NAME=%s OUTFILE='%s'." % (output, q(spv)), "BEGIN PROGRAM Python3.", "import json,os,spss",
               "pathlab_restored=(spss.ActiveDataset()==pathlab_original_name and spss.GetVariableCount()==pathlab_original_count)",
               "with open(%r,'w',encoding='utf-8') as stream:" % str(marker)]
    if args.clean_instance:
        syntax += ["    json.dump({'completed':os.path.isfile(%r),'isolated_clean_instance':pathlab_original_count==0,'variables':spss.GetVariableCount()},stream)" % str(result)]
    else:
        syntax += ["    json.dump({'completed':os.path.isfile(%r),'original_active_restored':pathlab_restored,'original_initially_unnamed':pathlab_original_unnamed},stream)" % str(result)]
    syntax += ["END PROGRAM."]
    source.write_text("\n".join(syntax) + "\n", encoding="utf-8")
    context = {"source": str(source), "result": str(result), "marker": str(marker), "spv": str(spv), "plots": args.plots,
               "isolated_clean_instance": args.clean_instance, "installed_command": args.installed,
               "bundle_version": version, "bundle_sha256": digest}
    context_path = folder / "context.json"
    context_path.write_text(json.dumps(context, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"next_step": "Open source in SPSS and choose Run > All, then use --collect with context.", "source": str(source), "context": str(context_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
