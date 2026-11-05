"""Least-recently-used eviction: the baseline."""
from collections import OrderedDict


class LRUCache:
    def __init__(self, capacity: int, **_):
        self.capacity = capacity
        self.blocks: OrderedDict[int, None] = OrderedDict()   # least recently used first

    def access(self, block: int, upcoming: list[int]) -> bool:
        """True on a hit. On a miss the block is inserted and the least recently used block is evicted."""
        if block in self.blocks:
            self.blocks.move_to_end(block)
            return True
        if len(self.blocks) >= self.capacity:
            self.blocks.popitem(last=False)
        self.blocks[block] = None
        return False


POLICY = LRUCache
