"""inbox_questions.py — Pending-questions inbox endpoints for hermes-webui.

Adds GET /inbox/questions       (HTML page)
     GET /api/inbox/questions   (JSON list)
     POST /api/inbox/questions/answer (record an answer)

Reads/writes the `pending_questions` table in the Starrco kanban.db (the
global kanban.db at /home/hermes/.hermes/kanban.db). The schema is owned
by /home/hermes/.hermes/lib/pending_questions.py.

Open on the Tailnet -- no auth gate per operator decision (tailnet-only).
Anchored: SOUL.md "Pending questions inbox" + Track B 2026-05-14.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# Ensure the shared library is importable regardless of how the webui was launched.
_LIB_DIR = "/home/hermes/.hermes/lib"
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

try:
    import pending_questions as pq  # type: ignore
except ImportError:  # graceful: endpoints will 503 if the lib is missing
    pq = None  # type: ignore

_log = logging.getLogger(__name__)

# Default DB path; overridable via HERMES_PENDING_QUESTIONS_DB env var for tests.
import os
DEFAULT_DB = os.environ.get(
    "HERMES_PENDING_QUESTIONS_DB",
    "/home/hermes/.hermes/kanban.db",
)


def _send_json(handler, status: int, payload: dict) -> bool:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        pass
    return True


def _send_html(handler, status: int, html: str) -> bool:
    body = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        pass
    return True


def _db_path() -> str:
    return DEFAULT_DB


def _lib_or_503(handler) -> bool:
    if pq is None:
        return _send_json(handler, 503, {"error": "pending_questions library not available"})
    try:
        pq.ensure_schema(_db_path())
    except Exception as e:  # noqa: BLE001
        _log.warning("inbox_questions: ensure_schema failed: %s", e)
        return _send_json(handler, 503, {"error": f"db unavailable: {e}"})
    return False


# ── Public entry points called from api/routes.py ──────────────────────────


def handle_get(handler, parsed) -> bool:
    """Returns True if the request was handled."""
    if parsed.path == "/inbox/questions":
        return _serve_page(handler)
    if parsed.path == "/api/inbox/questions":
        return _serve_list_json(handler)
    if parsed.path == "/api/inbox/questions/count":
        return _serve_count_json(handler)
    return False


def handle_post(handler, parsed) -> bool:
    if parsed.path == "/api/inbox/questions/answer":
        return _handle_answer(handler)
    return False


# ── Handlers ───────────────────────────────────────────────────────────────


def _serve_list_json(handler) -> bool:
    if _lib_or_503(handler):
        return True
    by_task = pq.list_by_task(_db_path())
    total = sum(len(t["questions"]) for t in by_task)
    return _send_json(handler, 200, {"questions": by_task, "total": total})


def _serve_count_json(handler) -> bool:
    if _lib_or_503(handler):
        return True
    n = pq.count_pending(_db_path())
    return _send_json(handler, 200, {"count": n})


def _handle_answer(handler) -> bool:
    if _lib_or_503(handler):
        return True
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0 or length > 65536:
        return _send_json(handler, 400, {"error": "missing or oversized body"})
    raw = handler.rfile.read(length)
    try:
        body = json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return _send_json(handler, 400, {"error": f"invalid json: {e}"})

    qid = body.get("question_id")
    choice_idx = body.get("choice_idx")
    custom = body.get("custom_text")
    if not qid:
        return _send_json(handler, 400, {"error": "question_id required"})
    if choice_idx is None and not custom:
        return _send_json(handler, 400, {"error": "provide choice_idx or custom_text"})

    try:
        result = pq.answer(
            _db_path(),
            qid,
            choice_idx=int(choice_idx) if choice_idx is not None else None,
            custom_text=str(custom) if custom else None,
        )
    except ValueError as e:
        return _send_json(handler, 400, {"error": str(e)})
    except Exception as e:  # noqa: BLE001
        _log.exception("inbox_questions: answer failed")
        return _send_json(handler, 500, {"error": str(e)})

    return _send_json(handler, 200, {"ok": True, "result": result})


# ── HTML page (zero-dependency, vanilla JS, server-rendered shell) ─────────


_PAGE_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pending Questions — Hermes</title>
<style>
  :root { color-scheme: dark; }
  body { font: 14px/1.5 ui-sans-serif,system-ui,-apple-system,Inter,sans-serif;
         background:#0d1117; color:#c9d1d9; margin:0; padding:24px; }
  h1 { font-size: 20px; margin: 0 0 8px; }
  .muted { color:#8b949e; font-size: 12px; }
  .task { background:#161b22; border:1px solid #30363d; border-radius:8px;
          padding:16px; margin: 16px 0; }
  .task-title { font-weight: 600; margin-bottom: 4px; font-size: 15px; }
  .task-id { font-family: ui-monospace,monospace; color:#8b949e; font-size: 11px; }
  .question { margin: 14px 0; padding: 12px; background:#0d1117;
              border:1px solid #21262d; border-radius:6px; }
  .question-text { font-weight:500; margin-bottom: 10px; }
  .choice { display:block; margin: 4px 0; cursor:pointer; }
  .choice input { margin-right: 8px; }
  .recommended { color:#58a6ff; font-weight: 600; }
  .badge { display:inline-block; padding:1px 6px; font-size:10px;
           border-radius:10px; background:#1f6feb; color:white;
           margin-left:6px; vertical-align: middle; }
  textarea { width: 100%; min-height: 50px; background:#0d1117;
             color:#c9d1d9; border:1px solid #30363d; border-radius:4px;
             padding:6px; font: inherit; box-sizing: border-box; }
  button { background:#238636; color:white; border:none; padding:8px 16px;
           border-radius:6px; cursor:pointer; font-weight:600; margin-top: 8px; }
  button:disabled { background:#30363d; cursor: not-allowed; }
  button:hover:not(:disabled) { background:#2ea043; }
  .empty { text-align:center; padding: 48px; color:#8b949e; }
  .toast { position: fixed; bottom: 20px; right: 20px; background:#238636;
           color:white; padding:12px 20px; border-radius:6px;
           box-shadow: 0 4px 12px rgba(0,0,0,.4); }
  .toast.error { background:#da3633; }
  .toast.fade { opacity: 0; transition: opacity .5s; }
</style></head>
<body>
<h1>Pending Questions</h1>
<div class="muted" id="summary">Loading...</div>
<div id="root"></div>

<script>
const root = document.getElementById('root');
const summary = document.getElementById('summary');

function escapeHTML(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

function toast(msg, isErr) {
  const t = document.createElement('div');
  t.className = 'toast' + (isErr ? ' error' : '');
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => { t.classList.add('fade'); setTimeout(() => t.remove(), 500); }, 2500);
}

async function load() {
  const r = await fetch('/api/inbox/questions');
  if (!r.ok) { root.innerHTML = '<div class="empty">Failed to load.</div>'; return; }
  const data = await r.json();
  const total = data.total || 0;
  summary.textContent = total === 0
    ? 'No pending questions. All caught up.'
    : `${total} pending question${total === 1 ? '' : 's'} across ${data.questions.length} task${data.questions.length === 1 ? '' : 's'}.`;
  if (total === 0) {
    root.innerHTML = '<div class="empty">Nothing waiting on you right now.</div>';
    return;
  }
  root.innerHTML = data.questions.map(task => `
    <div class="task" data-task-id="${escapeHTML(task.task_id)}">
      <div class="task-title">${escapeHTML(task.task_title)}</div>
      <div class="task-id">${escapeHTML(task.task_id)}</div>
      ${task.questions.map(q => questionHTML(q)).join('')}
    </div>
  `).join('');
  document.querySelectorAll('button[data-action="submit"]').forEach(b => {
    b.addEventListener('click', onSubmit);
  });
}

function questionHTML(q) {
  const choices = q.choices.map((choice, i) => {
    const isRec = i === q.recommended_idx;
    const checked = isRec ? 'checked' : '';
    return `<label class="choice ${isRec ? 'recommended' : ''}">
      <input type="radio" name="q-${q.id}" value="${i}" ${checked}>
      ${escapeHTML(choice)}${isRec ? '<span class="badge">recommended</span>' : ''}
    </label>`;
  }).join('');
  return `
    <div class="question" data-qid="${escapeHTML(q.id)}">
      <div class="question-text">${escapeHTML(q.question_text)}</div>
      ${choices}
      <label class="choice"><input type="radio" name="q-${q.id}" value="__custom__">
        <em>Other (write-in):</em></label>
      <textarea data-custom-for="${escapeHTML(q.id)}" placeholder="Type a different answer..."></textarea>
      <button data-action="submit" data-qid="${escapeHTML(q.id)}">Submit answer</button>
    </div>
  `;
}

async function onSubmit(ev) {
  const btn = ev.currentTarget;
  const qid = btn.dataset.qid;
  const radio = document.querySelector(`input[name="q-${qid}"]:checked`);
  if (!radio) { toast('Pick a choice first.', true); return; }
  let payload = { question_id: qid };
  if (radio.value === '__custom__') {
    const ta = document.querySelector(`textarea[data-custom-for="${qid}"]`);
    const text = (ta?.value || '').trim();
    if (!text) { toast('Custom answer is empty.', true); return; }
    payload.custom_text = text;
  } else {
    payload.choice_idx = parseInt(radio.value, 10);
  }
  btn.disabled = true;
  btn.textContent = 'Submitting...';
  try {
    const r = await fetch('/api/inbox/questions/answer', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await r.json();
    if (!r.ok) { throw new Error(data.error || 'submit failed'); }
    if (data.result?.unblocked) {
      toast('Answered. Task unblocked.');
    } else if ((data.result?.remaining_for_task ?? 0) > 0) {
      toast(`Answered. ${data.result.remaining_for_task} more for this task.`);
    } else {
      toast('Answered.');
    }
    setTimeout(load, 500);
  } catch (e) {
    toast(e.message, true);
    btn.disabled = false;
    btn.textContent = 'Submit answer';
  }
}

load();
setInterval(load, 30000);
</script>
</body></html>
"""


def _serve_page(handler) -> bool:
    return _send_html(handler, 200, _PAGE_HTML)
