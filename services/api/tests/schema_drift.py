"""
Revision-aware ORM-vs-database drift helper for the migration tests.

What:
    Each migration test compares the ORM metadata with the schema of ITS OWN
    revision. Objects introduced by LATER stages are already declared in the
    ORM, so they show up as differences against an older revision. This helper
    removes exactly the differences that belong to a stage introduced after the
    tested revision - nothing else.

Why:
    A blanket "ignore unknown tables/indexes/constraints" filter would hide
    real, unrelated drift. Here every excluded object is named explicitly and
    tied to the revision that introduced it, so a difference that does not
    belong to a later stage still fails the test.
"""

from typing import Any, List, Sequence

# Ordered stage registry: (introducing revision, object names whose
# differences are expected before that revision is applied).
LATER_STAGES = (
    # VF-020E2: financial_events (mapped by VF-020E3).
    ("115998e2e795", ("financial_events",)),
    # VF-020E4: the budgets composite unique and the two rules tables (mapped
    # by VF-020E5).
    ("861064d31463", ("uq_budgets_id_user_id", "financial_rules", "financial_rule_goal_targets")),
    # VF-020E6: the execution tables, goal_transactions.rule_execution_id (with
    # its foreign key and index) and the goal_transactions ownership unique key.
    # The CHECK replacement is not diffed by compare_metadata.
    ("e0503e9ca9d3", (
        "rule_executions", "rule_execution_items", "rule_execution_audit",
        "rule_execution_id", "uq_goal_transactions_id_user_id",
    )),
    # VF-020E9A: the rule_alerts table (its constraints and indexes carry the
    # table name, so they are matched by name).
    ("a7c3e91d5b24", ("rule_alerts",)),
    # VF-020E10: the alert_dispatch_progress table (and its constraints/indexes,
    # which carry the table name). The sequence is not diffed by compare_metadata.
    ("c4d8a2f6e193", ("alert_dispatch_progress",)),
)

REVISION_ORDER = (
    "98acdc7016d2",
    "4d2f7b91a6c3",
    "7c1e5a9b3d28",
    "115998e2e795",
    "861064d31463",
    "e0503e9ca9d3",
    "a7c3e91d5b24",
    "c4d8a2f6e193",
)


def _names_for_stages_after(revision: str) -> List[str]:
    position = REVISION_ORDER.index(revision)
    names: List[str] = []
    for stage_revision, stage_names in LATER_STAGES:
        if REVISION_ORDER.index(stage_revision) > position:
            names.extend(stage_names)
    return names


def _matches(difference: Any, names: Sequence[str]) -> bool:
    text = repr(difference)
    # Constraints do not carry their name in their repr, so also compare the
    # explicit name of the difference's subject.
    subject_name = None
    if isinstance(difference, tuple) and len(difference) > 1:
        subject_name = getattr(difference[1], "name", None)
    return any(name in text for name in names) or (
        subject_name is not None and subject_name in names
    )


# Removes only the differences that belong to stages introduced AFTER
# `revision`. For a database at the latest stage nothing is removed.
def exclude_stages_after(differences: Sequence[Any], revision: str) -> List[Any]:
    names = _names_for_stages_after(revision)
    return [difference for difference in differences if not _matches(difference, names)]
