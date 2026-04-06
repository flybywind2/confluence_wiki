from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Space


def upsert_space(session: Session, space_key: str, root_page_id: str | None = None, name: str | None = None) -> Space:
    space = session.scalar(select(Space).where(Space.space_key == space_key))
    if space is None:
        space = Space(space_key=space_key, root_page_id=root_page_id, name=name or space_key)
        session.add(space)
    else:
        if root_page_id is not None:
            space.root_page_id = root_page_id
        if name is not None:
            space.name = name
    session.flush()
    return space
