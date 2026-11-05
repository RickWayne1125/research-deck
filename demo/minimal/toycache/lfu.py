"""Least-frequently-used eviction (attempt A): keep the blocks that were requested most often so far."""
from collections import Counter


class LFUCache:
    def __init__(self, capacity: int, **_):
        self.capacity = capacity
        self.blocks: set[int] = set()
        self.counts: Counter[int] = Counter()

    def access(self, block: int, upcoming: list[int]) -> bool:
        self.counts[block] += 1
        if block in self.blocks:
            return True
        if len(self.blocks) >= self.capacity:
            self.blocks.remove(min(self.blocks, key=lambda b: (self.counts[b], b)))
        self.blocks.add(block)
        return False


POLICY = LFUCache
