# Sanctum Sanctorum Bookstore — Engineering Notes

## Deployment

- **Live URL**: `https://sanctum-sanctorum-bookstore.onrender.com` *(or your deployed URL)*
- **API Docs**: `/docs` (Interactive Swagger UI)
- **Web Interface**: `/` (Member clubhouse frontend)
- **Database**: SQLite / PostgreSQL compatible (configured via `SANCTUM_DATABASE_URL`).
- **Seeded demo data**: The application auto-seeds standard books and members on first start if the database is empty:
  - Apprentice member: `Stephen Strange` (`strange@sanctum.org`)
  - Adept member: `Wong` (`wong@sanctum.org`)
  - Master member: `The Ancient One` (`ancient@sanctum.org`)
  - Supreme member: `Agamotto` (`agamotto@sanctum.org`)

---

## Project Status & Implementation Overview

All requirements from `SPEC.md` and acceptance criteria across the test suite have been completed and verified.
**Test Results: 202 / 202 passed (100% pass rate).**

### Summary of Completed Modules:
1. **Books (`app/routers/books.py`, `app/services/books.py`, `app/schemas.py`)**:
   - ISBN-13 checksum validation (alternating weights 1 and 3, modulo 10) and sanitization (stripping hyphens and spaces).
   - Duplicate ISBN detection returning HTTP 409 Conflict.
   - `PATCH /books/{id}` partial update ignoring unpatchable fields (`isbn`) and null validation.
   - `GET /books` with case-insensitive substring search (`q` on title or author), price range filters (`min_price`, `max_price`), restriction filtering, custom sorting with id ascending tie-break, and accurate pre-pagination total counts.

2. **Members (`app/routers/members.py`, `app/services/members.py`, `app/schemas.py`)**:
   - Email sanitization (whitespace stripping and lowercasing) with RFC regex validation.
   - Case-insensitive duplicate email detection (HTTP 409).
   - Fixed `tier_at_least` comparison hierarchy (`>=` index rank instead of `>`).
   - `GET /members/{id}/stats`: aggregate orders paid, total cents spent, unreturned loans, overdue loans, and cumulative late fees.

3. **Orders (`app/routers/orders.py`, `app/services/orders.py`, `app/schemas.py`)**:
   - Pydantic validation: non-empty items and duplicate `book_id` prevention (HTTP 422).
   - Ordered validation pipeline: 422 schema -> 404 member/book existence -> 403 restricted access checks -> 409 stock availability.
   - Atomic all-or-nothing stock reservation at order creation time.
   - Discount calculation engine: membership tier discount + 5% bulk discount for orders of 10+ copies, rounded down via integer floor division.
   - Freezing `unit_price_cents` snapshot per line item.
   - Payment transition (`pending` -> `paid`).
   - Order cancellation (`pending` -> `cancelled`) with full automatic stock replenishment.

4. **Loans (`app/routers/loans.py`, `app/services/loans.py`, `app/models.py`)**:
   - Completed `Loan` ORM model columns: `due_at`, `returned_at`, and `late_fee_cents`.
   - Sequential validation pipeline: 404 existence -> 403 restricted tier validation -> 409 existing overdue loans -> 409 duplicate unreturned book loan -> 409 tier loan limits -> 409 out-of-stock.
   - Strict due-date boundary: loan at exactly `due_at` remains active without late fees.
   - Return processing: stock restored, late fees calculated at 25 cents per started day late (ceiling of elapsed duration) capped at the book's return-time price.
   - Dynamic computed loan status projection (`active`, `overdue`, `returned`).

5. **Reports (`app/routers/reports.py`, `app/services/reports.py`)**:
   - `GET /reports/top-books?limit=5`: relational group-by aggregation over paid order items, excluding unsold books, ordered by copies sold descending and title ascending.

---

## Architectural & Design Decisions

### 1. Layered Architecture (Thin Routers, Rich Services)
- **Routers** (`app/routers/`): Keep HTTP transport concerns minimal. They validate incoming request models, extract query parameters, inject database sessions (`get_db`) and clock timestamps (`get_now`), and return typed Pydantic responses.
- **Services** (`app/services/`): Pure business and domain logic. All relational integrity, stock arithmetic, permissions, and fee calculations reside here, making the core logic easily testable independent of the web framework.

### 2. Data Integrity & Concurrency Resilience
- **All-or-Nothing Stock Reservation**: In `create_order`, all books and their stock levels are validated before mutating any state. If a single book in a multi-item order has insufficient stock, zero stock is subtracted and no partial order is saved.
- **Stock Restoration on Cancel**: When a pending order is cancelled, book stock is restored to ensure inventory is never leaked.

### 3. Deterministic Time Injection (`app/clock.py`)
- Standardized on naive UTC datetime throughout the domain.
- The `get_now` dependency is strictly injected into routers and forwarded to services, avoiding hidden calls to system `datetime.now()`. This ensures absolute test determinism and reproducible clock simulation.

### 4. Read-Time Status Computation
- Rather than running scheduled cron jobs to update loan statuses in the database, loan status (`active`, `overdue`, `returned`) is dynamically computed at read time based on `returned_at`, `due_at`, and the injected `now`. This eliminates race conditions, stale status flags, and unnecessary database write operations.

---

## AI Usage

This project was developed with the assistance of **Google Gemini via Antigravity**.

### How AI Was Used:
- **Architecture & Scaffolding**: Inspecting existing partially finished services, verifying schemas against `SPEC.md`, and implementing missing routes and service operations.
- **Test-Driven Verification**: Formulating validation logic (e.g. ISBN-13 checksum algorithm, loan late-fee day ceil calculation, SQLAlchemy aggregations) and running targeted pytest suites incrementally.
- **Disciplined Human-in-the-Loop Process**:
  - All operations were carried out step-by-step with explicit human permission requested and granted before every file inspection, file edit, or command execution.
  - The developer critically reviewed each code diff, verified the test output, committed changes in logical units, and pushed to GitHub.

### Critical Review & Overrides:
- **Subtle Bug in Starter Code**: In `app/services/members.py`, the helper `tier_at_least(tier, minimum)` was initially written with a strict inequality `TIER_ORDER.index(tier) > TIER_ORDER.index(minimum)`. This caused members of tier `master` to be denied access to restricted books that required `master` or higher. We caught and corrected this to `>=`.
- **Schema Validation Layering**: Ensured that schema validation errors (such as duplicate book IDs in order items and negative quantities) trigger HTTP 422 *before* database lookups, preventing unnecessary DB queries and ensuring exact adherence to the specification order.
