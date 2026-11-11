"use strict";

const root = document.getElementById("root");
const state = { config: null, data: null, view: "overview", quiz: null, step: 0, answers: [], authMode: "login", explanation: null, busy: false };
const paths = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  book: '<path d="M3 4h6a4 4 0 0 1 3 2 4 4 0 0 1 3-2h6v15h-6a4 4 0 0 0-3 2 4 4 0 0 0-3-2H3z"/><path d="M12 6v15"/>',
  spark: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/>',
  chart: '<path d="M4 3v17h17M8 15v-4M13 15V7M18 15v-7"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 11h18M8 15h2M14 15h2"/>',
  chat: '<path d="M21 11a8 8 0 0 1-8 8H7l-5 3 2-6a8 8 0 0 1-1-5 9 9 0 0 1 18 0Z"/><path d="M7 11h10M7 7h6"/>',
  arrow: '<path d="M4 12h15m-6-6 6 6-6 6"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  file: '<path d="M14 2H5v20h14V7zM14 2v6h5M8 12h8M8 16h6"/>',
  out: '<path d="M9 5H4v14h5M11 12h10m-4-4 4 4-4 4"/>',
  link: '<path d="m9 15 6-6M7 17l-1 1a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0M17 7l1-1a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0" transform="translate(1 0) scale(.9)"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6"/>'
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.spark}</svg>`;
const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
const pct = value => value == null ? "—" : `${value}%`;
const label = key => ({ syllabus: "Syllabus", notes: "Study notes", past_paper: "Past paper" }[key] || key);
const views = [["overview", "Overview", "grid"], ["materials", "My materials", "book"], ["quiz", "Diagnostic", "target"], ["gaps", "Knowledge gaps", "chart"], ["plan", "Revision plan", "calendar"], ["assistant", "Topic assistant", "chat"]];
let toastTimer;

function toast(message, error = false) {
  const box = document.getElementById("toast");
  box.textContent = message; box.hidden = false; box.className = error ? "error" : "";
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { box.hidden = true; }, error ? 10000 : 4500);
}

async function api(path, options = {}) {
  const headers = options.body instanceof FormData ? {} : { "Content-Type": "application/json" };
  const response = await fetch(`/api${path}`, { credentials: "same-origin", ...options, headers: { ...headers, ...options.headers } });
  let data;
  try { data = await response.json(); } catch { throw new Error("The server returned an unreadable response. Please retry."); }
  if (!response.ok) {
    if (response.status === 401 && path !== "/login") { state.data = null; renderAuth(); }
    throw new Error(typeof data.detail === "string" ? data.detail : "Check the form values and try again.");
  }
  return data;
}

async function refresh() { state.data = await api("/dashboard"); }

function source(c, index = null) {
  return `<details class="source"><summary>${icon("link")}${index == null ? "View source" : `Source ${index}`} · ${esc(c.filename)} · p. ${c.page} · ${esc(c.section)}</summary><blockquote>${esc(c.quote)}</blockquote></details>`;
}

function badge(topic) { return `<span class="pill ${topic.status}">${topic.status === "untested" ? "Not tested" : topic.status}</span>`; }

function topicRows(topics, detailed = false) {
  if (!topics.length) return empty("Your topic map starts here", "Upload a syllabus to create your study map.", "materials", "Upload syllabus");
  return `<div class="topics">${topics.map(t => `<div class="topic-row"><div><div class="topic-title">${esc(t.title)}</div><div class="topic-reason">${esc(t.reason)}${detailed ? `<br>${esc(t.confidence)} · ${t.exam_matches} past-paper chunk matches` : ""}</div></div>${badge(t)}<div class="score">${pct(t.score)}<progress max="100" value="${t.score ?? 0}" aria-label="${esc(t.title)} recent accuracy"></progress></div></div>`).join("")}</div>`;
}

function empty(title, text, view = null, action = null) {
  return `<div class="empty">${icon("book")}<strong>${esc(title)}</strong>${esc(text)}${view ? `<br><button class="btn secondary" data-view="${view}">${esc(action)}</button>` : ""}</div>`;
}

function renderAuth() {
  const signup = state.authMode === "register";
  root.innerHTML = `<div class="auth"><section class="auth-story"><a href="/" class="brand"><span class="brand-mark">g</span>gapfinder<span aria-hidden="true">.</span></a><h1>Know your gaps.<br><em>Own your progress.</em></h1><p>Your material. Your weak spots. A revision plan that knows where you need to go next.</p><div class="auth-steps">01 &nbsp; Bring your study material<br>02 &nbsp; Find what needs attention<br>03 &nbsp; Make every study session count</div></section><main class="auth-form" id="main"><div class="auth-inner"><div class="eyebrow">A clearer way to study</div><h2>${signup ? "Make room for progress." : "Welcome to your study space."}</h2><p class="subtitle">${signup ? "Create an account to save your quizzes and revision plan." : "Pick up where you left off, one topic at a time."}</p><form id="auth-form">${signup ? '<label class="field">Your name<input name="name" autocomplete="name" required maxlength="80" placeholder="Alex Morgan"></label>' : ""}<label class="field">Email address<input type="email" name="email" autocomplete="username" required placeholder="you@example.com"></label><label class="field">Password<input type="password" name="password" autocomplete="${signup ? "new-password" : "current-password"}" minlength="8" maxlength="128" required placeholder="At least 8 characters"></label><p class="error-message" id="auth-error" role="alert" hidden></p><button class="btn" type="submit">${signup ? "Create account" : "Log in"} ${icon("arrow")}</button></form><div class="auth-switch">${signup ? "Already have an account?" : "New here?"}<button class="btn text" data-action="toggle-auth">${signup ? "Log in" : "Create an account"}</button></div>${state.config?.mode === "demo" ? `<div class="auth-demo"><button class="btn secondary" data-action="demo">Explore the biology demo ${icon("arrow")}</button><p>Local demo with sample biology material.<br>Deterministic quizzes · no AI API calls<br>${esc(state.config.demo_email)} / ${esc(state.config.demo_password)}</p></div>` : ""}</div></main></div>`;
}

function render() {
  if (!state.data) return renderAuth();
  const { user } = state.data;
  const view = views.find(v => v[0] === state.view) || views[0];
  root.innerHTML = `<div class="shell"><aside class="sidebar"><a class="brand" href="#overview"><span class="brand-mark">g</span>gapfinder.</a><p class="brand-sub">Study with direction</p><div class="nav-label">YOUR WORKSPACE</div><nav class="nav" aria-label="Main navigation">${views.map(([id, title, name]) => `<button data-view="${id}" class="${id === state.view ? "active" : ""}" ${id === state.view ? 'aria-current="page"' : ""}>${icon(name)}${title}</button>`).join("")}</nav><div class="sidebar-foot"><div class="tiny-note"><strong>A little better, every day.</strong>Focus on the gaps. Let the progress follow.</div><div class="profile"><div class="avatar">${esc(user.name.charAt(0).toUpperCase())}</div><div><div class="profile-name">${esc(user.name)}</div><div class="profile-sub">Personal study space</div></div><button class="logout" data-action="logout" aria-label="Log out">${icon("out")}</button></div></div></aside><div class="workspace"><header class="topbar"><div class="topbar-left"><span class="mobile-brand">gapfinder.</span><strong>My workspace</strong><span>/</span>${view[1]}</div><div class="mode">${state.config.mode === "demo" ? "Offline demo · lexical retrieval" : "Live · Groq + semantic retrieval"}</div><button class="logout mobile-brand" data-action="logout" aria-label="Log out">${icon("out")}</button></header><main class="main" id="main">${renderView()}</main></div></div>`;
}

function heading(eyebrow, title, subtitle, action = "") {
  return `<div class="heading-row"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p class="subtitle">${subtitle}</p></div>${action}</div>`;
}

function renderView() {
  if (state.view === "materials") return materials();
  if (state.view === "quiz") return diagnostic();
  if (state.view === "gaps") return gaps();
  if (state.view === "plan") return plan();
  if (state.view === "assistant") return assistant();
  return overview();
}

function overview() {
  const { user, topics, history, plan, documents } = state.data;
  const measured = topics.filter(t => t.score != null);
  const average = measured.length ? Math.round(measured.reduce((sum, t) => sum + t.score, 0) / measured.length) : null;
  const weak = topics.filter(t => t.status === "weak");
  const date = new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "Asia/Kolkata" }).format(new Date());
  const priorities = [...topics].sort((a,b) => b.priority - a.priority);
  return `${heading("Your learning, in focus", `Let's make progress, ${esc(user.name.split(" ")[0])}.`, "A clearer picture of what you know. A smarter plan for what comes next.", `<div class="date-label">${date}</div>`)}
  <section class="hero"><div><div class="eyebrow">${history.length ? "Your next small step" : "Start with a little clarity"}</div><h2>${history.length ? "Less guesswork.<br>More meaningful revision." : "Find your gaps.<br>Make your time count."}</h2><p>${history.length ? "Your latest answers shape your priorities. Take another diagnostic to see what’s changing." : "A short diagnostic turns your study material into a clear picture of where to focus."}</p><button class="btn" data-action="start-quiz">${state.data.active_quiz ? "Resume diagnostic" : history.length ? "Take another diagnostic" : "Take my first diagnostic"} ${icon("arrow")}</button></div><div class="hero-art" aria-hidden="true"><div class="orb"><div class="orb-core">${icon("target")}</div></div></div></section>
  <section class="stats" aria-label="Study summary">${stat("Topics mapped", topics.length, `${documents.length} uploaded materials`, "book")}${stat("Recent topic accuracy", pct(average), `${measured.length} of ${topics.length} topics assessed`, "chart")}${stat("Topics needing work", weak.length, topics.length - measured.length ? `${topics.length - measured.length} topics still untested` : "Based on your recent answers", "target")}${stat("Daily study time", `${user.minutes}<small>min</small>`, `${user.days}-day revision horizon`, "clock")}</section>
  <div class="two-col"><section class="card"><div class="card-heading"><div><h2>Your topic health</h2><p>Evidence from your latest diagnostic answers</p></div><button class="btn text" data-view="gaps">View all ${icon("arrow")}</button></div>${topicRows(priorities.slice(0, 6))}<div class="footnote">${history.length ? "Scores use your last eight answers per topic. Small samples need more testing." : "Untested topics stay untested until you answer questions. Take a diagnostic to establish your baseline."}</div></section><section class="card"><div class="card-heading"><div><h2>Your next study session</h2><p>A little structure for your study time</p></div>${icon("calendar")}</div>${plan.length ? `<div class="study-note">${icon("clock")}<div><h3>${user.minutes} minutes, with purpose</h3><p>Day 1 of your ${user.days}-day plan</p></div></div>${miniSessions(plan[0].sessions.slice(0,3))}<div class="card-bottom"><button class="btn secondary small" data-view="plan">Open revision plan ${icon("arrow")}</button></div>` : empty("Build your first plan", "Upload your syllabus to get started.")}</section></div>
  <section class="card pad spacer-top"><div class="eyebrow">How your progress happens</div><div class="pipeline"><div class="pipeline-step"><strong>01 &nbsp; Bring your material</strong><span>Syllabus, notes, and past papers.</span></div><div class="pipeline-step"><strong>02 &nbsp; Check your understanding</strong><span>Questions grounded in your notes.</span></div><div class="pipeline-step"><strong>03 &nbsp; Find your focus</strong><span>Topic-level gaps with clear evidence.</span></div><div class="pipeline-step"><strong>04 &nbsp; Revise. Retest. Repeat.</strong><span>A plan that follows your progress.</span></div></div></section>`;
}

function stat(title, number, caption, name) { return `<article class="stat"><div class="stat-top">${title}${icon(name)}</div><div class="stat-number">${number}</div><div class="stat-caption">${caption}</div></article>`; }

function miniSessions(sessions) {
  return sessions.map((s, i) => `<div class="mini-session"><div class="session-number">${String(i + 1).padStart(2, "0")}</div><div class="session-body"><strong>${esc(s.title)}</strong><p>${esc(s.task)}</p></div><div class="session-time">${s.minutes} min</div></div>`).join("");
}

function materials() {
  const docs = state.data.documents;
  return `${heading("Your sources of understanding", "Good material. Better direction.", "Start with your syllabus, then add the material you want to learn from.")}
    <div class="two-col"><section class="card pad"><h2 class="section-title">Add study material</h2><p class="subtitle">PDF, TXT, or Markdown · up to 5 MB · text-based PDFs only</p><form id="upload-form"><div class="field spacer-top"><label for="material-kind">Material type</label><select id="material-kind" name="kind"><option value="syllabus">Syllabus — one topic per line</option><option value="notes" ${docs.length ? "selected" : ""}>Study notes / textbook chapter</option><option value="past_paper">Past exam paper</option></select><small>Syllabi add topics. Past papers help estimate exam relevance. Questions draw their evidence from study notes.</small></div><div class="upload-box"><label class="field" for="material-file">Choose a file<input id="material-file" type="file" name="file" accept=".pdf,.txt,.md" required></label></div><button class="btn" type="submit">${icon("upload")} Upload and map material</button></form></section><section class="card"><div class="card-heading"><div><h2>Your library</h2><p>${docs.length} material${docs.length === 1 ? "" : "s"} in your study space</p></div>${icon("book")}</div>${docs.length ? docs.map(d => `<div class="file-row"><div class="file-icon">${icon("file")}</div><div class="file-info"><strong>${esc(d.filename)}</strong><p>${label(d.kind)} · ${d.kind === "syllabus" ? "Topic map source" : `${d.chunks} indexed chunks`}</p></div><span class="pill strong">Ready</span></div>`).join("") : empty("Your library is empty", "Add a syllabus, then upload your notes.")}</section></div>
    <section class="card spacer-top"><div class="card-heading"><div><h2>Your syllabus map</h2><p>${state.data.topics.length} topics · material is mapped using the configured retrieval embeddings</p></div></div>${topicRows(state.data.topics)}<div class="footnote">New syllabus uploads add topics to your existing map. Topic matching is automatic and should be reviewed for ambiguous material.</div></section>`;
}

function diagnostic() {
  const quiz = state.quiz;
  if (quiz?.submitted) return quizResults(quiz);
  if (!quiz) return `${heading("A check-in, not a final exam", "Find out where you stand.", "A short quiz gives your revision plan a better starting point.")}<section class="card pad quiz-wrap"><div class="eyebrow">Your diagnostic</div><h2 class="section-title">Six questions. A clearer picture.</h2><p class="subtitle">Questions are selected across topics with available notes, prioritizing your current gaps. Every question includes a source reference.</p><div class="notice spacer-top">${state.config.mode === "demo" ? "Offline demo uses source-based fill-in-the-blank questions to test factual recall. Live mode uses Groq to generate diagnostic questions." : "Live questions are generated from retrieved material. Source references are validated, but generated questions can still need review."}</div><button class="btn" data-action="start-quiz">${state.data.active_quiz ? "Resume diagnostic" : "Start diagnostic"} ${icon("arrow")}</button></section>`;
  const q = quiz.questions[state.step];
  const topic = state.data.topics.find(t => t.id === q.topic_id);
  return `${heading("One question at a time", "Give your understanding a check-in.", "Answer from memory first. The source is there when you need it.")}<div class="quiz-wrap"><div class="quiz-progress"><span>Question ${state.step + 1} of ${quiz.questions.length}</span><progress max="${quiz.questions.length}" value="${state.answers.filter(x => x != null).length}" aria-label="Questions answered"></progress><span>${state.answers.filter(x => x != null).length} answered</span></div><section class="card quiz-card"><span class="pill">${esc(topic?.title || "Diagnostic")}</span><h2>${esc(q.question)}</h2><div class="options" role="group" aria-label="Answer options">${q.options.map((option,i) => `<button class="option ${state.answers[state.step] === i ? "selected" : ""}" aria-pressed="${state.answers[state.step] === i}" data-answer="${i}"><span class="option-letter">${"ABCD"[i]}</span>${esc(option)}</button>`).join("")}</div>${source(q.citation)}<div class="quiz-footer"><button class="btn secondary" data-action="previous" ${state.step === 0 ? "disabled" : ""}>Back</button>${state.step < quiz.questions.length - 1 ? '<button class="btn" data-action="next">Next question ' + icon("arrow") + '</button>' : '<button class="btn" data-action="submit-quiz">Finish diagnostic ' + icon("check") + '</button>'}</div></section><p class="subtitle">Your quiz is saved. Answers are saved when you finish the diagnostic.</p></div>`;
}

function quizResults(quiz) {
  const correct = quiz.results.filter(r => r.correct).length;
  return `${heading("A starting point for your next step", "Here's what your answers tell us.", "Use the feedback to understand each gap, then revisit your plan.", '<button class="btn secondary" data-action="new-quiz">New diagnostic</button>')}<div class="quiz-wrap"><div class="result-hero"><div class="eyebrow">Diagnostic complete</div><div class="result-score">${Math.round(100 * correct / quiz.results.length)}%</div><p>${correct} of ${quiz.results.length} answers correct. Your topic report and revision plan are updated.</p><div class="question-chips"><button data-view="gaps">See knowledge gaps →</button><button data-view="plan">Open updated plan →</button></div></div><section class="card">${quiz.questions.map((q,i) => `<article class="result-item"><span class="${quiz.results[i].correct ? "result-correct" : "result-wrong"}">${quiz.results[i].correct ? "✓ Correct" : "↗ Needs another look"} · Question ${i + 1}</span><h3>${esc(q.question)}</h3><p>Your answer: ${esc(q.options[quiz.answers[i]])}<br>Correct answer: <strong>${esc(q.options[q.correct_index])}</strong></p><p class="spacer-top">${esc(q.explanation)}</p>${source(q.citation)}</article>`).join("")}</section></div>`;
}

function gaps() {
  const { topics, history } = state.data;
  return `${heading("Find the gaps you didn't know to ask about", "Your understanding, topic by topic.", "A diagnosis backed by your answers, with space for uncertainty.", '<button class="btn" data-action="start-quiz">Retest my knowledge ' + icon("arrow") + '</button>')}<section class="card section-gap"><div class="card-heading"><div><h2>Knowledge gap report</h2><p>Weak: below 50% · Medium: 50–79% · Strong: 80% and above</p></div></div>${topicRows([...topics].sort((a,b) => b.priority - a.priority), true)}<div class="footnote">Accuracy uses the latest eight answers per topic. “Strong” is a provisional signal, especially with fewer than three answers. Exam relevance counts matching past-paper chunks, not verified marks or question frequency.</div></section><section class="card"><div class="card-heading"><div><h2>Progress across attempts</h2><p>Your overall quiz accuracy; topic-level accuracy is listed below each attempt.</p></div></div>${history.length ? history.map((h,i) => `<div class="history-row"><div class="history-label">Attempt ${i + 1}<div class="topic-reason">${new Date(h.date).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}</div></div><progress value="${h.score}" max="100" aria-label="Attempt ${i+1} accuracy"></progress><strong>${h.score}%</strong><button class="btn text small" data-quiz-id="${h.id}">Review</button></div><div class="footnote">${Object.entries(h.topics).map(([id, score]) => `${esc(topics.find(t => t.id === id)?.title || "Topic")}: ${score}%`).join(" · ")}</div>`).join("") : empty("Your progress starts with one attempt", "Complete a diagnostic to establish your baseline.", "quiz", "Open diagnostic")}</section>`;
}

function plan() {
  const { user, plan: days } = state.data;
  return `${heading("Your time, put to better use", "A plan that follows your progress.", "Study time goes first to weaker topics, adjusted for past-paper relevance.")}<section class="card pad section-gap"><form id="preferences-form" class="preference-bar"><label class="field">Days available<input type="number" name="days" value="${user.days}" min="1" max="30" required></label><label class="field">Minutes per day<input type="number" name="minutes" value="${user.minutes}" min="10" max="240" required></label><button class="btn" type="submit">Update my plan ${icon("arrow")}</button></form></section><div class="notice">This rolling plan is recalculated after each diagnostic. Each day stays within your time budget. Untested topics receive assessment priority; time allocations are calculated in code.</div>${days.length ? days.map(day => `<section class="card day-card"><div class="day-heading"><div><h2>Day ${day.day}</h2><p>${new Date(day.date + "T12:00:00").toLocaleDateString("en-IN", { weekday:"long", day:"numeric", month:"short" })}</p></div><span class="pill strong">${day.minutes} min total</span></div>${day.sessions.map((s,i) => `<div class="mini-session"><div class="session-number">${String(i+1).padStart(2,"0")}</div><div class="session-body"><strong>${esc(s.title)}</strong><p>${esc(s.task)}</p><p>${esc(s.reason)}</p><button class="btn text small" data-explain-topic="${s.topic_id}">Open topic material ${icon("arrow")}</button></div><div class="session-time">${s.minutes} min</div></div>`).join("")}</section>`).join("") : empty("A syllabus gives your plan its structure", "Upload your syllabus and notes to get started.", "materials", "Add material")}`;
}

function assistant() {
  const answer = state.explanation;
  return `${heading("Understanding, grounded in your material", "Let's make that topic click.", "Ask about a concept. Every response starts by retrieving your uploaded notes.")}<div class="two-col"><section class="card pad"><form id="assistant-form"><label class="field">Focus topic<select name="topic_id"><option value="">All my topics</option>${state.data.topics.map(t => `<option value="${t.id}">${esc(t.title)}</option>`).join("")}</select></label><label class="field spacer-top">What would you like to understand?<textarea name="question" required minlength="3" maxlength="1000" placeholder="Explain the light-dependent reactions of photosynthesis."></textarea></label><button class="btn spacer-top" type="submit">Explain from my notes ${icon("arrow")}</button></form><div class="question-chips">${state.data.topics.slice(0,3).map(t => `<button data-explain-topic="${t.id}">${esc(t.title)}</button>`).join("")}</div><p class="subtitle">${state.config.mode === "demo" ? "Offline demo returns source excerpts. Enable live mode for AI explanations." : "Explanations are generated from retrieved notes. Review cited material when checking an answer."}</p></section><section class="card pad">${answer ? `<div class="eyebrow">From your study material</div><div class="assistant-answer">${esc(answer.answer)}</div>${answer.citations.map((c,i) => source(c, c.number || i+1)).join("")}` : empty("Your notes, made more accessible", "Choose a topic or ask a specific question to see supporting material.")}</section></div>`;
}

async function work(button, task, loading = "Working…") {
  if (state.busy) return;
  state.busy = true;
  const old = button?.innerHTML;
  if (button) { button.disabled = true; button.textContent = loading; }
  try { await task(); }
  catch (error) { toast(error.message, true); }
  finally { state.busy = false; if (button?.isConnected) { button.disabled = false; button.innerHTML = old; } }
}

async function startQuiz() {
  state.quiz = state.data.active_quiz ? await api(`/quizzes/${state.data.active_quiz}`) : await api("/quizzes", { method:"POST", body: JSON.stringify({count:6}) });
  state.data.active_quiz = state.quiz.id;
  state.answers = []; state.step = 0; state.view = "quiz"; render(); window.scrollTo(0,0);
}

root.addEventListener("click", async event => {
  const button = event.target.closest("button");
  if (!button || button.disabled) return;
  if (state.busy) return;
  if (button.dataset.view) { state.view = button.dataset.view; render(); window.scrollTo(0,0); return; }
  if (button.dataset.answer != null) { state.answers[state.step] = Number(button.dataset.answer); render(); return; }
  if (button.dataset.quizId) return work(button, async () => { state.quiz = await api(`/quizzes/${button.dataset.quizId}`); state.view = "quiz"; render(); window.scrollTo(0,0); }, "Opening…");
  if (button.dataset.explainTopic) {
    const topic = state.data.topics.find(t => t.id === button.dataset.explainTopic);
    return work(button, async () => { state.explanation = await api("/explain", {method:"POST",body:JSON.stringify({topic_id:topic.id,question:`Explain ${topic.title}`})}); state.view="assistant"; render(); window.scrollTo(0,0); }, "Retrieving…");
  }
  const action = button.dataset.action;
  if (action === "toggle-auth") { state.authMode = state.authMode === "login" ? "register" : "login"; renderAuth(); }
  else if (action === "demo") await work(button, async () => { await api("/login", {method:"POST",body:JSON.stringify({email:state.config.demo_email,password:state.config.demo_password})}); await refresh(); render(); }, "Opening your study space…");
  else if (action === "logout") await work(button, async () => { await api("/logout", {method:"POST"}); state.data=null; state.quiz=null; state.explanation=null; renderAuth(); });
  else if (action === "start-quiz" || action === "new-quiz") await work(button, startQuiz, "Preparing your questions…");
  else if (action === "previous") { state.step--; render(); }
  else if (action === "next") { if (state.answers[state.step] == null) return toast("Choose an answer before moving on.", true); state.step++; render(); }
  else if (action === "submit-quiz") await work(button, async () => {
    if (state.quiz.questions.some((_,i) => state.answers[i] == null)) throw new Error("Choose an answer for every question before finishing.");
    state.quiz = await api(`/quizzes/${state.quiz.id}/submit`, {method:"POST",body:JSON.stringify({answers:state.answers})});
    await refresh(); render(); window.scrollTo(0,0); toast("Diagnostic complete. Your gap report and plan are updated.");
  }, "Updating your diagnosis…");
});

root.addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.target;
  const data = new FormData(form);
  const button = form.querySelector('button[type="submit"]');
  if (form.id === "auth-form") {
    await work(button, async () => {
      try { await api(`/${state.authMode}`, {method:"POST",body:JSON.stringify(Object.fromEntries(data))}); await refresh(); render(); }
      catch(error) { const node=document.getElementById("auth-error"); node.textContent=error.message; node.hidden=false; }
    }, "Opening your study space…");
  } else if (form.id === "upload-form") {
    await work(button, async () => { await api("/materials", {method:"POST",body:data}); await refresh(); render(); toast("Material added and mapped to your topics."); }, "Reading and indexing…");
  } else if (form.id === "preferences-form") {
    await work(button, async () => { await api("/preferences", {method:"PUT",body:JSON.stringify({days:Number(data.get("days")),minutes:Number(data.get("minutes"))})}); await refresh(); render(); toast("Your revision plan is updated."); }, "Updating your plan…");
  } else if (form.id === "assistant-form") {
    await work(button, async () => { state.explanation = await api("/explain", {method:"POST",body:JSON.stringify({question:data.get("question"),topic_id:data.get("topic_id") || null})}); render(); }, "Retrieving your notes…");
  }
});

async function init() {
  try { state.config = await api("/config"); await refresh(); render(); }
  catch(error) { if (!state.config) root.innerHTML = `<main class="main" id="main"><h1>Could not reach your study space.</h1><p class="subtitle">${esc(error.message)}</p><p class="subtitle">Refresh this page once the backend is running.</p></main>`; else renderAuth(); }
}
init();
