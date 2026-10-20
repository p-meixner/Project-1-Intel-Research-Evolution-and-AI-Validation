# Intel - Project 1 Corporate Finance Application

**Committee action: watch / defer; no initiation at the September 1, 2026 close.**
Intended user: a buy-side investment committee with no Intel position. Security:
NASDAQ INTC common equity; USD; 12-24 month monitoring horizon. The model has a
remaining-2026 stub plus five full annual three-statement forecasts (2027-2031),
signed FCFF, WACC, terminal value, a claims/dilution bridge, causal scenarios,
reverse DCF, sensitivity, peer references, and explicit funding gates.

Start with **[the visible report](output/report.html)**. Open it in a browser;
no server, installation, API key or internet is needed. The case selector shows
all three statements for each scenario. Static PDFs are in `output/pdf/` and the
Brightspace upload copies are in `submission/`.

## Reproduce the application

Python 3.12 or later; **no third-party packages for the model or validation**.
From this directory:

```text
python model.py
python validate.py
python cold_run.py
```

From the parent course folder on this Windows computer:

```powershell
.venv\Scripts\python.exe Project1-Intel\model.py
.venv\Scripts\python.exe Project1-Intel\validate.py
.venv\Scripts\python.exe Project1-Intel\cold_run.py
```

Expected deliberate failure, for Video 2:

```text
python model.py --break-cash
```

It must exit nonzero with a balance-sheet mismatch. Do not describe it as an
unexpected bug. Change assumptions by copying `inputs.json` and using
`python model.py --inputs my-inputs.json --out my-output`; preserve the base.

## Repository map

- `inputs.json`: historical inputs, assumption paths, price and share definitions.
- `model.py`: statement roll-forward, WACC, DCF, bridge, reverse DCF, scenarios,
  peer definitions, and browser-readable report. Standard library only.
- `validate.py`: 12 published training answers, historical/source checks,
  articulation, prewritten directional tests, bridge identities and refusal tests.
- `cold_run.py`: builds a fresh environment and isolated copy; compares output.
- `output/results.json`, `output/statements.csv`, `output/report.html`: executed output.
- `output/validation.json`, `output/cold-run.log`: actual validation evidence.
- `docs/`: content-equivalent research, memo, evidence, assumption and AI-use records.
- `evidence/originals/`: unchanged Edition A and old locked-prediction record.
- `evidence/sources/`: authoritative source captures, dated retrieval log and hashes.
- `recording-guides/`: preparation scripts and evidence cues, **not certified transcripts**.
- `submission/`: uniform filenames, manifest and outstanding student-action checklist.

`fetch_sources.py` is optional, needs requests/beautifulsoup4 and network access.
Source downloads are already saved. SEC direct downloads returned 403; the
official Intel mirror worked. Do not refresh historical facts silently.
`build_package.py` regenerates documents using `requirements-pdf.txt`; those
packages are not needed to reproduce financial results.

## Interpretation and limits

The displayed range is conditional, not a statistical interval or a calibrated
market target. The downside has a financing deficit and a negative raw equity
residual; the displayed zero floor is not a finding that all equity options are
worthless. September balances are estimates rolled from June; NCI, equity
holdings, dilution and other claims use disclosed proxies. They need diligence
before any initiation. WACC beta/debt cost are judgments; terminal value carries
most of the base valuation. Peer EV/sales uses dated annual balances and is a
diagnostic, not a current EV certification. See `docs/evidence-ledger.md`.

Edition A is preserved without a checkpoint receipt under the instructor's
clarification supplied by the student October 19. No earlier receipt or AI-off
authorship is newly certified. The old Lab 11 prediction is preserved with historical evidence gaps. A new AI-assisted prediction and run were committed before execution under Peter's reported instructor permission. The validation record labels this accurately; it is not AI-off evidence. Recordings, corrected actual transcripts, accessible
hosting and Brightspace submission must be completed by the student.

The parent Git remote is the instructor's course repository. **This package has
not been pushed there.** Publish this project in your own repository or approved
course submission location, with access for the instructional team. No external
messages, uploads, publication or submission are claimed by the build.

A separate local Git repository was initialized inside Project1-Intel. Its
Codex-authored commit records the AI-assisted build, not earlier student work.
PDFs were rendered and visually reviewed; the memo is two pages. The report's
local links and case visibility structure were checked. Live browser interaction
could not be verified because no browser connection was available.
