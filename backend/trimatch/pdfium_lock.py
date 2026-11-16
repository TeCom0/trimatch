"""pdfium is not thread-safe: every use in this process goes through this one lock."""

import threading

PDFIUM_LOCK = threading.Lock()
