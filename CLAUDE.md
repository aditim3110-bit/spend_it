# SpendIt

A payment-splitting app built to compete with Splitwise. The full spec is `docs/PRD.md`. Read the sections for a feature before starting work on it. The PRD wins over any assumption.

## Repo layout

- `backend/`: FastAPI API (Python 3.12, uv)
- `ios/`: SwiftUI app (`SpendIt.xcodeproj`, created in Xcode, never by hand)
- `fixtures/split/`: shared JSON test cases for the split engine. Python and Swift must both pass every case.
- `shared/currencies.json`: ISO 4217 currencies and their decimals (real money only), read by both backend and iOS. Never use Apple's or Babel's currency data for decimals.
- `web/`: web app, Phase 4 (not yet)
- `docs/`: PRD and design notes

## Commands

- Start services: `docker compose up -d db redis`
- Run the API: `cd backend && uv run fastapi dev app/main.py`
- Backend tests: `cd backend && uv run pytest`
- Migrations: `cd backend && uv run alembic upgrade head` (new: `uv run alembic revision --autogenerate -m "..."`)
- Lint and format: `cd backend && uv run ruff check . && uv run ruff format .`
- iOS build and test: `xcodebuild -project ios/SpendIt.xcodeproj -scheme SpendIt -destination 'platform=iOS Simulator,name=iPhone 17' test` (adjust the simulator name to one installed)

## Rules that must never break

1. **Money is integers.** Store and pass amounts as integer minor units plus an ISO 4217 currency code (S$84.50 is `8450, "SGD"`). Never use float for money, in Python or Swift. Use the currency's own exponent (JPY 0, KWD 3).
2. **Rounding happens once,** inside the split engine, using the largest-remainder method. Ties go first to the single payer (if there is exactly one and they are a participant), then by participant ID ascending (lowercase string compare). See PRD section 7.
3. **Every expense balances.** The payers' total, the shares' total and the expense amount are all equal. The split engine enforces this and returns typed errors. Caps: total ≤ 10¹³ minor units, ≤ 100 payers, ≤ 100 participants, each payer and each person's input capped at the total (percent ≤ 100%, share weight ≤ 1,000). See PRD section 7, "Limits".
4. **The ledger is append-only.** An edit creates a new `expense_revisions` row. A delete is a soft delete. Balances are derived and can be rebuilt from revisions.
5. **Writes are idempotent.** Every POST, PUT, PATCH and DELETE needs an `Idempotency-Key` header, money or not. A retry with the same key replays the saved response; the same key with a different body is rejected.
6. **The server decides.** Clients may preview a split locally, but the server recomputes it, and the server's result is what gets saved.
7. **The API is versioned and contract-first.** All routes live under `/v1`. The OpenAPI spec is the contract. After changing the API, regenerate the Swift client.
8. **No secrets in the repo.** Use `.env` (gitignored) and `.env.example`.

## Backend conventions

- Layers: thin routers (`app/api/v1/`) call services (`app/services/`), which call repositories (`app/repositories/`), which use ORM models (`app/models/`).
- Pydantic v2 schemas use `extra="forbid"`. Use async SQLAlchemy 2.0 and Alembic.
- Errors follow RFC 9457 problem details.
- Property-based tests with Hypothesis on the split engine and balances. Example tests alone are not enough.

## iOS conventions

- SwiftUI, minimum iOS 17, `@Observable` view models, repository pattern, SwiftData for the offline cache.
- Feature modules are local Swift packages (`Ledger`, `Groups`, `ReceiptScan`, ...). They depend on `CoreAPI` and `DesignSystem` only, never on each other.
- The API client is generated from the backend's OpenAPI spec (`swift-openapi-generator`).
- Add Swift files inside the project's synced folders so Xcode picks them up. Never edit `project.pbxproj` by hand; ask me to add targets or capabilities in Xcode.

## How I want to work

- I want to understand the code, not just receive it. Explain non-obvious design choices in a sentence or two.
- When I say "I'll write this one", give me the plan, the interface and the tests, not the implementation. Review my code afterwards.
- Use plan mode for anything that touches more than a couple of files. Wait for my go-ahead before writing.
- Work in small increments that each end in passing tests. Run the tests before you say something is done.
- If the PRD is ambiguous or contradicts itself, stop and ask. Don't guess.

## Current phase

Phase 0, Foundations (PRD section 19): repo skeleton, split engine plus shared fixtures, initial schema, OTP auth, CI.
