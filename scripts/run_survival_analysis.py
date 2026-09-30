"""Kaplan-Meier time-to-fill analysis.

Reads the dbt mart analytics.mart_requisition_survival from DuckDB, fits
Kaplan-Meier survival curves, and writes to outputs/:
- km_overall.png              one curve for all requisitions
- km_by_job_family.png        one curve per job family
- time_to_fill_summary.csv    summary table (overall + each job family)

All business rules (eligibility, fill event, duration) live in dbt. This
script uses duration_days and event_observed exactly as the mart provides them.

Run from the project root, after `uv run dbt build`:
    uv run python scripts/run_survival_analysis.py
"""

from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import pandas as pd
from lifelines import KaplanMeierFitter
from lifelines.plotting import add_at_risk_counts
from matplotlib.ticker import PercentFormatter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "recruitment.duckdb"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
MART_TABLE = "analytics.mart_requisition_survival"

CHECKPOINT_DAYS = (30, 45, 60)
OVERALL_LABEL = "All requisitions"
NOT_REACHED = "Not reached within observed follow-up"
INSUFFICIENT_FOLLOW_UP = "Insufficient follow-up"
NO_FILLS = "No fills yet"

# Chart colors. Series colors come in a fixed order that stays distinguishable
# for common types of color blindness. Text and gridlines use neutral grays.
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a"]
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
TEXT_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
AXIS_LINE = "#c3c2b7"


# --------------------------------------------------------------------------
# Load and check
# --------------------------------------------------------------------------


def load_mart() -> pd.DataFrame:
    if not DB_PATH.exists():
        raise SystemExit(
            f"Database not found: {DB_PATH}\n"
            "Run `uv run python scripts/create_sample_data.py` and `uv run dbt build` first."
        )
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        return con.execute(f"select * from {MART_TABLE} order by requisition_id").df()


def get_as_of_date(mart: pd.DataFrame) -> str:
    """The reporting date comes from the mart, so it always matches what dbt used."""
    as_of_dates = mart["analysis_as_of_date"].unique()
    if len(as_of_dates) != 1:
        raise ValueError(f"Expected one analysis_as_of_date, found {len(as_of_dates)}.")
    return pd.Timestamp(as_of_dates[0]).date().isoformat()


def check_survival_curve(kmf: KaplanMeierFitter) -> None:
    """Survival probabilities must stay between 0 and 1 and never increase."""
    survival = kmf.survival_function_.iloc[:, 0]
    if not survival.between(0, 1).all():
        raise ValueError(f"{kmf.label}: survival probability outside 0-1.")
    if not survival.is_monotonic_decreasing:  # pandas: "never increases"
        raise ValueError(f"{kmf.label}: survival probability increases over time.")


# --------------------------------------------------------------------------
# Kaplan-Meier fit and summary
# --------------------------------------------------------------------------


def fit_kaplan_meier(requisitions: pd.DataFrame, label: str) -> KaplanMeierFitter:
    kmf = KaplanMeierFitter(alpha=0.05)  # alpha=0.05 gives 95% confidence intervals
    kmf.fit(
        durations=requisitions["duration_days"],
        event_observed=requisitions["event_observed"],
        label=label,
    )
    check_survival_curve(kmf)
    return kmf


def value_at(step_function: pd.DataFrame, day: int) -> pd.Series:
    """Read a Kaplan-Meier step function at a given day (last step on or before it)."""
    return step_function.loc[:day].iloc[-1]


def unfilled_after(kmf: KaplanMeierFitter, longest_observed_days: int, day: int) -> str:
    """Estimated share still unfilled after `day` days, with its 95% confidence interval.

    Beyond the longest observed duration the curve is only carried forward
    flat, which the data does not support, so we refuse to report a number.
    """
    if day > longest_observed_days:
        return INSUFFICIENT_FOLLOW_UP
    estimate = value_at(kmf.survival_function_, day).iloc[0]
    lower, upper = value_at(kmf.confidence_interval_survival_function_, day)
    return f"{estimate:.0%} ({lower:.0%}-{upper:.0%})"


def summarize(requisitions: pd.DataFrame, kmf: KaplanMeierFitter, label: str) -> dict:
    filled = requisitions.loc[requisitions["event_observed"] == 1, "duration_days"]
    longest_observed_days = int(requisitions["duration_days"].max())
    km_median = kmf.median_survival_time_  # infinite if the curve never reaches 50%

    summary = {
        "group": label,
        "requisitions": len(requisitions),
        "filled_by_as_of_date": len(filled),
        "open_right_censored": int((requisitions["event_observed"] == 0).sum()),
        "longest_observed_days": longest_observed_days,
        # Filled-only statistics: they ignore requisitions that are still open.
        "filled_only_mean_days": round(filled.mean(), 1) if len(filled) else NO_FILLS,
        "filled_only_median_days": round(filled.median(), 1) if len(filled) else NO_FILLS,
        # Kaplan-Meier estimates: they also use what we know about open requisitions.
        "km_median_days": NOT_REACHED if km_median == float("inf") else round(km_median),
    }
    for day in CHECKPOINT_DAYS:
        summary[f"km_unfilled_after_{day}d"] = unfilled_after(kmf, longest_observed_days, day)
    return summary


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------


def set_chart_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "font.family": "sans-serif",
            "font.size": 10,
            "text.color": TEXT_PRIMARY,
            "axes.labelcolor": TEXT_SECONDARY,
            "axes.edgecolor": AXIS_LINE,
            "xtick.color": TEXT_MUTED,
            "ytick.color": TEXT_MUTED,
            "xtick.labelcolor": TEXT_SECONDARY,
            "ytick.labelcolor": TEXT_SECONDARY,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "legend.frameon": False,
        }
    )


def draw_curve(ax: plt.Axes, kmf: KaplanMeierFitter, color: str) -> None:
    kmf.plot_survival_function(
        ax=ax,
        color=color,
        linewidth=2,
        ci_show=True,  # shaded 95% confidence interval
        ci_alpha=0.12,
        show_censors=True,  # tick marks where open requisitions leave the data
        censor_styles={"marker": "|", "ms": 9, "mew": 1.5},
        legend=False,
    )


def finish_chart(ax: plt.Axes, fitters: list, title: str, subtitle: str, max_day: int) -> None:
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", pad=26)
    ax.text(0, 1.03, subtitle, transform=ax.transAxes, color=TEXT_SECONDARY, fontsize=9.5)
    ax.set_xlabel("Days since requisition approval")
    ax.set_ylabel("Estimated probability of remaining unfilled")
    ax.set_ylim(0, 1.02)
    ax.set_xlim(0, max_day + 5)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.grid(axis="y", color=GRIDLINE, linewidth=0.8)
    ax.set_axisbelow(True)

    # Reference lines: the 50% line (median) and the checkpoint days.
    ax.axhline(0.5, color=AXIS_LINE, linewidth=1, zorder=0)
    ax.text(max_day + 4, 0.515, "50% (median)", ha="right", color=TEXT_MUTED, fontsize=8.5)
    for day in CHECKPOINT_DAYS:
        if day <= max_day:
            ax.axvline(day, color=GRIDLINE, linewidth=1, zorder=0)

    # At-risk table under the chart, with columns at the checkpoint days.
    xticks = [0, *CHECKPOINT_DAYS, *range(90, max_day + 1, 30)]
    ax.set_xticks([tick for tick in xticks if tick <= max_day])
    add_at_risk_counts(*fitters, ax=ax, rows_to_show=["At risk", "Events", "Censored"])


def plot_overall(kmf: KaplanMeierFitter, as_of_date: str, max_day: int, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 6.2))
    draw_curve(ax, kmf, SERIES_COLORS[0])
    finish_chart(
        ax,
        [kmf],
        title="Time to fill: all requisitions (Kaplan-Meier)",
        subtitle=(
            f"As of {as_of_date}. Line = estimate, shaded band = 95% confidence interval, "
            "tick marks = requisitions still open (censored)."
        ),
        max_day=max_day,
    )
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_by_job_family(fitters: list, as_of_date: str, max_day: int, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 7.4))
    for kmf, color in zip(fitters, SERIES_COLORS, strict=True):
        draw_curve(ax, kmf, color)
    ax.legend(
        handles=[line for line in ax.get_lines() if not line.get_label().startswith("_")],
        loc="upper right",
        title="Job family",
        alignment="left",
    )
    finish_chart(
        ax,
        fitters,
        title="Time to fill by job family (Kaplan-Meier)",
        subtitle=(
            f"As of {as_of_date}. Shaded bands = 95% confidence intervals, "
            "tick marks = requisitions still open (censored)."
        ),
        max_day=max_day,
    )
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main() -> None:
    plt.switch_backend("Agg")  # write PNG files only, never open a window
    set_chart_style()
    OUTPUT_DIR.mkdir(exist_ok=True)

    mart = load_mart()
    as_of_date = get_as_of_date(mart)
    max_day = int(mart["duration_days"].max())

    overall_kmf = fit_kaplan_meier(mart, OVERALL_LABEL)
    summaries = [summarize(mart, overall_kmf, OVERALL_LABEL)]

    family_fitters = []
    for job_family, requisitions in mart.groupby("job_family", sort=True):
        kmf = fit_kaplan_meier(requisitions, f"{job_family} (n={len(requisitions)})")
        family_fitters.append(kmf)
        summaries.append(summarize(requisitions, kmf, job_family))

    summary = pd.DataFrame(summaries)
    if not (summary["filled_by_as_of_date"] + summary["open_right_censored"]).equals(
        summary["requisitions"]
    ):
        raise ValueError("Filled + censored does not add up to total requisitions.")

    summary_path = OUTPUT_DIR / "time_to_fill_summary.csv"
    summary.to_csv(summary_path, index=False)
    plot_overall(overall_kmf, as_of_date, max_day, OUTPUT_DIR / "km_overall.png")
    plot_by_job_family(family_fitters, as_of_date, max_day, OUTPUT_DIR / "km_by_job_family.png")

    print(f"Time-to-fill survival summary, as of {as_of_date}")
    print("filled_only_* : only requisitions filled by the as-of date (open ones are ignored)")
    print("km_*          : Kaplan-Meier estimates that also use open (censored) requisitions")
    print("km_unfilled_after_Nd : estimate (95% confidence interval)\n")
    print(summary.set_index("group").T.to_string())
    print(f"\nWrote {summary_path.relative_to(PROJECT_ROOT)}")
    print("Wrote outputs/km_overall.png")
    print("Wrote outputs/km_by_job_family.png")


if __name__ == "__main__":
    main()
