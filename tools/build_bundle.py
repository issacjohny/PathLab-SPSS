"""Build a genuine SPSS .spe and native compatible .spd custom dialog.

Formats verified against IBM's STATS_PROPOR_REGR bundle and SPSS 27's own
ExtensionBundleInstaller. Pure Python runtime uses normal zipimport.
"""
from io import BytesIO
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def package_metadata(filename):
    """Read lightweight package metadata without importing numerical libraries."""
    spec = importlib.util.spec_from_file_location("pathlab_build_" + filename.stem, filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BRANDING = package_metadata(ROOT / "pathlab_spss" / "branding.py")
AUTHOR = BRANDING.AUTHOR
VERSION = package_metadata(ROOT / "pathlab_spss" / "__init__.py").__version__
SUPPORT_FILES = ("README.md", "requirements.txt", "AUTHORS.txt", "CITATION.txt",
                 "LICENSE", "THIRD-PARTY-NOTICES.txt", "MAINTAINER.txt")
NS = "http://spss.com/clementine/extensions"
ET.register_namespace("", NS)


def element(parent, tag, **attributes):
    return ET.SubElement(parent, "{" + NS + "}" + tag,
                         {key: str(value) for key, value in attributes.items()})


def layout(control, row, column=0, fill="horizontal", weight="0.0"):
    element(control, "Layout", columnWeight="1.0", fill=fill, gridColumn=column,
            gridRow=row, gridWidth="1", rowWeight=weight)


def native_dialog():
    root = ET.Element("{" + NS + "}Extension", {"debug": "false", "version": "1.0"})
    element(root, "ExtensionDetails", id="PATHLAB_DIALOG", label="PathLab",
            description="Advanced mediation, moderation and conditional process analysis",
            provider=AUTHOR, providerTag="pathlab", version=VERSION, copyright="2026 " + AUTHOR)
    element(element(root, "Resources"), "Bundle", id="bundle1", path="PATHLAB_DIALOG", type="properties")
    element(element(element(root, "CommonObjects"), "Actions"), "Action",
            id="PATHLAB_DIALOG_action", label="PathLab: Mediation and Moderation...")
    element(element(element(root, "UserInterface"), "Controls"), "MenuItem",
            action="PATHLAB_DIALOG_action", offset="0", showIcon="false", spssMenu="Analyze")
    node = element(root, "Node", id="PATHLAB_DIALOG",
                   label="PathLab: Mediation and Moderation — " + AUTHOR, type="modelBuilder")
    props = element(node, "Properties")
    syntax = ("PATHLAB %%x%% %%y%% %%mediators%% %%covariates%% %%w%% %%z%% %%q%%\n"
              "/MODEL %%analysis%% %%structure%% %%family%% %%categorical%% %%reference%%\n"
              "/MODERATION %%first%% %%second%% %%serial%% %%direct%%\n"
              "/OPTIONS %%bootstrap%% %%confidence%% %%seed%% %%robust%%\n"
              "/PLOTS %%plots%% %%plot_directory%%\n"
              "/OUTPUT %%output_detail%% %%output_json%%.\n")
    element(props, "Property", name="PATHLAB_DIALOG", syntax=syntax)
    element(props, "Property", name="PATHLAB_DIALOG_modal", description="false")
    element(props, "Property", name="source_vars", isList="true", label="Variables:",
            selectionPool="source_fields", syntax="%%ThisValue%%", valueType="field")
    field_labels = {"x": "Predictor (X):", "y": "Outcome (Y):", "mediators": "Mediators (ordered for serial models):",
                    "covariates": "Covariates (optional):", "w": "Moderator W:", "z": "Moderator Z:",
                    "q": "Moderator Q:", "categorical": "Categorical variables (optional):"}
    for key, label in field_labels.items():
        attrs = dict(name=key, isList="true", label=label, selectionPool="source_fields",
                     syntax=key.upper() + "=%%ThisValue%%", valueType="field")
        if key in ("x", "y"):
            attrs["isRequired"] = "true"
        element(props, "Property", **attrs)

    def enum(key, label, choices, default, keyword=None):
        prop = element(props, "Property", name=key, label=label, defaultValue=default,
                       syntax=(keyword or key.upper()) + "=%%ThisValue%%", valueType="enum")
        options = element(prop, "Enumeration")
        for value, caption in choices:
            element(options, "Enum", value=value, label=caption, syntax=value.upper())

    enum("analysis", "Analysis goal:", [("auto", "Choose automatically from selected variables"),
                                        ("mediation", "Mediation"), ("moderation", "Moderation"),
                                        ("conditional", "Conditional process: mediation + moderation")], "auto")
    enum("structure", "Mediation structure:", [("parallel", "Parallel: separate mediator pathways"),
                                               ("serial", "Serial: mediators in listed order"),
                                               ("combined", "Combined: all forward mediator paths")], "parallel")
    enum("family", "Outcome equation:", [("linear", "Continuous: linear regression"),
                                         ("logistic", "Binary 0/1: logistic regression")], "linear")
    enum("reference", "Categorical reference group:", [("first", "Lowest observed value / first alphabetical"),
                                                       ("last", "Highest observed value / last alphabetical")], "first")
    enum("robust", "Coefficient covariance:", [("hc3", "HC3 robust"), ("classical", "Classical")], "hc3")
    enum("plots", "Diagrams to show:", [("both", "Show both diagrams (recommended)"),
                                        ("interaction", "Interaction diagrams only"),
                                        ("jn", "Johnson–Neyman diagrams only"), ("none", "Tables only")], "both", keyword="TYPE")
    enum("output_detail", "Results to show:", [("standard", "Standard: summary, effects and diagrams"),
                                               ("full", "Full: add detailed contrasts and diagnostics")], "standard", keyword="DETAIL")
    for key, label in (("first", "First stage: X to each mediator:"),
                       ("second", "Final stage: each mediator to Y:"),
                       ("serial", "Serial stage: mediator to mediator:"),
                       ("direct", "Direct path: X to Y:")):
        enum(key, label, [("none", "None"), ("w", "W"), ("z", "Z"), ("q", "Q"),
                          ("wz", "Joint W and Z"), ("wq", "Joint W and Q"), ("zq", "Joint Z and Q")], "none")
    for key, label, default, low, high, kind in (
        ("bootstrap", "Bootstrap samples:", 5000, 200, 50000, "integer"),
        ("confidence", "Confidence level (%):", 95, 80, 99.9, "double"),
        ("seed", "Random seed:", 20261028, 0, 2147483647, "integer")):
        element(props, "Property", name=key, label=label, defaultValue=default,
                min=low, max=high, syntax=key.upper()+"=%%ThisValue%%", valueType=kind)
    element(props, "Property", name="output_json", label="Optional complete results file (.json):",
            syntax="JSON=%%ThisValue%%", valueType="string")
    element(props, "Property", name="plot_directory", label="Optional folder for PNG diagrams:",
            syntax="DIRECTORY=%%ThisValue%%", valueType="string")
    element(node, "SelectionPool", id="source_fields", type="fields")
    panel = element(element(element(element(node, "UserInterface"), "Tabs"), "Tab", helpLink="PATHLAB_DIALOG.htm"), "PropertiesPanel")
    def subpanel(label, title, row):
        control = element(panel, "PropertiesSubPanel", buttonLabel=label, dialogTitle=title,
                          helpLink="PATHLAB_DIALOG.htm")
        layout(control, row, 3, fill="none")
        return element(control, "PropertiesPanel")

    def combo(parent, key, row, column=0):
        control = element(parent, "ComboBoxControl", property=key, attr_name="", based_on="variable_names",
                          target_id="", use_values="false")
        layout(control, row, column)

    def source(parent, property_name, row, span=1):
        # The classic SPSS runtime populates the main source-variable property.
        # Subdialog browsers bind that same populated list instead of declaring
        # new empty source properties that have no active-dataset initializer.
        browser = element(parent, "SourceFieldsBrowser", property="source_vars", copyFields="true",
                          selectionPool="source_fields", storage="[real integer string]")
        layout(browser, row, fill="both", weight="1.0")
        browser.find("{" + NS + "}Layout").set("gridHeight", str(span))
        return browser

    def field(parent, key, row, column=2):
        multi = key in ("mediators", "covariates", "categorical")
        storage = "[real integer]" if key in ("y", "mediators") else "[real integer string]"
        control = element(parent, "MultiFieldChooserControl" if multi else "SingleFieldChooserControl",
                          property=key, storage=storage)
        layout(control, row, column, fill="both" if multi else "horizontal", weight="1.0" if multi else "0.0")
        return control

    source(panel, "source_vars", 0, 9)
    # Classic SPSS supplies the active dictionary only to the main source list.
    # All targets remain in the verified column-2 transfer area.
    combo(panel, "analysis", 0, 2)
    field(panel, "x", 1)
    field(panel, "y", 2)
    field(panel, "mediators", 3)
    for row, key in enumerate(("w", "z", "q"), start=4):
        field(panel, key, row)
    field(panel, "covariates", 7)
    field(panel, "categorical", 8)
    model = subpanel("Model...", "PathLab: Model and Reference Coding", 0)
    combo(model, "structure", 0)
    combo(model, "family", 1)
    combo(model, "reference", 2)
    note = element(model, "StaticText", text="Every model includes the direct X to Y path.\nSerial uses mediator order from the main dialog.\nSelect categorical X, moderators or covariates in the main dialog.\nCovariates enter every mediator and outcome equation.\nFor binary outcomes, use 0/1 coding; mediators remain quantitative.")
    layout(note, 3)
    moderation = subpanel("Moderators...", "PathLab: Choose Moderated Paths", 1)
    for row, key in enumerate(("first", "second", "serial", "direct")):
        combo(moderation, key, row)
    note = element(moderation, "StaticText", text="Choose moderator variables W, Z or Q in the main dialog first.\nFor moderation without mediators: assign W and set Direct path to W.\nFor moderated mediation: assign W to the first or final stage.\nJoint pairs include all required lower-order interactions.")
    layout(note, 4)
    plots = subpanel("Diagrams...", "PathLab: Interaction and Johnson–Neyman Diagrams", 2)
    combo(plots, "plots", 0)
    layout(element(plots, "ServerDirectoryChooserControl", property="plot_directory", mode="save"), 1)
    note = element(plots, "StaticText", text="Diagrams appear in the SPSS Viewer; an export folder is optional.\nInteraction diagrams show fitted outcomes at moderator probe values.\nJohnson–Neyman diagrams show where a conditional path slope differs from zero.\nThey require a continuous moderator and an eligible conditional path.\nOther moderators are held at the conditions shown on each diagram.")
    layout(note, 2)
    options = subpanel("Options...", "PathLab: Inference and Results", 3)
    for row, key in enumerate(("bootstrap", "confidence", "seed")):
        layout(element(options, "TextBoxControl", property=key), row)
    combo(options, "robust", 3)
    combo(options, "output_detail", 4)
    layout(element(options, "ServerFileChooserControl", property="output_json", mode="save"), 5)
    note = element(options, "StaticText", text="Recommended starting settings: 5,000 samples, 95% confidence and HC3.\nStandard results show the summary, effects and requested diagrams first.\nFull results add detailed contrasts and diagnostics.\nAll equations use the same complete-case sample and joint case resamples.")
    layout(note, 6)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def archive(entries):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for name, content in entries.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 28, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, content)
    return buffer.getvalue()


def manifest_line(key, value):
    # Java's Manifest reader limits physical lines to 72 bytes, continuation starts with a space.
    text = key + ": " + value
    lines = []
    while len(text.encode("utf-8")) > 70:
        cut = 70
        while len(text[:cut].encode("utf-8")) > 70:
            cut -= 1
        lines.append(text[:cut])
        text = " " + text[cut:]
    lines.append(text)
    return "\r\n".join(lines)


def build(destination=None):
    destination = Path(destination) if destination else ROOT / "dist"
    destination.mkdir(parents=True, exist_ok=True)
    runtime = {}
    for file in sorted((ROOT / "pathlab_spss").glob("*.py")):
        runtime["pathlab_spss/" + file.name] = file.read_bytes()
    if "pathlab_spss/__init__.py" not in runtime or "pathlab_spss/core.py" not in runtime:
        raise RuntimeError("The complete PathLab runtime must exist before bundling.")
    provenance = ROOT / "source-provenance.json"
    if provenance.is_file():
        runtime["pathlab_spss/source-provenance.json"] = provenance.read_bytes()
    dialog = native_dialog()
    source = ROOT / "dialog"
    source.mkdir(exist_ok=True)
    (source / "PATHLAB_DIALOG.xml").write_bytes(dialog)
    spd = archive({"PATHLAB_DIALOG.xml": dialog,
                   "PATHLAB_DIALOG.properties": b"# PathLab English labels are defined in the XML.\n",
                   "PATHLAB_DIALOG.htm": (source / "PATHLAB_DIALOG.htm").read_bytes()})
    fields = {"Name": "PATHLAB", "Display-Name": "PathLab: Mediation and Moderation",
              "Dialog-Specs": "PATHLAB.spd", "Command-Specs": "PATHLAB.xml", "Code-Files": "PATHLAB.py",
              "Misc-Files": ",".join(("pathlab_spss.zip", *SUPPORT_FILES)),
              "Summary": "Advanced observed-variable mediation and moderation",
              "Description": "Menu-driven parallel, serial and combined mediation with conditional process inference.",
              "Author": AUTHOR, "Version": VERSION, "Product-Version": "27",
              "Date": "10/28/2026", "Categories": "statistics", "Plugins": "Python", "Python-Version": "3"}
    manifest = "\r\n".join(manifest_line(k, v) for k, v in fields.items()) + "\r\n\r\n"
    bundle_entries = {"META-INF/MANIFEST.MF": manifest.encode("utf-8"),
                      "PATHLAB.xml": (ROOT / "PATHLAB.xml").read_bytes(),
                      "PATHLAB.py": (ROOT / "PATHLAB.py").read_bytes(),
                      "PATHLAB.spd": spd, "pathlab_spss.zip": archive(runtime)}
    bundle_entries.update({name: (ROOT / name).read_bytes() for name in SUPPORT_FILES})
    spe = archive(bundle_entries)
    target = destination / ("PathLab-%s.spe" % VERSION)
    target.write_bytes(spe)
    (destination / ("PathLab-%s.spd" % VERSION)).write_bytes(spd)
    release_entries = {target.name: spe}
    for name in ("setup.pyw", "PathLab-Setup.cmd", "VALIDATION.md", "RELEASE-NOTES.txt", *SUPPORT_FILES):
        file = ROOT / name
        if file.is_file():
            release_entries[name] = file.read_bytes()
    for file in sorted((ROOT / "examples").glob("*")):
        if file.is_file():
            release_entries["examples/" + file.name] = file.read_bytes()
    for file in sorted((ROOT / "validation").glob("*.json")):
        release_entries["validation/" + file.name] = file.read_bytes()
    release = destination / ("PathLab-SPSS-%s.zip" % VERSION)
    release.write_bytes(archive(release_entries))
    evidence = {"bundle": target.name, "sha256": hashlib.sha256(spe).hexdigest(),
                "version": VERSION, "developer": BRANDING.developer_metadata(),
                "license": {"spdx_id": "MIT", "file": "LICENSE"},
                "size_bytes": len(spe), "native_dialog": "PATHLAB_DIALOG", "minimum_spss": 27,
                "runtime_modules": sorted(runtime), "installation_verified_during_build": False,
                "validation_report": "VALIDATION.md",
                "validation_evidence": ["validation/" + p.name for p in sorted((ROOT / "validation").glob("*.json"))],
                "windows_release": release.name, "release_sha256": hashlib.sha256(release.read_bytes()).hexdigest()}
    (destination / ("build-manifest-%s.json" % VERSION)).write_text(json.dumps(evidence, indent=2)+"\n", encoding="utf-8")
    (destination / "build-manifest.json").write_text(json.dumps(evidence, indent=2)+"\n", encoding="utf-8")
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    print(json.dumps(build(parser.parse_args().output), indent=2))
