from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import get_db, get_session_factory

DbSession = Annotated[Session, Depends(get_db)]

SessionFactory = Annotated[sessionmaker[Session], Depends(get_session_factory)]
