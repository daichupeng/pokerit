"""Create all database tables against DATABASE_URL (dev bootstrap).

For production, replace this with a real migration tool (e.g. Alembic).
"""

from poker_engine.db.base import Base, DATABASE_URL, engine

# Importing models registers them on Base.metadata.
import poker_engine.db.models  # noqa: F401


def main() -> None:
    print(f"Creating schema on: {DATABASE_URL}")
    Base.metadata.create_all(engine)
    tables = ", ".join(sorted(Base.metadata.tables))
    print(f"Done. Tables: {tables}")


if __name__ == "__main__":
    main()
