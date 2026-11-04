"""Repository scans: no secrets or hosted identifiers, no automatic reset, production runner untouched."""

import re
from pathlib import Path

from staging_ops.target_config import REPOSITORY_ROOT

SCANNED = [
    "services/api/staging_ops",
    "services/api/tests/unit/staging_tooling",
    "services/api/tests/integration/staging_tooling",
    "docs/operations/staging",
]
# Synthetic references used by the tests; a real project reference never appears.
ALLOWED_PROJECT_REFERENCES = {"stgprojectrefabcdefgh", "prdprojectrefabcdefgh", "otherprojectrefabcdef", "project-ref"}
EXAMPLE_HOST_SUFFIXES = (".example.test", ".invalid", "example.test")

_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]*")
_SB_KEY = re.compile(r"\bsb_(?:publishable|secret)_[A-Za-z0-9_\-]{8,}")
_DB_URL = re.compile(r"postgres(?:ql)?(?:\+\w+)?://([^/\s:@'\"]+):([^@\s'\"]+)@([^/\s:'\"?]+)")
_HOSTED = re.compile(r"\b([a-z0-9\-]+)\.(supabase\.co|supabase\.com|onrender\.com)\b")
_EMAIL = re.compile(r"\b[\w.+\-]+@([\w\-]+(?:\.[\w\-]+)+)\b")
_PRIVATE_IP = re.compile(r"\b(?:10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)\b")


def leaks(text: str):
    found = []

    if _JWT.search(text):
        found.append("JSON Web Token")

    if _SB_KEY.search(text):
        found.append("Supabase key")

    for user, password, host in _DB_URL.findall(text):
        placeholder = host.startswith("<") or password.startswith(("<", "{", "$")) or "{" in host
        if not placeholder and not host.endswith(EXAMPLE_HOST_SUFFIXES) and host not in ("localhost", "127.0.0.1"):
            found.append("database URL with credentials")

    for label, _domain in _HOSTED.findall(text):
        if label not in ALLOWED_PROJECT_REFERENCES and not label.startswith("<") and label not in ("db", "aws-0", "api"):
            found.append(f"hosted hostname ({label[:3]}...)")

    for domain in _EMAIL.findall(text):
        if not domain.endswith(EXAMPLE_HOST_SUFFIXES):
            found.append("e-mail address")

    if _PRIVATE_IP.search(text):
        found.append("private IP address")

    return found


def scanned_files():
    for relative in SCANNED:
        base = REPOSITORY_ROOT / relative

        if not base.exists():
            continue

        for path in sorted(base.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".md", ".json", ".sh", ".yml"} and "__pycache__" not in path.parts:
                yield path


class TestScanner:
    def test_the_scanner_catches_what_it_claims_to(self):
        assert leaks("eyJ" + "hbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.c2ln")
        assert leaks("sb_" + "secret_" + "abcdefghijk")
        assert leaks("postgresql://user:" + "hunter2@" + "db.real-host.net/valor")
        assert leaks("https://" + "abcdefghijklmnopqrst" + ".supabase.co")
        assert leaks("someone@" + "gmail.com")
        assert not leaks("postgresql://<user>:<password>@<host>:5432/valor_staging")
        assert not leaks("postgresql://svc:pw@staging-db.example.test/valor_staging")


class TestRepository:
    def test_no_secret_or_hosted_identifier_in_the_staging_files(self):
        problems = {str(path.relative_to(REPOSITORY_ROOT)): leaks(path.read_text(encoding="utf-8")) for path in scanned_files()}
        problems = {name: found for name, found in problems.items() if found}

        assert problems == {}

    def test_there_are_files_to_scan(self):
        assert any(path.name == "identity.py" for path in scanned_files())

    def test_no_pipeline_or_script_runs_the_staging_tooling(self):
        # A reset must never follow an ordinary test failure: nothing automated calls it.
        for path in (REPOSITORY_ROOT / ".github").rglob("*"):
            if path.is_file():
                assert "staging_ops" not in path.read_text(encoding="utf-8"), path

        for path in (REPOSITORY_ROOT / "services/api").glob("*"):
            if path.is_file() and path.name != "Dockerfile":
                assert "staging_ops" not in path.read_text(encoding="utf-8", errors="ignore"), path

        compose = REPOSITORY_ROOT / "docker-compose.yml"
        assert "staging_ops" not in compose.read_text(encoding="utf-8")

    def test_the_application_never_imports_the_staging_tooling(self):
        for path in (REPOSITORY_ROOT / "services/api/app").rglob("*.py"):
            assert "staging_ops" not in path.read_text(encoding="utf-8"), path

    def test_only_the_alembic_hook_and_the_tooling_itself_reference_the_package(self):
        referencing = []

        for path in (REPOSITORY_ROOT / "services/api").rglob("*.py"):
            relative = path.relative_to(REPOSITORY_ROOT / "services/api")

            if relative.parts[0] in {"staging_ops", ".venv"} or "tests" in relative.parts[:1] or "__pycache__" in relative.parts:
                continue

            if "staging_ops" in path.read_text(encoding="utf-8"):
                referencing.append(str(relative))

        assert referencing == ["alembic/env.py"]

    def test_the_production_guarded_runner_is_not_aware_of_staging_bootstrap(self):
        runner = (REPOSITORY_ROOT / "docs/operations/sql/run_guarded_migration.sh").read_text(encoding="utf-8")

        assert "staging_ops" not in runner and "VF_STAGING_BINDING" not in runner
        assert 'refuse "only revisions a7c3e91d5b24 and c4d8a2f6e193 may be applied with this runner"' in runner

    def test_the_alembic_hook_is_inert_without_the_binding_variable(self):
        env_source = (REPOSITORY_ROOT / "services/api/alembic/env.py").read_text(encoding="utf-8")

        assert 'os.environ.get("VF_STAGING_BINDING")' in env_source
        assert env_source.index("if not raw_binding:\n        return") < env_source.index("from staging_ops.binding import")
