import bcrypt, sqlalchemy as sa
from services.storage import engine, users

def verify(username: str, password: str) -> bool:
    with engine.connect() as conn:
        row = conn.execute(sa.select(users.c.pwd_hash).where(users.c.username == username)).first()
    if not row:
        return False
    return bcrypt.checkpw(password.encode(), row.pwd_hash.encode())
