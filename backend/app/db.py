import os
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()
TZ = timezone(timedelta(hours=8))


def now():
    return datetime.now(TZ)


engine = create_engine(
    os.getenv("DATABASE_URL", "postgresql+psycopg://charge:charge@localhost:5432/charge"),
    pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "5")),
    pool_pre_ping=True,
    pool_timeout=5,
    connect_args={
        "options": "-c timezone=Asia/Shanghai -c statement_timeout=15000 -c lock_timeout=5000"
    },
)
Session = sessionmaker(engine, expire_on_commit=False)
metadata = MetaData()
