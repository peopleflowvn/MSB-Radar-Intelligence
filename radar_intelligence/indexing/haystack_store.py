from __future__ import annotations

from typing import Any

from .core import DocumentChange, InMemoryDocumentIndex, IndexApplyResult, SearchDocument


class HaystackDocumentIndex:
    """Haystack adapter preserving Radar-owned document lifecycle semantics.

    The supplied document store is infrastructure only. Person identity,
    document versions, event ordering and tombstones remain controlled here.
    """

    def __init__(self, document_store: Any) -> None:
        self._store = document_store
        self._lifecycle = InMemoryDocumentIndex()

    def apply(self, change: DocumentChange, chunks: tuple[SearchDocument, ...]) -> IndexApplyResult:
        result = self._lifecycle.apply(change, chunks)
        if result.status in {"duplicate", "stale"}:
            return result

        old_ids = [document.id for document in self._haystack_documents(change.document.document_id)]
        if result.status == "deleted":
            if old_ids:
                self._store.delete_documents(old_ids)
            return result

        try:
            from haystack import Document
            from haystack.document_stores.types import DuplicatePolicy
        except ImportError as exc:  # pragma: no cover - exercised without optional dependency
            raise RuntimeError("Haystack adapter requires the 'haystack' optional dependency") from exc

        new_documents = [
            Document(
                id=chunk.chunk_id,
                content=chunk.content,
                embedding=list(chunk.embedding) if chunk.embedding is not None else None,
                meta=dict(chunk.metadata),
            )
            for chunk in chunks
        ]
        self._store.write_documents(new_documents, policy=DuplicatePolicy.OVERWRITE)
        new_ids = {document.id for document in new_documents}
        obsolete_ids = [document_id for document_id in old_ids if document_id not in new_ids]
        if obsolete_ids:
            self._store.delete_documents(obsolete_ids)
        return result

    def documents(self, document_id: str | None = None) -> tuple[SearchDocument, ...]:
        source = self._haystack_documents(document_id)
        return tuple(
            SearchDocument(
                chunk_id=document.id,
                content=document.content or "",
                embedding=tuple(document.embedding) if document.embedding is not None else None,
                metadata=dict(document.meta),
            )
            for document in source
        )

    def _haystack_documents(self, document_id: str | None) -> list[Any]:
        documents = self._store.filter_documents()
        if document_id is None:
            return documents
        return [document for document in documents if document.meta.get("document_id") == document_id]
