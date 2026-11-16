"""Alembic environment. Called from trimatch.store.db.upgrade (connection passed in) or from
the alembic CLI in backend/ (URL from trimatch.store.db.database_url)."""

from alembic import context

from trimatch.store.models import Base

config = context.config
target_metadata = Base.metadata


def run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


conn = config.attributes.get("connection")
if conn is not None:
    run(conn)
else:
    from trimatch.store.db import engine

    with engine().connect() as connection:
        run(connection)
        connection.commit()
