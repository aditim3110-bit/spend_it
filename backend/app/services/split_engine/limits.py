"""Caps from PRD section 7 ("Limits").

They keep every number in the rounding formula inside a 64-bit integer, so the
Swift port on the iPhone gets exactly the same answers as this Python code.
"""

MAX_TOTAL = 10**13  # minor units: S$100 billion, ¥10 trillion, KWD 10 billion
MAX_PARTICIPANTS = 100
MAX_PAYERS = 100
MAX_SHARE_WEIGHT = 1000  # shares mode: a couple is 2, nobody needs 1000
PERCENT_TOTAL = 10_000  # percentages are basis points: 10000 = 100.00%
