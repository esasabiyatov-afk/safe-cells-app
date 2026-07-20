"""Short-lived, process-local delivery of generated DOCX files to the browser."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from secrets import token_urlsafe
from threading import Lock
from time import monotonic
from typing import Callable, Iterable

from app.documents import DocumentPublishError
from app.services.documents import GeneratedDocument


DEFAULT_TTL_SECONDS = 10 * 60
DEFAULT_MAX_DOCUMENTS = 48


@dataclass(frozen=True, slots=True)
class DownloadDocument:
    download_id: str
    file_name: str

    def to_dict(self) -> dict[str, str]:
        return {"download_id": self.download_id, "file_name": self.file_name}


@dataclass(frozen=True, slots=True)
class DownloadArtifact:
    file_name: str
    content: bytes


@dataclass(frozen=True, slots=True)
class _StoredArtifact:
    artifact: DownloadArtifact
    expires_at: float
    sequence: int


class DocumentDownloadStore:
    """Keep generated files in memory until one authenticated browser download."""

    def __init__(
        self,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_documents: int = DEFAULT_MAX_DOCUMENTS,
        time_provider: Callable[[], float] = monotonic,
    ) -> None:
        if ttl_seconds <= 0 or max_documents <= 0:
            raise ValueError("Параметры временного хранилища документов должны быть положительными.")
        self._ttl_seconds = ttl_seconds
        self._max_documents = max_documents
        self._time_provider = time_provider
        self._lock = Lock()
        self._items: dict[str, _StoredArtifact] = {}
        self._sequence = 0

    @staticmethod
    def _validate_artifact(artifact: DownloadArtifact) -> None:
        file_name = artifact.file_name
        if (
            not isinstance(file_name, str)
            or not file_name.strip()
            or Path(file_name).name != file_name
            or not file_name.casefold().endswith(".docx")
        ):
            raise DocumentPublishError("Не удалось подготовить безопасное имя документа.")
        if not isinstance(artifact.content, bytes) or not artifact.content:
            raise DocumentPublishError("Сформированный документ оказался пустым.")

    def _purge_expired(self, now: float) -> None:
        expired = [
            download_id
            for download_id, stored in self._items.items()
            if stored.expires_at <= now
        ]
        for download_id in expired:
            self._items.pop(download_id, None)

    def publish(self, artifacts: Iterable[DownloadArtifact]) -> list[DownloadDocument]:
        prepared = list(artifacts)
        if not prepared:
            return []
        if len(prepared) > self._max_documents:
            raise DocumentPublishError("Слишком много документов в одном комплекте.")
        for artifact in prepared:
            self._validate_artifact(artifact)

        now = self._time_provider()
        with self._lock:
            surviving = {
                download_id: stored
                for download_id, stored in self._items.items()
                if stored.expires_at > now
            }
            download_ids: list[str] = []
            while len(download_ids) < len(prepared):
                candidate = token_urlsafe(32)
                if candidate not in surviving and candidate not in download_ids:
                    download_ids.append(candidate)

            overflow = len(surviving) + len(prepared) - self._max_documents
            if overflow > 0:
                oldest = sorted(
                    surviving.items(), key=lambda item: item[1].sequence
                )[:overflow]
                for download_id, _stored in oldest:
                    surviving.pop(download_id, None)

            published: list[DownloadDocument] = []
            next_sequence = self._sequence
            for artifact, download_id in zip(prepared, download_ids, strict=True):
                next_sequence += 1
                surviving[download_id] = _StoredArtifact(
                    artifact=artifact,
                    expires_at=now + self._ttl_seconds,
                    sequence=next_sequence,
                )
                published.append(
                    DownloadDocument(
                        download_id=download_id,
                        file_name=artifact.file_name,
                    )
                )
            self._items = surviving
            self._sequence = next_sequence
            return published

    def claim(self, download_id: object) -> DownloadArtifact | None:
        if not isinstance(download_id, str) or not download_id.strip():
            return None
        now = self._time_provider()
        with self._lock:
            self._purge_expired(now)
            stored = self._items.pop(download_id.strip(), None)
        return stored.artifact if stored is not None else None


def publish_generated_documents(
    store: DocumentDownloadStore,
    *,
    output_directory: Path,
    generated: Iterable[GeneratedDocument],
) -> list[DownloadDocument]:
    """Read a complete staged set before making any item available."""

    directory = Path(output_directory)
    artifacts: list[DownloadArtifact] = []
    try:
        for document in generated:
            path = directory / document.file_name
            if path.parent != directory or not path.is_file():
                raise OSError("generated document is missing")
            artifacts.append(
                DownloadArtifact(file_name=document.file_name, content=path.read_bytes())
            )
    except OSError as exc:
        raise DocumentPublishError(
            "Не удалось передать сформированные документы в браузер."
        ) from exc
    return store.publish(artifacts)
