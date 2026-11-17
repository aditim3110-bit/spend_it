# Split engine fixtures

Shared test cases for the split engine. The Python engine (`backend/app/services/split_engine/`)
and the Swift port must both pass **every** file here. Format: `../schema/split.schema.json`.

## Units

- Money is integer minor units of `currency` (SGD 8450 = S$84.50, JPY 1000 = ¥1000, KWD 1000 = 1.000 KWD).
- `percent` values are basis points: `3333` = 33.33%, and they must sum to `10000`.
- `shares` values are integer weights.
- IDs are lowercase ASCII and are compared byte by byte.

## Rounding (PRD section 7)

Largest remainder: each person gets `floor(total * w / sum_w)`. The leftover units go one each to
the people with the largest fractional remainders. Exact ties are ordered:

1. The payer, if there is exactly one payer and they are a participant.
2. Then participant ID, ascending.

## Validation order

When an input has several problems, the engine reports the first one in this order. Most fixtures have only
one problem; the few with two pin down this order. Both implementations must follow it.

1. `UnsupportedCurrency`
2. `InvalidTotal` (total <= 0 or total > 10^13)
3. `EmptyParticipants` (`side: payers`, then `side: shares`)
4. `TooManyParticipants` (more than 100; payers, then shares)
5. `DuplicateParticipant` (payers, then shares)
6. `InvalidPayerAmount` (a payer amount <= 0 or > total)
7. `SumMismatch` with `side: payers`
8. `NegativeShare` (any negative input value)
9. `ShareTooLarge` (an input above its cap: exact > total, percent > 10000, shares > 1000)
10. Mode-specific checks: `PercentSumInvalid`, `ZeroTotalWeight`, or `SumMismatch` with `side: shares` for exact

## Limits and overflow

Caps: total <= 10^13, at most 100 payers and 100 participants, each payer amount <= total, and each
input <= its cap (exact <= total, percent <= 10000, shares <= 1000). Check the individual values
before adding them up. Then `total * w` is at most 10^18 and every sum is at most 10^15, so both
fit in a signed 64-bit integer and Python and Swift report identical errors.
