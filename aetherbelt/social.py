"""aetherbelt.social - approval-gated X (Twitter) compose + queue.

DESIGN (Steward: consent + accountability, mirrors the money rule):
  - The agent COMPOSES and QUEUES. It never posts on its own.
  - Posting requires (a) X credentials in the environment (owner-provided) AND
    (b) an explicit `aetherbelt send --id N` from the owner.
  - Without credentials, `send` hard-refuses. No silent network calls.
  - Every draft + send attempt is emitted to AETHERBUS for observability.

Why: an autonomous social poster violates consent (things leave the machine
without a human flip) and risks inauthentic AI spam. The queue makes the agent
a proposer; the owner is the executor. Same shape as coinmoth's caps.

Commands (wired in cli.py):
  aetherbelt share <file.md> [--thread]   draft a post from a note -> outbox
  aetherbelt outbox [--n 10]              preview queued drafts
  aetherbelt send --id N                  POST draft N (owner flip; needs creds)
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
OUTBOX = os.path.join(HOME, "aetherbelt_outbox.jsonl")
X_POST_URL = "https://api.twitter.com/2/tweets"

# --- AETHERBUS (silent fallback) ---
try:
    sys.path.insert(0, os.path.join(HOME, "aetherbus"))
    from aetherbus import emit as bus_emit
except Exception:  # noqa: BLE001
    def bus_emit(*_a, **_k):
        return False

X_CHAR_LIMIT = 280


def _strip_md(text):
    """Flatten markdown to plain text for a social post (no syntax leaks)."""
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"`(.*?)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # links -> label
    text = re.sub(r"https?://\S+", "", text)  # strip raw urls (count against limit)
    return text.strip()


def compose(note_path, as_thread=False):
    """Read a note, produce a draft post (or thread) within char limits."""
    with open(note_path, encoding="utf-8") as fh:
        raw = fh.read()
    # drop YAML frontmatter
    body = re.sub(r"^---\n.*?\n---\n", "", raw, flags=re.S)
    plain = _strip_md(body)
    # prefer a "POST" variant if it exists alongside
    post_path = note_path[:-len(".POST.md")] + ".POST.md" if note_path.endswith(".POST.md") else note_path[:-3] + ".POST.md"
    if os.path.exists(post_path):
        with open(post_path, encoding="utf-8") as fh:
            plain = _strip_md(re.sub(r"^---\n.*?\n---\n", "", fh.read(), flags=re.S))
    if as_thread:
        # split into <=280 chunks on paragraph boundaries
        paras = [p for p in plain.split("\n\n") if p.strip()]
        chunks, cur = [], ""
        for p in paras:
            if len(cur) + len(p) + 2 <= X_CHAR_LIMIT:
                cur = (cur + "\n\n" + p).strip()
            else:
                if cur:
                    chunks.append(cur)
                # paragraph itself too long -> split by sentence, then by hard cut
                if len(p) <= X_CHAR_LIMIT:
                    cur = p
                else:
                    cur = ""
                    for sent in re.split(r"(?<=[.!?])\s+", p):
                        if len(cur) + len(sent) + 1 <= X_CHAR_LIMIT:
                            cur = (cur + " " + sent).strip()
                        else:
                            if cur:
                                chunks.append(cur)
                            # sentence longer than limit -> hard truncate with ellipsis
                            if len(sent) > X_CHAR_LIMIT:
                                chunks.append(sent[: X_CHAR_LIMIT - 1].rstrip() + "…")
                                cur = ""
                            else:
                                cur = sent
        if cur:
            chunks.append(cur)
        return chunks[:10]
    # single post: truncate with ellipsis if over limit
    if len(plain) > X_CHAR_LIMIT:
        plain = plain[: X_CHAR_LIMIT - 1].rstrip() + "…"
    return [plain]


def queue_draft(note_path, as_thread=False):
    parts = compose(note_path, as_thread)
    draft = {
        "id": None,
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": note_path,
        "thread": as_thread,
        "parts": parts,
        "status": "drafted",
    }
    os.makedirs(os.path.dirname(OUTBOX), exist_ok=True)
    # assign next id
    n = 0
    if os.path.exists(OUTBOX):
        with open(OUTBOX, encoding="utf-8") as fh:
            for line in fh:
                try:
                    n = max(n, int(json.loads(line).get("id", 0)))
                except Exception:
                    pass
    draft["id"] = n + 1
    with open(OUTBOX, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(draft, ensure_ascii=False) + "\n")
    bus_emit("aetherbelt", "social-draft",
             f"drafted {'thread' if as_thread else 'post'} from {os.path.basename(note_path)} "
             f"({len(parts)} part(s))",
             level="info", data={"id": draft["id"], "parts": len(parts)})
    return draft


def list_outbox(n=10):
    if not os.path.exists(OUTBOX):
        return []
    out = []
    with open(OUTBOX, encoding="utf-8") as fh:
        for line in fh:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out[-n:]


def send_draft(draft_id):
    """Owner flip. Requires X_BEARER_TOKEN in env. Hard-refuses without it."""
    token = os.environ.get("X_BEARER_TOKEN") or os.environ.get("X_API_KEY")
    if not token:
        bus_emit("aetherbelt", "social-send", f"REFUSED id {draft_id}: no X credentials in env",
                 level="alert", data={"id": draft_id})
        return (1, "REFUSED: no X_BEARER_TOKEN / X_API_KEY in environment. "
                   "Owner must provide credentials, then re-run `aetherbelt send --id %d`." % draft_id)
    drafts = list_outbox(1000)
    match = next((d for d in drafts if d.get("id") == draft_id), None)
    if not match:
        return (2, f"no drafted post with id {draft_id}")
    posted = 0
    for part in match["parts"]:
        try:
            req = urllib.request.Request(
                X_POST_URL,
                data=json.dumps({"text": part}).encode(),
                headers={"Authorization": f"Bearer {token}",
                          "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                ok = r.status == 201
            if ok:
                posted += 1
        except Exception as e:  # noqa: BLE001
            bus_emit("aetherbelt", "social-send", f"ERROR id {draft_id}: {e}",
                     level="alert", data={"id": draft_id})
            return (1, f"post error: {e}")
    bus_emit("aetherbelt", "social-send", f"POSTED id {draft_id} ({posted} part(s))",
             level="info", data={"id": draft_id, "posted": posted})
    # mark sent
    _mark_sent(draft_id)
    return (0, f"posted {posted}/{len(match['parts'])} part(s) for draft {draft_id}")


def _mark_sent(draft_id):
    if not os.path.exists(OUTBOX):
        return
    out = []
    with open(OUTBOX, encoding="utf-8") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                out.append(line)
                continue
            if d.get("id") == draft_id:
                d["status"] = "sent"
            out.append(json.dumps(d, ensure_ascii=False) + "\n")
    with open(OUTBOX, "w", encoding="utf-8") as fh:
        fh.writelines(out)
