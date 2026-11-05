"""Lookahead eviction (attempt B): the serving queue already holds the next requests, so on a miss evict the cached
block whose next request in that window is farthest away. A block the window never asks for goes first."""
from collections import OrderedDict


class LookaheadCache:
    def __init__(self, capacity: int, window: int = 8, **_):
        self.capacity = capacity
        self.window = window
        self.blocks: OrderedDict[int, None] = OrderedDict()   # least recently used first

    def access(self, block: int, upcoming: list[int]) -> bool:
        if block in self.blocks:
            self.blocks.move_to_end(block)
            return True
        if len(self.blocks) >= self.capacity:
            del self.blocks[self.victim(upcoming[: self.window])]
        self.blocks[block] = None
        return False

    def victim(self, upcoming: list[int]) -> int:
        next_use: dict[int, int] = {}
        for i, b in enumerate(upcoming):
            next_use.setdefault(b, i)
        # Ties (blocks the window never asks for) go in LRU order: max() keeps the first, the least recently used.
        return max(self.blocks, key=lambda b: next_use.get(b, len(upcoming)))


POLICY = LookaheadCache
