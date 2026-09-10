"""
Reads CPU quota and throttling accounting from the container's cgroup
filesystem.

What:
    Small, isolated helper that safely reads a handful of numeric CPU
    accounting values (or the literal "max"/"unavailable") from
    /sys/fs/cgroup, supporting both cgroup v2 (unified hierarchy) and
    cgroup v1 (separate "cpu"/"cpuacct" hierarchies).

Why:
    A prior Tesseract OCR root-cause investigation narrowed a 45+ second
    production OCR timeout to CPU quota/throttling on the Render
    container as the most likely dominant cause, but that could not be
    confirmed without directly observing the container's own cgroup CPU
    accounting during a real OCR request. This module exists to give
    receipt_ocr_service a way to log that accounting immediately
    before/after the Tesseract call. It is diagnostics-only: every read
    is wrapped so a missing file, a permission error, an unrecognized
    cgroup layout, or any other unexpected error degrades to
    "unavailable" values instead of raising, so this can never break OCR
    processing. Pure standard library - no new dependency.
"""

from pathlib import Path
from typing import Dict, Optional, Sequence, Union

from dataclasses import dataclass


# Value used for any metric that could not be read (missing file,
# permission error, or unexpected/unparseable content) instead of
# raising or silently omitting the field, so every diagnostic log line
# always has the same fields present with a predictable placeholder.
UNAVAILABLE = "unavailable"

# Value used for a CPU quota explicitly reported as unlimited (cgroup
# v2's cpu.max literal "max", or cgroup v1's cpu.cfs_quota_us value -1),
# so "no quota configured" is distinguishable in logs from "the quota
# could not be read".
UNLIMITED = "max"

# Root of the cgroup filesystem as mounted inside the container. Looked
# up fresh (as a module attribute, not pre-joined into other module-level
# path constants) inside every function below, so tests can monkeypatch
# this single value to point at a fake cgroup layout under tmp_path.
_CGROUP_ROOT = Path("/sys/fs/cgroup")


# A cgroup CPU metric value: either a concrete integer, UNLIMITED
# (quota_us only), or UNAVAILABLE.
CpuMetricValue = Union[int, str]


@dataclass(frozen=True)
class CgroupCpuMetrics:
    """
    Point-in-time CPU quota/throttling snapshot read from the container's
    cgroup filesystem.

    What:
        Holds only numeric (or the literal "max"/"unavailable") CPU
        accounting values that are safe to log for OCR CPU-throttling
        diagnostics.

    Why:
        Groups the handful of fields needed to confirm or rule out
        Render CPU-quota throttling as the cause of slow Tesseract OCR
        runs, without exposing any receipt content, file paths, user
        IDs, or host/container identifiers.

    Fields:
    - cgroup_version: "v2", "v1", or UNAVAILABLE when neither could be
      read.
    - quota_us: configured CPU quota in microseconds per period,
      UNLIMITED when the cgroup reports no limit, or UNAVAILABLE.
    - period_us: CPU accounting period in microseconds, or UNAVAILABLE.
    - nr_periods: number of elapsed accounting periods, or UNAVAILABLE.
    - nr_throttled: number of periods in which the cgroup was
      throttled, or UNAVAILABLE.
    - throttled_usec: cumulative time throttled, in microseconds
      (converted from nanoseconds on cgroup v1), or UNAVAILABLE.
    - usage_usec: cumulative CPU time actually consumed, in
      microseconds (converted from nanoseconds on cgroup v1), or
      UNAVAILABLE.
    """

    cgroup_version: str
    quota_us: CpuMetricValue
    period_us: CpuMetricValue
    nr_periods: CpuMetricValue
    nr_throttled: CpuMetricValue
    throttled_usec: CpuMetricValue
    usage_usec: CpuMetricValue


_UNAVAILABLE_METRICS = CgroupCpuMetrics(
    cgroup_version=UNAVAILABLE,
    quota_us=UNAVAILABLE,
    period_us=UNAVAILABLE,
    nr_periods=UNAVAILABLE,
    nr_throttled=UNAVAILABLE,
    throttled_usec=UNAVAILABLE,
    usage_usec=UNAVAILABLE,
)


# Safely reads and strips a small cgroup accounting file.
# This function exists as the single point that keeps every reader
# below from ever raising for a diagnostics-only read: a missing file,
# a permission error, or any other OS-level failure becomes None instead
# of propagating.
# Parameters:
# - path: cgroup accounting file to read.
# Returns:
# - The file's stripped text content, or None when it could not be read.
def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text().strip()
    except OSError:
        return None


# Parses a raw integer string from a cgroup accounting file.
# Parameters:
# - raw_value: text expected to contain a plain integer.
# Returns:
# - The parsed integer, or UNAVAILABLE when it is not a valid integer.
def _parse_int(raw_value: str) -> CpuMetricValue:
    try:
        return int(raw_value)
    except ValueError:
        return UNAVAILABLE


# Parses a cgroup `cpu.stat`-style file (one "<key> <value>" pair per
# line) into a dict covering exactly `field_names`.
# This function exists to share the same tolerant line-parsing logic
# between the cgroup v2 and cgroup v1 readers below, since both use the
# same "<key> <value>" per-line format for cpu.stat, just with different
# field names/units.
# Parameters:
# - stat_text: raw contents of a cgroup cpu.stat file.
# - field_names: the fields to extract; any not found in the file (or
#   the file being malformed) default to UNAVAILABLE.
# Returns:
# - A dict from field name to parsed value (or UNAVAILABLE).
def _parse_stat_file(
    stat_text: str,
    field_names: Sequence[str],
) -> Dict[str, CpuMetricValue]:
    parsed: Dict[str, CpuMetricValue] = {
        name: UNAVAILABLE for name in field_names
    }

    for line in stat_text.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue

        key, raw_value = parts
        if key in parsed:
            parsed[key] = _parse_int(raw_value)

    return parsed


# Reads CPU quota/throttling accounting from the cgroup v2 unified
# hierarchy (cpu.max and cpu.stat directly under the cgroup root, as
# bind-mounted for this container).
# Parameters:
# - None.
# Returns:
# - CgroupCpuMetrics for cgroup v2, with UNAVAILABLE for any file/field
#   that could not be read.
def _read_cgroup_v2_metrics() -> CgroupCpuMetrics:
    quota_us: CpuMetricValue = UNAVAILABLE
    period_us: CpuMetricValue = UNAVAILABLE

    cpu_max_text = _read_text(_CGROUP_ROOT / "cpu.max")
    if cpu_max_text is not None:
        parts = cpu_max_text.split()
        if len(parts) == 2:
            raw_quota, raw_period = parts
            quota_us = (
                UNLIMITED if raw_quota == "max" else _parse_int(raw_quota)
            )
            period_us = _parse_int(raw_period)

    stat_field_names = (
        "usage_usec",
        "nr_periods",
        "nr_throttled",
        "throttled_usec",
    )
    stat_fields = {name: UNAVAILABLE for name in stat_field_names}

    cpu_stat_text = _read_text(_CGROUP_ROOT / "cpu.stat")
    if cpu_stat_text is not None:
        stat_fields = _parse_stat_file(cpu_stat_text, stat_field_names)

    return CgroupCpuMetrics(
        cgroup_version="v2",
        quota_us=quota_us,
        period_us=period_us,
        nr_periods=stat_fields["nr_periods"],
        nr_throttled=stat_fields["nr_throttled"],
        throttled_usec=stat_fields["throttled_usec"],
        usage_usec=stat_fields["usage_usec"],
    )


# Reads CPU quota/throttling accounting from a cgroup v1 "cpu"
# hierarchy, trying both the unmerged ("cpu") and comounted
# ("cpu,cpuacct") mount layouts used by different Linux distributions.
# Parameters:
# - None.
# Returns:
# - CgroupCpuMetrics for cgroup v1, with UNAVAILABLE for any file/field
#   that could not be read, or None when neither mount layout's quota
#   file exists at all (so the caller can tell "this is not a cgroup v1
#   host" apart from "cgroup v1, but some files unreadable").
def _read_cgroup_v1_metrics() -> Optional[CgroupCpuMetrics]:
    for cpu_dir_name in ("cpu", "cpu,cpuacct"):
        cpu_root = _CGROUP_ROOT / cpu_dir_name

        quota_text = _read_text(cpu_root / "cpu.cfs_quota_us")
        period_text = _read_text(cpu_root / "cpu.cfs_period_us")

        if quota_text is None and period_text is None:
            # Neither file exists under this mount layout - try the
            # other cgroup v1 layout name instead of reporting
            # UNAVAILABLE for a layout that isn't actually in use.
            continue

        quota_us: CpuMetricValue = UNAVAILABLE
        if quota_text is not None:
            parsed_quota = _parse_int(quota_text)
            quota_us = (
                UNLIMITED if parsed_quota == -1 else parsed_quota
            )

        period_us: CpuMetricValue = (
            _parse_int(period_text)
            if period_text is not None
            else UNAVAILABLE
        )

        stat_field_names = ("nr_periods", "nr_throttled", "throttled_time")
        stat_fields = {name: UNAVAILABLE for name in stat_field_names}

        cpu_stat_text = _read_text(cpu_root / "cpu.stat")
        if cpu_stat_text is not None:
            stat_fields = _parse_stat_file(cpu_stat_text, stat_field_names)

        # cgroup v1's cpu.stat reports throttled_time in nanoseconds
        # (unlike cgroup v2's cpu.stat, which reports throttled_usec in
        # microseconds directly) - convert here so a before/after
        # comparison works the same way regardless of cgroup version.
        throttled_usec = stat_fields["throttled_time"]
        if isinstance(throttled_usec, int):
            throttled_usec = throttled_usec // 1000

        # cpuacct.usage lives alongside cpu.cfs_quota_us when comounted
        # ("cpu,cpuacct"), or under the separate "cpuacct" hierarchy
        # otherwise. Reported in nanoseconds; converted to microseconds
        # to match cgroup v2's usage_usec unit.
        usage_text = _read_text(cpu_root / "cpuacct.usage")
        if usage_text is None:
            usage_text = _read_text(
                _CGROUP_ROOT / "cpuacct" / "cpuacct.usage"
            )

        usage_usec: CpuMetricValue = UNAVAILABLE
        if usage_text is not None:
            parsed_usage = _parse_int(usage_text)
            if isinstance(parsed_usage, int):
                usage_usec = parsed_usage // 1000

        return CgroupCpuMetrics(
            cgroup_version="v1",
            quota_us=quota_us,
            period_us=period_us,
            nr_periods=stat_fields["nr_periods"],
            nr_throttled=stat_fields["nr_throttled"],
            throttled_usec=throttled_usec,
            usage_usec=usage_usec,
        )

    return None


# Reads a point-in-time snapshot of CPU quota/throttling accounting for
# the current cgroup.
# This function exists as the single public entry point OCR telemetry
# calls immediately before/after the Tesseract call. It detects whether
# the host uses cgroup v2 (unified hierarchy, signaled by the presence
# of /sys/fs/cgroup/cgroup.controllers) or cgroup v1 (separate "cpu"/
# "cpu,cpuacct" hierarchies), reads the corresponding files, and never
# raises: any failure mode (missing files, permission errors, an
# unrecognized cgroup layout, or any other unexpected error while
# parsing) degrades to UNAVAILABLE values instead of propagating, so a
# read failure here can never break OCR processing.
# Parameters:
# - None.
# Returns:
# - CgroupCpuMetrics with every field populated, using UNAVAILABLE for
#   any value that could not be read and UNLIMITED for a quota
#   explicitly reported as unbounded.
def read_cgroup_cpu_metrics() -> CgroupCpuMetrics:
    try:
        if _read_text(_CGROUP_ROOT / "cgroup.controllers") is not None:
            return _read_cgroup_v2_metrics()

        v1_metrics = _read_cgroup_v1_metrics()
        if v1_metrics is not None:
            return v1_metrics
    except Exception:
        # Defensive catch-all: this is diagnostics-only telemetry, so no
        # unexpected error while reading/parsing cgroup files may ever
        # propagate into OCR processing.
        pass

    return _UNAVAILABLE_METRICS


# Computes an after-minus-before delta for one numeric cgroup CPU
# metric.
# This function exists to keep delta computation consistent (and always
# safe) across every metric OCR telemetry logs a delta for, instead of
# repeating the same "both sides must be concrete numbers" guard at each
# call site.
# Parameters:
# - before: metric value from the "before" snapshot.
# - after: metric value from the "after" snapshot.
# Returns:
# - The integer delta when both values are concrete numbers, otherwise
#   UNAVAILABLE (covers a metric that could not be read on either side,
#   and covers quota_us specifically when it is UNLIMITED rather than a
#   number).
def cpu_metric_delta(
    before: CpuMetricValue,
    after: CpuMetricValue,
) -> CpuMetricValue:
    if isinstance(before, int) and isinstance(after, int):
        return after - before

    return UNAVAILABLE
