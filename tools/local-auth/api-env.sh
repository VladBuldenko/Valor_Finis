# SOURCE this file (do not execute it) to prepare the shell for the FastAPI app against the LOCAL Supabase Auth stack.
#   cd <repo>/tools/local-auth && source ./api-env.sh && cd ../../services/api && ...      (see README.md)
# Everything is validated BEFORE anything is exported. On any rejection nothing is exported and non-zero is returned,
# so always chain it: `source ./api-env.sh && <next command>`.
# status.env is NOT sourced: only its public API_URL and PUBLISHABLE_KEY are read, so the secret / service-role keys,
# the JWT secret and the admin DB URL it holds never enter this shell. No secret value is ever printed.
_la_here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

_la_setup() {
  local here="$1" env_file line key val api_url="" pub_key="" py v
  local loopback_http_re='^http://(127\.0\.0\.1|localhost|\[::1\]):[0-9]+/?$'
  env_file="$here/status.env"

  [ -r "$env_file" ] || { echo "refusing: $env_file not found (create it: see README.md)" >&2; return 1; }
  while IFS= read -r line || [ -n "$line" ]; do
    key="${line%%=*}"; val="${line#*=}"; val="${val%\"}"; val="${val#\"}"
    case "$key" in API_URL) api_url="$val" ;; PUBLISHABLE_KEY) pub_key="$val" ;; esac
  done < "$env_file"

  [[ "$api_url" =~ $loopback_http_re ]] || { echo "refusing: status.env API_URL is missing or not a plain loopback http URL" >&2; return 1; }
  [ -n "$pub_key" ] || { echo "refusing: status.env has no PUBLISHABLE_KEY" >&2; return 1; }

  # libpq environment variables can redirect a connection even when the URL is fine (e.g. PGHOSTADDR). Refuse, never unset.
  for v in PGHOST PGHOSTADDR PGPORT PGDATABASE PGSERVICE PGSERVICEFILE PGSYSCONFDIR PGOPTIONS; do
    if printenv "$v" > /dev/null; then echo "refusing: libpq variable $v is set; unset it first" >&2; return 1; fi
  done

  py="${LOCAL_AUTH_PYTHON:-$here/../../services/api/.venv/bin/python}"
  [ -x "$py" ] || { echo "refusing: no Python with SQLAlchemy at the API venv; set LOCAL_AUTH_PYTHON" >&2; return 1; }
  LOCAL_AUTH_APP_DATABASE_URL="${LOCAL_AUTH_APP_DATABASE_URL:-}" "$py" -I "$here/check_database_url.py" || return 1

  # Validation passed: publish only what the API needs. The one key it gets is the public publishable key.
  export DATABASE_URL="$LOCAL_AUTH_APP_DATABASE_URL"
  export AUTH_MODE=supabase
  export SUPABASE_URL="$api_url"
  export SUPABASE_PUBLISHABLE_KEY="$pub_key"
  export RECEIPT_STORAGE_DRIVER=local
  export RECEIPT_UPLOAD_DIR="$here/receipt-uploads"
  export RECEIPT_OCR_DRIVER=tesseract
  export RECEIPT_MAX_FILE_SIZE_MB=10
  export RULE_EVENT_BACKGROUND_DISPATCH=false
  mkdir -p "$RECEIPT_UPLOAD_DIR"
}

if _la_setup "$_la_here"; then
  unset -f _la_setup; unset _la_here
else
  unset -f _la_setup; unset _la_here
  return 1
fi
