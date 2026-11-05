"""A synthetic request trace: block ids with a skewed popularity whose hot set moves every `drift_every` requests."""
import random


def make_trace(length: int, blocks: int, skew: float, drift_every: int, seed: int) -> list[int]:
    rng = random.Random(seed)
    cum, total = [], 0.0
    for rank in range(blocks):
        total += 1.0 / (rank + 1) ** skew
        cum.append(total)
    ranks = rng.choices(range(blocks), cum_weights=cum, k=length)
    order = list(range(blocks))            # order[rank] = the block that currently has that popularity rank
    trace = []
    for i, rank in enumerate(ranks):
        if drift_every and i and i % drift_every == 0:
            shift = blocks // 8
            order = order[shift:] + order[:shift]   # the hot set moves to other blocks
        trace.append(order[rank])
    return trace
