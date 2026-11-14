# Source this to run the FastAPI app against the LOCAL Supabase Auth stack (tools/local-auth/README.md).
# Reads the locally generated status.env (gitignored). Prints nothing secret. Local only.
_here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
set -a; source "$_here/status.env"; set +a
export DATABASE_URL="${LOCAL_AUTH_APP_DATABASE_URL:?set LOCAL_AUTH_APP_DATABASE_URL to a DISPOSABLE local database, e.g. postgresql://postgres@127.0.0.1:54332/valor_localauth}"
case "$DATABASE_URL" in *127.0.0.1*|*localhost*) ;; *) echo "refusing: DATABASE_URL is not local" >&2; return 1;; esac
export AUTH_MODE=supabase
export SUPABASE_URL="$API_URL"
export SUPABASE_PUBLISHABLE_KEY="$PUBLISHABLE_KEY"
export RECEIPT_STORAGE_DRIVER=local
export RECEIPT_UPLOAD_DIR="$_here/receipt-uploads"
export RECEIPT_OCR_DRIVER=tesseract
export RECEIPT_MAX_FILE_SIZE_MB=10
export RULE_EVENT_BACKGROUND_DISPATCH=false
mkdir -p "$RECEIPT_UPLOAD_DIR"
# the API process must never receive the secret/service credentials
unset SECRET_KEY SERVICE_ROLE_KEY JWT_SECRET ANON_KEY DB_URL
