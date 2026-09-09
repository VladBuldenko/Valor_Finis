import os
from typing import Optional

from dotenv import load_dotenv


load_dotenv()


SUPPORTED_AUTH_MODES = {
    "development",
    "supabase",
}

SUPPORTED_RECEIPT_STORAGE_DRIVERS = {
    "local",
    "supabase",
}

SUPPORTED_RECEIPT_OCR_DRIVERS = {
    "tesseract",
    "unconfigured",
}

# Default maximum number of decoded receipt image pixels (width * height)
# allowed before OCR processing.
#
# Rationale: sized to the worst-case *decoded* memory a single request can
# hold on a modest single-instance production container, not to the
# largest image a camera can produce.
#
# - RGB decodes to 3 bytes/pixel, RGBA (e.g. a PNG with transparency) to
#   4 bytes/pixel. At 30,000,000 pixels that is ~90MB (RGB) / ~120MB
#   (RGBA) for the raw decoded bitmap alone.
# - pytesseract.image_to_string() is called with a PIL Image object (not
#   a file path). For an image with an alpha channel, pytesseract's
#   internal prepare()/save() flattens it onto a *new* opaque RGB copy
#   before writing it to a temp file for the tesseract subprocess to
#   read; that second full-resolution RGB buffer (~90MB more at 30MP)
#   stays referenced in our process alongside the original RGBA buffer
#   for the whole subprocess call, since the OCR provider keeps the
#   source PIL Image open until the call returns. Worst case (RGBA
#   input) is therefore ~7 bytes/pixel held concurrently in our own
#   process: ~210MB at 30,000,000 pixels (versus ~420MB at the previous
#   60,000,000-pixel default).
# - Tesseract itself then runs as a *separate* OS subprocess (its own
#   Leptonica image decode plus binarization/layout-analysis/LSTM
#   buffers, which scale with image dimensions) on top of that, adding a
#   further, comparable-order-of-magnitude cost sharing the same
#   container memory ceiling as the FastAPI process.
# - `process_receipt` is a sync route (FastAPI threadpool), so multiple
#   uploads can each independently hold this footprint at the same time.
#   A modest Render MVP instance (roughly 512MB-1GB total RAM) also has
#   to fit the baseline Python/FastAPI/SQLAlchemy process. At the
#   previous 60,000,000-pixel default, a single worst-case (RGBA) request
#   could already approach or exceed a 512MB-1GB instance on its own once
#   the tesseract subprocess is included, and two concurrent such
#   requests could plausibly OOM-kill the whole container for all users
#   -- a needlessly large resource-exhaustion window. 30,000,000 pixels
#   cuts that single-request footprint roughly in half while still
#   comfortably covering real iPhone receipt photos (~12-24MP, i.e.
#   25%-150% headroom); unusually high-resolution 44-48MP ProRAW/HEIF-max
#   captures fall outside this MVP budget and can be handled later via
#   client- or server-side downscaling before OCR.
# - This stays well below Pillow's own decompression-bomb warning
#   threshold (~89,478,485 pixels, `PIL.Image.MAX_IMAGE_PIXELS`), so a
#   compressed-but-small malicious file is still rejected before it can
#   decode into a large in-memory bitmap.
DEFAULT_RECEIPT_OCR_MAX_IMAGE_PIXELS = 30_000_000

# Default Tesseract OCR execution timeout, in seconds.
#
# Rationale: this MVP processes one receipt photo per request (not a
# batch job) on a modest Render instance. Normal OCR of a single receipt
# image typically completes in a few seconds; 20 seconds gives generous
# headroom for slower/cold hardware while still bounding the worst-case
# CPU time a single request can consume, protecting the API worker from
# a pathological or adversarial image tying up processing indefinitely.
DEFAULT_RECEIPT_OCR_TIMEOUT_SECONDS = 20


# Returns and validates the configured authentication mode.
# This function exists to fail fast when AUTH_MODE contains
# an unsupported or misspelled value.
# Parameters:
# - None.
# Returns:
# - Validated authentication mode.
# Raises:
# - ValueError when AUTH_MODE is unsupported.
def get_auth_mode() -> str:
    auth_mode = os.getenv(
        "AUTH_MODE",
        "development",
    ).strip().lower()

    if auth_mode not in SUPPORTED_AUTH_MODES:
        supported_modes = ", ".join(
            sorted(SUPPORTED_AUTH_MODES),
        )

        raise ValueError(
            "Unsupported AUTH_MODE "
            f"'{auth_mode}'. "
            f"Supported values: {supported_modes}."
        )

    return auth_mode


# Returns and validates the configured receipt storage driver.
# This function exists to fail fast when RECEIPT_STORAGE_DRIVER
# contains an unsupported or misspelled value.
# Parameters:
# - None.
# Returns:
# - Validated receipt storage driver.
# Raises:
# - ValueError when RECEIPT_STORAGE_DRIVER is unsupported.
def get_receipt_storage_driver() -> str:
    storage_driver = os.getenv(
        "RECEIPT_STORAGE_DRIVER",
        "local",
    ).strip().lower()

    if storage_driver not in SUPPORTED_RECEIPT_STORAGE_DRIVERS:
        supported_drivers = ", ".join(
            sorted(SUPPORTED_RECEIPT_STORAGE_DRIVERS),
        )

        raise ValueError(
            "Unsupported RECEIPT_STORAGE_DRIVER "
            f"'{storage_driver}'. "
            f"Supported values: {supported_drivers}."
        )

    return storage_driver


# Returns and validates the configured receipt OCR driver.
# This function exists to fail fast when RECEIPT_OCR_DRIVER
# contains an unsupported or misspelled value.
# Parameters:
# - None.
# Returns:
# - Validated receipt OCR driver.
# Raises:
# - ValueError when RECEIPT_OCR_DRIVER is unsupported.
def get_receipt_ocr_driver() -> str:
    ocr_driver = os.getenv(
        "RECEIPT_OCR_DRIVER",
        "tesseract",
    ).strip().lower()

    if ocr_driver not in SUPPORTED_RECEIPT_OCR_DRIVERS:
        supported_drivers = ", ".join(
            sorted(SUPPORTED_RECEIPT_OCR_DRIVERS),
        )

        raise ValueError(
            "Unsupported RECEIPT_OCR_DRIVER "
            f"'{ocr_driver}'. "
            f"Supported values: {supported_drivers}."
        )

    return ocr_driver


# Returns and validates the configured maximum decoded receipt image
# pixel count allowed before OCR processing.
# This function exists to bound OCR memory usage for decoded images
# independently of the uploaded file's compressed byte size, since a
# small compressed file can still decode into a very large bitmap
# ("decompression bomb").
# Parameters:
# - None.
# Returns:
# - Validated maximum number of decoded image pixels.
# Raises:
# - ValueError when RECEIPT_OCR_MAX_IMAGE_PIXELS is not a positive integer.
def get_receipt_ocr_max_image_pixels() -> int:
    raw_value = os.getenv(
        "RECEIPT_OCR_MAX_IMAGE_PIXELS",
        str(DEFAULT_RECEIPT_OCR_MAX_IMAGE_PIXELS),
    ).strip()

    try:
        max_image_pixels = int(raw_value)
    except ValueError:
        max_image_pixels = None

    if max_image_pixels is None or max_image_pixels <= 0:
        raise ValueError(
            "Invalid RECEIPT_OCR_MAX_IMAGE_PIXELS "
            f"'{raw_value}'. Must be a positive integer."
        )

    return max_image_pixels


# Returns and validates the configured Tesseract OCR execution timeout.
# This function exists to bound worst-case OCR CPU/wall-clock time per
# receipt so a single pathological or adversarial image cannot tie up
# an application worker indefinitely.
# Parameters:
# - None.
# Returns:
# - Validated Tesseract OCR timeout in seconds.
# Raises:
# - ValueError when RECEIPT_OCR_TIMEOUT_SECONDS is not a positive integer.
def get_receipt_ocr_timeout_seconds() -> int:
    raw_value = os.getenv(
        "RECEIPT_OCR_TIMEOUT_SECONDS",
        str(DEFAULT_RECEIPT_OCR_TIMEOUT_SECONDS),
    ).strip()

    try:
        timeout_seconds = int(raw_value)
    except ValueError:
        timeout_seconds = None

    if timeout_seconds is None or timeout_seconds <= 0:
        raise ValueError(
            "Invalid RECEIPT_OCR_TIMEOUT_SECONDS "
            f"'{raw_value}'. Must be a positive integer."
        )

    return timeout_seconds


# Validates authentication-related application configuration.
# This function exists to fail fast during application startup
# when Supabase authentication is enabled but required settings
# are missing.
# Parameters:
# - auth_mode: configured authentication mode.
# - supabase_url: configured Supabase project URL.
# - supabase_publishable_key: configured Supabase publishable key.
# Returns:
# - None.
# Raises:
# - ValueError when required Supabase authentication
#   configuration is missing.
def validate_auth_configuration(
    auth_mode: str,
    supabase_url: Optional[str],
    supabase_publishable_key: Optional[str],
) -> None:
    if auth_mode != "supabase":
        return

    missing_settings = []

    if not supabase_url:
        missing_settings.append(
            "SUPABASE_URL",
        )

    if not supabase_publishable_key:
        missing_settings.append(
            "SUPABASE_PUBLISHABLE_KEY",
        )

    if missing_settings:
        missing_settings_text = ", ".join(
            missing_settings,
        )

        raise ValueError(
            "Missing required Supabase configuration: "
            f"{missing_settings_text}."
        )


# Validates receipt storage configuration.
# This function exists to fail fast during application startup
# when Supabase receipt storage is enabled but required settings
# are missing.
# Parameters:
# - storage_driver: configured receipt storage driver.
# - supabase_url: configured Supabase project URL.
# - supabase_secret_key: configured Supabase backend secret key.
# - receipt_storage_bucket: configured Supabase Storage bucket.
# Returns:
# - None.
# Raises:
# - ValueError when required Supabase Storage configuration
#   is missing.
def validate_receipt_storage_configuration(
    storage_driver: str,
    supabase_url: Optional[str],
    supabase_secret_key: Optional[str],
    receipt_storage_bucket: str,
) -> None:
    if storage_driver != "supabase":
        return

    missing_settings = []

    if not supabase_url:
        missing_settings.append(
            "SUPABASE_URL",
        )

    if not supabase_secret_key:
        missing_settings.append(
            "SUPABASE_SECRET_KEY",
        )

    if not receipt_storage_bucket:
        missing_settings.append(
            "RECEIPT_STORAGE_BUCKET",
        )

    if missing_settings:
        missing_settings_text = ", ".join(
            missing_settings,
        )

        raise ValueError(
            "Missing required Supabase receipt storage configuration: "
            f"{missing_settings_text}."
        )


class AppSettings:
    """
    Application settings.

    This class stores and validates environment-based
    application configuration.

    Fields:
    - database_url: PostgreSQL database connection string.
    - auth_mode: authentication mode used by the API.
    - supabase_url: Supabase project URL.
    - supabase_publishable_key: Supabase publishable key used for Auth.
    - supabase_secret_key: Supabase secret key used by trusted backend services.
    - receipt_storage_driver: Storage backend used for receipt files.
    - receipt_storage_bucket: Supabase Storage bucket used for receipts.
    - receipt_upload_dir: Local directory used for receipt file uploads.
    - receipt_max_file_size_mb: Maximum receipt file size in megabytes.
    - receipt_ocr_driver: OCR provider used to extract text from receipts.
    - receipt_ocr_max_image_pixels: maximum decoded receipt image pixel
      count (width * height) allowed before OCR processing.
    - receipt_ocr_timeout_seconds: maximum Tesseract OCR execution time,
      in seconds, allowed per receipt.
    """

    def __init__(self) -> None:
        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/valor",
        )

        self.auth_mode = get_auth_mode()

        self.supabase_url = (
            os.getenv("SUPABASE_URL") or None
        )

        self.supabase_publishable_key = (
            os.getenv("SUPABASE_PUBLISHABLE_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
            or None
        )

        self.supabase_secret_key = (
            os.getenv("SUPABASE_SECRET_KEY")
            or None
        )

        self.receipt_storage_driver = (
            get_receipt_storage_driver()
        )

        self.receipt_storage_bucket = os.getenv(
            "RECEIPT_STORAGE_BUCKET",
            "receipts",
        ).strip()

        self.receipt_upload_dir = os.getenv(
            "RECEIPT_UPLOAD_DIR",
            "uploads/receipts",
        )

        self.receipt_max_file_size_mb = int(
            os.getenv(
                "RECEIPT_MAX_FILE_SIZE_MB",
                "10",
            )
        )

        self.receipt_ocr_driver = (
            get_receipt_ocr_driver()
        )

        self.receipt_ocr_max_image_pixels = (
            get_receipt_ocr_max_image_pixels()
        )

        self.receipt_ocr_timeout_seconds = (
            get_receipt_ocr_timeout_seconds()
        )

        validate_auth_configuration(
            auth_mode=self.auth_mode,
            supabase_url=self.supabase_url,
            supabase_publishable_key=self.supabase_publishable_key,
        )

        validate_receipt_storage_configuration(
            storage_driver=self.receipt_storage_driver,
            supabase_url=self.supabase_url,
            supabase_secret_key=self.supabase_secret_key,
            receipt_storage_bucket=self.receipt_storage_bucket,
        )

    @property
    def receipt_max_file_size_bytes(self) -> int:
        """
        Returns the maximum allowed receipt file size in bytes.

        What:
            Converts the configured megabyte limit into bytes.

        Why:
            Keeps file size conversion outside the receipt storage service.
        """

        return self.receipt_max_file_size_mb * 1024 * 1024


settings = AppSettings()