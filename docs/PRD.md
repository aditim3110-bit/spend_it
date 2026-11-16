# SpendIt — Master PRD

Nov 12, 2026

## 1. Executive summary & product vision

SpendIt is a shared-expense app whose promise is that nobody at the table has to think about money until the moment they settle, and even then it takes one tap. It competes with Splitwise on the two things Splitwise users complain about most: the friction of actually paying, and the manual labour of entering and splitting a bill.

**Vision statement.** Worry less about the money, live more in the moment. Every design decision is judged against one question: does this remove a step between "we spent money together" and "we're square"?

**What SpendIt does that Splitwise does not (launch differentiators):**

1. **Zero-entry bills.** Scan a receipt, or just say "split dinner 84 dollars with Aditi and Ravi, I paid" — SpendIt drafts the expense and you confirm.
2. **Everyone claims their own items.** A scanned bill becomes a shared claim sheet; each person ticks what they ate, and tax and service charge follow proportionally. The payer stops being the group accountant.
3. **Nearby detection.** In a big group, SpendIt proposes the people physically around you as participants, learns your corrections, and gets quieter over time.
4. **Split with anyone.** A non-user receives a link, types a name and a phone or email, claims their items, and is in the ledger — no app install, no account.
5. **Settle in-app.** A SpendIt Wallet holds a balance you can top up, settle from and withdraw — no switching to a bank app and no re-recording the payment.

**Scope of this PRD.** This is the master document: it covers the full product and every feature above, with the implementation approach for each, and then sequences them into an iOS-first launch. Individual features will get their own detailed specs that inherit from this one.

**Platform decision in one line.** iOS first (SwiftUI, built in Xcode), a single FastAPI backend (Python, built in VS Code) serving iOS now and web later, Postgres as the ledger of record. Section 5 explains why.

## 2. Market & competitive context

Splitwise is the incumbent, but its 2025–2026 moves — a tightened free tier and roughly doubled Pro pricing — have opened a window for a challenger with a better free experience and real payments outside the US and Europe.

| Player | Model (as of mid-2026) | Payments | Receipt / AI entry | Weak spot SpendIt attacks |
| --- | --- | --- | --- | --- |
| [Splitwise](https://apps.apple.com/app/splitwise-bill-splitter/id458023433) | Free tier capped at a few expenses per day with ads; Pro about US$4.99/mo or US$39.99–49.99/yr depending on storefront | Splitwise Pay (US only, via Coastal Community Bank); Pay by Bank via Tink in UK, FR, DE, AT; Venmo/PayPal (US), Paytm (India) | Receipt scan is Pro-only; no voice entry; payer does the item assignment | No in-app settlement in Singapore, India (beyond Paytm) or most of APAC; daily caps; manual item splitting |
| Tricount | Free, no paid tier | None in-app | None | Pure tracker, no payments or AI |
| Partly | Free with AI scan; Premium about €19.99/yr | IBAN / PayPal / Revolut links (Europe) | AI receipt scan | Europe-centric |
| Splid | Free, works without accounts | None | None | Simple, no rich features |

**What the market tells us**

- Payment integration is the most-requested Splitwise feature by its own admission, and App Store reviews repeatedly cite "two apps for every transaction" as the pain. In-app settlement is a core differentiator, not a nice-to-have.
- Splitwise's receipt scanning being paywalled, and its item assignment being done by one person, leaves room for a free, collaborative claim flow.
- Free-tier generosity is now a competitive lever. SpendIt should keep core splitting unlimited and free, and monetise payments (FX spread, instant-withdrawal fees) and power features (analytics, exports) later.
- No incumbent has a native proximity or voice entry path. These are new interaction models, not feature-parity items.

**Initial market.** Singapore first (the founding team's home market; PayNow rails, high iPhone share, dense group-dining culture), then India and the wider APAC corridor where Splitwise payments are absent. Section 11 explains how the wallet licensing path follows this sequence.

Sources: [Splitwise App Store listing](https://apps.apple.com/app/splitwise-bill-splitter/id458023433), [Splitwise Pay FAQ](https://dx0qysuen8cbs.cloudfront.net/pay), [Open Banking Expo on the Tink expansion, Oct 2025](https://www.openbankingexpo.com/news/splitwise-expands-pay-by-bank-across-europe-with-tink/), [Finny: Splitwise pricing 2026](https://getfinny.app/blog/splitwise-pricing-2026), [Locals Insider Splitwise review](https://localsinsider.com/apps/track-shared-costs-splitwise-app/), [Partly vs Splitwise](https://app-partly.web.app/en/blog/partly-vs-splitwise/). Pricing figures are storefront-dependent and should be re-verified before any pricing decision.

## 3. Goals, non-goals & success metrics

The launch goal is a ledger people trust and an entry flow that is faster than Splitwise's; payments and AI entry are what make them switch.

**Goals (12 months from iOS launch)**

| Goal | Metric | Target |
| --- | --- | --- |
| Entry is effortless | Median time from "add expense" tap to saved expense | < 12 s manual, < 6 s voice or scan |
| People actually settle | Share of debts settled within 7 days of creation | > 60% (Splitwise anecdotally far lower) |
| Groups stick | Groups with ≥ 1 expense in each of 4 consecutive weeks | 40% of groups created |
| Guests convert | Guest-link recipients who later create an account | > 25% |
| Ledger is trusted | Balance disputes or "wrong math" support tickets per 10k expenses | < 2 |
| Wallet adoption (once live) | Monthly settlements through Wallet as share of all settlements | > 35% in Singapore |

**Non-goals for v1**

- Budgeting, spend categorisation or personal finance insights.
- Android (follows web; see Section 19).
- Business or team expense reporting, approvals, reimbursement workflows.
- Being a general P2P payments app. The Wallet exists only to settle SpendIt balances.
- Crypto, BNPL or lending of any kind.

**Guardrail metrics** (must not regress while chasing the goals): crash-free sessions > 99.5%; p95 API latency < 300 ms for ledger reads; zero ledger inconsistencies (sum of all balances in any group must equal zero at all times, checked nightly).

## 4. Personas & core jobs to be done

Four personas drive the requirements; the Organiser is the one who installs the app and brings everyone else.

| Persona | Who | Core job | What they need from SpendIt |
| --- | --- | --- | --- |
| The Organiser | Pays first at dinner, books the Airbnb, chases people after | "Get paid back without being the nag" | Fast entry (scan, voice), auto participant selection, one-tap reminders, in-app settlement |
| The Occasional | Joins a trip group twice a year, otherwise dormant | "Tell me what I owe and let me pay it now" | Clear balance screen, Wallet or PayNow settle, no daily caps or ads punishing low use |
| The Couple / Flatmates | Two people, dozens of small shared costs a month | "Keep a running tally, settle monthly" | Two-person shortcuts (you paid / split equally), recurring expenses later, net balance not line items |
| The Guest | Was at dinner, has no account and will not install one | "Claim my share in 30 seconds and be done" | Web claim link, no signup, item-level claiming, a receipt of what they owe and how to pay |

**Top user stories (launch)**

1. As an Organiser, I can scan the dinner receipt, SpendIt proposes the people around me, each of them ticks their dishes, and the expense is saved with tax split proportionally.
2. As any user, I can say "I paid 120 for groceries, split with Aditi" and confirm a correctly drafted expense.
3. As an Occasional, I open the app, see "You owe Pranav S$42.50", tap Settle, and it is done from my Wallet or via a PayNow deep link.
4. As a Guest, I open a link, enter my name and phone, claim "2 oranges, 4 apples", and see exactly what I owe and how to pay.
5. As a Flatmate, I log "Electricity, S$180, I paid, split equally" in three taps.
6. As any user, I can move an expense I logged against a friend into our trip group once the group exists, without re-entering it.

## 5. Platform & technical foundation

One FastAPI backend owns all business logic and the ledger; the iOS app (SwiftUI) and the later web app are thin clients of the same API, so splitting math is never duplicated across platforms.

&#91;embedded content: system architecture: 3 clients, 1 API, 3 stores, 3 external services\]

All three clients call the same versioned API; the API alone talks to the stores and to external services, so the split math, permissions and money rules exist in exactly one place.

**A correction on the stack.** FastAPI is a Python web framework for building APIs; it cannot be the iOS frontend. The iOS client has to be Swift (SwiftUI) built in Xcode, as you intended. The web client, when it comes, will be a JavaScript app (React or SvelteKit) or server-rendered templates from FastAPI itself for simple pages like the guest claim flow. The division is:

| Layer | Technology | Built in | Owns |
| --- | --- | --- | --- |
| iOS app | Swift 6, SwiftUI, Swift Concurrency, SwiftData for the local cache | Xcode | UI, offline cache, camera, speech, Bluetooth, Apple Pay sheet |
| Guest web pages (launch) | FastAPI + Jinja2 templates + a little HTMX; mobile-first | VS Code | Guest claim links, settlement receipts, email/SMS landing pages |
| Web app (Phase 3) | React (Next.js) or SvelteKit, TypeScript, same REST API | VS Code | Full product parity on desktop |
| API | FastAPI (Python 3.12), Pydantic v2 models, async SQLAlchemy 2.0, Alembic migrations | VS Code | All business rules, split math, balances, auth, permissions |
| Database | PostgreSQL 16 (Supabase or Neon in early stages, RDS later) | — | Ledger of record; every money value in integer minor units |
| Cache & queues | Redis (rate limits, OTP state, proximity sessions); background jobs via ARQ or Celery | — | Receipt OCR jobs, notifications, FX refresh, nightly ledger audit |
| Object storage | S3-compatible bucket with signed URLs | — | Receipt images, voice clips (deleted after transcription) |
| AI services | Apple Speech (on-device) → LLM with structured output (Claude API) for intent parsing; Apple Vision for OCR, LLM vision for line-item structuring | — | Voice entry, receipt itemisation |
| Push & messaging | APNs for iOS; Twilio Verify (SMS OTP), Resend or SES (email) | — | OTPs, reminders, guest links |
| Payments (Phase 2) | Licensed partner, see Section 11 | — | Wallet top-up, hold, payout |
| Observability | OpenTelemetry → Grafana Cloud or Datadog; Sentry on iOS and API | — | Latency, errors, ledger audit alerts |

**Backend principles**

- **The ledger is append-only.** Expenses are never updated in place; every edit creates a new revision and the previous one is retained. Balances are derived, never stored as the source of truth (they are cached and reconciled nightly).
- **Money is integers.** Every amount is stored as `(amount_minor: bigint, currency: char(3))`. Rounding happens exactly once, at the split step, using the largest-remainder method (Section 7). No floats anywhere in the money path, including Swift (`Decimal` or `Int` minor units on the client).
- **Every write is idempotent.** Clients send an `Idempotency-Key` header (a UUID generated on-device); the API stores the response for 24 h and replays it on retry. This is what makes offline queuing and flaky-network retries safe.
- **Thin clients.** The iOS app may preview a split locally for responsiveness, but the server recomputes and the server's result is what is saved and displayed.
- **Versioned API from day one.** `/v1/...` so the web client and future Android client can evolve independently of iOS releases that users install slowly.

**iOS app architecture**

- SwiftUI with an MVVM-plus-repository structure: Views → ViewModels (`@Observable`) → Repositories (cache + API client) → generated API client (from the FastAPI OpenAPI spec via `swift-openapi-generator`). Generating the client from the spec keeps the two codebases from drifting.
- A local write-ahead queue in SwiftData: expenses created offline are stored with status `pending_sync` and flushed in order with their idempotency keys when the network returns.
- Feature modules as Swift packages: `Ledger`, `Groups`, `Wallet`, `Proximity`, `VoiceEntry`, `ReceiptScan`, `GuestLinks`. Each depends on `CoreAPI` and `DesignSystem`, never on each other, so a feature can be flag-gated or cut without ripple.
- Minimum iOS 17 (needed for `@Observable`, SwiftData and the current Speech APIs). This covers the vast majority of active iPhones in Singapore.

**Environments.** `dev` (local Docker Compose: Postgres, Redis, API), `staging` (TestFlight builds point here), `prod`. Feature flags via a simple `feature_flags` table read on app launch and cached, so Bluetooth, voice and wallet can be enabled per user cohort.

## 6. Identity & onboarding

A user is identified by at least one verified contact point — an E.164 phone number or an email address — and the second one, when added, doubles as account recovery and as a second way friends can find them.

**Requirements**

- Sign-up and sign-in are the same flow: enter phone (with country code picker defaulting to the SIM or locale region) or email, receive a 6-digit OTP, enter it. No passwords.
- Sign in with Apple is offered on iOS because App Store review requires it when any third-party login exists, and because it gives us a verified email with zero typing. It maps to the email identity (Apple's private-relay address counts as the email).
- Both identifiers are globally unique: one phone number or email can belong to exactly one account. Attempting to add one already in use triggers a merge-or-recover flow, never a silent failure.
- A user with both identifiers can sign in or recover with either. A user with only one is prompted (not forced) after their first settled expense to add the other.
- Profile: display name (required), avatar (optional), default currency (derived from region, editable), home country.

**OTP mechanics**

- SMS via Twilio Verify (handles carrier routing and fraud rules). Email OTP via a transactional email provider, same code format.
- Codes expire in 10 minutes, 5 attempts per code, 3 sends per identifier per hour, 10 per IP per hour. State lives in Redis keyed by a hashed identifier.
- On success the API issues a short-lived access token (JWT, 15 min) and a rotating refresh token (30 days, stored in the iOS Keychain). Refresh tokens are one-time-use; reuse revokes the whole family (detects token theft).
- Device record created on first login (`device_id`, platform, APNs token) so pushes and session revocation work per device.

**Contact matching (how friends find each other)**

- With permission, the app uploads SHA-256 hashes of the user's address-book phone numbers and emails (normalised to E.164 / lowercase) and the server returns which hashes match existing users. Raw contacts never leave the device, and the hashes are not stored server-side beyond the request.
- A friend relationship is implicit: anyone you have shared an expense with appears in your Friends list. There is no friend-request step; it is friction with no safety benefit when the first interaction is a shared bill.

**Recovery and edge cases**

- Lost phone number: sign in with email, then replace the number (requires OTP on the new number and a 24-hour notice email to the old address).
- Lost both: support-assisted recovery with proof via a prior settlement record; out of scope to automate at launch.
- Guest identity (Section 15) is a separate lightweight table; when a guest later signs up with the same verified phone or email, their guest records are attached to the new account automatically.

**Implementation notes**

- Tables: `users`, `user_identifiers (user_id, kind: phone|email, value_normalised, verified_at, is_primary)`, `devices`, `refresh_tokens`.
- FastAPI dependency `current_user()` validates the JWT and loads the user once per request; all routers depend on it except `/auth/*` and `/guest/*`.
- iOS: phone entry uses `PhoneNumberKit` for formatting and validation; OTP field supports SMS autofill (`textContentType = .oneTimeCode`).

## 7. Core ledger: expense model & split math

Every expense reduces to the same two lists — who paid how much, and who owes how much — and both lists must sum to the expense total. Every split mode, every voice command and every receipt claim is just a different way of producing those two lists.

**Required fields**

| Field | Rule |
| --- | --- |
| Name | Free text, 1–120 chars. Voice and scan prefill it (merchant name). |
| Amount | Positive integer in minor units of the currency (S$84.50 → 8450 SGD). Currencies with 0 or 3 decimals (JPY, KWD) use their own minor-unit exponent from ISO 4217. |
| Currency | Defaults to the currency of the user's current location (CoreLocation → reverse-geocoded country → ISO currency), falling back to the profile default. Editable per expense. Last-used currency per group is remembered. |
| Date | Defaults to today in the user's time zone; editable; stored as a date plus the creation timestamp. |
| Payers | One or more `(user, amount_paid)`; sum must equal Amount. |
| Participants & split | One or more `(user, amount_owed)`; sum must equal Amount. Derived from the chosen split mode. |
| Notes | Optional free text, up to 2,000 chars; attachments (receipt image) optional. |
| Context | Either a group or a direct (non-group) expense between the participants. |

**Two-person shortcuts.** When exactly two people are involved (you and X), the UI shows four one-tap options instead of a split editor. They map to the general model as follows:

| Shortcut | Payers | Owed shares |
| --- | --- | --- |
| You paid, split equally | You: 100% | You 50%, X 50% → X owes you half |
| You are owed the full amount | You: 100% | X 100% → X owes you everything |
| X paid, split equally | X: 100% | You 50%, X 50% → you owe X half |
| X is owed the full amount | X: 100% | You 100% → you owe X everything |

The fourth case is the "X paid for me" case. These shortcuts are purely a UI layer; the stored record is identical to a general split.

**Split modes for three or more people** (also available for two if the user expands the editor):

1. **Equally** among the selected participants.
2. **Exact amounts** — user types each person's amount; the editor shows the running remainder and will not save until it is zero.
3. **Percentages** — each person a percentage; must sum to 100.00 (two decimals allowed).
4. **Shares** — each person an integer weight (1 share, 2 shares); a couple sharing a room gets 2 shares against singles' 1. Amount owed is proportional to weight.
5. **By items** (Section 14) — generated from receipt claims; shown read-only with a "view claims" link.

**Multiple payers.** Any split mode can be combined with more than one payer (two people split the hotel bill at the desk). Payer amounts are entered exactly and must sum to the total.

**Rounding: the largest-remainder rule.** Equal, percentage and share splits produce fractions of a cent. The server allocates with the largest-remainder (Hamilton) method so the parts always sum exactly to the total and no one is ever off by more than one minor unit:

```latex
\text{base}_i = \left\lfloor \frac{A \cdot w_i}{\sum_j w_j} \right\rfloor,\qquad r = A - \sum_i \text{base}_i,\qquad \text{owed}_i = \text{base}_i + [\,i \text{ is among the } r \text{ largest fractional remainders}\,]
```

Ties on the fractional remainder are broken deterministically so the same input always produces the same output on every platform:

1. **The payer first.** If the expense has exactly one payer and that payer is among the tied participants, the payer receives the extra minor unit. The person covering the bill absorbs the rounding, so friends never owe a cent they didn't cause.
2. **Then by participant ID.** Any remaining ties (and every tie when there are several payers, or when the payer is not a participant) go to participants in ascending ID order. IDs are compared as lowercase canonical strings, byte by byte.

Payer priority only breaks exact ties; it never overrides a larger fractional remainder. Because each participant receives at most one extra unit, the payer never absorbs more than one minor unit per expense.

Examples: S$100.00 split equally three ways, paid by Ben → Ben 3334, the others 3333 each; the UI shows it ("Ben pays 1¢ more"). S$2.00 split equally three ways, paid by Ben → base 66 each with 2 cents left over: Ben gets one, and the other goes to whichever of the remaining two has the lower ID.

**Net effect per expense.** For each person, `net_i = paid_i − owed_i`. Positive means the expense made others owe them; negative means they owe. The sum of all `net_i` within an expense is zero by construction, which is the invariant the nightly audit checks across every expense and every group.

**Editing and deleting.** An edit creates a new `expense_revision`; the expense points at its current revision and the old one stays for history and dispute resolution. Delete is a soft-delete (`deleted_at`) and reversible for 30 days. Any participant can edit; the activity feed records who changed what, and every other participant gets a notification.

**Validation lives in one place.** A `SplitEngine` module on the server takes `(total, currency, payers, mode, inputs)` and returns the two lists or a typed error (`SumMismatch`, `NegativeShare`, `EmptyParticipants`). The iOS app ships a Swift port of the same algorithm for instant previews, with a shared JSON fixture suite that both implementations must pass in CI.

## 8. Balances, debt simplification & settlement

A balance is the sum of per-expense net effects between two people in one currency; a settlement is just an expense with one payer, one participant and the type `settlement`, so the same ledger machinery produces "you're square".

**Balance computation**

- Pairwise balance in a context (a group, or the direct relationship) = sum over all live expense revisions of `net` between the pair, per currency. SpendIt never silently converts currencies into one balance; a trip with SGD and THB expenses shows two lines, with an optional "show in SGD" toggle using an indicative rate (clearly labelled).
- Balances are materialised in a `balances` table updated transactionally with every expense write, and rebuilt from scratch by the nightly audit job. If the audit disagrees with the materialised value, it alerts and repairs.
- The home screen shows: total you are owed, total you owe (per currency), then per-friend and per-group lines.

**Debt simplification (group setting, on by default)**

- Within a group, raw pairwise debts can form chains (A owes B 10, B owes C 10). Simplification computes each member's overall net position and produces the minimum set of transfers that settles everyone: sort debtors and creditors, greedily match the largest debtor to the largest creditor, repeat. This is Splitwise's behaviour and users expect it.
- Simplification never changes anyone's net position; it only changes who pays whom. The UI makes this explicit ("You owe Ravi S$10 instead of Aditi because Aditi owes Ravi").
- A group admin can turn it off (some groups prefer to track exactly who paid for whom). Direct (non-group) balances are never simplified across friends.

**Settlement methods at launch (before the Wallet ships)**

1. **Record a payment** — "I paid Aditi S$42.50 in cash". Creates a settlement expense; the counterparty is notified and can dispute within the activity feed.
2. **PayNow / UPI deep link (Singapore and India)** — SpendIt generates a PayNow QR or `upi://pay` intent prefilled with the counterparty's registered proxy (mobile number) and the amount, opens the user's bank app, and on return asks "Did the payment go through?" to record it. No money touches SpendIt, so no licence is needed, and it already beats Splitwise in these markets.
3. **Settle via Wallet** (Phase 2, Section 11) — instant, recorded automatically.

**Partial settlement and allocation.** A user can settle any amount up to the balance. Settlements reduce the net balance, not specific expenses, which keeps the model simple; a per-expense "paid" marker is deliberately out of scope.

**Reminders.** A creditor can nudge once per debt per 72 hours (push and, if no app, SMS or email). Automatic gentle reminders go out 7 days after a trip group's last expense. All reminder copy is written to be socially safe ("SpendIt reminder" framing, never the creditor's words).

## 9. Groups

A group is a named container with a member list, a default currency and a default split, and it is the unit for debt simplification, Bluetooth detection and receipt claim sessions.

**Requirements**

- Create with name, optional cover emoji or photo, type (trip, home, couple, event, other — the type only changes defaults and the suggested icon), default currency, and whether debt simplification is on.
- Add members from Friends, from contacts (hash match), by sharing an invite link, or as a guest placeholder (Section 15). Invite links are revocable and can be set to require admin approval.
- Roles: creator is admin; admins can add or remove members, change settings, archive the group. Any member can add and edit expenses.
- A member can only leave when their balance in the group is zero; otherwise they are prompted to settle first (same rule as Splitwise, and it prevents orphaned debts).
- Per-group default split: equal, or a saved share weighting (the couple with 2 shares). New expenses prefill from it.
- Group feed: chronological list of expenses and settlements, with filters (mine, unsettled, by member) and a per-member "what I paid / what I owe" summary.
- Archive, not delete: archived groups are read-only and hidden from the main list; restorable.

**Group balance view.** Two tabs: *Simplified* (who pays whom, minimum transfers) and *Detailed* (pairwise). A "Settle all" action creates the settlement intents for every transfer the current user is on the paying side of.

**Implementation notes**

- Tables: `groups`, `group_members (group_id, user_id|guest_id, role, joined_at, left_at)`, `group_invites (token, created_by, expires_at, requires_approval)`.
- Membership history is retained so an expense from before someone left still renders their name.
- Expense writes check `group_members` for every payer and participant; a non-member in the payload is rejected with a clear error rather than auto-added, except in the proximity flow where the user explicitly confirms the add.

## 10. Moving expenses between personal and group

Moving an expense changes only its context pointer; the payers and participants stay exactly as they were, so the ledger total never changes — only which balance view the expense counts toward.

**Why this matters.** The common case is a trip: three friends start logging dinners directly against each other on day one, someone creates a "Bali 2027" group on day two, and now half the trip is outside the group's simplified balance. Today Splitwise users delete and re-enter.

**Rules**

- **Personal → group:** allowed when every payer and participant is a member of the target group. If someone is not, the mover is offered "Add Aditi to Bali 2027 and move" in one step (requires admin, or the group's open-add setting).
- **Group → personal:** allowed always; the expense becomes a direct expense among the same people. The group feed shows a "moved out by Pranav" entry.
- **Group → group:** same membership check as personal → group.
- Settlements cannot be moved; they belong to the context where the debt was.
- Bulk move: multi-select in the friend feed, filter by date range, move all eligible expenses; ineligible ones are listed with the reason.
- Every move is an activity-feed event and notifies all participants, since it changes what they see on their group balance.

**Implementation**

- `expenses.context_type (direct|group)` and `expenses.group_id (nullable)`. A move is a new revision with the new context, inside one transaction that also decrements the old context's materialised balances and increments the new one's.
- Because balances are per-context, a move is a pure re-bucketing; the nightly audit's zero-sum check holds per context before and after.
- API: `POST /v1/expenses/{id}/move {target: {type, group_id}}` returning the new revision, or `409` with `missing_members: [...]`.

## 11. SpendIt Wallet

The Wallet is a stored-value balance users top up, settle from and withdraw — which legally makes SpendIt an e-money issuer, so it ships in Phase 2 on a licensed partner's rails rather than at launch. The product experience is designed now so the ledger and UI are ready when the rails are.

**The regulatory reality (why this is not a launch feature)**

- In Singapore, holding customer funds that can be used to pay others and withdrawn is *e-money issuance* and *domestic money transfer* under the Payment Services Act 2019. Doing it directly requires a Standard or Major Payment Institution licence from MAS, safeguarding of the float, AML/CFT programmes and KYC. Personal payment accounts also have balance and annual-flow caps set by MAS (historically S$5,000 and S$30,000; verify the current figures before design freeze). India (RBI PPI rules) and every other market have equivalents.
- Splitwise solved this the same way: Splitwise Pay runs on a sponsor bank (Coastal Community Bank) in the US and on Tink's open-banking rails in Europe. SpendIt should do likewise: a licensed e-money or Banking-as-a-Service partner holds the funds and performs KYC; SpendIt owns the UX and the sub-ledger.
- Decision required from the founders (Section 20): partner-first (fast, revenue share) versus own licence (18–24 months, capital requirements). This PRD assumes partner-first.

**User experience**

1. **Enable Wallet** — one-time KYC flow (name, date of birth, ID document, selfie) handled by the partner's SDK; SpendIt receives only a pass/fail and a KYC reference.
2. **Top up** — via PayNow QR (Singapore), Apple Pay, or card. Funds are credited after the partner confirms receipt (PayNow is near-instant; cards may be held until cleared).
3. **Settle** — on any debt, "Pay from Wallet" moves funds to the creditor's Wallet instantly and records the settlement expense atomically. If the creditor has not enabled Wallet, the funds are held in a pending credit for 14 days with an invite; unclaimed funds return to the payer.
4. **Withdraw** — to the user's linked bank account via FAST/PayNow; free for standard (same day), with a small fee for instant later as a revenue line.
5. **Auto-settle (opt-in)** — "Automatically pay debts under S$20 from my Wallet after 48 hours." This is the feature that makes money truly disappear from the moment; it is gated behind a clear consent screen and a per-group toggle.

**Ledger design**

- The Wallet keeps its own double-entry sub-ledger (`wallet_accounts`, `wallet_entries` with debit and credit legs) separate from the expense ledger. A settlement produces one expense-ledger record and two wallet entries, in one database transaction, with the partner transfer reference attached.
- Every wallet balance is reconciled daily against the partner's statement; any discrepancy freezes affected accounts for review.
- Idempotency is mandatory on every money movement; the partner transfer ID is stored before the local credit is posted, so a crash between the two cannot double-credit.

**Limits and controls.** Per-transaction and daily limits set below the regulatory caps; velocity checks; Face ID or passcode confirmation for any outbound movement over a user-set threshold; instant freeze from the app if a phone is lost.

**Revenue model (later).** FX spread on cross-currency settlements, instant-withdrawal fee, and interest on float where the partner shares it. Core settlement in the home currency stays free so Wallet adoption is not throttled.

**Pre-wallet bridge.** Until Phase 2, the PayNow / UPI deep-link settlement (Section 8) delivers most of the "no app switching" value without SpendIt touching funds.

## 12. Bluetooth proximity participant detection

When a user opens "Add expense", their phone briefly advertises a rotating anonymous token over Bluetooth LE and listens for others'; SpendIt resolves nearby tokens to SpendIt users and pre-selects them, ranked by signal strength and past behaviour. The user always confirms, and every correction trains the ranking.

**How it works on iOS (and the constraints that shape it)**

- **Transport:** CoreBluetooth. Each device acts as both peripheral (advertising a SpendIt service UUID plus a 16-byte ephemeral token) and central (scanning for that UUID). No pairing, no connection; everything needed is in the advertisement packet.
- **Ephemeral tokens:** the token rotates every 15 minutes and is derived on-device from a server-issued daily key, so an observer cannot track a person across the day. The server maps `token → user` only for the resolving request and only for users who have proximity enabled.
- **Foreground only, by design.** iOS restricts background BLE advertising (the service UUID moves into an overflow area and is only visible to other iOS apps scanning specifically for it) and throttles background scans. Rather than fight this, detection runs in two foreground moments: the 10 seconds after opening Add expense, and an explicit "I'm at a gathering" session a user can start for up to 4 hours (which uses the background-scan exception for a declared service UUID and the `bluetooth-central` and `bluetooth-peripheral` background modes). The gathering session is also what makes the receipt claim flow (Section 14) seamless.
- **Both phones need SpendIt open or in a session** for mutual detection. The product copes: if only Pranav's phone detects Aditi (her app in the background, advertising in overflow mode), that is still enough to suggest her to Pranav.
- **Distance:** RSSI is noisy, so the app uses a smoothed RSSI over the scan window with a threshold tuned to roughly a dinner table (about −7 to −75 dBm on iPhone, calibrated in testing). People beyond it appear in a collapsed "also nearby" list rather than pre-selected.
- Android (later) supports the same via BLE advertising; web clients do not participate.

**Resolution and ranking**

1. The client sends the set of observed `(token, smoothed_rssi, first_seen, last_seen)` to `POST /v1/proximity/resolve` together with the current context (group ID if any).
2. The server resolves tokens to users, drops anyone not in the user's Friends or the group (strangers in the same restaurant are never shown), and scores each candidate.
3. Score = weighted sum of: signal strength bucket, whether they are in the current group, how often this user has included them in expenses in the last 90 days, how often this user previously *removed* them after auto-selection, and co-occurrence with other detected people. Weights start hand-tuned and move to a small logistic model once there is feedback data.
4. Candidates above the threshold are pre-selected; the user adds or removes freely; the final participant list versus the suggested list is logged as the training signal (`proximity_feedback`).

**The learning loop ("the AI learns patterns over time")**

- Per user, per candidate: an acceptance rate that decays over time. Someone you always remove (a flatmate who is nearby but not at dinner) sinks below the threshold within a few corrections; someone you always add even on weak signal rises.
- Per group: typical participant set and typical time of day, so a Tuesday-night "Flat" group expense pre-selects flatmates even with no Bluetooth contact.
- All of this is a ranking model, not a generative one; it runs server-side in milliseconds and is fully explainable ("suggested because: nearby, in this group").

**Privacy and consent**

- Opt-in with a plain-language screen; Bluetooth permission requested only at that moment. Off by default for new accounts.
- Tokens, RSSI and resolutions are retained for 24 hours for debugging, then deleted. Only the aggregate acceptance rates persist.
- A user can hide from detection while still detecting others ("ghost mode"), and can see which people their phone detected in any given expense.
- App Store review note: the `NSBluetoothAlwaysUsageDescription` string must describe this exact purpose; background modes must be justified in the review notes.

**Fallbacks.** No Bluetooth or no detections: the participant picker opens pre-filled from the group's usual set (the per-group model above), so the feature degrades gracefully to a smart default rather than to nothing.

**Passive co-presence for outing nudges.** Beyond the two foreground moments above, proximity-enabled phones also listen passively in the background, at the throttled rate iOS allows. These sightings are used only to notice that friends spent time together, which powers the "Add to SpendIt" nudge in Section 15A. They are never used to pre-select anyone without the user opening the app, and they follow the same 24-hour retention.

## 13. Voice AI expense entry

The user holds the mic button and speaks naturally; on-device speech recognition produces text, a language model turns the text into a structured draft expense, and the user sees the normal expense card prefilled and taps Confirm. Nothing is saved without confirmation.

**Pipeline**

1. **Capture** — `SFSpeechRecognizer` with on-device recognition requested (`requiresOnDeviceRecognition = true` where the locale supports it; English, Mandarin, Hindi and Tamil cover the launch market). Live transcript shown while speaking so the user can see mishearing immediately. Audio is not uploaded in the default path.
2. **Parse** — the transcript, plus a compact context bundle, goes to `POST /v1/voice/parse`. The server calls an LLM with a strict JSON schema (structured output) and returns a `DraftExpense`. The context bundle is what makes this accurate: the user's display name, the current group's members (names and IDs), the user's top 30 friends by recent activity, the default currency, today's date and the user's locale.
3. **Resolve** — names in the draft are matched to real people. Exact and nickname matches resolve silently; ambiguous ones ("Adi" matching Aditi and Aditya) become a chip the user taps to pick; unknown names become "add as guest?" chips.
4. **Confirm** — the standard expense card appears, prefilled, with the parsed fields highlighted and a one-line paraphrase ("S$84 Dinner, you paid, split equally with Aditi and Ravi"). The user edits anything, then confirms. The server validates through the same `SplitEngine` as manual entry.

**Draft schema (what the model must return)**

```markdown
DraftExpense {
  name: string
  amount_minor: int | null
  currency: ISO-4217 | null
  date: ISO date | null            // "yesterday", "last Friday" resolved server-side
  payers: [{ ref: "me" | name, amount_minor: int | null }]
  split: { mode: equal | exact | percent | shares | full_to_one,
           entries: [{ ref: "me" | name, value: number | null }] }
  group_hint: string | null         // "in the Bali group"
  notes: string | null
  confidence: 0..1
  clarification_needed: string | null
}
```

**Utterances the parser must handle (acceptance tests)**

| Said | Expected draft |
| --- | --- |
| "Dinner 84 dollars, I paid, split with Aditi and Ravi" | 8400 SGD, payer me, equal across me, Aditi, Ravi |
| "Aditi paid 120 for groceries, split between us" | 12000, payer Aditi, equal me and Aditi |
| "Ravi owes me 30 for the taxi" | 3000, payer me, full\_to\_one Ravi |
| "Hotel 600, I paid, Aditi and I two shares, Ravi one share" | shares me 2, Aditi 2 → interpreted as couple 2 shares total unless clarified; `clarification_needed` set |
| "Split 90 three ways in the Bali group, Ravi paid 50 and I paid 40" | two payers, equal split, group\_hint Bali |
| "Lunch" | amount null → card opens with amount field focused, no error |

**Design rules**

- Never guess money. If the amount or who paid is missing or below a confidence threshold, the card opens with that field empty and focused; the model's `clarification_needed` text is shown as a hint.
- Currency words ("rupees", "baht") override the default; bare numbers use the current default currency.
- A follow-up utterance within 30 seconds edits the same draft ("actually Ravi didn't come") rather than starting a new one.
- Latency budget: end of speech to prefilled card under 2 seconds at p90. On-device transcription is near-instant; the LLM call is the budget, so use a fast model tier and keep the prompt small.
- Privacy: transcripts are stored with the expense only if the user keeps the default "save voice note as text" setting; otherwise discarded after parsing. Audio never leaves the device unless on-device recognition is unavailable for the locale, and then the user is told.

**Voice actions beyond creating an expense.** The same parser handles non-sensitive in-app actions, so a user can say "move last night's dinner to the Bali group" or "remind Ravi about the taxi" without navigating. The model returns an `intent` field alongside the draft; each intent maps to an existing API call and runs through the same preview-then-confirm card, and anything that moves real money is excluded.

| Intent | Example utterance | Backing API | Confirmation |
| --- | --- | --- | --- |
| `create_expense` | "Dinner 84, I paid, split with Aditi" | `POST /expenses` | Prefilled card, tap Confirm |
| `move_expense` | "Move the taxi from yesterday into the Bali group" | `POST /expenses/{id}/move` | Card shows the matched expense and target; tap Confirm |
| `edit_expense` | "Change dinner to 90", "add Ravi to the hotel" | `PUT /expenses/{id}` (new revision) | Card shows before and after |
| `delete_expense` | "Delete the coffee I just added" | `DELETE /expenses/{id}` | Confirm; 30-day restore applies |
| `record_settlement` | "Aditi paid me back 40 in cash" | `POST /settlements` | Confirm; counterparty notified as usual |
| `remind` | "Remind Ravi about the taxi" | `POST /balances/{pair}/remind` | One-tap confirm, 72-hour cooldown applies |
| `create_group` / `add_member` | "Start a group called Bali with Aditi and Ravi" | `POST /groups`, `POST /groups/{id}/members` | Confirm |
| `query` | "How much does Ravi owe me?", "What did we spend in Bali?" | `GET /balances`, `GET /expenses` | None; spoken and shown answer, no write |
| `navigate` | "Open the Bali group" | client-side | None |

**Rules for voice actions**

- **Expense resolution.** Phrases like "last night's dinner" or "the taxi" resolve against the user's recent expenses (last 30 days, in the current context first) by name, date and amount. One strong match proceeds to the card; several matches become a pick list; none falls back to search.
- **Same permissions as touch.** Voice can only do what the user could do by tapping: moving into a group still requires every participant to be a member (or triggers the "add and move" offer), editing requires being a participant, and so on. The intent layer adds no new authority.
- **Excluded from voice.** Wallet top-ups, Wallet settlements, withdrawals, changing linked bank accounts, deleting the account, or changing login identifiers. These require the normal screen with Face ID where applicable. A voice request for one of them gets a spoken "open Wallet to do that" and a deep link, never an execution.
- **One confirm per action.** Multi-step utterances ("create the Bali group, add Aditi and Ravi, and move yesterday's dinner into it") are decomposed into an ordered list of actions shown on one card; the user confirms the whole list or removes steps. The actions execute sequentially and stop at the first failure.
- **Undo.** Every voice-executed write shows a 10-second undo toast, backed by the revision history (edits and moves revert to the previous revision; deletes restore).

**Evaluation additions.** The fixture set gains intent-classification cases (target 97% intent accuracy; misclassifying a `query` as a write is the error class to drive to zero) and expense-resolution cases against synthetic ledgers.

**Evaluation.** A fixture set of at least 300 transcripts across accents and phrasings, run nightly against the parser; field-level accuracy target 95% on amount and payer, 90% on participant set. Every user correction to a voice draft is logged (with consent) as a new fixture candidate.

**Backend implementation.** A `voice` router, a `VoiceParser` service that builds the prompt from the context bundle, calls the model with the schema, and post-processes dates and currencies deterministically in Python rather than trusting the model. Name resolution is a separate pure function reused by the receipt flow.

## 14. Receipt scan & item-level claiming

A scanned receipt becomes a live claim session: every participant ticks their own items on their own phone, shared items are split among those who tick them, and tax, service charge and discounts are allocated in proportion to each person's item subtotal. The payer only presses "Close bill".

**Flow**

1. **Capture** — `VisionKit` document camera (auto edge detection, perspective correction, multi-page) or import from Photos / Files. Image uploaded to object storage via a signed URL; a job is queued.
2. **Itemise** — server job runs OCR (`VNRecognizeTextRequest` output from the device is sent along as a hint; the server runs an LLM vision model on the image for structure). Output: merchant, date, currency, line items `(description, qty, unit_price, line_total)`, and adjustment lines classified as `tax`, `service_charge`, `discount`, `tip`, `rounding`, plus the printed total. The job verifies `sum(items) + sum(adjustments) == total`; if it does not reconcile, the UI flags the gap and lets the payer fix a line before anyone claims.
3. **Participants** — proximity suggestions (Section 12) or manual selection, plus "add a guest" (Section 15). Each participant gets a push: "Pranav scanned the bill at Din Tai Fung — tap what you had."
4. **Claim** — every participant sees the same item list and multi-selects. An item can be claimed by several people (shared starters) and is split equally among its claimers; quantity lines (4 × beer) can be claimed per unit ("I had 2"). Live presence shows who has finished. Unclaimed items are highlighted for the payer, who can assign them, mark them "everyone", or absorb them.
5. **Allocate adjustments** — for each person, `adj_share_i = adjustment × (items_i / sum(items))`, using the largest-remainder method so cents reconcile. Discounts and tips follow the same proportion; a fixed per-head charge (some venues' cover charge) can be toggled to equal split by the payer.
6. **Close** — the payer closes the session (or it auto-closes 24 hours after the last claim with unclaimed items assigned to the payer and flagged). The result is a normal expense with split mode `by_items`, payer(s) as entered, and each participant's owed amount. The claim breakdown is stored and viewable from the expense forever.

**Edge cases handled**

- Sharing is the default, never an error: any number of people can tap the same item and its cost is split equally among them with no prompt. On a quantity line (4 beers), a plain tap means "I shared this line"; a claimer may optionally state exact units ("I had 2"). Stated units are honoured, and whatever is left is split equally among the claimers who did not state a number. If stated units alone exceed the printed quantity, nobody is blocked: the line falls back to a split proportional to the units each person stated, with a small note so people can correct it if they want.

  Example: the receipt shows "Truffle fries, S$14" and "Tiger Beer × 4, S$48". Aditi and Pranav both tap the fries: S$7 each, done. On the beers, Aditi states "2", Ravi states "1", and Pranav just taps the line: Aditi S$24, Ravi S$12, Pranav gets the remaining unit, S$12. If instead Aditi, Ravi and Pranav each state "2" (6 against 4), the S$48 is split in proportion 2:2:2, S$16 each, and the line shows "6 of 4 units claimed, split proportionally" so anyone can adjust before the payer closes the bill.
- Receipt in a currency different from the group default: currency is taken from the receipt, with a confirmation chip.
- Multiple receipts for one meal (drinks bill at the bar): sessions can be chained into one expense or kept separate.
- Someone claims nothing: they are removed from the split unless the payer keeps them on "shared only" items.
- Illegible receipt: falls back to manual entry of items; the photo is still attached.

**Realtime.** Claim sessions are the one place SpendIt needs live updates. A WebSocket endpoint (`/v1/claims/{session_id}/ws`, FastAPI native) broadcasts claim changes; clients also poll every 5 seconds as a fallback. Each claim is a small idempotent write (`PUT /claims/{session}/items/{item}/me {units}`) so conflicts are trivially last-write-wins per person.

**Data.** `receipts (id, expense_id?, image_url, merchant, parsed_json, status)`, `receipt_items (receipt_id, line_no, description, qty, unit_minor, total_minor, kind)`, `claim_sessions (receipt_id, group_id?, opened_by, closes_at, status)`, `claims (session_id, item_id, claimant_user_id|guest_id, units)`.

**Quality targets.** Line-item extraction accuracy of 95% on a benchmark of 500 Singapore and India receipts (thermal, faded, multi-language); reconcile rate above 90% without manual fixes; p90 scan-to-claimable under 6 seconds. OCR cost per receipt is tracked as a unit-economics metric from day one.

## 15. Splitting with non-users via guest links

A guest is a lightweight identity — a display name plus a verified phone or email — created from a link, able to claim items and view what they owe on a mobile web page, and automatically merged into a full account if they ever sign up with the same identifier.

**Flow for the guest**

1. Receives a link (`spendit.app/c/8f3kQ2`) via iMessage, WhatsApp or email from the payer. The link is tied to one claim session or one expense.
2. Opens a mobile-first web page (FastAPI-rendered, no app required). Enters what they would like to be called and a phone number or email, receives an OTP, enters it. OTP verification is required so a guest cannot be impersonated and so the record can be merged later.
3. Sees the item list (if the expense came from a receipt) and multi-selects their items — "2 oranges, 4 apples" — with the same shared-item and quantity rules as app users. Tax and fees are allocated proportionally exactly as in Section 14. If the expense has no items, they simply see their share as set by the payer and acknowledge it.
4. Sees a receipt page: what they claimed, their adjustment share, the total they owe, and how to pay (PayNow QR or UPI intent for the payer's registered proxy; later, a card or Apple Pay button funding the payer's Wallet). They can mark "I've paid" which notifies the payer to confirm.
5. Gets a magic link by SMS or email to return to their page any time; a "Get the app" prompt is shown once, after they are done, never before.

**Flow for the payer**

- On the participants step, "Add someone without SpendIt" creates a guest placeholder with a name (and optionally a phone or email, which pre-addresses the link). The share sheet opens with the link.
- The payer sees guest status live: *invited*, *verified*, *claimed*, *paid (unconfirmed)*, *settled*.
- Guests appear in balances like anyone else, under a "guests" badge. Debts with guests can be settled by recording a payment, and are included in group totals but excluded from debt simplification (a guest cannot be asked to pay a third party they never met).

**Security and abuse**

- Link tokens are 128-bit random, single-session, expire 14 days after creation, and are revocable by the payer. Opening a link reveals nothing until the OTP step except the payer's first name and the merchant.
- Rate limits on OTP per link and per identifier; a guest cannot change their claim after the session closes.
- A guest's phone or email is visible only to the payer who added them, not to other participants.

**Merging into a real account.** On sign-up, if the verified identifier matches `guest_identities`, all guest participations, balances and claims are re-pointed to the new `user_id` in one transaction, and the guest row is marked merged. Friends who had a balance with the guest now see the full user. This is also how guest conversion (a launch metric) is measured.

**Data.** `guest_identities (id, display_name, identifier_kind, identifier_normalised, verified_at, merged_user_id?)`, `guest_links (token, expense_id|claim_session_id, created_by, expires_at, revoked_at)`. Expense participant rows carry either `user_id` or `guest_id`, never both, enforced by a check constraint.

## 15A. "Add to SpendIt" nudge after a shared outing

When SpendIt sees that you spent time near the same friends and then everyone left, it sends one notification, such as "Looks like you were out with Aditi and Ravi. Did someone pay? Add to SpendIt." One tap opens receipt scan or voice entry with those people already selected. It needs no setup at all: it uses the nearby detection (Section 12) and, optionally, location the user already allowed.

**Why this approach.** iOS gives other apps no feed of Apple Pay payments. Apple's FinanceKit API covers only US Apple Card, Apple Cash and Savings plus UK connected accounts, behind a managed entitlement ([FinanceKit requirements](https://developer.apple.com/financekit)), so it captures almost nothing in Singapore. The other route, a Shortcuts Wallet automation, works but needs every user to build the automation by hand, which conflicts with the zero-friction goal. Detecting the *moment* of a shared expense instead of the *payment* needs no setup, and the moment is most of the value: once the app opens at the right time, scan or voice fills in the amount in seconds.

**How a nudge is triggered**

1. **Co-presence.** With proximity enabled, the phone listens passively in the background for other SpendIt users' rotating tokens (Section 12). iOS throttles background Bluetooth scanning, which is fine here: SpendIt only needs to know that the same friends stayed nearby for a while, not to the second.
2. **An outing.** The server sees an outing when two or more SpendIt friends were co-present for at least 30 minutes (tunable). If the user has granted location, Apple's low-power visit detection (`CLVisit`) adds the place and the arrival and departure times, and a map lookup can suggest a name ("Din Tai Fung?"), clearly marked as a guess.
3. **The end.** The outing ends when co-presence drops off, or the visit's departure fires. The nudge goes out within about 10 minutes of that.
4. **The notification.** "Out with Aditi and Ravi at Din Tai Fung? Did someone pay?" with actions:
   - **Scan the receipt**: opens the camera, with the outing's people as participants (Section 14).
   - **Say it**: opens voice entry with the same people in context (Section 13).
   - **Nothing to split**: dismisses and teaches the model.
5. **Only one expense per outing.** Everyone in the outing may get the nudge. As soon as one person adds an expense that includes the others, the others' notification is replaced with "Pranav added the bill. Tap to claim your items." Nobody adds the same dinner twice.

**Keeping it quiet**

- **Learns what isn't shared.** Outings at the same place with the same people that the user keeps dismissing (flatmates at home, colleagues at the office during work hours) stop producing nudges after 3 dismissals. Users can also mark a place or group "never nudge".
- **Skips outings that already have an expense.** No nudge if anyone in the outing already logged an expense with these people during or just after it.
- **Caps.** At most 2 nudges a day per user, none during quiet hours (they go to an in-app list instead), and none for outings shorter than the threshold.
- **One switch.** "Outing reminders" is on by default once proximity is on, with a single toggle in settings to turn it off.

**Privacy**

- Co-presence is matched only between people who are already friends or share a group. Strangers in the same place are never seen.
- Raw tokens and visit data are discarded within 24 hours. Only the learned "don't nudge here" preferences persist.
- Location is optional. Without it, nudges still work from co-presence alone, without a place name.

**Implementation**

- iOS: background Bluetooth modes (`bluetooth-central`, `bluetooth-peripheral`) for passive co-presence, `CLLocationManager.startMonitoringVisits()` when location is allowed, `MKLocalSearch` for the place-name guess, `UserNotifications` with an `OUTING_NUDGE` category and three actions, deep links `spendit://outing/{id}/scan` and `/voice`.
- Backend: an `outings` table (participants, start, end, optional place, status), a job that closes outings and decides whether to nudge, and a rule that withdraws the others' nudges once an expense covers the outing. New endpoints: `POST /v1/proximity/observations` (batched sightings from the phone) and `GET /v1/outings/{id}`. Confirmed expenses carry `source: "outing_nudge"`.
- Metrics: nudge-to-expense conversion, dismissal rate, share of group expenses that started from a nudge, median time from outing end to saved expense.
- Phase: Phase 2, after proximity detection is stable.
- Later: when a SpendIt card exists (Section 11), its own transaction feed can make the nudge exact, with the amount and merchant from the real payment.

## 16. Data model

The schema centres on an append-only `expense_revisions` table; everything else either feeds into it (receipts, voice drafts, claims) or is derived from it (balances).

| Table | Key columns | Notes |
| --- | --- | --- |
| `users` | id, display\_name, avatar\_url, default\_currency, home\_country, created\_at | No credentials here |
| `user_identifiers` | user\_id, kind (phone/email), value\_normalised (unique), verified\_at, is\_primary | One row per identifier; max one of each kind per user |
| `devices` | user\_id, platform, apns\_token, last\_seen\_at | Push targets and session management |
| `refresh_tokens` | id, user\_id, device\_id, family\_id, expires\_at, used\_at | Rotation with family revocation |
| `guest_identities` | id, display\_name, identifier\_kind, identifier\_normalised, verified\_at, merged\_user\_id | Section 15 |
| `groups` | id, name, type, default\_currency, simplify\_debts, archived\_at, created\_by |  |
| `group_members` | group\_id, user\_id or guest\_id, role, joined\_at, left\_at | History retained |
| `expenses` | id, context\_type (direct/group), group\_id, current\_revision\_id, kind (expense/settlement), created\_by, deleted\_at | Pointer to the live revision |
| `expense_revisions` | id, expense\_id, rev\_no, name, amount\_minor, currency, expense\_date, split\_mode, notes, receipt\_id, created\_by, created\_at, reason (create/edit/move) | Immutable |
| `expense_payers` | revision\_id, user\_id or guest\_id, amount\_minor | Sum = amount |
| `expense_shares` | revision\_id, user\_id or guest\_id, owed\_minor, input\_value (for exact/percent/shares) | Sum = amount |
| `balances` | context\_type, group\_id, party\_a, party\_b, currency, amount\_minor | Materialised; a < b ordering; rebuilt nightly |
| `receipts`, `receipt_items` | see Section 14 | Parsed JSON kept for re-processing |
| `claim_sessions`, `claims` | see Section 14 | Realtime claim state |
| `voice_drafts` | user\_id, transcript, draft\_json, outcome (confirmed/edited/discarded), created\_at | Training and evaluation data, consent-gated |
| `proximity_feedback` | user\_id, candidate\_id, suggested, accepted, rssi\_bucket, group\_id, created\_at | Aggregated into per-pair acceptance rates |
| `wallet_accounts`, `wallet_entries`, `wallet_transfers` | double-entry legs with partner references | Phase 2, Section 11 |
| `activity_events` | actor, verb, object\_type, object\_id, context, payload, created\_at | Drives feeds and notifications |
| `idempotency_keys` | key, user\_id, request\_hash, response\_json, expires\_at | 24-hour replay |
| `feature_flags` | key, rollout\_pct, allowlist | Read on launch |

**Invariants enforced in the database or the service layer**

- For every revision: `sum(expense_payers.amount_minor) = sum(expense_shares.owed_minor) = amount_minor`. Checked in the service layer on write and by the nightly audit as a SQL assertion.
- A participant row references exactly one of `user_id` / `guest_id` (check constraint).
- `balances` for any context sum to zero across all pairs and currencies.
- Money columns are `bigint`; currency is `char(3)`; no `numeric` or `float` money columns anywhere.
- Soft-deleted expenses are excluded from balances by a partial index on `deleted_at IS NULL`.

**Indexing priorities.** `(group_id, expense_date desc)` for feeds; `(party_a, party_b, currency)` on balances; `(user_id, created_at)` on activity; GIN on `receipt_items.description` for later search.

## 17. API surface (FastAPI)

One REST API under `/v1`, JSON everywhere, JWT bearer auth, `Idempotency-Key` required on every POST/PUT that moves or records money. FastAPI's generated OpenAPI spec is the contract from which the Swift client is generated.

| Area | Endpoints | Notes |
| --- | --- | --- |
| Auth | `POST /auth/otp/send`, `POST /auth/otp/verify`, `POST /auth/apple`, `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/identifiers`, `DELETE /auth/identifiers/{id}` | Rate-limited by identifier and IP |
| Users | `GET/PATCH /me`, `POST /me/contacts/match`, `GET /friends` | Contact match takes hashes only |
| Groups | `POST /groups`, `GET /groups`, `GET/PATCH /groups/{id}`, `POST /groups/{id}/members`, `DELETE /groups/{id}/members/{pid}`, `POST /groups/{id}/invites`, `POST /invites/{token}/accept`, `POST /groups/{id}/archive` | Leave blocked while balance non-zero (409) |
| Expenses | `POST /expenses`, `GET /expenses?context=...&cursor=...`, `GET /expenses/{id}`, `PUT /expenses/{id}` (new revision), `DELETE /expenses/{id}`, `POST /expenses/{id}/restore`, `POST /expenses/{id}/move`, `GET /expenses/{id}/revisions` | Body carries payers, split mode and inputs; server returns computed shares |
| Split preview | `POST /split/preview` | Pure function, no persistence; used by clients for live editors |
| Balances | `GET /balances`, `GET /balances/friends/{id}`, `GET /groups/{id}/balances?simplified=true` | Per currency |
| Settlements | `POST /settlements` (record), `POST /settlements/paynow-intent`, `POST /settlements/{id}/confirm`, `POST /settlements/{id}/dispute` | Wallet variant added in Phase 2 |
| Reminders | `POST /balances/{pair}/remind` | 72-hour cooldown |
| Receipts & claims | `POST /receipts/upload-url`, `POST /receipts`, `GET /receipts/{id}`, `PATCH /receipts/{id}/items/{n}`, `POST /claims` (open session), `GET /claims/{sid}`, `PUT /claims/{sid}/items/{item}/me`, `POST /claims/{sid}/close`, `WS /claims/{sid}/ws` | Session scoped to participants and verified guests |
| Voice | `POST /voice/parse`, `POST /voice/drafts/{id}/outcome` | Returns `DraftExpense` with resolved people |
| Proximity | `GET /proximity/key` (daily token key), `POST /proximity/resolve`, `POST /proximity/feedback`, `POST /proximity/sessions` (gathering mode) | Resolves only to friends or group members |
| Guests | `POST /guests/links`, `DELETE /guests/links/{token}`, `GET /g/{token}` (web page), `POST /guest/otp/send`, `POST /guest/otp/verify`, `PUT /guest/claims/...`, `GET /guest/me` | Separate `guest_session` cookie, never a user JWT |
| Wallet (Phase 2) | `POST /wallet/enable`, `GET /wallet`, `POST /wallet/topups`, `POST /wallet/settle`, `POST /wallet/withdrawals`, `GET /wallet/entries`, `POST /wallet/freeze` | Partner webhooks under `/webhooks/{partner}` with signature verification |
| Activity & push | `GET /activity?cursor=...`, `POST /devices`, `PATCH /me/notification-prefs` |  |
| Admin / audit | `POST /internal/audit/run`, `GET /internal/flags` | Internal network only |

**Conventions**

- Cursor pagination (`cursor`, `limit`) on every list; cursors are opaque base64 of `(created_at, id)`.
- Errors follow RFC 9457 problem details: `{type, title, status, detail, errors[]}`; split validation errors list the offending participant and the remainder.
- All timestamps UTC ISO-8601; `expense_date` is a plain date.
- Webhooks and background jobs are idempotent on the partner's event ID.
- Request and response models are Pydantic v2 with `model_config = ConfigDict(extra="forbid")` so unknown fields fail loudly during development.

**Project layout (backend).** `app/api/v1/<router>.py` thin routers → `app/services/<domain>.py` business logic (including `split_engine.py`, `balances.py`, `voice_parser.py`, `receipt_parser.py`, `proximity.py`) → `app/repositories/` SQLAlchemy queries → `app/models/` ORM. Services are pure enough to unit-test without HTTP; the split engine has property-based tests (Hypothesis) asserting the sum invariant for random inputs.

## 18. Non-functional requirements

SpendIt handles other people's money and their physical proximity, so correctness, privacy and offline resilience are launch requirements, not hardening work for later.

**Security**

- TLS 1.3 only; certificate pinning in the iOS app for the API host.
- JWT access tokens 15 minutes, refresh rotation with reuse detection; all tokens revocable per device.
- Secrets in a managed vault, never in the repo; separate keys per environment.
- Face ID / passcode gate (optional) for opening the app, mandatory for Wallet outbound movements above a threshold.
- Webhook signature verification and replay protection for every partner.
- Annual penetration test before the Wallet launch; dependency scanning in CI.

**Privacy (PDPA in Singapore, DPDP in India, GDPR-ready)**

- Data minimisation: contact hashes not raw contacts; proximity tokens rotate and expire; voice audio stays on-device by default; receipt images deletable by the uploader.
- Export and delete-account flows in-app, completing within 30 days, with ledger rows anonymised rather than removed where a counterparty still has a balance (the money fact survives, the identity does not).
- Clear per-feature consent screens for Bluetooth, microphone, camera, contacts and notifications, each requested at the moment of first use.
- Data residency: primary region Singapore (ap-southeast-1); an India region when Indian users exceed a set threshold or regulation requires it.

**Offline and sync**

- Reads work offline from the SwiftData cache; the balance screen shows a "last updated" stamp.
- Expense creation, edits and settlement records queue offline with their idempotency keys and flush in order; conflicts (someone else edited the same expense) surface as a merge prompt showing both revisions.
- Receipt scans capture offline and upload later; claim sessions and voice parsing require connectivity and say so.

**Performance**

- p95 API latency under 300 ms for reads and 500 ms for expense writes; split preview under 50 ms.
- App cold start to home screen under 1.5 s on an iPhone 12.
- Claim-session WebSocket fan-out under 500 ms to all participants.

**Reliability and correctness**

- Nightly ledger audit: recompute every balance from revisions and compare with the materialised table; any mismatch pages on-call and auto-repairs after logging.
- Database point-in-time recovery; daily backups tested monthly by restore.
- 99.9% API availability target; graceful degradation when AI services are down (manual entry always works).

**Notifications**

- Push for: added to an expense, expense edited or moved, claim session opened, reminder received, settlement recorded or confirmed, guest claimed or paid. Per-category toggles.
- SMS and email only for OTPs, guest links, and reminders to people without the app.
- Quiet hours respected by default (22:00–08:00 local).

**Accessibility and localisation**

- Full VoiceOver labelling, Dynamic Type, minimum 44 pt touch targets; voice entry is itself an accessibility feature and is tested with VoiceOver on.
- English at launch; string tables prepared for Simplified Chinese, Hindi and Tamil; currency and number formatting through `Foundation` locale APIs, never hand-rolled.

**Analytics.** Privacy-respecting product analytics (no third-party ad SDKs) with events for every funnel step in Section 3's metrics, and an explicit per-feature "time to saved expense" measurement.

## 19. Release plan & phasing

Four phases: a trustworthy ledger first, then the AI entry features that differentiate, then the Wallet once a licensed partner is signed, then web and Android. Each phase has an exit gate; nothing in a later phase starts shipping to users until the gate before it is met.

&#91;embedded content: roadmap: 5 phases, 4 gates\]

Bands are in order, not to scale; the diamonds are the exit gates, and the highlighted band is the public iOS launch.

**Phase 0 — Foundations (about 6 weeks).** Backend skeleton, auth with phone and email OTP, Sign in with Apple, split engine with the shared fixture suite, Postgres schema and migrations, CI with property tests, TestFlight pipeline, design system in SwiftUI. *Gate:* split engine passes 100% of fixtures on both platforms; auth end-to-end on TestFlight.

**Phase 1 — iOS launch, core ledger (about 10 weeks).** Expenses with all split modes and two-person shortcuts, groups, balances with simplification, record settlement, PayNow and UPI deep-link settlement, guest links with OTP and simple (non-itemised) shares, activity feed and push, offline queue, move expenses between contexts, account export and delete. Soft launch to a closed Singapore cohort, then App Store. *Gate:* nightly audit clean for 14 consecutive days; crash-free sessions above 99.5%; median manual entry under 12 s in the cohort.

**Phase 2 — Effortless entry (about 10 weeks, overlapping Phase 1 beta).** Receipt scan and itemisation, collaborative claim sessions with realtime, itemised guest claiming, voice entry with the evaluation harness, Bluetooth proximity behind a feature flag to 10% then 100%, and the zero-setup "Add to SpendIt" outing nudge (Section 15A). *Gate:* receipt reconcile rate above 90%; voice amount/payer accuracy above 95%; proximity suggestion acceptance above 70% without degrading entry time.

**Phase 3 — Wallet (timing depends on partner; target 4–6 months after Phase 1).** Partner integration, KYC, top-up, settle, withdraw, auto-settle opt-in, reconciliation, freeze, penetration test, MAS-compliant disclosures. Singapore only at first. *Gate:* 30 days of reconciliation with zero unexplained variance in a closed beta; legal sign-off.

**Phase 4 — Web and Android (after Phase 2 is stable).** Web app on the same API with full parity minus Bluetooth and voice capture; Android with proximity and voice; India as the second market with UPI-first settlement and an India data region if required.

**Team shape for Phases 0–2.** Two iOS engineers, two backend engineers, one ML/AI engineer (receipt and voice pipelines), one designer, one product lead; a part-time compliance advisor from Phase 2 onward to prepare the Wallet.

**Staffing and sequencing assumptions.** Estimates assume this team from the start of Phase 0; if the team is smaller, phases stretch but the order and gates stay fixed. Durations are planning estimates, not commitments, and should be re-baselined at the end of Phase 0.

## 20. Risks, dependencies & open questions

The two risks that can sink the plan are regulatory (the Wallet) and platform (Apple's Bluetooth and background rules); both are mitigated by sequencing them behind a product that already wins without them.

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| No suitable licensed Wallet partner in Singapore on acceptable terms | Medium | High | PayNow/UPI deep-link settlement ships in Phase 1 and captures most of the value; Wallet is additive |
| Apple rejects background Bluetooth usage or users refuse the permission | Medium | Medium | Foreground-first design; group-default fallback makes the feature degrade to a smart picker |
| Receipt OCR accuracy on faded thermal receipts and mixed-language menus | High | Medium | Payer fix-up step before claiming; benchmark set from day one; manual item entry fallback |
| Voice parser mis-assigns payer or amount | Medium | High (money) | Never auto-save; confidence gating; field-level accuracy target enforced in CI |
| Ledger bug produces wrong balances | Low | Very high (trust) | Append-only revisions, integer money, shared fixtures, nightly zero-sum audit, property tests |
| AI inference cost per expense makes free tier uneconomic | Medium | Medium | Small prompts, fast model tiers, on-device speech; cost per expense tracked as a KPI; cap scans per day only if needed |
| Splitwise responds with its own payments in APAC | Medium | Medium | Speed to market plus the collaborative claim flow, which is an interaction model, not a feature toggle |
| Guest-link abuse (spam links, impersonation) | Low | Medium | OTP on every guest, link expiry and revocation, rate limits |

**External dependencies.** Apple (App Store review, Sign in with Apple, Speech and Vision frameworks), Twilio or equivalent for OTP, an LLM provider with structured-output support, an e-money or BaaS partner for the Wallet, PayNow proxy lookup rules (settlement intent needs the counterparty's registered mobile number, which they must consent to expose).

**Open questions for the founders**

- [ ] Wallet strategy: partner-first (assumed here) or pursue a Standard Payment Institution licence in parallel?
- [ ] Free forever for core splitting, with revenue only from Wallet and power features — confirm, since it shapes the cost ceiling for AI features.
- [ ] Launch cohort: friends-and-family in Singapore first, or a university campus launch (NTU) for density?
- [ ] Should Bluetooth proximity be on by default after the first consent, or opt-in per group?
- [ ] Minimum iOS version: 17 (recommended) or 16 for wider reach at the cost of SwiftData and `@Observable`?
- [ ] Web guest pages: server-rendered from FastAPI (assumed) or a small React app from day one to seed the Phase 4 web client?
- [ ] India as market two: confirm, and whether UPI deep links need a payment-aggregator relationship for reliability.

**Next steps.** Approve the phasing and open questions above; then this PRD spawns five feature specs (ledger and groups, guest links, receipt claiming, voice entry, proximity) and one compliance memo (Wallet), each owned by one engineer and reviewed against this document.
