"""Nightly ledger audit (PRD sections 8 and 16).

    cd backend && uv run python -m app.jobs.audit            # check and repair
    cd backend && uv run python -m app.jobs.audit --dry-run  # check only

It checks two things:
1. Every saved revision balances: payers = shares = amount. The ledger is append-only, so
   a broken revision can't be "repaired" automatically; it is reported for a human, and
   no balances are changed in that run.
2. The balances table equals a rebuild from scratch from the ledger. Any difference is
   reported and (unless --dry-run) corrected in the same transaction.

Problems are logged at ERROR level and the command exits with status 1, so whatever runs
it nightly (cron, a scheduled job) can alert on it. Wiring up that schedule and the alert
is a deploy task. Running it once also fills the table for expenses saved before the
balances table existed.
"""

import argparse
import asyncio
import logging
import sys
import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import make_engine, make_sessionmaker
from app.repositories import balances as balance_repo
from app.repositories.balances import Key
from app.services.balances import expected_from_ledger

log = logging.getLogger("spendit.audit")

UNBALANCED_REVISIONS = text(
    """
    SELECT r.id FROM expense_revisions r
    LEFT JOIN (SELECT revision_id, sum(amount_minor) total FROM expense_payers
               GROUP BY revision_id) p ON p.revision_id = r.id
    LEFT JOIN (SELECT revision_id, sum(owed_minor) total FROM expense_shares
               GROUP BY revision_id) s ON s.revision_id = r.id
    WHERE p.total IS DISTINCT FROM r.amount_minor OR s.total IS DISTINCT FROM r.amount_minor
    """
)


@dataclass
class AuditReport:
    unbalanced_revisions: list[uuid.UUID] = field(default_factory=list)
    # key -> (what the table says, what the ledger says)
    balance_differences: dict[Key, tuple[int, int]] = field(default_factory=dict)
    repaired: bool = False

    @property
    def clean(self) -> bool:
        return not self.unbalanced_revisions and not self.balance_differences


async def run_audit(session: AsyncSession, *, repair: bool = True) -> AuditReport:
    """Run the audit in one transaction and commit any repair."""
    await balance_repo.lock_for_audit(session)
    report = AuditReport()

    report.unbalanced_revisions = list((await session.execute(UNBALANCED_REVISIONS)).scalars())
    for rev in report.unbalanced_revisions:
        log.error("Ledger audit: revision %s does not balance", rev)

    table = await balance_repo.all_nonzero(session)
    expected = await expected_from_ledger(session, skip=set(report.unbalanced_revisions))
    for key in sorted(table.keys() | expected.keys(), key=Key.sort_key):
        stored, correct = table.get(key, 0), expected.get(key, 0)
        if stored != correct:
            report.balance_differences[key] = (stored, correct)
            log.error("Ledger audit: balance %s is %s, ledger says %s", key, stored, correct)

    if report.unbalanced_revisions and repair:
        # A damaged ledger needs a person to look at it; don't change anything on our own.
        log.error("Ledger audit: not repairing balances while revisions are unbalanced")
        repair = False
    if report.balance_differences and repair:
        fixes = {
            key: correct - stored for key, (stored, correct) in report.balance_differences.items()
        }
        await balance_repo.apply(session, fixes)
        report.repaired = True
        log.error("Ledger audit: repaired %d balance rows", len(fixes))
    await session.commit()
    if report.clean:
        log.info("Ledger audit: clean")
    return report


async def _main(repair: bool) -> int:
    engine = make_engine(get_settings().database_url)
    try:
        async with make_sessionmaker(engine)() as session:
            report = await run_audit(session, repair=repair)
    finally:
        await engine.dispose()
    return 0 if report.clean else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the ledger and balances.")
    parser.add_argument("--dry-run", action="store_true", help="report only, don't repair")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(asyncio.run(_main(repair=not args.dry_run)))


if __name__ == "__main__":
    main()
