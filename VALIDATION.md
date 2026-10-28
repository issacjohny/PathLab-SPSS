# PathLab for SPSS validation

Validated on 28 October 2026. This report separates numerical, runtime, and
native dialog checks; successful source tests do not by themselves establish
compatibility with every SPSS release.

## Version 0.2.2 license and publication preparation

The developer approved the MIT license on 28 October 2026. Version 0.2.2
packages that license, maintainer contact information and publication
materials. The statistical calculation code is unchanged from 0.2.1.
The GitHub repository and release URLs are recorded in the submission
metadata. GitHub publication is separate from IBM Extension Hub acceptance.

Historical native SPSS evidence below retains its original tested version
and hashes. Version 0.2.2 has not yet received a new native installation or
menu-driven calculation acceptance run. Its build and source checks must be
recorded separately from historical SPSS execution evidence. Final main-menu
OK execution and later SPSS releases remain open validation work.

The 0.2.2 extension suite passes 101 tests. All 25 Python source/setup
files parse with SPSS 27's Python 3.8.2. The SPE contains the approved
MIT license, dependency notices and maintainer details. Every packaged
runtime file except the version module is byte-identical to 0.2.1.
Evidence is in `validation/spss27-v022-packaging.json`.

## Version 0.2.1 developer attribution

Version 0.2.1 adds developer credit for Dr. B. Issac Johny, Professor,
Gnanam School of Business, Thanjavur, to package metadata, the dialog title,
help, setup, results, JSON exports and diagram footers. The scientific core
is unchanged. Its statistical validation evidence below belongs to 0.2.0;
it is retained with the original version and file hashes.

The attribution release was checked with the extension test suite, Python 3.8
syntax parsing, and report/diagram generation using SPSS 27's bundled Python.
The two branded synthetic diagrams were visually inspected. These checks do
not claim another complete native menu calculation or verification of later
SPSS releases.

The IBM installer reported successful installation of 0.2.1. The installed
bundle, runtime, command files and attribution files match the release;
the installed dialog retains the credited title and its help matches the
bundle. An isolated import of the installed runtime reports 0.2.1. The
running SPSS session was left open and needs a user restart to load the
updated runtime. Evidence is in `validation/spss27-v021-attribution.json`.

## Version 0.2 diagram and guided-output checks

The extended suite passes 101 tests, including interaction/J–N plot mappings,
moderator conditions, categorical/logistic applicability, guided analysis
validation, readable report summaries, and native Viewer boundary behavior.
The scientific computation core remains the frozen source snapshot recorded
in `source-provenance.json`.

SPSS 27's Python 3.8.2 successfully imports Matplotlib 3.7.5 with the existing
NumPy 1.24.4/pandas 2.0.3/SciPy 1.10.1/statsmodels 0.14.1 versions. Initial
runtime tests used libraries added only to the workspace validation directory.
The full detailed report with diagrams
disabled was rerun in an isolated real SPSS 27 engine: 71 complete cases,
200/200 successful bootstrap replications, 12 effects, and two indices.

Interaction and Johnson–Neyman PNG rendering has also run inside the actual
SPSS GUI backend on the deterministic synthetic data. The conditional
X-to-mediator slope has an analytic J–N boundary of approximately -0.912441.
The installed 0.2 command then completed inside a fresh SPSS 27 GUI instance,
with no external SDK connection. It used 71 complete cases and 200/200
successful bootstrap replications, produced 12 effect rows and two index rows,
and embedded both diagrams with no Viewer notices. The test saved only its
own synthetic output document. Both 1344 by 944 embedded PNGs were decoded
and their RGBA pixel hashes matched the original rendered diagrams exactly;
SPSS re-encodes PNG files, so file-byte hashes are not used for this check.
The numeric J–N boundary was -0.9124413470404931. Sanitized evidence is in
`validation/spss27-v02-diagrams.json`; the synthetic example PNGs are in the
same folder. The raw synthetic SPV is retained locally and is not distributed.

For GUI reproduction, `tools/verify_gui.py` routes to the file-only
`tools/gui_diagram_validation.py` helper. It prepares a fresh extracted bundle,
a separate synthetic output document, and a uniquely named populated scratch
dataset. Run the prepared developer file from SPSS's **Run > All**, then
collect its JSON and SPV evidence. Do not keep an external `RunSyntax` client
connected while an extension invokes `SpssClient` for Viewer insertion.
Fresh extraction paths avoid Python 3.8 zip-import caches during development.
An existing installed command can still take precedence over temporary XML
registration. Installed acceptance uses `--installed` after installing the
matching SPE and restarting SPSS; this mode makes no import-path changes and
does not register replacement XML. The collector rejects missing results or
a runtime version that differs from the requested bundle.

The version 0.2 bundle has now been installed using IBM's extension-bundle
installer. Read-only SHA-256 checks confirm both installed `PATHLAB.py` and
`PATHLAB/pathlab_spss.zip` match the release SPE exactly. The install-time
dependency setup also added Matplotlib 3.7.5 to PathLab's per-user Python 3.8
library folder. This uses SPSS's bundled Python and does not install a separate
system Python.

The final installed SPE has SHA-256 beginning `21d2e4b79f90`. Its command entry
and runtime archive are identical to those used for the successful installed
native-command calculation above. The installed command XML also matches the
final SPE. SPSS rewrites the installed dialog XML with metadata, localization
attributes and normalized numerical formatting; a semantic comparison verified
all 27 property definitions and 25 control bindings and grid layouts against
the final SPE. Read-only installation evidence is in
`validation/spss27-v02-installation.json`.

The final **Analyze > PathLab** menu entry was opened in actual SPSS 27.
The main form's eight variable assignments and the Model, Moderators, Diagrams
and Options forms were inspected. X/Y/W assignment interaction was checked in
an earlier candidate with the same assignment fields. On the current display,
the main dialog was moved near the top so all controls fitted; smaller display
layouts remain unverified. The final main **OK** button was not used to run an
analysis. These menu-form checks are separate from the successful installed
native-command calculation and embedded-diagram acceptance described above.

## Initial SPSS 27 runtime checks

The installed Windows SPSS 27 runtime reports SPSS `27.0.0.0` / integration
plug-in `spss270`, with bundled 64-bit Python `3.8.2`. Its stock Python did not
contain NumPy, pandas, SciPy, or statsmodels. Test dependencies were installed
only into the workspace at `.local/spss27-deps`; the SPSS installation and the
user's Python libraries were not changed during these initial checks. The
later installed acceptance setup is described above.

The following numerical versions imported and executed successfully in that
Python: NumPy `1.24.4`, pandas `2.0.3`, SciPy `1.10.1`, statsmodels `0.14.1`.
Using the website worker's newer dependency pins would not support Python 3.8.

`tools/check_runtime.py --smoke-engine` successfully ran an isolated SPSS engine
using synthetic data, read the active dataset, computed moderated mediation,
created native SPSS pivot tables and text blocks, and ended the procedure.
The synthetic source had 90 cases; SPSS's active filter excluded 18, leaving
72 selected cases; one SPSS user-missing value excluded one more case from the
common analysis sample. The result used 71 complete cases and completed all
200 paired bootstrap replications. It produced 12 direct/indirect/total effect
rows and two moderated mediation index rows. The original `TVARS` output
preference was restored. Local execution evidence is saved in
`.local/spss27-smoke-evidence.json`.

The actual SPSS cursor already applies `FILTER BY`. `GetCaseCount()` reports
the complete dataset size. The adapter records original, selected, filter,
and common listwise sample counts separately. SPSS `SimplePivotTable` is a
method on `BasePivotTable`, not a function on the `spss` module; the report
uses the supported API.

## Version 0.1 automated tests (historical)

At the version 0.1 checkpoint, the full extension test suite passed **76 tests**
using the existing workspace Python 3.11 statistical environment. The current
version 0.2 count is recorded above. Run from the repository root:

```powershell
.\.local\worker-venv\Scripts\python.exe -m pytest extensions/pathlab-spss/tests -q --basetemp=.local/pathlab-spss-runtime-suite
```

Tests include independent numerical references, source-core fidelity, preset
graph semantics and hierarchy, unsupported request rejection, categorical
coding on the common sample, active SPSS dataset integration mocks, label
preference restoration on failure, weight/split refusal, and atomic finite JSON
exports. The complete-case and native Viewer behavior above was additionally
executed in SPSS 27's real Python 3.8 runtime.

## Version 0.1 native extension dispatch and GUI execution (historical)

The bundled command XML was registered in an isolated SPSS 27 engine with
`EXTENSION /SPECIFICATION COMMAND=...`. SPSS parsed the command, called the
packaged `PATHLAB.Run`, processed its keyword templates, and entered the
packaged runtime through `_dispatch`. The test used an extracted IBM-style
installation layout with `PATHLAB.py` and `PATHLAB.xml` in the extension root
and `pathlab_spss.zip` in its `PATHLAB` subdirectory.

A native-command calculation driven from an external Python process stalled
at the first NumPy import inside SPSS's embedded callback. The same engine and
libraries successfully completed the direct adapter calculation described
above. The same packaged extension was then tested in the **actual SPSS 27 GUI
backend**, using the documented `SpssClient.RunSyntax` interface solely as the
test driver. The GUI Python search path was set for that session only; no
extension or dependency installation was made in the user's profile. SPSS
registered the command XML, processed the native `PATHLAB` command, loaded the
packaged runtime, completed 200 of 200 bootstrap replications on the 71-case
common sample, generated the native Viewer output, and saved a complete result
JSON. This confirms that the native GUI execution path works and distinguishes
the external-drive NumPy initialization stall from normal SPSS GUI operation.

The synthetic validation output contains no user data. The original empty
SPSS data document was restored after testing. A sanitized summary is included
in `validation/spss27-gui.json`. The raw synthetic result used for checking was
saved locally at `.local/spss27-gui-result.json`.

At the version 0.1 checkpoint, native dialog rendering had also been inspected
in SPSS's compatible Custom Dialog Builder preview. Persistent installation
and a menu-driven analysis had not yet been checked at that checkpoint.
Current installation evidence is described in the version 0.2 section above.
The release uses a genuine compatible `.spd` dialog and `.spe` bundle.

Newer SPSS versions are compatibility targets. Their Python versions select
their own compatible numerical dependencies; this report does not claim they
were installed or executed here.

## Reproducing the isolated engine smoke

Launch a fresh SPSS Python process with the SPSS installation and its `JRE/bin`
directories on the process `PATH`, then run `tools/check_runtime.py` with
`--dependency-path` pointing to the chosen numerical library directory and
`--smoke-engine`. The script refuses a pre-existing backend so it cannot replace
a dataset in an active SPSS GUI session. The normal preflight is read-only and
does not start the SPSS engine.

`spss.SetOutput('off')` disables only the external Python console echo during
this test. Native pivot tables are still constructed. This avoids a Windows
code-page error when external console output contains Unicode variable labels
or arrows; it does not suppress the user's SPSS Viewer output.

`tools/verify_gui.py` prepares a developer-only GUI check from the SPE bundle,
a compatible dependency directory, a destination folder and the dataset name
to restore. It makes a fresh extraction path and writes a synthetic validation
file without connecting to SPSS. Prefer a separate empty SPSS instance with
`--clean-instance`, then open the prepared file there and choose **Run > All**.
After its marker exists, use `--collect` to verify the numerical result and
embedded PNGs in the test's own saved SPV. The helper does not install anything.
Use `--installed` to check the already-installed bundle after restarting SPSS. The
helper does not execute analysis in an externally connected `RunSyntax` call.

Official API references:

- [SPSS 27 Python Reference Guide](https://www.ibm.com/docs/SSLVMB_27.0.0/pdf/en/Python_Reference_Guide_for_IBM_SPSS_Statistics.pdf)
- [Running SPSS from an external Python process](https://www.ibm.com/docs/en/spss-statistics/30.0.0?topic=programs-running-spss-statistics-from-external-python-process)
