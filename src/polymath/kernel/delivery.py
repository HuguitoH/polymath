import asyncio
from pathlib import Path
from typing import Protocol


class Deliverer(Protocol):
    """Renders a brief to wherever Hugo actually receives it."""

    name: str

    async def deliver(self, text: str) -> None: ...


class ConsoleDeliverer:
    name = "console"

    async def deliver(self, text: str) -> None:
        print(text)
