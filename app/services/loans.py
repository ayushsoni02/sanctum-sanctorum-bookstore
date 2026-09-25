"""Library loan operations: borrowing and returning books."""
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Book, Loan, Member, MemberTier
from app.schemas import LoanCreate, LoanOut, LoanStatus
from app.services.members import ensure_can_access_restricted, get_member

# Maximum concurrent unreturned loans per tier (None = unlimited).
TIER_LOAN_LIMIT: Dict[str, Optional[int]] = {
    MemberTier.APPRENTICE.value: 1,
    MemberTier.ADEPT.value: 3,
    MemberTier.MASTER.value: 5,
    MemberTier.SUPREME.value: None,
}

LOAN_PERIOD = timedelta(days=14)
LATE_FEE_PER_DAY_CENTS = 25


def loan_status(loan: Loan, now: datetime) -> LoanStatus:
    """``returned`` if returned; else ``overdue`` if now > due_at; else ``active``."""
    if loan.returned_at is not None:
        return "returned"
    if now > loan.due_at:
        return "overdue"
    return "active"


def to_loan_out(loan: Loan, now: datetime) -> LoanOut:
    """Serialize a loan, computing its status at read time."""
    return LoanOut(
        id=loan.id,
        member_id=loan.member_id,
        book_id=loan.book_id,
        borrowed_at=loan.borrowed_at,
        due_at=loan.due_at,
        returned_at=loan.returned_at,
        late_fee_cents=loan.late_fee_cents,
        status=loan_status(loan, now),
    )


def calculate_late_fee(due_at: datetime, returned_at: datetime, price_cents: int) -> int:
    """25 cents per started day late (any partial day counts), capped at the book's price; 0 if not late."""
    if returned_at <= due_at:
        return 0
    seconds_late = (returned_at - due_at).total_seconds()
    days_late = math.ceil(seconds_late / 86400)
    fee = days_late * LATE_FEE_PER_DAY_CENTS
    return min(fee, price_cents)


def create_loan(db: Session, data: LoanCreate, now: datetime) -> LoanOut:
    """Borrow a book for 14 days.

    Checks, in order:
    1. 404 member not found; 404 book not found
    2. 403 book restricted and member tier below master
    3. 409 member has any overdue loan
    4. 409 member already has an unreturned loan of this book
    5. 409 member is at their tier's loan limit
    6. 409 book is out of stock
    On success: borrowed_at = now, due_at = now + 14 days, returned_at None,
    late_fee_cents 0, and stock is decremented by one.
    """
    # 1. 404: Member and book must exist
    member = get_member(db, data.member_id)
    book = db.get(Book, data.book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    # 2. 403: Book restricted and member tier below master
    if book.restricted:
        ensure_can_access_restricted(member)

    # Fetch member's current unreturned loans
    active_loans = db.scalars(
        select(Loan).where(Loan.member_id == member.id, Loan.returned_at.is_(None))
    ).all()

    # 3. 409: Member has any overdue loan
    for loan in active_loans:
        if now > loan.due_at:
            raise HTTPException(status_code=409, detail="Member has overdue loans")

    # 4. 409: Member already has an unreturned loan of this book
    for loan in active_loans:
        if loan.book_id == book.id:
            raise HTTPException(status_code=409, detail="Member already has an unreturned loan of this book")

    # 5. 409: Member is at their tier's loan limit
    limit = TIER_LOAN_LIMIT.get(member.tier)
    if limit is not None and len(active_loans) >= limit:
        raise HTTPException(status_code=409, detail=f"Member has reached their tier loan limit of {limit}")

    # 6. 409: Book is out of stock
    if book.stock <= 0:
        raise HTTPException(status_code=409, detail="Book is out of stock")

    # Success: decrement stock and create loan
    book.stock -= 1
    loan = Loan(
        member_id=member.id,
        book_id=book.id,
        borrowed_at=now,
        due_at=now + LOAN_PERIOD,
        returned_at=None,
        late_fee_cents=0,
    )
    db.add(loan)
    db.commit()
    db.refresh(loan)
    return to_loan_out(loan, now)


def get_loan(db: Session, loan_id: int, now: datetime) -> LoanOut:
    """Return a loan by id, or raise 404."""
    loan = db.get(Loan, loan_id)
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan not found")
    return to_loan_out(loan, now)


def return_loan(db: Session, loan_id: int, now: datetime) -> LoanOut:
    """Return a borrowed book.

    Rules: 404 if missing; 409 if already returned. Sets returned_at = now, restores one copy
    of stock and charges a late fee (see ``calculate_late_fee``).
    """
    loan = db.get(Loan, loan_id)
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan not found")
    if loan.returned_at is not None:
        raise HTTPException(status_code=409, detail="Loan has already been returned")

    loan.returned_at = now
    loan.book.stock += 1
    loan.late_fee_cents = calculate_late_fee(loan.due_at, now, loan.book.price_cents)
    db.commit()
    db.refresh(loan)
    return to_loan_out(loan, now)


def list_member_loans(
    db: Session, member_id: int, now: datetime, status: Optional[LoanStatus] = None
) -> List[LoanOut]:
    """A member's loans ordered by id, optionally filtered by computed status; 404 if member missing."""
    get_member(db, member_id)
    loans = db.scalars(
        select(Loan).where(Loan.member_id == member_id).order_by(Loan.id.asc())
    ).all()

    result = [to_loan_out(loan, now) for loan in loans]
    if status is not None:
        result = [l for l in result if l.status == status]
    return result
