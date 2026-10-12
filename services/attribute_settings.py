"""Central, typed behavior limits for Attribute Assistant.

These values are part of the module's contract, not deployment secrets. Keep
them together here and expose the client-facing subset through the workspace
API instead of duplicating magic numbers across routes and UI code.
"""

from typing import Final


PRODUCT_PAGE_SIZE: Final = 80
MAX_PAGE_SIZE: Final = 200
ALLOWED_VALUE_PAGE_SIZE: Final = 40
TEMPLATE_VALUE_PAGE_SIZE: Final = 80
WORKSPACE_BATCH_LIMIT: Final = 30
HISTORY_LIMIT: Final = 50
BULK_CONFIDENCE: Final = 90
DONOR_PRODUCT_CONCURRENCY: Final = 3
OPERATION_ERROR_LIMIT: Final = 50

