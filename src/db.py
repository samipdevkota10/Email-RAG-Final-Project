from contextlib import contextmanager
from typing import Generator, Tuple

from Database.dbconnection import DBConnection


@contextmanager
def db_session() -> Generator[Tuple[DBConnection, object, object], None, None]:
    """
    Provide a shared DB session context used by the evaluation routes.

    Yields:
        (db, conn, cursor): The connection helper, psycopg2 connection, and cursor.
    """
    db = DBConnection()
    try:
        conn, cur = db.connect()
        yield db, conn, cur
    finally:
        db.close()

