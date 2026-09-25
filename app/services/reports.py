"""Reporting queries."""
from typing import List

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import Book, Order, OrderItem, OrderStatus
from app.schemas import TopBook


def top_books(db: Session, limit: int = 5) -> List[TopBook]:
    """Best-selling books.

    Rules: copies_sold sums quantities over ``paid`` orders only; books with no sales are
    excluded; sorted by copies_sold desc, then title asc; at most ``limit`` rows.
    """
    query = (
        select(
            Book.id.label("book_id"),
            Book.title.label("title"),
            func.sum(OrderItem.quantity).label("copies_sold"),
        )
        .join(OrderItem, OrderItem.book_id == Book.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.status == OrderStatus.PAID.value)
        .group_by(Book.id, Book.title)
        .having(func.sum(OrderItem.quantity) > 0)
        .order_by(desc("copies_sold"), Book.title.asc())
        .limit(limit)
    )
    rows = db.execute(query).all()
    return [TopBook(book_id=r.book_id, title=r.title, copies_sold=int(r.copies_sold)) for r in rows]
