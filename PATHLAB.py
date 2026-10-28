"""SPSS extension-command entry point used by the PathLab menu dialog."""
from pathlib import Path
import os
import sys


def _runtime():
    """IBM installs miscellaneous files under the extension bundle's name."""
    appdata = Path(os.environ.get("APPDATA") or str(Path.home()))
    dependencies = appdata / "PathLab" / ("python-%d.%d" % sys.version_info[:2])
    if dependencies.is_dir() and str(dependencies) not in sys.path:
        sys.path.insert(0, str(dependencies))
    archive = Path(__file__).resolve().parent / "PATHLAB" / "pathlab_spss.zip"
    if archive.is_file() and str(archive) not in sys.path:
        sys.path.insert(0, str(archive))
    from pathlab_spss import run_dialog
    return run_dialog


def _dispatch(**kwargs):
    return _runtime()(**kwargs)


def Run(args):
    """Receive IBM's parsed command dictionary; users operate the native dialog."""
    from extension import Template, Syntax, processcmd
    templates = [
        Template("X", var="x", ktype="varname"),
        Template("Y", var="y", ktype="varname"),
        Template("MEDIATORS", var="mediators", ktype="existingvarlist", islist=True),
        Template("COVARIATES", var="covariates", ktype="existingvarlist", islist=True),
        Template("W", var="w", ktype="varname"),
        Template("Z", var="z", ktype="varname"),
        Template("Q", var="q", ktype="varname"),
        Template("STRUCTURE", subc="MODEL", var="structure", ktype="str",
                 vallist=["parallel", "serial", "combined"]),
        Template("FAMILY", subc="MODEL", var="family", ktype="str", vallist=["linear", "logistic"]),
        Template("CATEGORICAL", subc="MODEL", var="categorical", ktype="existingvarlist", islist=True),
        Template("REFERENCE", subc="MODEL", var="reference", ktype="str", vallist=["first", "last"]),
        Template("ANALYSIS", subc="MODEL", var="analysis", ktype="str",
                 vallist=["auto", "mediation", "moderation", "conditional"]),
        Template("BOOTSTRAP", subc="OPTIONS", var="bootstrap", ktype="int", vallist=[200, 50000]),
        Template("CONFIDENCE", subc="OPTIONS", var="confidence", ktype="float", vallist=[80, 99.9]),
        Template("SEED", subc="OPTIONS", var="seed", ktype="int", vallist=[0, 2147483647]),
        Template("ROBUST", subc="OPTIONS", var="robust", ktype="str", vallist=["hc3", "classical"]),
        Template("JSON", subc="OUTPUT", var="output_json", ktype="literal"),
        Template("DETAIL", subc="OUTPUT", var="output_detail", ktype="str", vallist=["standard", "full"]),
        Template("TYPE", subc="PLOTS", var="plots", ktype="str", vallist=["both", "interaction", "jn", "none"]),
        Template("DIRECTORY", subc="PLOTS", var="plot_directory", ktype="literal"),
    ]
    for keyword, argument in (("FIRST", "moderate_first"), ("SECOND", "moderate_second"),
                              ("SERIAL", "moderate_serial"), ("DIRECT", "moderate_direct")):
        templates.append(Template(keyword, subc="MODERATION", var=argument, ktype="str",
                                  vallist=["none", "w", "z", "q", "wz", "wq", "zq"]))
    processcmd(Syntax(templates), args[next(iter(args))], _dispatch)
