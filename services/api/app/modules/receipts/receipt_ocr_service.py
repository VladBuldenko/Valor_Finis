import logging
from pathlib import Path
from typing import Protocol

import pytesseract
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.app_config import settings
from app.modules.receipts import receipt_storage_service
from app.modules.receipts.receipt_errors import (
    ReceiptFileStorageError,
    ReceiptOcrFileNotFoundError,
    ReceiptOcrProcessingError,
)


# Logger for this module. Only safe, non-sensitive reason categories are
# logged here - never OCR-extracted text, receipt content, or local
# file paths. See TesseractReceiptOcrProvider.extract_text() and
# extract_receipt_text() for the specific categories logged.
logger = logging.getLogger(__name__)


# Languages loaded by the Tesseract OCR engine for receipt text extraction.
# "eng" (English) is bundled with the tesseract-ocr OS package by default.
# "deu" (German) is installed explicitly via tesseract-ocr-deu in the
# Dockerfile to correctly recognize German receipts (umlauts and common
# German retail terms such as "SUMME"/"GESAMT"/"MWST" used by the parser).
TESSERACT_OCR_LANGUAGES = "eng+deu"


class ReceiptOcrProvider(Protocol):
    """
    Interface for receipt OCR providers.

    What:
        Defines the operation required from any OCR provider.

    Why:
        Allows the application to replace the OCR implementation
        without changing receipt business logic.
    """

    def extract_text(self, file_path: Path) -> str:
        """
        Extracts text from a receipt file.

        Parameters:
        - file_path: local path of the receipt image or PDF.

        Returns:
        - Raw text extracted from the receipt.
        """

        ...


class UnconfiguredReceiptOcrProvider:
    """
    Placeholder OCR provider used before a real provider is configured.

    What:
        Represents the temporary OCR implementation.

    Why:
        Keeps the OCR architecture operational while preventing
        fake or incomplete OCR results from being returned.
    """

    def extract_text(self, file_path: Path) -> str:
        """
        Rejects OCR processing because no provider is configured.

        Parameters:
        - file_path: local path of the receipt file.

        Returns:
        - Never returns successfully.

        Raises:
        - ReceiptOcrProcessingError always.
        """

        raise ReceiptOcrProcessingError()


# Normalizes orientation and downscales a decoded receipt image for OCR.
# This function exists to keep real-resolution camera photos (e.g. a
# 3024x4032 iPhone photo, ~12,000,000 decoded pixels) fast and reliable to
# process with Tesseract on a modest Render instance, without weakening the
# existing pre-decode pixel-budget check in TesseractReceiptOcrProvider
# .extract_text() (that check still runs first, against the *original*
# image, before this function is ever called).
# Parameters:
# - receipt_image: decoded (already `.load()`-ed) receipt image. Ownership
#   of this image transfers to this function: when downscaling occurs, the
#   caller's image is closed here once no longer needed, so the caller
#   must not use `receipt_image` again after calling this function.
# Returns:
# - The image to pass to Tesseract: the same image (only orientation-
#   normalized, never upscaled) when it is already at or below the
#   configured maximum long edge, otherwise a new, smaller image resized
#   to that maximum long edge with the original aspect ratio preserved.
def _prepare_receipt_image_for_ocr(
    receipt_image: Image.Image,
) -> Image.Image:
    # Many phone cameras (including iPhones) store photos with an EXIF
    # Orientation tag instead of physically rotating the pixel data, so a
    # portrait photo can be decoded "sideways" unless this is applied.
    # in_place=True avoids Pillow's own default behavior of always
    # allocating a full extra copy of the image (even when no rotation is
    # needed) - see PIL.ImageOps.exif_transpose() - which would add a
    # third full-resolution buffer alongside the ones already accounted
    # for in RECEIPT_OCR_MAX_IMAGE_PIXELS' memory analysis.
    ImageOps.exif_transpose(receipt_image, in_place=True)

    width, height = receipt_image.size
    long_edge = max(width, height)
    max_long_edge = settings.receipt_ocr_max_long_edge

    # Never upscale: a smaller-than-budget image is already cheap for
    # Tesseract, and enlarging it would add blur/interpolation artifacts
    # without adding any real text detail.
    if long_edge <= max_long_edge:
        return receipt_image

    scale = max_long_edge / long_edge
    target_size = (
        max(1, round(width * scale)),
        max(1, round(height * scale)),
    )

    logger.info(
        "receipt_ocr_image_resized "
        "original_size=%sx%s resized_size=%sx%s",
        width,
        height,
        target_size[0],
        target_size[1],
    )

    # LANCZOS is a high-quality resampling filter well suited to
    # downscaling text-heavy images without introducing the aliasing a
    # cheaper filter (e.g. nearest-neighbor) would add to fine character
    # strokes.
    resized_image = receipt_image.resize(
        target_size,
        Image.Resampling.LANCZOS,
    )

    # Release the full-resolution buffer now that a smaller working copy
    # exists, instead of holding both for the remainder of the OCR call.
    receipt_image.close()

    return resized_image


class TesseractReceiptOcrProvider:
    """
    OCR provider backed by the open-source Tesseract OCR engine.

    What:
        Extracts raw text from JPEG/PNG receipt images using the
        tesseract-ocr binary through the pytesseract wrapper. Before OCR,
        the decoded image is orientation-normalized and, only when larger
        than the configured maximum long edge, downscaled for that OCR
        call (the original stored receipt file is never modified).

    Why:
        Provides a production-usable, deterministic, and free OCR
        implementation suitable for an MVP, replacing the temporary
        UnconfiguredReceiptOcrProvider. Running Tesseract locally in the
        application container avoids external paid OCR credentials.
        Downscaling real-resolution camera photos (e.g. ~12MP iPhone
        photos) before OCR keeps processing time/CPU cost bounded on a
        modest Render instance without weakening the pixel-budget
        decompression-bomb protection, which still runs against the
        original image first.
    """

    def extract_text(self, file_path: Path) -> str:
        """
        Extracts raw text from a receipt image using Tesseract OCR.

        Parameters:
        - file_path: local path of the receipt image.

        Returns:
        - Raw text extracted by the Tesseract OCR engine. May be empty
          when no text is detected; emptiness is validated by the caller.

        Raises:
        - ReceiptOcrProcessingError when the file is not a readable image,
          the decoded image exceeds the configured pixel budget, the
          Tesseract OCR engine fails to process it, or processing exceeds
          the configured timeout.
        """

        try:
            with Image.open(file_path) as receipt_image:
                # Image.open() only reads the file header, not the full
                # pixel data. Checking dimensions here (before .load())
                # rejects oversized/decompression-bomb-style images while
                # they are still cheap to inspect, instead of after they
                # have been fully decoded into memory.
                width, height = receipt_image.size
                declared_pixels = width * height

                if declared_pixels > settings.receipt_ocr_max_image_pixels:
                    logger.warning(
                        "receipt_ocr_image_too_large "
                        "declared_pixels=%s max_pixels=%s",
                        declared_pixels,
                        settings.receipt_ocr_max_image_pixels,
                    )

                    raise ReceiptOcrProcessingError()

                # Loading the image data here (instead of lazily, on first
                # use by pytesseract) surfaces truncated/corrupt files as
                # UnidentifiedImageError/OSError at this point.
                receipt_image.load()

                # Normalize orientation and downscale real-resolution
                # camera photos (e.g. ~12MP iPhone photos) before OCR; see
                # _prepare_receipt_image_for_ocr() for the memory/timing
                # rationale. This only affects the in-memory working copy
                # used for OCR - the original stored receipt file on disk
                # is never modified.
                ocr_image = _prepare_receipt_image_for_ocr(
                    receipt_image,
                )

                return pytesseract.image_to_string(
                    ocr_image,
                    lang=TESSERACT_OCR_LANGUAGES,
                    timeout=settings.receipt_ocr_timeout_seconds,
                )
        # The except clauses below are intentionally split by exception
        # type (instead of one combined tuple) so that each failure mode
        # can be logged under its own safe, non-sensitive reason category
        # for Render log diagnosis, while still converting every case to
        # the same generic ReceiptOcrProcessingError for the caller/client
        # (fail-closed behavior and the external API contract are
        # unchanged). Ordering matters: TesseractNotFoundError is an
        # OSError subclass and TesseractError is a RuntimeError subclass,
        # so the more specific pytesseract exceptions must be caught
        # before the generic OSError/RuntimeError clauses.
        except UnidentifiedImageError as error:
            logger.warning("receipt_ocr_invalid_image")

            raise ReceiptOcrProcessingError() from error
        except pytesseract.TesseractNotFoundError as error:
            # The tesseract binary itself is missing/not on PATH - an
            # environment/deployment problem, not a bad receipt file.
            logger.error("receipt_ocr_tesseract_not_found")

            raise ReceiptOcrProcessingError() from error
        except pytesseract.TesseractError as error:
            # TesseractError covers both a non-zero engine exit (generic
            # engine failure) and a missing language data file. The
            # underlying tesseract CLI reports the latter by mentioning
            # "tessdata" in its stderr output; only that safe keyword
            # match is used for categorization, the raw message itself
            # (which could in principle echo file paths) is never logged.
            if "tessdata" in (error.message or "").lower():
                logger.error(
                    "receipt_ocr_tesseract_language_data_missing"
                )
            else:
                logger.warning("receipt_ocr_engine_failed")

            raise ReceiptOcrProcessingError() from error
        except OSError as error:
            logger.warning("receipt_ocr_invalid_image")

            raise ReceiptOcrProcessingError() from error
        except RuntimeError as error:
            # pytesseract raises a bare RuntimeError("Tesseract process
            # timeout") when the OCR subprocess exceeds `timeout` (see
            # pytesseract.pytesseract.timeout_manager). TesseractError
            # (handled above) is itself a RuntimeError subclass, so by
            # this point only the bare timeout RuntimeError remains.
            logger.warning("receipt_ocr_timeout")

            raise ReceiptOcrProcessingError() from error


# Selects the OCR provider implementation for the configured driver.
# This function exists to keep OCR provider selection isolated from
# application configuration and to fail fast on invalid driver names.
# Parameters:
# - driver: validated receipt OCR driver name.
# Returns:
# - ReceiptOcrProvider implementation matching the requested driver.
# Raises:
# - ValueError when the driver name is not supported.
def select_receipt_ocr_provider(driver: str) -> ReceiptOcrProvider:
    if driver == "tesseract":
        return TesseractReceiptOcrProvider()

    if driver == "unconfigured":
        return UnconfiguredReceiptOcrProvider()

    raise ValueError(
        f"Unsupported RECEIPT_OCR_DRIVER '{driver}'."
    )


receipt_ocr_provider: ReceiptOcrProvider = select_receipt_ocr_provider(
    driver=settings.receipt_ocr_driver,
)


# Extracts normalized text from a stored receipt file.
# This function exists to isolate receipt business logic
# from both the selected OCR provider and storage provider.
# Parameters:
# - storage_path: internal path of the stored receipt file.
# Returns:
# - Non-empty normalized OCR text.
# Raises:
# - ReceiptOcrFileNotFoundError when a local stored file does not exist.
# - ReceiptOcrProcessingError when storage access fails,
#   the OCR provider fails, or the provider returns empty text.
def extract_receipt_text(
    storage_path: str,
) -> str:
    try:
        with receipt_storage_service.materialize_receipt_file(
            storage_path=storage_path,
        ) as file_path:
            if not file_path.is_file():
                logger.warning("receipt_ocr_file_not_found")

                raise ReceiptOcrFileNotFoundError()

            try:
                extracted_text = (
                    receipt_ocr_provider.extract_text(
                        file_path=file_path,
                    )
                )
            except ReceiptOcrProcessingError:
                raise
            except Exception as error:
                raise ReceiptOcrProcessingError() from error

    except ReceiptOcrFileNotFoundError:
        raise
    except ReceiptOcrProcessingError:
        raise
    except ReceiptFileStorageError as error:
        raise ReceiptOcrProcessingError() from error

    normalized_text = extracted_text.strip()

    if not normalized_text:
        logger.warning("receipt_ocr_empty_result")

        raise ReceiptOcrProcessingError()

    return normalized_text