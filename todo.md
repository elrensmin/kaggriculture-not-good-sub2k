# todo

The real gap versus Boey is lead time, not quantity: he buys land and fills it the same day
(19 plants on d6); we buy on d6/d8 with no seed for it, so it sits bare 1–2 days. His
`empty = 0` isn't a bigger seed budget — it's an ordered one.

The structural rule to impose: a sequenced seed buy — the seed for a quadrant is bought the
day before the land, out of the same budget, ordered ahead of the land order within
`MAX_ORDERS`, total spend unchanged. Not `SEED_FILL_BUFFER` (enlarges spend), not a bigger
budget.

acts → watering → production → revenue.

**target: to match Boey's performance in the first 10 days.**
