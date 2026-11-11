import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .db import (Chunk, Document, LoginSession, Quiz, Topic, User, check_password,
                 hash_password, make_database, now, token_digest, uid)
from .diagnosis import build_plan, diagnose
from .generation import Generator
from .ingestion import ingest, payloads
from .retrieval import Retrieval

log = logging.getLogger(__name__)
ROOT = Path(__file__).parent
COOKIE = "gapfinder_session"


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="Student", min_length=1, max_length=80)


class QuizRequest(BaseModel):
    count: int = Field(default=6, ge=3, le=12)


class Answers(BaseModel):
    answers: list[int] = Field(min_length=1, max_length=12)


class Preferences(BaseModel):
    days: int = Field(ge=1, le=30)
    minutes: int = Field(ge=10, le=240)


class ExplainRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    topic_id: str | None = None


def public_quiz(quiz):
    questions = []
    for i, q in enumerate(quiz.questions):
        item = {k: q[k] for k in ("topic_id", "question", "options", "citation")}
        item["index"] = i
        if quiz.submitted:
            item.update(correct_index=q["correct_index"], explanation=q["explanation"])
        questions.append(item)
    return {"id": quiz.id, "questions": questions, "created": quiz.created,
            "submitted": quiz.submitted, "answers": quiz.answers, "results": quiz.results}


def report_data(db, user_id):
    topics = list(db.scalars(select(Topic).where(Topic.user_id == user_id).order_by(Topic.title)))
    quizzes = list(db.scalars(select(Quiz).where(Quiz.user_id == user_id, Quiz.submitted.is_not(None))
                              .order_by(Quiz.submitted, Quiz.id)))
    papers = set(db.scalars(select(Document.id).where(Document.user_id == user_id, Document.kind == "past_paper")))
    counts = {}
    for chunk in db.scalars(select(Chunk).where(Chunk.user_id == user_id)):
        if chunk.document_id in papers:
            counts[chunk.topic_id] = counts.get(chunk.topic_id, 0) + 1
    return diagnose(topics, quizzes, counts)


def create_app(settings=None):
    config = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        config.data_dir.mkdir(parents=True, exist_ok=True)
        engine, factory = make_database(config.database_url)
        retrieval = Retrieval(config)
        generator = Generator(config)
        app.state.db = factory
        app.state.retrieval = retrieval
        app.state.generator = generator
        app.state.login_attempts = {}
        try:
            with factory() as db:
                if config.mode == "demo":
                    demo = db.scalar(select(User).where(User.email == config.demo_email.lower()))
                    if not demo:
                        demo = User(email=config.demo_email.lower(), password_hash=hash_password(config.demo_password), name="Alex")
                        db.add(demo)
                        db.commit()
                    if not db.scalar(select(Document).where(Document.user_id == demo.id)):
                        for filename, kind in (("syllabus.txt", "syllabus"), ("notes.md", "notes"), ("past-papers.txt", "past_paper")):
                            ingest(db, retrieval, demo.id, filename, kind, (ROOT / "samples" / filename).read_bytes())
                # Recover any previously committed material after a restart or index configuration change.
                for user_id in db.scalars(select(User.id)):
                    retrieval.index(payloads(db, user_id))
            yield
        finally:
            generator.close()
            retrieval.close()
            engine.dispose()

    app = FastAPI(title="GapFinder AI", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def browser_protection(request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "Cross-origin writes are not allowed."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def database(request: Request):
        with request.app.state.db() as db:
            yield db

    def current_user(request: Request, db=Depends(database)):
        token = request.cookies.get(COOKIE)
        session = db.get(LoginSession, token_digest(token)) if token else None
        if not session or session.expires < time.time():
            raise HTTPException(401, "Please log in to continue.")
        user = db.get(User, session.user_id)
        if user is None:
            raise HTTPException(401, "Please log in to continue.")
        return user

    def authenticate(response, db, user):
        token = secrets.token_urlsafe(32)
        db.add(LoginSession(token_hash=token_digest(token), user_id=user.id, expires=time.time() + 7 * 86400))
        db.commit()
        response.set_cookie(COOKIE, token, httponly=True, secure=config.cookie_secure,
                            samesite="strict", max_age=7 * 86400)
        return {"name": user.name, "email": user.email}

    @app.get("/api/config")
    def configuration():
        return {"mode": config.mode, "embedding_backend": config.embedding_backend,
                "demo_email": config.demo_email if config.mode == "demo" else None,
                "demo_password": config.demo_password if config.mode == "demo" else None}

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": config.mode}

    @app.post("/api/register", status_code=201)
    def register(body: Credentials, response: Response, db=Depends(database)):
        email = body.email.strip().lower()
        if "@" not in email or any(c.isspace() for c in email):
            raise HTTPException(422, "Enter a valid email address.")
        user = User(email=email, name=body.name.strip() or "Student", password_hash=hash_password(body.password))
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "An account with this email already exists.")
        return authenticate(response, db, user)

    @app.post("/api/login")
    def login(body: Credentials, request: Request, response: Response, db=Depends(database)):
        address = request.client.host if request.client else "local"
        timestamp = time.time()
        attempts = [x for x in request.app.state.login_attempts.get(address, []) if x > timestamp - 300]
        if len(attempts) >= 15:
            raise HTTPException(429, "Too many login attempts. Try again in five minutes.")
        attempts.append(timestamp)
        request.app.state.login_attempts[address] = attempts
        user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
        if not user or not check_password(body.password, user.password_hash):
            raise HTTPException(401, "Email or password is incorrect.")
        return authenticate(response, db, user)

    @app.post("/api/logout")
    def logout(request: Request, response: Response, db=Depends(database)):
        token = request.cookies.get(COOKIE)
        session = db.get(LoginSession, token_digest(token)) if token else None
        if session:
            db.delete(session)
            db.commit()
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/dashboard")
    def dashboard(user=Depends(current_user), db=Depends(database)):
        report, history = report_data(db, user.id)
        documents = list(db.scalars(select(Document).where(Document.user_id == user.id).order_by(Document.created)))
        active = db.scalar(select(Quiz).where(Quiz.user_id == user.id, Quiz.submitted.is_(None))
                           .order_by(Quiz.created.desc()))
        return {"user": {"name": user.name, "email": user.email, "days": user.days, "minutes": user.minutes},
                "topics": report, "history": history, "plan": build_plan(report, user.days, user.minutes),
                "documents": [{"id": d.id, "filename": d.filename, "kind": d.kind, "chunks": d.chunk_count} for d in documents],
                "active_quiz": active.id if active else None}

    @app.post("/api/materials", status_code=201)
    async def upload(request: Request, file: UploadFile = File(...), kind: str = Form(...),
                     user=Depends(current_user), db=Depends(database)):
        if kind not in {"syllabus", "notes", "past_paper"}:
            raise HTTPException(422, "Choose syllabus, notes, or past_paper.")
        content = await file.read(5 * 1024 * 1024 + 1)
        await file.close()
        if not content or len(content) > 5 * 1024 * 1024:
            raise HTTPException(413, "Upload a nonempty file smaller than 5 MB.")
        filename = Path((file.filename or "material.txt").replace("\\", "/")).name[:200]
        try:
            doc = await run_in_threadpool(ingest, db, request.app.state.retrieval, user.id, filename, kind, content)
        except ValueError as exc:
            db.rollback()
            raise HTTPException(422, str(exc))
        except Exception:
            db.rollback()
            log.exception("Material indexing failed")
            raise HTTPException(503, "Material indexing failed. Check the configured embedding model and Qdrant connection.")
        return {"id": doc.id, "filename": doc.filename, "chunks": doc.chunk_count}

    @app.post("/api/quizzes", status_code=201)
    def create_quiz(body: QuizRequest, request: Request, user=Depends(current_user), db=Depends(database)):
        report, _ = report_data(db, user.id)
        existing = db.scalar(select(Quiz).where(Quiz.user_id == user.id, Quiz.submitted.is_(None)).order_by(Quiz.created.desc()))
        if existing:
            return public_quiz(existing)
        eligible = []
        retrieval = request.app.state.retrieval
        try:
            for topic in sorted(report, key=lambda x: (-x["priority"], x["title"])):
                chunks = retrieval.search(user.id, topic["title"], topic_id=topic["id"], kind="notes", limit=4)
                if chunks:
                    eligible.append(chunks)
            if not eligible:
                raise HTTPException(422, "Upload your syllabus and study notes before starting a diagnostic.")
            quiz_id = uid()
            offset = int(quiz_id.replace("-", "")[:8], 16)
            selected = [eligible[i % len(eligible)][(offset + i // len(eligible)) % len(eligible[i % len(eligible)])]
                        for i in range(body.count)]
            questions = request.app.state.generator.questions(selected, quiz_id)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except Exception:
            log.exception("Quiz generation failed")
            raise HTTPException(503, "Quiz generation failed. Check Groq limits, the selected model, and the retrieval connection.")
        quiz = Quiz(id=quiz_id, user_id=user.id, questions=questions)
        db.add(quiz)
        db.commit()
        return public_quiz(quiz)

    def owned_quiz(quiz_id, user, db):
        quiz = db.get(Quiz, quiz_id)
        if not quiz or quiz.user_id != user.id:
            raise HTTPException(404, "Quiz not found.")
        return quiz

    @app.get("/api/quizzes/{quiz_id}")
    def get_quiz(quiz_id: str, user=Depends(current_user), db=Depends(database)):
        return public_quiz(owned_quiz(quiz_id, user, db))

    @app.post("/api/quizzes/{quiz_id}/submit")
    def submit_quiz(quiz_id: str, body: Answers, user=Depends(current_user), db=Depends(database)):
        quiz = owned_quiz(quiz_id, user, db)
        if quiz.submitted:
            return public_quiz(quiz)
        if len(body.answers) != len(quiz.questions) or any(type(x) is not int or x not in range(4) for x in body.answers):
            raise HTTPException(422, "Choose one of the four options for every question.")
        results = [{"topic_id": q["topic_id"], "correct": answer == q["correct_index"],
                    "question": q["question"]} for q, answer in zip(quiz.questions, body.answers)]
        db.execute(update(Quiz).where(Quiz.id == quiz.id, Quiz.submitted.is_(None))
                   .values(answers=body.answers, results=results, submitted=now()))
        db.commit()
        db.refresh(quiz)
        return public_quiz(quiz)

    @app.put("/api/preferences")
    def preferences(body: Preferences, user=Depends(current_user), db=Depends(database)):
        user.days, user.minutes = body.days, body.minutes
        db.commit()
        report, _ = report_data(db, user.id)
        return {"plan": build_plan(report, user.days, user.minutes)}

    @app.post("/api/explain")
    def explain(body: ExplainRequest, request: Request, user=Depends(current_user), db=Depends(database)):
        if body.topic_id:
            topic = db.get(Topic, body.topic_id)
            if not topic or topic.user_id != user.id:
                raise HTTPException(404, "Topic not found.")
        try:
            chunks = request.app.state.retrieval.search(user.id, body.question, topic_id=body.topic_id, kind="notes", limit=4)
            # Weak matches are not evidence that the material supports the question.
            chunks = [c for c in chunks if c["score"] >= (0.08 if config.embedding_backend == "hash" else 0.35)]
            text, citations = request.app.state.generator.explain(body.question, chunks)
            return {"answer": text, "citations": citations}
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except Exception:
            log.exception("Explanation failed")
            raise HTTPException(503, "The explanation service is unavailable. Please retry.")

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    @app.get("/")
    def index():
        return FileResponse(ROOT / "static" / "index.html")

    return app


app = create_app()
