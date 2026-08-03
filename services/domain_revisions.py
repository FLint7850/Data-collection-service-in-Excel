"""Process-local revisions for lightweight cross-user configuration polling."""

import threading
import uuid


_DOMAINS = ("file_import", "feed_comparison", "settings")
_lock = threading.Lock()
_revisions = {domain: uuid.uuid4().hex for domain in _DOMAINS}


def domain_revision(domain: str) -> str:
    with _lock:
        try:
            return _revisions[domain]
        except KeyError as exc:
            raise ValueError(f"Unsupported revision domain: {domain}") from exc


def bump_domain_revision(domain: str) -> str:
    with _lock:
        if domain not in _revisions:
            raise ValueError(f"Unsupported revision domain: {domain}")
        revision = uuid.uuid4().hex
        _revisions[domain] = revision
        return revision
