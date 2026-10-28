# Try PathLab through the SPSS menus

**Developed by Dr. B. Issac Johny**  
Professor  
Gnanam School of Business, Thanjavur

Public maintainer: johnydurai@gmail.com · https://www.johny.uk. Version 0.2.2
packages the approved MIT license and maintainer details; the numerical engine
and the demonstration selections below are unchanged. See the release
validation report for the versions actually executed in SPSS.

`pathlab-demo.csv` contains 180 entirely synthetic cases. Open it using **File → Import Data → CSV Data** and treat the variables as scale variables for these examples. These artificial data demonstrate the controls; they are not evidence for any research claim.

## Simple mediation

1. Open **Analyze → PathLab: Mediation and Moderation…**.
2. Choose **Mediation** as the analysis goal. Set **X** to X, **Y** to Y and add **M1** as the mediator.
3. Under **Model…**, keep Parallel and the continuous outcome.
4. Leave the moderator boxes empty. Under **Options…**, use 1,000 bootstrap samples for a quick demonstration, 95% confidence and HC3.
5. Click **OK** and review the indirect-effect estimate and bootstrap interval. There is no moderated arrow in this model, so an interaction or Johnson–Neyman diagram is inapplicable.

## Moderation with interaction and Johnson–Neyman diagrams

1. Start a fresh PathLab dialog. Choose **Moderation**, assign X and Y, and leave Mediators blank.
2. Assign W to the main **Moderator W** box. Open **Moderators…** and set **Direct path: X to Y** to **W**; leave the other stages at None.
3. Open **Diagrams…** and keep **Show both diagrams (recommended)**. Optionally choose an export folder for PNG copies.
4. Under **Options…**, use 1,000 bootstrap samples for this demonstration, 95% confidence and HC3. Click **OK**.
5. Read the interaction diagram as fitted Y across X at the displayed W values. Read the Johnson–Neyman diagram as the X→Y slope across W; its band and zero line indicate where the pointwise interval excludes zero.

## Serial conditional process with three moderators

1. Choose **Conditional process**. Assign X, Y and mediators **M1**, then **M2**, in that order.
2. Under **Model…**, select **Serial** and keep the continuous outcome.
3. Assign W, Z and Q to their matching main-dialog boxes. Under **Moderators…**, set First stage to W, Serial stage to Z, Final stage to Q, and Direct path to None.
4. Add C to the main **Covariates (optional)** box.
5. Under **Diagrams…**, keep both diagram types. Three numerical moderators use the 16th and 84th percentiles; other moderators are held at each panel's labeled conditions.
6. Under **Options…**, use 1,000 bootstrap samples, 95% confidence, seed 20261028 and HC3. Click **OK**.

Review the fitted equations, conditional indirect associations, indices/derivatives and diagrams. Choose **Full** results when you also want the detailed contrast and diagnostic appendix.

## Diagram previews

`interaction-preview.png` and `johnson-neyman-preview.png` show the two diagram styles using a separate, deterministic synthetic validation dataset. They illustrate the appearance and interpretation; they are not expected results for `pathlab-demo.csv`.
