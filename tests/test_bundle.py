"""Validate native bundle contents and the GUI-to-runtime command contract."""
import importlib.util
from io import BytesIO
from pathlib import Path
import sys
import subprocess
import types
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gui_exposes_required_options_and_menu():
    builder = load_file("pathlab_bundle_builder", ROOT / "tools/build_bundle.py")
    root = ET.fromstring(builder.native_dialog())
    ns = {"c": builder.NS}
    assert root.find("c:UserInterface/c:Controls/c:MenuItem", ns).attrib["spssMenu"] == "Analyze"
    assert root.find("c:CommonObjects/c:Actions/c:Action", ns).attrib["label"] == "PathLab: Mediation and Moderation..."
    assert root.find("c:ExtensionDetails", ns).attrib["provider"] == "Dr. B. Issac Johny"
    assert root.find("c:ExtensionDetails", ns).attrib["copyright"] == "2026 Dr. B. Issac Johny"
    assert root.find("c:Node", ns).attrib["label"] == "PathLab: Mediation and Moderation — Dr. B. Issac Johny"
    properties = {p.attrib["name"]: p for p in root.findall("c:Node/c:Properties/c:Property", ns)}
    assert properties["x"].attrib["isRequired"] == properties["y"].attrib["isRequired"] == "true"
    assert properties["bootstrap"].attrib["defaultValue"] == "5000"
    assert properties["robust"].attrib["defaultValue"] == "hc3"
    assert properties["plots"].attrib["defaultValue"] == "both"
    assert properties["output_detail"].attrib["defaultValue"] == "standard"
    assert {"mediators", "covariates", "w", "z", "q", "categorical", "reference", "family",
            "structure", "first", "second", "serial", "direct", "confidence", "seed", "output_json",
            "plots", "plot_directory", "output_detail", "analysis"} <= set(properties)
    for name in ("first", "second", "serial", "direct"):
        assert {p.attrib["value"] for p in properties[name].findall("c:Enumeration/c:Enum", ns)} == {
            "none", "w", "z", "q", "wz", "wq", "zq"}
    lists = root.findall(".//c:MultiFieldChooserControl", ns)
    assert {c.attrib["property"] for c in lists} == {"mediators", "covariates", "categorical"}
    assert not root.findall(".//c:TargetFieldChooserControl", ns)
    panels = root.findall(".//c:PropertiesSubPanel", ns)
    assert {p.attrib["buttonLabel"] for p in panels} == {"Model...", "Moderators...", "Diagrams...", "Options..."}
    main = root.find("c:Node/c:UserInterface/c:Tabs/c:Tab/c:PropertiesPanel", ns)
    main_fields = [p for p in main.iter() if p.tag.endswith("FieldChooserControl")]
    assert {p.attrib["property"] for p in main_fields} == {"x", "y", "mediators", "w", "z", "q", "covariates", "categorical"}
    assert all(p.find("c:Layout", ns).attrib["gridColumn"] == "2" for p in main_fields)
    # Native SPSS 27 drops choosers inside nested compatible-form groups.
    # Keep all role lists directly on the proven main target column.
    assert not main.findall("c:PropertiesPanel", ns)
    # SPSS 27's classic preview placed a spanning main instruction over the
    # source-variable label; keep instructions in the working Help/panes.
    assert not main.findall("c:StaticText", ns)
    assert all(node.attrib.get("gridWidth") == "1" for node in root.findall(".//c:StaticText/c:Layout", ns))
    assert root.find(".//c:ServerDirectoryChooserControl", ns).attrib["property"] == "plot_directory"
    # SPSS classic initializes this source property from the active dictionary;
    # independently named subdialog source lists stayed empty in native testing.
    assert [node.attrib["property"] for node in root.findall(".//c:SourceFieldsBrowser", ns)] == ["source_vars"]
    stage_controls = [node for node in root.findall(".//c:ComboBoxControl", ns) if node.attrib["property"] in {"first", "second", "serial", "direct"}]
    assert all(node.find("c:Layout", ns).attrib["gridColumn"] == "0" for node in stage_controls)
    assert not any(pan.findall(".//c:SourceFieldsBrowser", ns) for pan in panels)
    syntax = properties["PATHLAB_DIALOG"].attrib["syntax"]
    assert syntax.count("/OUTPUT") == 1 and "/PLOTS %%plots%% %%plot_directory%%" in syntax


def test_command_keywords_match_python_templates(monkeypatch):
    captured = []
    class Template:
        def __init__(self, keyword, **kwargs):
            self.keyword = keyword
            self.options = kwargs
            captured.append(self)
    def processcmd(syntax, args, target):
        assert args == {"test": "parsed"}
        assert target.__name__ == "_dispatch"
    monkeypatch.setitem(sys.modules, "extension", types.SimpleNamespace(Template=Template,
                        Syntax=lambda value: value, processcmd=processcmd))
    entry = load_file("PATHLAB_test", ROOT / "PATHLAB.py")
    entry.Run({"PATHLAB": {"test": "parsed"}})
    xml = ET.parse(ROOT / "PATHLAB.xml")
    expected = {(sub.attrib["Name"], p.attrib["Name"])
                for sub in xml.getroot() for p in sub}
    actual = {(t.options.get("subc", ""), t.keyword) for t in captured}
    assert actual == expected
    assert xml.getroot().attrib["LanguageVersion"] == "3"


def test_complete_bundle_and_zip_runtime(tmp_path):
    builder = load_file("pathlab_bundle_builder", ROOT / "tools/build_bundle.py")
    evidence = builder.build(tmp_path)
    first = (tmp_path / evidence["bundle"]).read_bytes()
    builder.build(tmp_path)
    assert (tmp_path / evidence["bundle"]).read_bytes() == first
    with zipfile.ZipFile(BytesIO(first)) as spe:
        assert spe.namelist()[0] == "META-INF/MANIFEST.MF"
        manifest = spe.read("META-INF/MANIFEST.MF").decode().replace("\r\n ", "")
        assert "Name: PATHLAB\r\n" in manifest
        assert "Product-Version: 27\r\n" in manifest
        assert "Version: 0.2.2\r\n" in manifest
        assert "Author: Dr. B. Issac Johny\r\n" in manifest
        assert {"AUTHORS.txt", "CITATION.txt", "LICENSE", "THIRD-PARTY-NOTICES.txt", "MAINTAINER.txt"} <= set(spe.namelist())
        assert all(name in manifest for name in ("LICENSE", "THIRD-PARTY-NOTICES.txt", "MAINTAINER.txt"))
        license_text = spe.read("LICENSE").decode()
        assert license_text.startswith("MIT License")
        assert "Copyright (c) 2026 Dr. B. Issac Johny" in license_text
        assert "DRAFT FOR DEVELOPER REVIEW" not in license_text
        assert "johnydurai@gmail.com" in spe.read("MAINTAINER.txt").decode()
        assert "Gnanam School of Business, Thanjavur" in spe.read("AUTHORS.txt").decode()
        assert "Version 0.2.2" in spe.read("CITATION.txt").decode()
        assert "Dialog-Specs: PATHLAB.spd\r\n" in manifest
        with zipfile.ZipFile(BytesIO(spe.read("PATHLAB.spd"))) as spd:
            assert {"PATHLAB_DIALOG.xml", "PATHLAB_DIALOG.properties", "PATHLAB_DIALOG.htm"} == set(spd.namelist())
            ET.fromstring(spd.read("PATHLAB_DIALOG.xml"))
            help_text = spd.read("PATHLAB_DIALOG.htm").decode()
            assert all(text in help_text for text in ("Developed by Dr. B. Issac Johny", "Professor", "Gnanam School of Business, Thanjavur"))
        with zipfile.ZipFile(BytesIO(spe.read("pathlab_spss.zip"))) as runtime:
            assert {"pathlab_spss/__init__.py", "pathlab_spss/core.py", "pathlab_spss/errors.py", "pathlab_spss/branding.py"} <= set(runtime.namelist())
            assert all("__pycache__" not in name for name in runtime.namelist())
    assert evidence["developer"] == {"name": "Dr. B. Issac Johny", "title": "Professor",
                                     "affiliation": "Gnanam School of Business, Thanjavur",
                                     "credit": "Developed by Dr. B. Issac Johny"}
    assert evidence["license"] == {"spdx_id": "MIT", "file": "LICENSE"}
    with zipfile.ZipFile(tmp_path / evidence["windows_release"]) as release:
        assert {"AUTHORS.txt", "CITATION.txt", "LICENSE", "THIRD-PARTY-NOTICES.txt", "MAINTAINER.txt"} <= set(release.namelist())


def test_packaged_runtime_imports_from_ibm_install_layout(tmp_path):
    builder = load_file("pathlab_bundle_builder", ROOT / "tools/build_bundle.py")
    evidence = builder.build(tmp_path / "build")
    extensions = tmp_path / "extensions"
    (extensions / "PATHLAB").mkdir(parents=True)
    with zipfile.ZipFile(tmp_path / "build" / evidence["bundle"]) as spe:
        (extensions / "PATHLAB.py").write_bytes(spe.read("PATHLAB.py"))
        (extensions / "PATHLAB/pathlab_spss.zip").write_bytes(spe.read("pathlab_spss.zip"))
    result = subprocess.run([sys.executable, "-c", "import PATHLAB; PATHLAB._runtime(); import pathlab_spss; print(pathlab_spss.__file__)"],
                            cwd=extensions, capture_output=True, text=True, check=True)
    assert "pathlab_spss.zip" in result.stdout
