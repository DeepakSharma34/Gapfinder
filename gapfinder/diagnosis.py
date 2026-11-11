"""Transparent score aggregation and bounded, deterministic time allocation."""
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def diagnose(topics, quizzes, exam_counts):
    evidence = defaultdict(list)
    history = []
    for quiz in quizzes:
        if quiz.results is None:
            continue
        for item in quiz.results:
            evidence[item["topic_id"]].append(item)
        history.append({"id": quiz.id, "date": quiz.submitted,
                        "score": round(100 * sum(r["correct"] for r in quiz.results) / len(quiz.results)),
                        "topics": {tid: round(100 * sum(x["correct"] for x in quiz.results if x["topic_id"] == tid) /
                            sum(x["topic_id"] == tid for x in quiz.results)) for tid in {r["topic_id"] for r in quiz.results}}})
    report = []
    for topic in topics:
        attempts = evidence[topic.id]
        # Last eight answers per topic lets new evidence replace older evidence.
        recent = attempts[-8:]
        score = round(100 * sum(x["correct"] for x in recent) / len(recent)) if recent else None
        status = "untested" if score is None else "weak" if score < 50 else "medium" if score < 80 else "strong"
        wrong = sum(not x["correct"] for x in recent)
        confidence = "not assessed" if not recent else "limited evidence" if len(recent) < 3 else "developing evidence" if len(recent) < 6 else "more evidence"
        reason = "Take a diagnostic to measure this topic." if not recent else f"{wrong} of the last {len(recent)} answers incorrect."
        importance = 1 + min(exam_counts.get(topic.id, 0), 5) * 0.2
        gap = 0.65 if score is None else max(0.1, 1 - score / 100)
        report.append({"id": topic.id, "title": topic.title, "score": score, "status": status,
                       "reason": reason, "confidence": confidence, "attempted": len(attempts),
                       "recent_count": len(recent), "exam_matches": exam_counts.get(topic.id, 0),
                       "priority": round(gap * importance, 3)})
    return report, history


def build_plan(report, days, minutes):
    if not report:
        return []
    ranked = sorted(report, key=lambda t: (-t["priority"], t["title"]))
    # Ten-minute blocks. Each day stays within the student's requested budget.
    allocation = defaultdict(int)
    scheduled = []
    for day in range(days):
        sessions = []
        remaining = minutes
        while remaining:
            topic = max(ranked, key=lambda t: t["priority"] / (1 + allocation[t["id"]] / 20))
            length = min(20, remaining)
            allocation[topic["id"]] += length
            sessions.append({"topic_id": topic["id"], "title": topic["title"], "minutes": length,
                             "task": "Review the cited material, recall it without notes, then answer a new diagnostic question.",
                             "reason": "Initial assessment needed" if topic["score"] is None else
                                 f"{topic['score']}% recent accuracy; {topic['exam_matches']} matching past-paper chunks."})
            remaining -= length
        scheduled.append({"day": day + 1, "date": (datetime.now(ZoneInfo("Asia/Kolkata")).date() + timedelta(days=day)).isoformat(),
                          "minutes": minutes, "sessions": sessions})
    return scheduled
