# Walkthrough: time-to-fill survival analysis

This guide is for analytics engineers who know SQL and recruitment metrics but are new
to survival analysis. It has three parts:

1. [The statistical idea](#part-1-the-statistical-idea): survival curves, censoring,
   and a five-requisition example worked by hand.
2. [Rebuild the project from an empty folder](#part-2-rebuild-the-project-from-an-empty-folder),
   file by file.
3. [Read the results and change the reporting date](#part-3-read-the-results).

---

## Part 1: The statistical idea

### 1.1 What a survival curve means in recruitment

Survival analysis studies **how long it takes until an event happens**. The name comes
from medicine, where the event is death. In recruitment:

- the **clock starts** when the requisition is approved;
- the **event** is the first accepted offer (the requisition is "filled");
- a requisition that is still open has "survived" so far.

The **survival curve** S(t) answers one question for every day *t*:

> What share of requisitions is **still unfilled** *t* days after approval?

It starts at 100% on day 0 and steps down each time a requisition fills. For example,
S(45) = 40% means: an estimated 40% of requisitions are still unfilled 45 days after
approval.

Why this matters for the business: a hiring manager asks "if I open a role today,
how likely is it that it's still open in six weeks?" The survival curve answers
that directly. An average time to fill does not.

### 1.2 Right-censoring

On the reporting date, some requisitions are still open. For each of them:

- we **know** it remained unfilled through its last observed day (its current age);
- we **do not yet know** its eventual time to fill.

This is **right-censoring**. "Censored" means we stopped observing before the event
happened. "Right" means the missing part is on the right-hand side of the timeline
(the future).

### 1.3 An open requisition's age is not its time to fill

Requisition `REQ-1043` (Engineering) was approved on 2026-04-06 and was still open
on the reporting date, 2026-05-31. Its age is 55 days.

55 days is **not** its time to fill. Its time to fill is **at least** 55 days,
possibly much longer. Common mistakes:

| Approach | Problem |
|---|---|
| Treat 55 as its time to fill | Understates it: the requisition hasn't filled yet |
| Drop it and average filled requisitions only | Ignores that it has already waited 55 days |
| Wait until everything fills | The report is always months late |

The sample data shows why this matters. `REQ-1015` (Engineering) was approved on
2026-01-28 and was open on the reporting date after 123 days. The source extract
shows its offer was accepted on 2026-06-04, four days **after** the reporting date.
On 2026-05-31 nobody could know that. The correct historical record is "open, at least
123 days".

### 1.4 Censored requisitions contribute information until they are censored

Kaplan–Meier works **day by day**. On each day when a fill happens, it asks:

> Of the requisitions that were still open and still being observed just before
> this day, what share filled on this day?

A censored requisition is part of that "still open and observed" group (the **risk
set**, or "at risk") on every day **until** it is censored. It makes the fill rate on
each of those days more accurate, because it shows that not everyone filled. After
it is censored, it leaves the risk set, because we don't know what happened next.

### 1.5 The curve drops at fills, not at censoring

Censoring is not an outcome. It only means "we stopped watching". So:

- on a **fill** day, the curve steps **down**;
- on a **censoring** day, the curve stays **flat**. The requisition just leaves the
  risk set, so later steps are calculated from a smaller group (they get bigger).

In the charts, censoring is shown as small tick marks (|) on a flat part of the curve.

### 1.6 A hand-worked Kaplan–Meier example

Five requisitions, all observed from approval:

| Requisition | Status on reporting date | Days observed |
|---|---|---|
| A | Filled | 10 |
| B | Open (censored) | 15 |
| C | Filled | 20 |
| D | Filled | 30 |
| E | Open (censored) | 40 |

Walk through the days in order. "At risk" = still open and observed just before
that day.

| Day | At risk | Fills | Censored | Calculation | S(t), share still unfilled |
|---|---|---|---|---|---|
| 0 | 5 | – | – | start | 1.000 |
| 10 | 5 | 1 (A) | 0 | 1.000 × (1 − 1/5) | **0.800** |
| 15 | 4 | 0 | 1 (B) | no fill, no step | 0.800 |
| 20 | 3 | 1 (C) | 0 | 0.800 × (1 − 1/3) | **0.533** |
| 30 | 2 | 1 (D) | 0 | 0.533 × (1 − 1/2) | **0.267** |
| 40 | 1 | 0 | 1 (E) | no fill, no step | 0.267 |

The formula is always the same: **new S = previous S × (1 − fills ÷ at risk)**.

What the example shows:

- **B counted until it was censored.** On day 10, B was in the denominator (5 at
  risk). On day 20 it was gone (3 at risk).
- **Median time to fill:** the first day the curve reaches 50% or lower is **day 30**.
  (lifelines, the Python library used here, follows this convention.)
- **Filled-only statistics:** A, C, D took 10, 20, 30 days, so mean = median = **20 days**.
  That ignores that B and E stayed open for 15 and 40 days.
- **Dropping the open requisitions** gives a curve of 0.667, 0.333, 0. It says every
  requisition is filled by day 30. But E is known to be open on day 40.
- **Day 45 is beyond the data.** The longest observation is 40 days, so we cannot say
  what happens on day 45. lifelines would return 0.267 there by carrying the last
  value forward. That is why the project's script shows "Insufficient follow-up"
  instead.

You can check this in Python. Start `uv run python` in the project folder and paste:

```python
from lifelines import KaplanMeierFitter

kmf = KaplanMeierFitter().fit([10, 15, 20, 30, 40], event_observed=[1, 0, 1, 1, 0])
print(kmf.survival_function_)  # 1.0, 0.8, 0.8, 0.533, 0.267, 0.267
print(kmf.median_survival_time_)  # 30.0
```

### 1.7 When the median cannot be estimated

If more than half of a group is still unfilled at the end of the observed period, the
curve never reaches 50%. The median is then **not estimable** from this data. The
script reports "Not reached within observed follow-up". This is an honest answer: the
median is later than anything we have observed, and we don't know how much later.

### 1.8 Small groups and limited follow-up

- Each fill moves the curve by 1 ÷ (number at risk). With 20 requisitions, the first
  fill is a 5-point step. With 2 at risk, a single fill halves the curve.
- The **right-hand end** of a curve rests on the few requisitions observed that long.
  The at-risk table under each chart shows how many.
- The **95% confidence interval** (shaded band) shows this uncertainty. Wide bands mean
  the sample is too small to pin down the value.
- One statistical detail: when a group has **no fills yet**, lifelines' confidence
  interval formula (Greenwood's formula) gives a zero-width interval such as
  "100% (100%-100%)". That does not mean certainty. There is simply no variation yet
  for the formula to measure.

### 1.9 The key assumption

In plain English:

> Within each group analyzed, censoring should not systematically hide different
> future fill behavior.

In other words, requisitions that are still open should, on average, go on to fill
like the similar requisitions we observed for longer. Kaplan–Meier needs this to treat
censored requisitions as "like the others, just not finished".

A fixed reporting date does **not** guarantee this. Recently approved requisitions are
the ones most likely to be censored. If hiring conditions changed (a hiring freeze, a
new sourcing partner, a tighter labor market), recent requisitions may fill differently
from older ones, and the curve would mix two different periods.

Survival analysis handles the "not finished yet" problem well, but it does **not**
remove every source of bias. Data quality, changes in process, and how cancelled
requisitions are treated all still matter.

### 1.10 Descriptive, not causal

If the Engineering curve sits above the Customer Support curve, Engineering
requisitions **in this data** stayed open longer. That does not prove that job family
*causes* slower hiring. Differences could come from seniority, location mix, approval
timing, recruiter capacity, or chance. This project does not run statistical tests or
regression models.

### 1.11 How to phrase results

Good:

> "An estimated 40% of Sales requisitions remain unfilled 45 days after approval
> (95% CI 17%–63%)."

This is the actual value for Sales in this project's output (see the summary table).
Note how wide the interval is with 19 requisitions.

Not the same thing:

> "A Sales requisition that has already been open for 45 days has a 40% chance of
> staying open another 45 days."

The first sentence is about **all requisitions, measured from approval**. The second
is about requisitions that **have already waited 45 days**. That is a conditional
probability, S(90) ÷ S(45), which this project does not report.

---

## Part 2: Rebuild the project from an empty folder

The commands work in PowerShell and in macOS/Linux terminals. Run them one at a time,
from the project root unless stated otherwise. Forward slashes (`/`) in paths work in
PowerShell too.

### Step 1: Install uv

Follow the [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/).
uv manages the Python version, the virtual environment (`.venv`) and the dependency
lockfile (`uv.lock`).

### Step 2: Scaffold the Python project with the uv CLI

```powershell
mkdir time-to-fill-survival
cd time-to-fill-survival
uv init --bare --name time-to-fill-survival --python 3.12
uv python pin 3.12
uv add dbt-core dbt-duckdb duckdb lifelines pandas matplotlib
uv add --dev ruff
uv run dbt --version
```

What each command does:

- `uv init --bare` creates only `pyproject.toml` (no sample code).
- `uv python pin 3.12` writes `.python-version`. uv downloads Python 3.12 if needed.
- `uv add` installs packages into `.venv`, records them in `pyproject.toml`, and writes
  exact versions to `uv.lock`. Anyone who runs `uv sync` later gets the same versions.
- `uv run <command>` runs a command inside the project environment. You never need to
  activate `.venv` yourself.

Then add a basic Ruff configuration at the end of `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100

[tool.ruff.lint]
# E/F: pycodestyle errors and pyflakes, I: import order, B: common bugs, UP: modern syntax
select = ["E", "F", "I", "B", "UP"]
```

### Step 3: Create the folders

```powershell
mkdir models
mkdir models/staging
mkdir models/marts
mkdir tests
mkdir scripts
mkdir data
mkdir outputs
mkdir docs
```

Create a `.gitignore` so that generated files are not committed: `.venv/`, dbt's
`target/` and `logs/`, and `data/*.duckdb`. See this repository's `.gitignore`.

### Step 4: dbt project and connection

We create the dbt files by hand instead of running `dbt init`. `dbt init` asks
interactive questions, adds example models, and stores the connection profile in your
home folder. Keeping `profiles.yml` inside the project means every command uses the
same local DuckDB file.

**`dbt_project.yml`**: the project settings and the **reporting date**. This is the
only place the date is defined.

```yaml
name: time_to_fill_survival
version: "1.0.0"
profile: time_to_fill_survival

model-paths: ["models"]
test-paths: ["tests"]

vars:
  # The reporting ("as of") date for the whole workflow. It is defined only here.
  # dbt writes it into the mart column analysis_as_of_date, and the Python
  # analysis reads it back from that column.
  analysis_as_of_date: "2026-05-31"

models:
  time_to_fill_survival:
    staging:
      +materialized: view
    marts:
      +materialized: table
```

**`profiles.yml`**: how dbt connects to DuckDB.

```yaml
# dbt finds this file because it sits in the folder where you run dbt.
# The DuckDB path is relative to that folder (the project root).
time_to_fill_survival:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: data/recruitment.duckdb
      schema: analytics
      threads: 1
```

- dbt looks for `profiles.yml` in the current folder first, so **always run dbt from
  the project root**.
- `schema: analytics` means dbt builds its models in the `analytics` schema. The raw
  data lives in a separate `raw` schema.
- `threads: 1` makes dbt run one step at a time. That's plenty for this size and keeps
  DuckDB's single-writer rule simple.

You can check the connection with `uv run dbt debug`.

### Step 5: The synthetic source data

Create **`scripts/create_sample_data.py`** (copy it from this repository). It writes 63
requisitions to `raw.requisitions` with the five source columns: `requisition_id`,
`job_family`, `site`, `approved_date`, `offer_accepted_date`.

How it works:

1. For each of three job families (Customer Support, Sales, Engineering), it creates
   21 requisitions with a random site (Austin or Dublin) and a random approval date
   between 2025-12-01 and 2026-06-08.
2. It draws a **true time to fill** from a log-normal distribution around a typical
   value per family (28, 40 and 60 days). Log-normal gives mostly moderate values and
   a few slow roles, like real hiring.
3. It computes the true acceptance date, then keeps only what an ATS extract pulled
   on **2026-06-10** could contain. Later acceptances become null.

Important design choices:

- **No event flags are generated.** Filled or open is decided later, in dbt, from the
  dates. This matches real data, where status fields can be stale or overwritten.
- **The extract date (2026-06-10) is later than the reporting date (2026-05-31).**
  So the source contains 6 offers accepted after the reporting date and 3 requisitions
  approved after it. That is the "future information" dbt must not use.
- **A fixed random seed (`RANDOM_SEED = 117`)** makes the data identical on every run.
  The seed was chosen because its sample stays close to the simulation settings (each
  family's sample median is within 10% of its typical value). Try a few other seeds:
  with about 20 requisitions per group, some samples differ a lot from the settings.
  This is the small-sample uncertainty that the confidence intervals describe.

Run it:

```powershell
uv run python scripts/create_sample_data.py
```

### Step 6: Source and staging model

**`models/staging/_sources.yml`** declares `raw.requisitions` as a dbt **source** and
adds tests: unique/not-null IDs and required job family, site and approval date. See
the repository file.

**`models/staging/stg_requisitions.sql`**:

```sql
-- Staging: clean types and text only. No business rules here.
-- The reporting cutoff, event flag and duration are defined in the mart.

select
    trim(cast(requisition_id as varchar)) as requisition_id,
    trim(cast(job_family as varchar)) as job_family,
    trim(cast(site as varchar)) as site,
    cast(approved_date as date) as approved_date,
    cast(offer_accepted_date as date) as offer_accepted_date
from {{ source('raw', 'requisitions') }}
```

Staging is deliberately thin. It gives the rest of the project clean, typed columns
and one place to fix source quirks. It is a **view**, so it always shows the current
source data.

### Step 7: The analytical mart

**`models/marts/mart_requisition_survival.sql`** holds all the business rules:

```sql
-- One row per requisition approved on or before the reporting date,
-- prepared for time-to-fill survival analysis.
--
-- Rules (calendar days):
--   start             = approved_date
--   fill event        = first accepted offer, counted only if accepted on or
--                       before the reporting date
--   observation end   = offer_accepted_date if it is an event, otherwise the
--                       reporting date (the requisition is right-censored)
--   duration_days     = observation_end_date - approved_date

{% set analysis_as_of_date = "cast('" ~ var('analysis_as_of_date') ~ "' as date)" %}

with requisitions as (

    select * from {{ ref('stg_requisitions') }}

),

eligible as (

    -- Requisitions approved after the reporting date did not exist yet on that date.
    select
        *,
        {{ analysis_as_of_date }} as analysis_as_of_date
    from requisitions
    where approved_date <= {{ analysis_as_of_date }}

),

flagged as (

    -- An acceptance after the reporting date is future information.
    -- On the reporting date, that requisition was still open.
    select
        *,
        coalesce(offer_accepted_date <= analysis_as_of_date, false) as is_filled_as_of_date
    from eligible

),

observed as (

    select
        *,
        case
            when is_filled_as_of_date then offer_accepted_date
            else analysis_as_of_date
        end as observation_end_date
    from flagged

)

select
    requisition_id,
    job_family,
    site,
    approved_date,
    offer_accepted_date,
    analysis_as_of_date,
    observation_end_date,
    date_diff('day', approved_date, observation_end_date) as duration_days,
    case when is_filled_as_of_date then 1 else 0 end as event_observed,
    case when is_filled_as_of_date then 'Filled' else 'Open' end as status_as_of_date
from observed
```

Step by step:

1. **`eligible`**: keep only requisitions approved on or before the reporting date,
   and stamp the reporting date on every row. `var('analysis_as_of_date')` reads the
   value from `dbt_project.yml`.
2. **`flagged`**: a requisition counts as filled only if its offer was accepted **on or
   before** the reporting date. `coalesce(..., false)` turns a missing acceptance
   (null) into "not filled".
3. **`observed`**: the observation ends at the acceptance date for filled requisitions
   and at the reporting date for open ones.
4. **Final select**: duration in calendar days, the 0/1 event flag Kaplan–Meier needs,
   and a readable status.

`status_as_of_date` is **derived from dates**. We don't copy a "current status" field
from the source, because that field describes today, not the reporting date.

`offer_accepted_date` is kept as the raw source value for auditing, so it can show a
date after the reporting date (see `REQ-1015` below). Analysis must use
`event_observed` and `duration_days`, never this column.

**Worked examples from the actual mart** (reporting date 2026-05-31):

| requisition_id | approved_date | offer_accepted_date | observation_end_date | duration_days | event_observed | status_as_of_date |
|---|---|---|---|---|---|---|
| REQ-1007 (filled) | 2025-12-17 | 2026-01-29 | 2026-01-29 | 43 | 1 | Filled |
| REQ-1043 (open) | 2026-04-06 | null | 2026-05-31 | 55 | 0 | Open |
| REQ-1015 (filled after cutoff) | 2026-01-28 | 2026-06-04 | 2026-05-31 | 123 | 0 | Open |
| REQ-1061 (approved after cutoff) | 2026-06-03 | null | – | – | – | *not in the mart* |

- **REQ-1007:** accepted before the reporting date → a fill after 43 days.
- **REQ-1043:** no acceptance → open, censored at 55 days.
- **REQ-1015:** accepted on 2026-06-04, after the reporting date. On 2026-05-31 it
  was still open, so it is censored at 123 days. Using the June date would be
  **leakage**.
- **REQ-1061:** approved after the reporting date, so it did not exist yet. Excluded.

The sample data has no acceptance exactly **on** the reporting date. That case is
covered by the unit test below (a requisition approved 2026-05-01 and accepted
2026-05-31 is a fill after 30 days).

**`models/marts/mart_requisition_survival.yml`** documents every column and adds tests:
`unique`/`not_null` on the ID, `not_null` on required columns, and `accepted_values`
for `event_observed` (0, 1) and `status_as_of_date` (Filled, Open).

It also contains a **dbt unit test**. A unit test runs the model on a few hand-made
input rows and compares the output with expected rows. This one checks the cutoff
edge cases:

| Input | Expected |
|---|---|
| Approved 2026-03-01, accepted 2026-04-10 | Filled, 40 days |
| Approved 2026-05-01, accepted **2026-05-31** (on the cutoff) | Filled, 30 days |
| Approved 2026-04-15, accepted **2026-06-05** (after the cutoff) | Open, 46 days |
| Approved 2026-04-01, never accepted | Open, 60 days |
| Approved **2026-06-03** (after the cutoff) | Not in the output |

The unit test sets its own reporting date (`overrides: vars:`), so it keeps working
when you change the project's reporting date.

### Step 8: Singular tests

Files in `tests/` are **singular tests**: SQL queries that return the rows that break
a rule. The test passes when the query returns nothing.

**`tests/assert_observation_end_not_after_as_of_date.sql`**:

```sql
-- We cannot observe a requisition beyond the reporting date.
select
    requisition_id,
    observation_end_date,
    analysis_as_of_date
from {{ ref('mart_requisition_survival') }}
where observation_end_date > analysis_as_of_date
```

The other three:

- `assert_acceptance_not_before_approval.sql`: no offer is accepted before approval.
- `assert_duration_days_nonnegative.sql`: no negative durations.
- `assert_counts_reconcile.sql`: every eligible requisition appears once in the mart,
  and filled + censored = total.

### Step 9: Build and test with dbt

```powershell
uv run dbt build
```

`dbt build` runs everything in dependency order: source tests → staging view → unit
test → mart table → mart tests. If a test fails, dbt skips the steps that depend on
it. Expected ending: `PASS=26 WARN=0 ERROR=0`.

Optional: look at the mart from Python.

```powershell
uv run python -c "import duckdb; print(duckdb.connect('data/recruitment.duckdb', read_only=True).sql('select * from analytics.mart_requisition_survival limit 5'))"
```

### Step 10: The survival analysis script

Create **`scripts/run_survival_analysis.py`** (copy it from this repository). Its parts:

| Function | What it does |
|---|---|
| `load_mart` | Reads the mart from DuckDB in **read-only** mode |
| `get_as_of_date` | Reads the reporting date from the mart (checks there is exactly one) |
| `fit_kaplan_meier` | Fits `lifelines.KaplanMeierFitter` on `duration_days` and `event_observed` with 95% intervals |
| `check_survival_curve` | Stops if a curve goes outside 0–1 or ever increases |
| `unfilled_after` | Reads the curve at day 30/45/60, or returns "Insufficient follow-up" beyond the longest observed duration |
| `summarize` | Builds one summary row: counts, filled-only mean/median, KM median, day 30/45/60 estimates |
| `plot_overall`, `plot_by_job_family` | Draw the curves with confidence bands, censoring ticks and at-risk tables |

Note what the script does **not** do. It does not filter by date, flag events or
compute durations. Those rules live in dbt.

Run it:

```powershell
uv run python scripts/run_survival_analysis.py
```

### Step 11: Lint

```powershell
uv run ruff check .
uv run ruff format --check .
```

`ruff check` finds common mistakes and unused imports. `ruff format --check` confirms
consistent formatting. Run `uv run ruff format .` to fix formatting.

### Which work belongs where?

| Belongs in dbt | Belongs in Python |
|---|---|
| Business definitions (start, event, cutoff, duration) | Statistical estimation (Kaplan–Meier, confidence intervals) |
| Eligibility and leakage prevention | Rules about what the estimate can support (follow-up, median) |
| Data tests that must pass before anyone uses the data | Lightweight checks of the model output |
| One reusable table for BI, SQL users and Python | Charts and presentation tables |

Rule of thumb: if a SQL analyst and a Python analyst should get the **same number of
filled and open requisitions**, the rule belongs in dbt.

---

## Part 3: Read the results

### The charts

Start with `outputs/km_overall.png`, then `outputs/km_by_job_family.png`.

1. **Read up from the day** you care about (30, 45, 60 have grey guide lines) to the
   curve, then across to the vertical axis. That is the estimated share still unfilled.
2. **Read across from 50%** to where the curve crosses it, then down. That is the
   estimated median time to fill.
3. **Check the band.** If the confidence bands of two groups overlap a lot, the data
   cannot clearly separate them.
4. **Check the at-risk table.** Where only a few requisitions are at risk, each step
   is large and the estimate is fragile.
5. **Look at the tick marks.** Many ticks early on mean many young, open requisitions.
   The curve's right side then rests on older requisitions only.

### The summary table

Compare `filled_only_median_days` with `km_median_days`, group by group. In this sample:

| Group | Open (censored) | Filled-only median | KM median |
|---|---|---|---|
| All requisitions | 17 of 60 | 40 days | 44 days |
| Customer Support | 3 of 20 | 26 days | 26 days |
| Sales | 6 of 19 | 43 days | 44 days |
| Engineering | 8 of 21 | 51 days | 65 days |

The gap is largest where the most requisitions are still open, and especially where
some of them are already old (Engineering has open requisitions at 113 and 123 days).
Filled-only statistics can't see those requisitions. Kaplan–Meier includes them for as
long as they were observed.

A useful way to open a discussion with a hiring team:

> "In this synthetic example, about 44% of requisitions were still unfilled 45 days after
> approval (95% CI 30%–57%). For Engineering the estimate is 71% (43%–87%). The
> filled-only median of 51 days for Engineering leaves out 8 open requisitions, two of
> them open for more than 110 days."

That supports conversations such as: which roles need an earlier sourcing plan, and is
a 45-day target realistic for every job family? With real data, a small sample and
wide intervals are a reason to **collect more data before setting targets**, not a
reason to pick the most convenient number.

### Change the reporting date and rerun

The reporting date is defined once, in `dbt_project.yml`
(`analysis_as_of_date: "2026-05-31"`).

**Option A: permanent change.** Edit the value in `dbt_project.yml`, then run:

```powershell
uv run dbt build
uv run python scripts/run_survival_analysis.py
```

**Option B: one-off run.** Override the variable on the command line:

```powershell
uv run dbt build --vars "analysis_as_of_date: 2026-01-31"
uv run python scripts/run_survival_analysis.py
```

The next plain `uv run dbt build` goes back to the date in `dbt_project.yml`.

Notes:

- You do **not** need to regenerate the source data or change the Python script.
  Python reads the date from the mart column `analysis_as_of_date`.
- The output files in `outputs/` are overwritten. Run the default date again to
  restore them.
- **Stay on or before 2026-06-10**, the simulated extract date. After that date the
  source has no information, and open requisitions would look observed for days
  nobody actually observed.

What to expect with an earlier date: fewer requisitions and shorter follow-up. For
example, with `2026-01-31` only 17 requisitions are eligible, and every group shows
"Insufficient follow-up" at 60 days. With `2026-01-20`, the overall median shows "Not
reached within observed follow-up". These are the honest answers when the data is too
young. Comparing reporting dates shows how estimates settle as more requisitions
finish.

---

## Where this could go next (outside this project's scope)

- A written policy for cancelled requisitions, possibly with competing-risk methods.
- Cox regression to look at several factors together (job family, site, seniority).
- Statistical tests for group differences.
- Real ATS data with status history, so holds and reopenings can be handled.
