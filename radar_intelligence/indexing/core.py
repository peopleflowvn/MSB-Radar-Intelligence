from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Mapping, Protocol, Sequence

from radar_intelligence.contracts import DocumentRef


def _required(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    return value


class ChangeOperation(str, Enum):
    UPSERT = "upsert"
    DELETE = "delete"
    PERSON_REASSIGNED = "person_reassigned"


@dataclass(frozen=True)
class DocumentChange:
    event_id: str
    operation: ChangeOperation
    document: DocumentRef
    updated_at: datetime
    source: str
    document_type: str
    text: str | None = None
    document_date: datetime | None = None
    application_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("event_id", "source", "document_type"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if self.updated_at.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")
        if self.operation != ChangeOperation.DELETE:
            object.__setattr__(self, "text", _required(self.text or "", "text"))

    @property
    def fingerprint(self) -> str:
        fields = (
            self.operation.value,
            self.document.document_id,
            self.document.person_id,
            self.document.version,
            self.document.content_hash,
            self.updated_at.astimezone(timezone.utc).isoformat(),
            self.text or "",
        )
        return sha256("\x1f".join(fields).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SearchDocument:
    chunk_id: str
    content: str
    embedding: tuple[float, ...] | None
    metadata: Mapping[str, str | int | None]


class Embedder(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class DocumentIndex(Protocol):
    def apply(self, change: DocumentChange, chunks: tuple[SearchDocument, ...]) -> IndexApplyResult: ...


class DocumentConverter:
    """Convert a Radar document into disposable, traceable search chunks."""

    def __init__(self, max_chars: int = 1200) -> None:
        if max_chars < 100:
            raise ValueError("max_chars must be at least 100")
        self._max_chars = max_chars

    def convert(self, change: DocumentChange) -> tuple[SearchDocument, ...]:
        if change.operation == ChangeOperation.DELETE:
            return ()
        pieces = self._split(change.text or "")
        result = []
        for position, content in enumerate(pieces):
            raw_id = f"{change.document.document_id}:{change.document.version}:{position}:{change.document.content_hash}"
            chunk_id = sha256(raw_id.encode("utf-8")).hexdigest()
            result.append(SearchDocument(chunk_id, content, None, {
                "person_id": change.document.person_id,
                "document_id": change.document.document_id,
                "source_record_id": change.document.source_record_id,
                "application_id": change.application_id,
                "source": change.source,
                "document_type": change.document_type,
                "document_date": change.document_date.isoformat() if change.document_date else None,
                "chunk_id": chunk_id,
                "chunk_position": position,
                "content_hash": change.document.content_hash,
                "version": change.document.version,
                "updated_at": change.updated_at.astimezone(timezone.utc).isoformat(),
            }))
        return tuple(result)

    def _split(self, text: str) -> tuple[str, ...]:
        paragraphs = [" ".join(part.split()) for part in text.replace("\r\n", "\n").split("\n")]
        paragraphs = [part for part in paragraphs if part]
        pieces: list[str] = []
        for paragraph in paragraphs:
            while len(paragraph) > self._max_chars:
                boundary = paragraph.rfind(" ", 0, self._max_chars + 1)
                boundary = boundary if boundary > 0 else self._max_chars
                pieces.append(paragraph[:boundary].strip())
                paragraph = paragraph[boundary:].strip()
            if paragraph:
                pieces.append(paragraph)

        # CV extraction commonly emits one short line per field. Indexing each
        # line separately produced tens of thousands of context-poor chunks.
        # Pack adjacent paragraphs without crossing the embedding-safe bound;
        # keep a newline so section/field boundaries remain visible to models.
        chunks: list[str] = []
        current = ""
        for piece in pieces:
            candidate = f"{current}\n{piece}" if current else piece
            if current and len(candidate) > self._max_chars:
                chunks.append(current)
                current = piece
            else:
                current = candidate
        if current:
            chunks.append(current)
        return tuple(chunks)


@dataclass(frozen=True)
class _VersionMarker:
    updated_at: datetime
    operation: ChangeOperation
    event_id: str

    @property
    def ordering_key(self) -> tuple[datetime, int, str]:
        # A delete wins a same-time race so an older representation cannot revive.
        priority = 1 if self.operation == ChangeOperation.DELETE else 0
        return (self.updated_at, priority, self.event_id)


@dataclass(frozen=True)
class IndexApplyResult:
    status: str
    document_id: str
    chunk_count: int


class InMemoryDocumentIndex:
    """Reference store for lifecycle semantics; not a production store."""

    def __init__(self) -> None:
        self._documents: dict[str, tuple[SearchDocument, ...]] = {}
        self._markers: dict[str, _VersionMarker] = {}
        self._events: dict[str, str] = {}

    def apply(self, change: DocumentChange, chunks: tuple[SearchDocument, ...]) -> IndexApplyResult:
        known_fingerprint = self._events.get(change.event_id)
        if known_fingerprint is not None:
            if known_fingerprint != change.fingerprint:
                raise ValueError("event_id was reused with a different payload")
            current = self._documents.get(change.document.document_id, ())
            return IndexApplyResult("duplicate", change.document.document_id, len(current))

        incoming = _VersionMarker(change.updated_at, change.operation, change.event_id)
        current_marker = self._markers.get(change.document.document_id)
        if current_marker is not None and incoming.ordering_key <= current_marker.ordering_key:
            self._events[change.event_id] = change.fingerprint
            current = self._documents.get(change.document.document_id, ())
            return IndexApplyResult("stale", change.document.document_id, len(current))

        self._events[change.event_id] = change.fingerprint
        self._markers[change.document.document_id] = incoming
        if change.operation == ChangeOperation.DELETE:
            self._documents.pop(change.document.document_id, None)
            return IndexApplyResult("deleted", change.document.document_id, 0)
        self._documents[change.document.document_id] = chunks
        return IndexApplyResult("indexed", change.document.document_id, len(chunks))

    def documents(self, document_id: str | None = None) -> tuple[SearchDocument, ...]:
        if document_id is not None:
            return self._documents.get(document_id, ())
        return tuple(chunk for chunks in self._documents.values() for chunk in chunks)


class IncrementalIndexer:
    def __init__(
        self,
        store: DocumentIndex,
        converter: DocumentConverter | None = None,
        embedder: Embedder | None = None,
        embedding_batch_size: int = 32,
    ) -> None:
        if embedding_batch_size <= 0:
            raise ValueError("embedding_batch_size must be positive")
        self._store = store
        self._converter = converter or DocumentConverter()
        self._embedder = embedder
        self._embedding_batch_size = embedding_batch_size

    def apply(self, change: DocumentChange) -> IndexApplyResult:
        chunks = self._converter.convert(change)
        if chunks and self._embedder is not None:
            vectors = []
            for start in range(0, len(chunks), self._embedding_batch_size):
                batch = chunks[start:start + self._embedding_batch_size]
                rows = self._embedder.embed_documents([chunk.content for chunk in batch])
                converted = [tuple(float(value) for value in row) for row in rows]
                if len(converted) != len(batch) or any(not vector for vector in converted):
                    raise ValueError("embedder returned an invalid vector batch")
                vectors.extend(converted)
            vectors = tuple(vectors)
            if len(vectors) != len(chunks) or any(not vector for vector in vectors):
                raise ValueError("embedder returned an invalid vector batch")
            chunks = tuple(replace(chunk, embedding=vector) for chunk, vector in zip(chunks, vectors))
        return self._store.apply(change, chunks)
