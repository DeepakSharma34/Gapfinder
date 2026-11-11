import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, ForeignKey, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    name: Mapped[str] = mapped_column(String(80), default="Student")
    days: Mapped[int] = mapped_column(default=5)
    minutes: Mapped[int] = mapped_column(default=60)


class LoginSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires: Mapped[float]


class Topic(Base):
    __tablename__ = "topics"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    chunk_count: Mapped[int] = mapped_column(default=0)
    created: Mapped[str] = mapped_column(String(40), default=now)


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    text: Mapped[str]
    page: Mapped[int]
    section: Mapped[str] = mapped_column(String(200))
    topic_id: Mapped[str] = mapped_column(String(36), index=True)


class Quiz(Base):
    __tablename__ = "quizzes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    questions: Mapped[list] = mapped_column(JSON)
    answers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    results: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created: Mapped[str] = mapped_column(String(40), default=now)
    submitted: Mapped[str | None] = mapped_column(String(40), nullable=True)


def make_database(url):
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, **kwargs)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ":" + digest.hex()


def check_password(password, encoded):
    salt, expected = encoded.split(":")
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return hmac.compare_digest(actual.hex(), expected)


def token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()
