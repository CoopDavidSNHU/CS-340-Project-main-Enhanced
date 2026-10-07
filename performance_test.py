"""
Performance and verification test for the enhanced AnimalShelter class.

For each rescue type, this script will:
  1. Compare csv used by a forced collection scan vs the indexed query.
  2. Compare the original approach (pull everything into Pandas and filter)
     with the new server side aggregation pipeline (time and data transferred).
  3. Verifies the results are correct.

"""

import time

import bson
import pandas as pd

from animal_shelter import AnimalShelter, RESCUE_FILTERS

shelter = AnimalShelter()


def size_mb(docs):
    """Size of a list of documents in megabytes."""
    return sum(len(bson.encode(d)) for d in docs) / 1_048_576


def explain_find(match, hint=None):
    """
    Run explain (executionStats) on a find query.
    Returns (csv examined, execution time in ms).
    """
    cmd = {"find": shelter.collection.name, "filter": match}
    if hint:
        cmd["hint"] = hint

    stats = shelter.database.command(
        {"explain": cmd, "verbosity": "executionStats"}
    )["executionStats"]

    return stats["totalDocsExamined"], stats["executionTimeMillis"]


def legacy(rule):
    """
    Original approach: fetch every document, then filter with Pandas.
    Returns (matching rows, seconds taken, MB transferred from the database).
    """
    start = time.perf_counter()

    docs = shelter.read({})  # everything being read
    df = pd.DataFrame.from_records(docs)
    df["age_in_weeks"] = pd.to_numeric(
        df["age_upon_outcome_in_weeks"], errors="coerce"
    )

    mask = (
        df["breed"].isin(rule["breeds"])
        & (df["sex_upon_outcome"] == rule["sex"])
        & (df["age_in_weeks"] >= rule["min_weeks"])
    )
    if rule["max_weeks"] is not None:
        mask &= df["age_in_weeks"] <= rule["max_weeks"]

    result = df[mask]
    return len(result), time.perf_counter() - start, size_mb(docs)


for name, rule in RESCUE_FILTERS.items():
    match = shelter._build_match(name)

    #Index vs collection scan
    scan_docs, scan_ms = explain_find(match, hint={"$natural": 1})
    idx_docs, idx_ms = explain_find(match)
    print(f"\n{name}")
    print(f"  docs examined: scan={scan_docs} ({scan_ms} ms)  "
          f"indexed={idx_docs} ({idx_ms} ms)")

    # Legacy Pandas filtering vs aggregation pipeline
    old_count, old_secs, old_mb = legacy(rule)

    start = time.perf_counter()
    rows = shelter.read_rescue_filter(name)
    new_secs = time.perf_counter() - start

    print(f"  legacy:      {old_count} rows, {old_secs:.2f}s, "
          f"{old_mb:.2f} MB transferred")
    print(f"  aggregation: {len(rows)} rows, {new_secs:.2f}s, "
          f"{size_mb(rows) * 1024:.1f} KB transferred")

    # 3. Verification checks
    assert len(rows) == old_count, "row counts differ"

    # An empty result is valid (for example, no Water Rescue matches)
    if rows:
        # Calculated and key fields must be present
        for field in ["age_in_weeks", "age_in_years", "breed", "sex_upon_outcome"]:
            assert field in rows[0], f"missing {field}"

        # Every returned row must meet the rescue rules
        assert all(r["sex_upon_outcome"] == rule["sex"] for r in rows)
        assert all(r["breed"] in rule["breeds"] for r in rows)
        assert all(r["age_in_weeks"] >= rule["min_weeks"] for r in rows)
        if rule["max_weeks"] is not None:
            assert all(r["age_in_weeks"] <= rule["max_weeks"] for r in rows)

    print("  checks passed")