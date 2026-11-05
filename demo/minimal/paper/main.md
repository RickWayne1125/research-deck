# Lookahead Eviction for a Small GPU Block Cache

Synthetic demo paper: every number in it is made up.

## 4 Evaluation

We replay a synthetic trace of 20,000 requests over 1,024 blocks through a cache of 64 blocks. The hot set moves to
other blocks every 2,000 requests.

LRU, the baseline, has a hit rate of 0.41. Counting past requests does not help: LFU reaches only 0.37, because its
counts still favor the blocks that were popular before the hot set moved. Lookahead eviction reads the next 8
requests in the serving queue and, on a miss, evicts the cached block whose next request is farthest away. It raises
the hit rate to 0.61 (Figure 1).

The look-ahead window needs no extra state: the scheduler already holds the queued requests, and the policy recieves
them with every access.
