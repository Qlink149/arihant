"""Cursor pagination processes all lead batches."""

import asyncio
from unittest.mock import MagicMock

from crm.services.sla_engine import _paginate_leads


def test_paginate_yields_multiple_batches():
    asyncio.run(_paginate_multiple_batches())


async def _paginate_multiple_batches():
    leads = [{"id": f"L{i}", "_id": i} for i in range(250)]

    class FakeCursor:
        def __init__(self, docs):
            self._docs = docs

        def sort(self, *args, **kwargs):
            return self

        def __aiter__(self):
            self._iter = iter(self._docs)
            return self

        async def __anext__(self):
            try:
                return next(self._iter)
            except StopIteration:
                raise StopAsyncIteration

    collection = MagicMock()
    collection.find.return_value = FakeCursor(leads)

    batches = []
    async for batch in _paginate_leads(collection, {}, batch_size=200):
        batches.append(batch)

    assert len(batches) == 2
    assert len(batches[0]) == 200
    assert len(batches[1]) == 50
