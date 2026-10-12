"""Central, typed behavior limits for Attribute Assistant.

These values are part of the module's contract, not deployment secrets. Keep
them together here and expose the client-facing subset through the workspace
API instead of duplicating magic numbers across routes and UI code.
"""

from enum import StrEnum
from typing import Final


class ProcessingMode(StrEnum):
    CHECK = "check"
    SUGGEST = "suggest"
    AUTO = "auto"
    AUTO_EXACT = "auto_exact"
    AUTO_PRIMARY = "auto_primary"
    AUTO_CONFIDENT = "auto_confident"
    AUTO_ALL = "auto_all"


class StaleProductError(Exception):
    """Raised when a delayed result targets an older product revision."""


PUBLIC_PROCESSING_MODES: Final = tuple(
    mode.value for mode in ProcessingMode if mode is not ProcessingMode.AUTO
)


PRODUCT_PAGE_SIZE: Final = 80
MAX_PAGE_SIZE: Final = 200
ALLOWED_VALUE_PAGE_SIZE: Final = 40
TEMPLATE_VALUE_PAGE_SIZE: Final = 80
WORKSPACE_BATCH_LIMIT: Final = 30
HISTORY_LIMIT: Final = 50
PRODUCT_REVISION_RETENTION: Final = 100
TEMPLATE_REVISION_RETENTION: Final = 100
BULK_CONFIDENCE: Final = 90
DONOR_PRODUCT_CONCURRENCY: Final = 3
URL_IMPORT_CONCURRENCY: Final = 4
BULK_CHUNK_SIZE: Final = 100
OPERATION_ERROR_LIMIT: Final = 50
AUTO_PRIMARY_CONFIDENCE: Final = 85
AUTO_CONFIDENT_CONFIDENCE: Final = 95
EXACT_VALUE_CONFIDENCE: Final = 100
REVIEW_VALUE_STATUSES: Final = frozenset({"missing", "suggested", "conflict", "unknown", "ambiguous"})
DONOR_SOURCE_ROLES: Final = frozenset({"primary", "verification"})
DONOR_FAILURE_STATUSES: Final = frozenset({"error", "not_found"})
DONOR_OPENED_STATUSES: Final = frozenset({"parsed", "no_attributes"})


def processing_mode(value: object) -> ProcessingMode:
    try:
        return ProcessingMode(str(value or ProcessingMode.SUGGEST.value))
    except ValueError as error:
        raise ValueError("Неизвестный режим обработки") from error

