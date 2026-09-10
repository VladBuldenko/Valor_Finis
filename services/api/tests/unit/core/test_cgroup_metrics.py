from pathlib import Path

import pytest
from pytest import MonkeyPatch

from app.core import cgroup_metrics
from app.core.cgroup_metrics import (
    UNAVAILABLE,
    UNLIMITED,
    cpu_metric_delta,
    read_cgroup_cpu_metrics,
)


# Points cgroup_metrics at a fake cgroup filesystem rooted at tmp_path,
# instead of the real /sys/fs/cgroup.
# This function exists to let every test below build a small, explicit
# fake cgroup layout without touching the real filesystem, since
# cgroup_metrics looks up its root fresh (via the _CGROUP_ROOT module
# attribute) on every read instead of pre-joining paths at import time.
# Parameters:
# - tmp_path: temporary directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the module's cgroup root.
# Returns:
# - The fake cgroup root directory.
def _use_fake_cgroup_root(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> Path:
    monkeypatch.setattr(cgroup_metrics, "_CGROUP_ROOT", tmp_path)

    return tmp_path


# ---------------------------------------------------------------------------
# cgroup v2 (unified hierarchy)
# ---------------------------------------------------------------------------


# Verifies that a limited cgroup v2 CPU quota and cpu.stat throttling
# counters are parsed correctly.
# This test exists to confirm the core "confirm Render CPU throttling"
# use case: a numeric quota/period and real throttling counters are
# read as plain integers, not left as placeholders.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the cgroup root.
# Returns:
# - None.
def test_read_cgroup_cpu_metrics_parses_v2_limited_quota(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    cgroup_root = _use_fake_cgroup_root(tmp_path, monkeypatch)

    (cgroup_root / "cgroup.controllers").write_text("cpu io memory\n")
    (cgroup_root / "cpu.max").write_text("50000 100000\n")
    (cgroup_root / "cpu.stat").write_text(
        "usage_usec 1234567\n"
        "user_usec 1000000\n"
        "system_usec 234567\n"
        "nr_periods 42\n"
        "nr_throttled 7\n"
        "throttled_usec 999000\n"
    )

    metrics = read_cgroup_cpu_metrics()

    assert metrics.cgroup_version == "v2"
    assert metrics.quota_us == 50000
    assert metrics.period_us == 100000
    assert metrics.nr_periods == 42
    assert metrics.nr_throttled == 7
    assert metrics.throttled_usec == 999000
    assert metrics.usage_usec == 1234567


# Verifies that an unlimited cgroup v2 CPU quota ("max" in cpu.max) is
# reported as the safe UNLIMITED placeholder instead of being treated as
# a parse failure.
# This test exists because the task explicitly requires that a "max"
# quota be reported safely, distinct from an unreadable/missing value.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the cgroup root.
# Returns:
# - None.
def test_read_cgroup_cpu_metrics_reports_v2_unlimited_quota_as_max(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    cgroup_root = _use_fake_cgroup_root(tmp_path, monkeypatch)

    (cgroup_root / "cgroup.controllers").write_text("cpu io memory\n")
    (cgroup_root / "cpu.max").write_text("max 100000\n")
    (cgroup_root / "cpu.stat").write_text(
        "usage_usec 100\nnr_periods 0\nnr_throttled 0\nthrottled_usec 0\n"
    )

    metrics = read_cgroup_cpu_metrics()

    assert metrics.cgroup_version == "v2"
    assert metrics.quota_us == UNLIMITED
    assert metrics.period_us == 100000


# Verifies that a missing cpu.stat file under cgroup v2 degrades the
# throttling fields to UNAVAILABLE without raising, while the quota (a
# separate file) is still read correctly.
# This test exists to confirm partial-failure safety: one missing file
# must not take down every other metric.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the cgroup root.
# Returns:
# - None.
def test_read_cgroup_cpu_metrics_v2_missing_stat_file_is_unavailable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    cgroup_root = _use_fake_cgroup_root(tmp_path, monkeypatch)

    (cgroup_root / "cgroup.controllers").write_text("cpu io memory\n")
    (cgroup_root / "cpu.max").write_text("50000 100000\n")
    # cpu.stat intentionally not created.

    metrics = read_cgroup_cpu_metrics()

    assert metrics.cgroup_version == "v2"
    assert metrics.quota_us == 50000
    assert metrics.nr_periods == UNAVAILABLE
    assert metrics.nr_throttled == UNAVAILABLE
    assert metrics.throttled_usec == UNAVAILABLE
    assert metrics.usage_usec == UNAVAILABLE


# Verifies that an unreadable cpu.max (simulated as a directory instead
# of a file, so reading it raises IsADirectoryError/OSError) degrades to
# UNAVAILABLE instead of raising out of read_cgroup_cpu_metrics().
# This test exists to confirm the task's explicit requirement that
# permission/read errors "must never break OCR processing".
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the cgroup root.
# Returns:
# - None.
def test_read_cgroup_cpu_metrics_v2_unreadable_quota_file_is_unavailable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    cgroup_root = _use_fake_cgroup_root(tmp_path, monkeypatch)

    (cgroup_root / "cgroup.controllers").write_text("cpu io memory\n")
    # A directory named "cpu.max" makes Path.read_text() raise
    # IsADirectoryError, an OSError subclass - the same failure family
    # as a permission error would raise.
    (cgroup_root / "cpu.max").mkdir()

    metrics = read_cgroup_cpu_metrics()

    assert metrics.cgroup_version == "v2"
    assert metrics.quota_us == UNAVAILABLE
    assert metrics.period_us == UNAVAILABLE


# ---------------------------------------------------------------------------
# cgroup v1 (separate cpu/cpuacct hierarchies)
# ---------------------------------------------------------------------------


# Verifies that a limited cgroup v1 quota/period, throttling counters
# (converted from nanoseconds to microseconds), and cpuacct usage
# (also converted from nanoseconds) are parsed correctly from the
# unmerged "cpu"/"cpuacct" mount layout.
# This test exists to confirm cgroup v1 support, required because Render
# (or any given host) is not guaranteed to expose cgroup v2.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the cgroup root.
# Returns:
# - None.
def test_read_cgroup_cpu_metrics_parses_v1_unmerged_layout(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    cgroup_root = _use_fake_cgroup_root(tmp_path, monkeypatch)

    # No cgroup.controllers file, so v1 detection is used.
    cpu_dir = cgroup_root / "cpu"
    cpu_dir.mkdir()
    (cpu_dir / "cpu.cfs_quota_us").write_text("50000\n")
    (cpu_dir / "cpu.cfs_period_us").write_text("100000\n")
    (cpu_dir / "cpu.stat").write_text(
        "nr_periods 10\nnr_throttled 3\nthrottled_time 5000000\n"
    )

    cpuacct_dir = cgroup_root / "cpuacct"
    cpuacct_dir.mkdir()
    (cpuacct_dir / "cpuacct.usage").write_text("2000000000\n")

    metrics = read_cgroup_cpu_metrics()

    assert metrics.cgroup_version == "v1"
    assert metrics.quota_us == 50000
    assert metrics.period_us == 100000
    assert metrics.nr_periods == 10
    assert metrics.nr_throttled == 3
    # throttled_time is in nanoseconds (5,000,000 ns = 5,000 usec).
    assert metrics.throttled_usec == 5000
    # cpuacct.usage is in nanoseconds (2,000,000,000 ns = 2,000,000 usec).
    assert metrics.usage_usec == 2_000_000


# Verifies that the comounted "cpu,cpuacct" cgroup v1 layout (used by
# some distributions instead of separate "cpu"/"cpuacct" directories) is
# also supported.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the cgroup root.
# Returns:
# - None.
def test_read_cgroup_cpu_metrics_parses_v1_comounted_layout(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    cgroup_root = _use_fake_cgroup_root(tmp_path, monkeypatch)

    comounted_dir = cgroup_root / "cpu,cpuacct"
    comounted_dir.mkdir()
    (comounted_dir / "cpu.cfs_quota_us").write_text("25000\n")
    (comounted_dir / "cpu.cfs_period_us").write_text("100000\n")
    (comounted_dir / "cpu.stat").write_text(
        "nr_periods 4\nnr_throttled 1\nthrottled_time 1000000\n"
    )
    (comounted_dir / "cpuacct.usage").write_text("500000000\n")

    metrics = read_cgroup_cpu_metrics()

    assert metrics.cgroup_version == "v1"
    assert metrics.quota_us == 25000
    assert metrics.throttled_usec == 1000
    assert metrics.usage_usec == 500_000


# Verifies that an unlimited cgroup v1 quota (-1 in cpu.cfs_quota_us) is
# reported as the same safe UNLIMITED placeholder used for cgroup v2's
# "max", so callers do not need to special-case the cgroup version.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the cgroup root.
# Returns:
# - None.
def test_read_cgroup_cpu_metrics_reports_v1_unlimited_quota_as_max(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    cgroup_root = _use_fake_cgroup_root(tmp_path, monkeypatch)

    cpu_dir = cgroup_root / "cpu"
    cpu_dir.mkdir()
    (cpu_dir / "cpu.cfs_quota_us").write_text("-1\n")
    (cpu_dir / "cpu.cfs_period_us").write_text("100000\n")

    metrics = read_cgroup_cpu_metrics()

    assert metrics.cgroup_version == "v1"
    assert metrics.quota_us == UNLIMITED


# ---------------------------------------------------------------------------
# Neither cgroup version available
# ---------------------------------------------------------------------------


# Verifies that when neither cgroup v2 nor cgroup v1 files exist at all
# (e.g. running outside any Linux cgroup, such as this test suite on a
# non-Linux development machine, or a stripped-down container), every
# field safely reports UNAVAILABLE instead of raising.
# This test exists to confirm the task's explicit requirement that
# missing files must degrade to "unavailable", not fail application
# startup or OCR processing.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the cgroup root.
# Returns:
# - None.
def test_read_cgroup_cpu_metrics_returns_unavailable_when_no_cgroup_found(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _use_fake_cgroup_root(tmp_path, monkeypatch)
    # tmp_path is empty: no cgroup.controllers, no "cpu" or
    # "cpu,cpuacct" directory.

    metrics = read_cgroup_cpu_metrics()

    assert metrics.cgroup_version == UNAVAILABLE
    assert metrics.quota_us == UNAVAILABLE
    assert metrics.period_us == UNAVAILABLE
    assert metrics.nr_periods == UNAVAILABLE
    assert metrics.nr_throttled == UNAVAILABLE
    assert metrics.throttled_usec == UNAVAILABLE
    assert metrics.usage_usec == UNAVAILABLE


# Verifies that an unexpected error anywhere in the read/parse path
# (simulated here, not just a missing file) is still swallowed by the
# top-level defensive catch-all, rather than propagating out of
# read_cgroup_cpu_metrics().
# This test exists because the task requires that telemetry can never
# break OCR processing, including failure modes beyond "file not found"
# (e.g. a future refactor accidentally introducing a bug in the parsing
# helpers).
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the cgroup root and
#   force an unexpected error during the v2 read path.
# Returns:
# - None.
def test_read_cgroup_cpu_metrics_never_raises_on_unexpected_error(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    cgroup_root = _use_fake_cgroup_root(tmp_path, monkeypatch)

    (cgroup_root / "cgroup.controllers").write_text("cpu io memory\n")

    def _raise_unexpected() -> None:
        raise ValueError("simulated unexpected parsing failure")

    monkeypatch.setattr(
        cgroup_metrics,
        "_read_cgroup_v2_metrics",
        lambda: _raise_unexpected(),
    )

    metrics = read_cgroup_cpu_metrics()

    assert metrics.cgroup_version == UNAVAILABLE


# ---------------------------------------------------------------------------
# cpu_metric_delta()
# ---------------------------------------------------------------------------


# Verifies that a delta between two concrete integer snapshots is
# computed as a plain after-minus-before integer.
# Parameters:
# - None.
# Returns:
# - None.
def test_cpu_metric_delta_computes_integer_difference() -> None:
    assert cpu_metric_delta(10, 17) == 7


# Verifies that a delta involving an UNAVAILABLE value on either side
# safely reports UNAVAILABLE instead of raising a TypeError from
# subtracting a string from an int.
# Parameters:
# - before: the "before" metric value under test.
# - after: the "after" metric value under test.
# Returns:
# - None.
@pytest.mark.parametrize(
    ("before", "after"),
    [
        (UNAVAILABLE, 10),
        (10, UNAVAILABLE),
        (UNAVAILABLE, UNAVAILABLE),
    ],
)
def test_cpu_metric_delta_is_unavailable_when_either_side_unavailable(
    before,
    after,
) -> None:
    assert cpu_metric_delta(before, after) == UNAVAILABLE


# Verifies that a delta involving the UNLIMITED ("max") quota placeholder
# safely reports UNAVAILABLE, since "max" is not a number that can be
# subtracted.
# This test exists because quota_us is the one field that can hold
# UNLIMITED rather than an integer or UNAVAILABLE.
# Parameters:
# - None.
# Returns:
# - None.
def test_cpu_metric_delta_is_unavailable_for_unlimited_quota() -> None:
    assert cpu_metric_delta(UNLIMITED, UNLIMITED) == UNAVAILABLE
