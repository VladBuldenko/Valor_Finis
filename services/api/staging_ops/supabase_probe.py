"""
Live Supabase project identity probe.

What:
    Confirms that the configured publishable key belongs to the project named
    by SUPABASE_URL, by asking that project's public Auth settings endpoint.

Why:
    The approved project reference is compared offline, but a URL alone does
    not prove the key and project agree. The probe sends the publishable key
    only to the already-validated `<ref>.supabase.co` host over HTTPS and
    never follows a redirect (a redirect would carry the key elsewhere).
    It is injectable so no test contacts a real project.
"""

import urllib.error
import urllib.request
from typing import Callable, Mapping, Optional

from staging_ops.errors import StagingRefused
from staging_ops.identity import ConfiguredTarget

PROBE_TIMEOUT_SECONDS = 5


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


# Probes the staging Supabase project named by the validated configuration.
# Parameters:
# - configured: target that already passed verify_configuration.
# - environ: process environment (the publishable key is read here only).
# - opener: optional urllib-compatible opener, for tests.
# Raises:
# - StagingRefused: SUPABASE_PROBE_FAILED when the project does not accept the key.
def probe_supabase_project(
    configured: ConfiguredTarget,
    environ: Mapping[str, str],
    opener: Optional[Callable] = None,
) -> None:
    url = f"https://{configured.supabase_project_ref}.supabase.co/auth/v1/settings"
    request = urllib.request.Request(url, headers={"apikey": environ["SUPABASE_PUBLISHABLE_KEY"]}, method="GET")
    open_url = opener or urllib.request.build_opener(_NoRedirect).open

    try:
        with open_url(request, timeout=PROBE_TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", None)
    except (urllib.error.URLError, OSError, ValueError):
        raise StagingRefused("SUPABASE_PROBE_FAILED", "the staging Supabase project did not accept the configured key") from None

    if status != 200:
        raise StagingRefused("SUPABASE_PROBE_FAILED", "the staging Supabase project did not accept the configured key")
