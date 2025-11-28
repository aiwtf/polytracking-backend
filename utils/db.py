import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set in environment.")

def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
