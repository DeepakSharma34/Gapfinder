from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gapfinder.db import Quiz
from gapfinder.diagnosis import build_plan, diagnose
from gapfinder.generation import GeneratedQuestion, Generator, QuestionBatch, validate_evidence
from gapfinder.ingestion import read_pages
from gapfinder.main import create_app


def test_auth_cookie_and_private_endpoints(client, settings):
    assert client.get("/api/dashboard").status_code == 401
    assert client.post("/api/login", json={"email": settings.demo_email, "password": "incorrect-password"}).status_code == 401
    response = client.post("/api/login", json={"email": settings.demo_email, "password": settings.demo_password})
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert client.get("/api/dashboard").status_code == 200
    client.post("/api/logout")
    assert client.get("/api/dashboard").status_code == 401


def test_diagnostic_grading_citations_and_adaptation(logged_in):
    client = logged_in
    initial = client.get("/api/dashboard").json()
    assert len(initial["topics"]) == 6
    assert all(t["score"] is None and t["status"] == "untested" for t in initial["topics"])
    response = client.post("/api/quizzes", json={"count": 6})
    assert response.status_code == 201, response.text
    quiz = response.json()
    assert len(quiz["questions"]) == 6
    assert len({q["topic_id"] for q in quiz["questions"]}) == 6
    assert all("correct_index" not in q and "explanation" not in q for q in quiz["questions"])
    assert client.post("/api/quizzes", json={"count":6}).json()["id"] == quiz["id"]
    with client.app.state.db() as db:
        private = db.get(Quiz, quiz["id"])
        correct = [q["correct_index"] for q in private.questions]
        for q in private.questions:
            matches = client.app.state.retrieval.search(private.user_id, q["citation"]["quote"], limit=20)
            source = next(c for c in matches if c["id"] == q["citation"]["chunk_id"])
            assert q["citation"]["quote"] in source["text"]
    assert client.post(f"/api/quizzes/{quiz['id']}/submit", json={"answers":[0]}).status_code == 422
    answers = [(n+1) % 4 if i == 0 else n for i,n in enumerate(correct)]
    result = client.post(f"/api/quizzes/{quiz['id']}/submit", json={"answers":answers})
    assert result.status_code == 200
    assert sum(r["correct"] for r in result.json()["results"]) == 5
    repeat = client.post(f"/api/quizzes/{quiz['id']}/submit", json={"answers":correct})
    assert repeat.json()["answers"] == answers  # resubmission cannot change a finished attempt
    dashboard = client.get("/api/dashboard").json()
    weak = next(t for t in dashboard["topics"] if t["status"] == "weak")
    assert dashboard["plan"][0]["sessions"][0]["topic_id"] == weak["id"]
    assert len(dashboard["history"]) == 1
    assert "limited" in weak["confidence"]
    new_quiz = client.post("/api/quizzes", json={"count":6}).json()
    assert new_quiz["id"] != quiz["id"]
    with client.app.state.db() as db:
        answers = [q["correct_index"] for q in db.get(Quiz, new_quiz["id"]).questions]
    client.post(f"/api/quizzes/{new_quiz['id']}/submit", json={"answers": answers})
    updated = client.get("/api/dashboard").json()
    topic = next(t for t in updated["topics"] if t["id"] == weak["id"])
    assert topic["score"] == 50 and topic["status"] == "medium"


def test_user_isolation_for_quizzes_topics_and_retrieval(logged_in):
    client = logged_in
    old = client.get("/api/dashboard").json()
    quiz = client.post("/api/quizzes", json={"count":3}).json()
    client.post("/api/logout")
    response = client.post("/api/register", json={"email":"other@example.com", "password":"other-password", "name":"Other"})
    assert response.status_code == 201
    assert client.get("/api/dashboard").json()["documents"] == []
    assert client.get(f"/api/quizzes/{quiz['id']}").status_code == 404
    assert client.post(f"/api/quizzes/{quiz['id']}/submit", json={"answers":[0,0,0]}).status_code == 404
    assert client.post("/api/explain", json={"question":"Explain biology", "topic_id":old["topics"][0]["id"]}).status_code == 404
    response = client.post("/api/explain", json={"question":"Explain photosynthesis"})
    assert response.json()["citations"] == []
    assert client.post("/api/quizzes", json={"count":3}).status_code == 422
    # Same query cannot cross the server-applied user filter.
    client.post("/api/materials", data={"kind":"syllabus"}, files={"file":("syllabus.txt",b"Ocean currents\nWeather systems")})
    response = client.post("/api/materials", data={"kind":"notes"}, files={"file":("notes.txt",
        b"# Ocean currents\n\nOcean currents transport heat across the planet. Circulation is influenced by prevailing winds and differences in water density. Salinity and temperature affect density and support deep circulation.")})
    assert response.status_code == 201, response.text
    answer = client.post("/api/explain", json={"question":"Ocean currents transport heat"}).json()
    assert answer["citations"]
    assert all("chlorophyll" not in c["quote"].lower() for c in answer["citations"])


def test_time_budget_validation_and_no_cross_origin_writes(logged_in):
    client = logged_in
    assert client.put("/api/preferences", json={"days":0,"minutes":50}).status_code == 422
    assert client.put("/api/preferences", json={"days":3,"minutes":35}).status_code == 200
    dashboard = client.get("/api/dashboard").json()
    assert len(dashboard["plan"]) == 3
    assert all(sum(s["minutes"] for s in d["sessions"]) == 35 for d in dashboard["plan"])
    assert client.put("/api/preferences", headers={"Origin":"https://other.example"},json={"days":3,"minutes":35}).status_code == 403


def test_upload_validation_and_no_partial_documents(logged_in):
    client = logged_in
    before = len(client.get("/api/dashboard").json()["documents"])
    for filename, contents in (("malware.exe",b"hello"),("bad.pdf",b"not a pdf"),("empty.txt",b"\n"),("wrong.txt",b"\xff")):
        response = client.post("/api/materials", data={"kind":"notes"}, files={"file":(filename,contents)})
        assert response.status_code == 422, response.text
    assert len(client.get("/api/dashboard").json()["documents"]) == before
    assert client.post("/api/materials",data={"kind":"notes"},files={"file":("big.txt",b"x" * (5*1024*1024+1))}).status_code == 413


def test_restart_preserves_quiz_and_index(settings):
    with TestClient(create_app(settings)) as client:
        client.post("/api/login", json={"email":settings.demo_email,"password":settings.demo_password})
        quiz = client.post("/api/quizzes",json={"count":3}).json()
        first_docs = client.get("/api/dashboard").json()["documents"]
    with TestClient(create_app(settings)) as client:
        client.post("/api/login",json={"email":settings.demo_email,"password":settings.demo_password})
        assert client.get(f"/api/quizzes/{quiz['id']}").status_code == 200
        assert len(client.get("/api/dashboard").json()["documents"]) == len(first_docs)
        assert client.post("/api/explain",json={"question":"Explain photosynthesis"}).json()["citations"]


def test_generated_citations_reject_invented_sources_and_quotes():
    source = {"id":"chunk-1","topic_id":"topic-1","document_id":"doc-1","filename":"notes.txt","page":2,
              "section":"Cells","text":"Ribosomes synthesize proteins by translating messenger RNA."}
    question = GeneratedQuestion(topic_id="topic-1",chunk_id="chunk-1",quote=source["text"],
        question="What do ribosomes synthesize?",options=["Proteins","Lipids","Starch","Cellulose"],
        correct_index=0,explanation="The passage states that ribosomes synthesize proteins.")
    assert validate_evidence(QuestionBatch(questions=[question]),[source])[0]["citation"]["page"] == 2
    for changes in ({"chunk_id":"invented"},{"topic_id":"invented"},{"quote":"Ribosomes manufacture planet-sized computers."},
                    {"options":["a","a","b","c"]}):
        with pytest.raises(ValueError):
            validate_evidence(QuestionBatch(questions=[question.model_copy(update=changes)]),[source])


def test_recent_window_replaces_old_mistakes_and_plan_updates():
    topics = [SimpleNamespace(id="a",title="Algebra"), SimpleNamespace(id="b",title="Biology")]
    quizzes = [SimpleNamespace(id=str(i),submitted=f"2026-11-{i+1:02d}",results=[{"topic_id":"a","correct":i>=8}]) for i in range(16)]
    report, history = diagnose(topics, quizzes, {"a":2})
    assert report[0]["score"] == 100 and report[0]["recent_count"] == 8
    assert report[1]["score"] is None
    assert build_plan(report,1,10)[0]["sessions"][0]["topic_id"] == "b"
    assert len(history) == 16


def test_live_generator_uses_retrieved_context_and_validation(settings):
    generator = Generator(replace(settings,mode="live",groq_key="test-only"))
    source = {"id":"c1","topic_id":"t1","document_id":"d1","filename":"notes.md","page":1,
              "section":"Cell biology","text":"Ribosomes synthesize proteins by translating messenger RNA."}
    question = {"topic_id":"t1","chunk_id":"c1","quote":source["text"],"question":"What do ribosomes synthesize?",
                "options":["Proteins","Starch","Lipids","Cellulose"],"correct_index":0,
                "explanation":"The source states that ribosomes synthesize proteins."}
    import json
    calls = []
    def complete(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"questions":[question]})))])
    generator.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    output = generator.questions([source],"seed")
    assert output[0]["correct_index"] == 0
    assert source["text"] in calls[0]["messages"][1]["content"]


def test_static_app_and_empty_pdf(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]
    import io
    from pypdf import PdfWriter
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300,height=300)
    writer.write(buffer)
    with pytest.raises(ValueError, match="OCR"):
        read_pages("scan.pdf",buffer.getvalue())
