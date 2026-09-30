"""Create a small synthetic requisition table in DuckDB: raw.requisitions.

The table imitates an extract from an applicant tracking system (ATS).

How the data is made:
1. Pick an approval date for each requisition.
2. Simulate how many days it takes to accept the first offer, and from that
   the "true" acceptance date.
3. Keep only what the source system could know on the day the extract was
   pulled (SOURCE_EXTRACT_DATE). Acceptances after that day are still in the
   future, so they are stored as null.

This script does not create event flags or durations. dbt derives them from
the dates and the reporting date (see dbt_project.yml).

Run from the project root:
    uv run python scripts/create_sample_data.py
"""

import random
from datetime import date, timedelta
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "recruitment.duckdb"

# Any fixed seed makes the data reproducible. This one was picked because its
# sample stays close to the settings below (each job family's sample median is
# within 10% of its typical value). With ~20 requisitions per group, some other
# seeds give samples that differ a lot from the settings. Try it and compare.
RANDOM_SEED = 117

FIRST_APPROVAL_DATE = date(2025, 12, 1)
LAST_APPROVAL_DATE = date(2026, 6, 8)

# The day the simulated ATS extract was pulled. It is ten days after the
# reporting date on purpose, so the source contains:
# - a few offers accepted after the reporting date, and
# - a few requisitions approved after the reporting date.
# dbt must ignore that "future" information when it builds the mart.
SOURCE_EXTRACT_DATE = date(2026, 6, 10)

# Typical (median) days from approval to accepted offer, per job family.
# These are made-up values for the demo, not benchmarks.
TYPICAL_DAYS_TO_FILL = {
    "Customer Support": 28,
    "Sales": 40,
    "Engineering": 60,
}
REQUISITIONS_PER_JOB_FAMILY = 21
SITES = ["Austin", "Dublin"]

# Spread of days to fill around the typical value (log-normal sigma).
# 0.5 means most fills land between roughly 0.4x and 2.7x the typical value.
DAYS_TO_FILL_SPREAD = 0.5
MINIMUM_DAYS_TO_FILL = 5


def simulate_requisitions(rng: random.Random) -> list[tuple]:
    """Return one tuple per requisition, ready to insert into raw.requisitions."""
    approval_window_days = (LAST_APPROVAL_DATE - FIRST_APPROVAL_DATE).days
    simulated = []

    for job_family, typical_days in TYPICAL_DAYS_TO_FILL.items():
        for _ in range(REQUISITIONS_PER_JOB_FAMILY):
            site = rng.choice(SITES)
            approved_date = FIRST_APPROVAL_DATE + timedelta(
                days=rng.randint(0, approval_window_days)
            )

            # Step 2: the true time to fill. A log-normal distribution gives
            # mostly moderate values plus a few slow, hard-to-fill roles.
            days_to_fill = max(
                MINIMUM_DAYS_TO_FILL,
                round(rng.lognormvariate(0, DAYS_TO_FILL_SPREAD) * typical_days),
            )
            true_accepted_date = approved_date + timedelta(days=days_to_fill)

            # Step 3: the extract cannot contain events that have not happened yet.
            if true_accepted_date <= SOURCE_EXTRACT_DATE:
                offer_accepted_date = true_accepted_date
            else:
                offer_accepted_date = None

            simulated.append((job_family, site, approved_date, offer_accepted_date))

    # Number requisitions in approval order, like an ATS would.
    simulated.sort(key=lambda row: (row[2], row[0]))
    return [
        (f"REQ-{1001 + index}", job_family, site, approved_date, offer_accepted_date)
        for index, (job_family, site, approved_date, offer_accepted_date) in enumerate(simulated)
    ]


def main() -> None:
    rows = simulate_requisitions(random.Random(RANDOM_SEED))

    DB_PATH.parent.mkdir(exist_ok=True)
    with duckdb.connect(str(DB_PATH)) as con:
        con.execute("create schema if not exists raw")
        con.execute(
            """
            create or replace table raw.requisitions (
                requisition_id      varchar,
                job_family          varchar,
                site                varchar,
                approved_date       date,
                offer_accepted_date date
            )
            """
        )
        con.executemany("insert into raw.requisitions values (?, ?, ?, ?, ?)", rows)

    with_acceptance = sum(1 for row in rows if row[4] is not None)
    print(f"Wrote {len(rows)} requisitions to raw.requisitions in {DB_PATH}")
    print(f"  Simulated source extract date: {SOURCE_EXTRACT_DATE}")
    print(f"  With an accepted offer in the extract: {with_acceptance}")
    print(f"  Without an accepted offer yet:         {len(rows) - with_acceptance}")
    print("Next step: uv run dbt build")


if __name__ == "__main__":
    main()
