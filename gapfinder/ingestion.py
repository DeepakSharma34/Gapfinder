import io
import re

from sqlalchemy import select

from .db import Chunk, Document, Topic
from .retrieval import terms


def read_pages(filename, content):
    if filename.lower().endswith(".pdf"):
        from pypdf import PdfReader
        try:
            reader = PdfReader(io.BytesIO(content))
            if len(reader.pages) > 150:
                raise ValueError("Use a PDF with at most 150 pages for this MVP.")
            pages = [(i + 1, (p.extract_text() or "").strip()) for i, p in enumerate(reader.pages)]
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("This PDF could not be read. Try a text-based PDF or a .txt file.") from exc
    elif filename.lower().endswith((".txt", ".md")):
        try:
            pages = [(1, content.decode("utf-8-sig"))]
        except UnicodeDecodeError as exc:
            raise ValueError("Text files must use UTF-8 encoding.") from exc
    else:
        raise ValueError("Upload a PDF, TXT, or Markdown file.")
    if not any(text.strip() for _, text in pages):
        raise ValueError("No readable text found. Scanned PDFs need OCR before upload.")
    if sum(len(t) for _, t in pages) > 500_000:
        raise ValueError("Use material with fewer than 500,000 characters for this MVP.")
    return pages


def topic_titles(pages):
    titles = []
    for _, text in pages:
        for line in text.splitlines():
            clean = re.sub(r"^\s*(?:#{1,6}\s*|[-*•]\s*|\d+[.)]\s*)", "", line).strip()
            if 3 <= len(clean) <= 100 and clean.lower() not in {"syllabus", "biology syllabus", "topics", "contents"}:
                if len(clean.split()) <= 12 and clean not in titles:
                    titles.append(clean)
    if not titles:
        raise ValueError("Put one topic per line in your syllabus, for example: Cell biology.")
    if len(titles) > 30:
        raise ValueError("Use a focused syllabus with at most 30 topics for the MVP.")
    return titles


def split_chunks(pages):
    output = []
    for page, text in pages:
        section = f"Page {page}"
        for paragraph in re.split(r"\n\s*\n", text):
            lines = paragraph.strip().splitlines()
            if not lines:
                continue
            if lines[0].startswith("#"):
                section = lines.pop(0).lstrip("# ")[:200] or section
            paragraph = " ".join(lines).strip()
            # Whole sentences where possible; bounded chunks with a short overlap on long passages.
            while paragraph:
                end = min(1000, len(paragraph))
                if end < len(paragraph):
                    boundary = paragraph.rfind(". ", 400, end)
                    if boundary != -1:
                        end = boundary + 1
                    else:
                        space = paragraph.rfind(" ", 400, end)
                        end = space if space != -1 else end
                value = paragraph[:end].strip()
                if len(value) >= 30:
                    output.append((page, section, value))
                if end >= len(paragraph):
                    break
                paragraph = paragraph[max(1, end - 100):].strip()
    return output


def map_topics(chunks, topics, encoder):
    topic_vectors = encoder.embed([t.title for t in topics])
    vectors = encoder.embed([f"{c.section} {c.text}" for c in chunks])
    for chunk, vector in zip(chunks, vectors):
        scores = []
        for topic, topic_vector in zip(topics, topic_vectors):
            denom = (sum(v * v for v in vector) * sum(v * v for v in topic_vector)) ** 0.5 or 1
            cosine = sum(a * b for a, b in zip(vector, topic_vector)) / denom
            heading_overlap = len(set(terms(topic.title)) & set(terms(chunk.section)))
            scores.append(cosine + 0.25 * heading_overlap)
        chunk.topic_id = topics[max(range(len(scores)), key=scores.__getitem__)].id


def payloads(db, user_id):
    documents = {d.id: d for d in db.scalars(select(Document).where(Document.user_id == user_id))}
    return [{"id": c.id, "text": c.text, "user_id": user_id, "document_id": c.document_id,
             "filename": documents[c.document_id].filename, "kind": documents[c.document_id].kind,
             "page": c.page, "section": c.section, "topic_id": c.topic_id}
            for c in db.scalars(select(Chunk).where(Chunk.user_id == user_id))]


def ingest(db, retrieval, user_id, filename, kind, content):
    pages = read_pages(filename, content)
    topics = list(db.scalars(select(Topic).where(Topic.user_id == user_id)))
    if kind == "syllabus":
        existing = {t.title.lower() for t in topics}
        for title in topic_titles(pages):
            if title.lower() not in existing:
                topic = Topic(user_id=user_id, title=title)
                db.add(topic)
                topics.append(topic)
                existing.add(title.lower())
        db.flush()
    elif not topics:
        raise ValueError("Upload your syllabus first so material can be mapped to topics.")
    doc = Document(user_id=user_id, filename=filename, kind=kind)
    db.add(doc)
    db.flush()
    # A syllabus defines the map; quiz evidence must come from notes or past papers.
    if kind != "syllabus":
        pieces = split_chunks(pages)
        if not pieces:
            raise ValueError("Include at least one paragraph of study material.")
        chunks = [Chunk(user_id=user_id, document_id=doc.id, page=page, section=section,
                        text=text, topic_id="") for page, section, text in pieces]
        map_topics(chunks, topics, retrieval.encoder)
        db.add_all(chunks)
        doc.chunk_count = len(chunks)
    else:
        chunks = list(db.scalars(select(Chunk).where(Chunk.user_id == user_id)))
        if chunks:
            map_topics(chunks, topics, retrieval.encoder)
    db.flush()
    retrieval.index(payloads(db, user_id))
    db.commit()
    return doc
