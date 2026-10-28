# PathLab for IBM SPSS Statistics

**Developed by Dr. B. Issac Johny**  
Professor  
Gnanam School of Business, Thanjavur

PathLab adds **Analyze → PathLab: Mediation and Moderation…** to SPSS. Choose variables, select the model and diagrams, and click **OK**. No analysis syntax, JSON model file or separate Python installation is required.

Version **0.2.2 beta** packages the approved MIT license, maintainer contact and publication materials. It retains the developer credit, interaction and Johnson–Neyman diagrams, guided analysis choices, all variable assignments in one place, and a choice between standard and full results. It uses the existing PathLab numerical engine without a Stratistics account, web service or PROCESS macro.

Public maintainer: **johnydurai@gmail.com** · [Developer website](https://www.johny.uk). [Source repository](https://github.com/issacjohny/PathLab-SPSS) and [version 0.2.2 download page](https://github.com/issacjohny/PathLab-SPSS/releases/tag/v0.2.2) provide the source code and downloadable beta package.

## Install or upgrade

1. Extract **PathLab-SPSS-0.2.2.zip**. Close SPSS, then double-click **PathLab-Setup.cmd** in the extracted folder.
2. Confirm the Python supplied with your SPSS installation. For SPSS 27, its usual location is `C:\Program Files\IBM\SPSS\Statistics\27\Python3\python.exe`. Click **Install calculation libraries** and wait for completion. This one-time step downloads the required libraries, including the diagram library.
3. Open SPSS and choose **Extensions → Install Local Extension Bundle**. Select **PathLab-0.2.2.spe** from the extracted folder. If PathLab is already installed, install this updated bundle.
4. Restart SPSS, open your dataset, and choose **Analyze → PathLab: Mediation and Moderation…**.

The full `.spe` contains the native dialog, command and calculation runtime. A `.spd` by itself supplies only the interface. Setup installs libraries into `%APPDATA%/PathLab/python-MAJOR.MINOR`; it does not replace SPSS's own packages. SPSS 27 already supplies Python 3.8. Analysis runs locally and never downloads packages or uploads the dataset.

The release targets SPSS 27 and later. Historical calculation and native command execution have been verified in SPSS 27, and 0.2.1 installation and attribution checks are recorded separately. Version 0.2.2 is a license/contact packaging update; it has not yet received another native SPSS calculation or installation acceptance run. [VALIDATION.md](VALIDATION.md) records dialog preview, image insertion and persistent installation separately for each tested build. Later SPSS releases require their own runtime and installation checks. An extension's minimum-version setting alone does not establish compatibility with every later release.

## Start with the analysis goal

Assign all variables in the main dialog: predictor **X**, outcome **Y**, optional ordered mediators **M**, moderators **W/Z/Q**, covariates, and categorical declarations. Leave the analysis goal at **Choose automatically from selected variables**, or choose Mediation, Moderation or Conditional process explicitly. An explicit goal must agree with the assigned variables; PathLab does not silently add moderators or change a path.

| Goal | Main dialog | Additional choices |
| --- | --- | --- |
| Mediation | X, Y, and one or more mediators | **Model…**: Parallel, Serial or Combined |
| Moderation | X, Y and W; leave mediators blank | **Moderators…**: set Direct path to W |
| Conditional process | X, Y, mediator(s), and moderator(s) | **Moderators…**: assign moderator(s) to the desired mediation stage(s) |

Use the main **Covariates (optional)** box for controls. Also put categorical X, moderator or covariate variables in the main **Categorical variables (optional)** box, then choose their reference-group rule under **Model…**. Each model variable has one role; categorical coding is an additional property of a selected variable.

The complete native dialog was checked on this Windows desktop's 1920×1080 display. SPSS can restore an older dialog position after an upgrade; move the title bar near the top of the screen if the bottom controls are outside the visible area. Smaller display layouts have not been verified.

## Choose interaction and Johnson–Neyman diagrams

Open **Diagrams…**. **Show both diagrams (recommended)** is selected initially. You can instead request only interaction diagrams, only Johnson–Neyman diagrams, or tables only. An export folder is optional: diagrams appear in the SPSS Viewer, and selecting a folder also saves PNG files in a new PathLab diagram subfolder there.

- **Interaction diagrams** show fitted outcomes across the predictor values for numerical moderator probes or the observed categorical levels. Confidence bands describe uncertainty in fitted means, not individual predictions. Binary-outcome fitted means are shown as probabilities.
- **Johnson–Neyman diagrams** show the conditional slope of a particular path across a continuous moderator. The zero line, pointwise confidence interval and analytic boundaries help identify where the interval excludes zero within the observed range. A logistic outcome uses a log-odds path slope, which is labeled on the diagram.

Other moderators are held at the conditions written on each panel. Every included condition is retained; large sets are paginated into four panels per PNG. Diagrams are produced for the included moderated paths rather than a silently selected single arrow. A categorical X has separate reference contrasts where applicable.

A pure mediation model has no interaction to plot. A categorical moderator cannot have a continuous Johnson–Neyman region. PathLab displays the reason when a requested diagram is inapplicable. These Johnson–Neyman diagrams concern individual conditional path slopes; bootstrap indirect-effect intervals are not relabeled as exact Johnson–Neyman regions. All intervals are pointwise.

## Read the results

Under **Options…**, the recommended starting settings are **5,000 bootstrap samples**, **95% confidence**, a reproducible seed, and **HC3** coefficient covariance. **Standard** output presents the model overview, main estimates and requested diagrams. **Full** adds detailed contrasts and diagnostic tables. The complete numerical result can also be saved with the optional results-file control.

First review sample size and missing-data exclusions, the fitted equations, and the moderator conditions. Then inspect the specific and summed indirect effects, conditional direct effects, indices or derivatives, and diagrams. Indirect effects and contrasts use paired whole-case percentile bootstrap intervals. HC3 affects coefficient inference; it does not change the paired-case resampling scheme.

Numerical probes are fixed before resampling: one or two numerical moderators use the 16th, 50th and 84th percentiles; three use the 16th and 84th percentiles to keep joint conditions bounded. Categorical reference levels are also fixed on the common analysis sample.

## Model definitions and limits

Parallel includes X→every mediator→Y. Serial includes X→M1→M2→…→Y in the listed order. Combined includes every X→M, M→Y and forward M→M path. Every structure also includes X→Y. Covariates enter every mediator and outcome equation. Moderation choices apply to every included path at that stage. A joint pair adds its three-way product and every required lower-order term.

The engine supports up to ten mediators, three exogenous moderators and twenty covariates, subject to path-count, rank, computation and result-size limits. The Combined preset allows at most six mediators; Parallel and Serial allow ten. Arbitrary graph editing and equation-specific covariates are not exposed in this menu interface.

Mediators and continuous outcomes must be numerical. Logistic Y must use 0/1 coding. Categorical X, moderators and covariates use raw observed category values with an explicitly chosen lowest/first or highest/last reference. PathLab does not implicitly center variables, construct scores or impute missing observations.

All equations use a single common complete-case sample, respecting SPSS user/system missing values and active filtering. Active weights and split files are rejected explicitly. Statistical associations alone do not establish causation. Logistic indirect products are log-odds-scale associations, not natural causal effects, probability differences or indirect-effect odds ratios.

## Build and verification

Build with `python tools/build_bundle.py`; it creates versioned `.spe`, `.spd` and Windows ZIP artifacts while preserving previous versioned releases. Run `python -m pytest tests` with the required statistical and plotting libraries. The package includes native command XML, compatible CLEF dialog XML, a Python command entry point and a pure-Python runtime ZIP in IBM's extension layout.

See [VALIDATION.md](VALIDATION.md), the synthetic examples and `validation/` for the distinction between numerical checks, real SPSS execution, dialog rendering and persistent installation. The exact frozen statistical source is recorded in `source-provenance.json`.

## Developer and citation

See [AUTHORS.txt](AUTHORS.txt) for the developer credit and [CITATION.txt](CITATION.txt) for the recommended software citation:

B. Issac Johny. (2026). *PathLab for IBM SPSS Statistics* (Version 0.2.2) [Computer software]. Gnanam School of Business, Thanjavur.

The statistical source provenance and third-party authorship and license terms remain recorded with their respective software.

## License and support

PathLab is distributed under the [MIT License](LICENSE), approved by the developer on 28 October 2026. See [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt) for the separately installed dependencies and their respective notices. Contact **johnydurai@gmail.com** for PathLab questions. The planned repository issue tracker is [GitHub Issues](https://github.com/issacjohny/PathLab-SPSS/issues), pending repository publication. IBM Extension Hub acceptance and IBM product support have not been established.

Format references: [IBM's official example bundle](https://github.com/IBMPredictiveAnalytics/STATS_PROPOR_REGR), [extension command XML](https://www.ibm.com/docs/en/spss-statistics/32.0.0?topic=commands-xml-specification-extension-command-syntax), [Python implementation contract](https://www.ibm.com/docs/en/spss-statistics/30.0.0?topic=commands-implementation-code).
