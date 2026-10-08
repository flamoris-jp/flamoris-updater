import threading
from urllib.parse import urljoin, urlsplit, urlunsplit

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.models import Manifest
from flamoris_update_core.wire import decode, digest

from .artifacts import Fetcher
from .releases import Catalog
from .signing import verify


class ReleaseSources:
    """Root-approved origins only; detached signatures authenticate exact downloaded bytes."""

    def __init__(self, store, sources):
        self.store = store
        self.sources = {
            (s.application_id, s.channel): (s, Fetcher(s.origins, s.tls_client)) for s in sources
        }
        self.lock = threading.RLock()

    def refresh(self, application, channel="stable"):
        configured = self.sources.get((application, channel))
        if configured is None:
            return  # Explicitly provisioned offline catalogs remain subject to expiry/signature checks.
        source, fetcher = configured
        with self.lock:
            raw = fetcher.bytes(source.catalog_url, 1024 * 1024)
            signature = fetcher.bytes(source.catalog_signature_url, 16 * 1024)
            self.store.accept_catalog(application, channel, raw, signature)

    def ensure(self, identity):
        with self.lock:
            for application, channel in self.sources:
                self.refresh(application, channel)
                record = self.store.journal.get("catalog", application + "." + channel)
                catalog = decode(Catalog, self.store.journal.blob(record["raw"]))
                match = next((e for e in catalog.releases if e.manifest_digest == identity), None)
                if match is None:
                    continue
                source, fetcher = self.sources[(application, channel)]
                url = urljoin(source.catalog_url, match.manifest_locator)
                manifest_raw = fetcher.bytes(url, 1024 * 1024)
                if digest(manifest_raw) != identity:
                    raise UpdateError("untrusted_release")
                parsed = urlsplit(url)
                signature_url = urlunsplit(
                    (
                        parsed.scheme,
                        parsed.netloc,
                        parsed.path.rsplit("/", 1)[0] + "/release.sig.json",
                        "",
                        "",
                    )
                )
                manifest_signature = fetcher.bytes(signature_url, 16 * 1024)
                verify(manifest_raw, manifest_signature, self.store.keys, application, "release")
                manifest = decode(Manifest, manifest_raw)
                if manifest.application_id != application or manifest.release != match.release:
                    raise UpdateError("invalid_manifest")
                human = fetcher.bytes(
                    urljoin(url, manifest.release_notes.human.locator), 1024 * 1024
                )
                changes = fetcher.bytes(
                    urljoin(url, manifest.release_notes.changes.locator), 1024 * 1024
                )
                self.store.import_release(
                    application, manifest_raw, manifest_signature, human, changes
                )
                return
            raise UpdateError(
                "untrusted_release", "Manifest digest is absent from configured signed catalogs"
            )
