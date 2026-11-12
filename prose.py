"""Answer supported prose questions without substituting nearby numeric facts."""
from __future__ import annotations

import math
import re
from datetime import datetime
from html import unescape
from urllib.parse import urlparse

from models import Answer, Source


STOP = set("what when where who is are was were the a an of for to from do does can could i you your our me my with and or in as at how much many please tell current now dupaco have has about get give know any it its be become".split())
MONTH_DATE = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+20\d{2}"


def _plain(text):
    text = re.sub(r"!\[[^\]]*\]\([^\n]*?\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return re.sub(r"\s+", " ", unescape(text).replace("**", "").replace("_", "")).strip(" #\n")


def _words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower())) - STOP


def _source(page, view, quote):
    return Source(page.url, view["sid"], quote)


def _decline(text=None, sources=None):
    return Answer(text or "I don't know from the supplied snapshots. Please contact the credit union to confirm.", sources or [], False)


def _historical(page):
    return bool(re.search(r"/(?:newsroom|blog|press)/|/20\d{2}/", page.url))


def _published(page, view):
    cache = view.setdefault("prose_publication_dates", {})
    if page.url not in cache:
        value = ""
        for line in page.markdown[:800].splitlines():
            candidate = line.strip()
            if re.fullmatch(MONTH_DATE, candidate):
                for fmt in ("%B %d, %Y", "%B %d %Y"):
                    try:
                        value = datetime.strptime(candidate, fmt).date().isoformat()
                        break
                    except ValueError:
                        pass
                if value:
                    break
        cache[page.url] = value
    return cache[page.url]


def _body(page):
    return re.split(r"\n#{1,4}\s+Handpicked for You", page.markdown, maxsplit=1, flags=re.I)[0]


def _paragraphs(page):
    return [p.strip() for p in re.split(r"\n\s*\n", _body(page)) if p.strip()]


def _pick(candidates):
    return sorted(candidates, key=lambda x: (-x[0], x[1].url, x[2]))[0] if candidates else None


def _routing(view):
    candidates = []
    for page, text, raw, tokens, heading in view["chunks"]:
        if not ({"routing", "aba"} & tokens):
            continue
        match = re.search(r"(?:routing(?:\s+number)?|ABA(?:\s+number)?)[^\d\n]{0,60}(\d{9})\b", text, re.I)
        if not match:
            continue
        path = urlparse(page.url).path.lower()
        rank = 100 if path.rstrip("/").endswith("contact") or "cash-management" in path else 50 if _historical(page) else 80
        candidates.append((rank, page, raw, match[1]))
    if not candidates:
        return _decline()
    rank = max(c[0] for c in candidates)
    best = [c for c in candidates if c[0] == rank]
    if len({c[3] for c in best}) > 1:
        return _decline("The official sources disagree on the routing number. Please contact the credit union to confirm.", [_source(c[1], view, c[2]) for c in best])
    chosen = sorted(best, key=lambda c: c[1].url)[0]
    return Answer("Routing number: " + chosen[3] + ".", [_source(chosen[1], view, chosen[2])])


def _closure(question, view):
    query = _words(question) - {"branch", "branches", "close", "closed", "closure", "open", "still", "today", "members", "full", "service", "banking", "go", "october"}
    candidates = []
    titles = view.get("title_tokens", {})
    for page in view["pages"].values():
        title = titles.get(page.url) or _words(page.title)
        if not ({"close", "closed", "closure"} & title):
            continue
        overlap = query & title
        if not overlap:
            continue
        candidates.append((len(overlap), _published(page, view), page))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (-c[0], c[1]), reverse=False)
    _, _, page = max(candidates, key=lambda c: (c[0], c[1], c[2].url))
    body = _body(page)
    if any(x in question for x in ("where", "full-service", "full service", "members go")):
        for raw in _paragraphs(page):
            text = _plain(raw)
            match = re.search(r"full[- ]service branches at\s+(.+?)(?:[,\u201d\"]|\.\s|$)", text, re.I)
            if match:
                return Answer("The notice directs members to the full-service branches at " + match[1].rstrip(".") + ".", [_source(page, view, raw)])
        return _decline()
    match = re.search(r"[^\n.!?]*(?:will close|scheduled to close|closing on|close on)\s+(" + MONTH_DATE + r")[^\n.!?]*[.!?]?", body, re.I)
    if match:
        return Answer("The published notice scheduled this branch to close " + match[1] + ".", [_source(page, view, match[0].strip())])
    return _decline()


def _address(question, view):
    match = re.search(r"(?:address of|address for|where is|where's)\s+(?:the\s+)?(.+?)(?:\s+branch|\?|$)", question)
    if not match:
        return None
    name = _words(match[1]) - {"address", "branch", "located"}
    if not name:
        return _decline("Please name the branch so I can identify its address.")
    candidates = []
    street = re.compile(r"\b\d{1,6}\s+[^\n]{3,130},\s*[A-Z]{2},?\s+\d{5}(?:-\d{4})?\b")
    for page in view["pages"].values():
        scope = (page.title + " " + urlparse(page.url).path).lower()
        if not any(x in scope for x in ("branch", "location", "contact")):
            continue
        for block in re.split(r"\n(?=#{2,4}\s)", _body(page)):
            if not name <= _words(block[:700]):
                continue
            if not re.search(r"\bbranch\b", block, re.I):
                continue
            for found in street.finditer(block[:1200]):
                raw = found[0]
                if name <= _words(raw) or name <= _words(block.split("\n", 1)[0]):
                    rank = 100 if not _historical(page) else 40
                    candidates.append((rank, page, raw))
    if not candidates:
        return _decline("I cannot confirm an address for that named branch in the selected snapshot.")
    rank = max(c[0] for c in candidates)
    best = [c for c in candidates if c[0] == rank]
    addresses = {c[2].lower().replace(".", "") for c in best}
    if len(addresses) > 1:
        return _decline("More than one branch address matches that name. Please specify the location.", [_source(c[1], view, c[2]) for c in best[:3]])
    chosen = _pick(best)
    return Answer(chosen[2] + ".", [_source(chosen[1], view, chosen[2])], chosen[0] >= 100)


def _forbes(view):
    candidates = []
    for page in view["pages"].values():
        if "forbes" not in page.title.lower():
            continue
        for raw in _paragraphs(page):
            text = _plain(raw)
            if "forbes" in text.lower() and re.search(r"\b(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th)) time\b", text, re.I):
                candidates.append((_published(page, view), page, raw, text))
    if not candidates:
        return _decline()
    published, page, raw, text = max(candidates, key=lambda c: (c[0], c[1].url))
    return Answer(text, [_source(page, view, raw)])


def _join(view):
    candidates = []
    for page in view["pages"].values():
        if not re.search(r"join|member", page.title, re.I):
            continue
        for raw in _paragraphs(page):
            for match in re.finditer(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", raw):
                label, url = match.groups()
                if not re.search(r"join|become a member|membership", label, re.I):
                    continue
                parsed = urlparse(url)
                if parsed.hostname and parsed.hostname.startswith("join.") and parsed.path in ("", "/"):
                    candidates.append((100 if not _historical(page) else 40, page, match[0], url))
    chosen = _pick(candidates)
    if chosen:
        return Answer("Join online: " + chosen[3], [_source(chosen[1], view, chosen[2])])
    return _decline()


def _membership(view):
    candidates = []
    for page in view["pages"].values():
        if not re.search(r"join|member", page.title, re.I) or _historical(page):
            continue
        body = _body(page)
        match = re.search(r"(?:^|\n)#{1,5}\s+[^\n]*(?:eligible to join|membership eligibility|who can join)[^\n]*\n", body, re.I)
        if not match:
            continue
        tail = body[match.end():]
        if tail.lstrip().startswith("##"):
            tail = tail[tail.index("\n") + 1:]
        block = re.split(r"\n#{1,3}\s", tail, maxsplit=1)[0]
        lines = [line for line in block.splitlines() if re.search(r"live or work|family member|belong to|^To join|open a savings", line, re.I)]
        if not lines:
            continue
        quote = "\n".join(lines)
        states = next((p for p in _paragraphs(page) if all(x in p for x in ("Iowa", "Illinois", "Wisconsin")) and re.search(r"find us|charter|serve", p, re.I)), None)
        text = _plain(quote)
        sources = [_source(page, view, quote)]
        if states:
            text += " " + _plain(states)
            sources.append(_source(page, view, states))
        candidates.append((100, page, quote, text, sources))
    chosen = _pick(candidates)
    return Answer(chosen[3], chosen[4]) if chosen else _decline()


def _student(question, view):
    pages = [p for p in view["pages"].values() if re.search(r"student loans?", p.title, re.I) and not _historical(p)]
    candidates = []
    for page in pages:
        paragraphs = _paragraphs(page)
        wanted = []
        if "refinan" in question:
            patterns = (r"refinance.*(?:monthly payment|student loan debt)", r"refinanc.*federal.*(?:lose|loss)")
        else:
            patterns = (r"defer full payments", r"origination fees?.*(?:prepayment|penalt)", r"funding gap.*flexible")
        for pattern in patterns:
            raw = next((p for p in paragraphs if re.search(pattern, _plain(p), re.I)), None)
            if raw:
                wanted.append(raw)
        if wanted:
            text = "Student loans: " + " ".join(_plain(p) for p in wanted)
            candidates.append((len(wanted), page, wanted[0], text, wanted))
    chosen = _pick(candidates)
    return Answer(chosen[3], [_source(chosen[1], view, raw) for raw in chosen[4]]) if chosen else _decline()


def _wallet(view):
    candidates = []
    for page, text, raw, tokens, heading in view["chunks"]:
        if not {"apple", "google", "samsung", "pay"} <= tokens or not ({"card", "cards"} & tokens):
            continue
        if not re.search(r"add|compatible", text, re.I):
            continue
        rank = 100 if not _historical(page) else 40
        rank += 5 if "compatible" in text.lower() else 0
        candidates.append((rank, page, raw, text))
    chosen = _pick(candidates)
    return Answer(chosen[3], [_source(chosen[1], view, chosen[2])]) if chosen else _decline()


def _contact_update(view):
    for page, text, raw, tokens, heading in view["chunks"]:
        if not {"personal", "information"} <= tokens:
            continue
        if not re.search(r"(?:review and change|update|correct).*personal information", text, re.I):
            continue
        if not re.search(r"log(?:ging)?\s*in|logging into|sign(?:ing)?\s*in", text, re.I):
            continue
        phone = re.search(r"\b\d{3}[- ]\d{3}[- ]\d{4}\b", text)
        result = "Log in to your account to review and change your personal information."
        if phone:
            result += " You can also call " + phone[0] + " to request a correction."
        return Answer(result, [_source(page, view, raw)])
    return _decline()


def _program(question, view):
    marker = re.compile(r"home\s*\$?\s*tart", re.I)
    candidates = []
    for page, text, raw, tokens, heading in view["chunks"]:
        if not marker.search(text) or not re.search(r"down payment|closing costs", text, re.I):
            continue
        if not re.search(r"provides|assistance|grant", text, re.I):
            continue
        rank = 100 if not _historical(page) else 60
        candidates.append((rank, _published(page, view), page, raw, text))
    if not candidates:
        return _decline()
    rank, published, page, raw, text = max(candidates, key=lambda c: (c[0], c[1], c[2].url))
    return Answer(text, [_source(page, view, raw)])


def _branch_count(view):
    candidates = []
    for page, text, raw, tokens, heading in view["chunks"]:
        if "branch" not in tokens and "branches" not in tokens:
            continue
        match = re.search(r"\b(\d+)\s+(?:full[- ]service\s+)?branch(?: office)? locations?\b", text, re.I)
        if not match or int(match[1]) <= 0:
            continue
        rank = 100 if urlparse(page.url).path.rstrip("/").endswith("/about") and not _historical(page) else 60 if _historical(page) else 80
        candidates.append((rank, _published(page, view), page, raw, match[1]))
    if not candidates:
        return _decline("The selected snapshot does not establish a reliable branch count.")
    rank = max(c[0] for c in candidates)
    candidates = [c for c in candidates if c[0] == rank]
    newest = max(c[1] for c in candidates)
    best = [c for c in candidates if c[1] == newest]
    if len({c[4] for c in best}) > 1:
        return _decline("The equally current branch-count statements disagree.", [_source(c[2], view, c[3]) for c in best[:3]])
    chosen = sorted(best, key=lambda c: c[2].url)[0]
    text = chosen[4] + " branch office locations"
    if rank < 100:
        text = "The latest dated report found" + (" (" + newest + ")" if newest else "") + " lists " + text + ". This is a dated report, not a verified live count."
    else:
        text += "."
    return Answer(text, [_source(chosen[2], view, chosen[3])], rank == 100)


def _volunteer(question, view):
    candidates = []
    requested = re.search(r"\b20\d{2}\b", question)
    for page, text, raw, tokens, heading in view["chunks"]:
        if "volunteer" not in tokens or not re.search(r"\b\d+\s+(?:\w+\s+){0,3}employees\s+(?:have\s+)?(?:used|took)\b", text, re.I):
            continue
        line = next((line for line in raw.splitlines() if re.search(r"\b\d+\s+(?:\w+\s+){0,3}employees\s+(?:have\s+)?(?:used|took)\b", _plain(line), re.I)), None)
        if line:
            raw, text = line, _plain(line).lstrip("- ")
        year = re.search(r"\bin\s+(20\d{2})\b", text, re.I)
        if not year or requested and requested[0] != year[1]:
            continue
        candidates.append((year[1], _published(page, view), page, raw, text))
    if not candidates:
        return _decline()
    year, _, page, raw, text = max(candidates, key=lambda c: (c[0], c[1], c[2].url))
    snapshot_year = re.search(r"20\d{2}", view["sid"])
    if "last year" in question and (not snapshot_year or int(year) != int(snapshot_year[0]) - 1):
        return _decline("I cannot establish last year's count. The available dated report states: " + text, [_source(page, view, raw)])
    return Answer(text, [_source(page, view, raw)])


def _fallback(question, view):
    query = _words(question)
    if len(query) < 2:
        return _decline()
    idf = view.get("idf", {})
    title_tokens = view.get("title_tokens", {})
    ranked = []
    for page, text, raw, tokens, heading in view["chunks"]:
        overlap = query & tokens
        if len(overlap) < 2 or len(overlap) / len(query) < 0.45:
            continue
        score = sum(idf.get(w, math.log(1 + len(view["chunks"]) / (1 + view["df"][w]))) for w in overlap)
        score /= 1 + len(tokens) / 100
        score += len(query & title_tokens.get(page.url, set()))
        if re.search(r"calculator|privacy-policy", page.url):
            score -= 15
        ranked.append((score, page, raw, text))
    chosen = _pick(ranked)
    if not chosen or chosen[0] < 6:
        return _decline()
    if len(re.findall(r"\d+(?:\.\d+)?%", chosen[3])) > 1:
        return _decline()
    return Answer(chosen[3], [_source(chosen[1], view, chosen[2])], False)


def answer_prose(question_normalized, view):
    q = question_normalized
    if "routing" in q or "aba number" in q:
        return _routing(view)
    if "branch" in q and any(x in q for x in ("close", "closure", "still open", "full-service", "full service", "members go")):
        closure = _closure(q, view)
        if closure is not None:
            return closure
    if "address" in q or re.search(r"where(?: is|'s) .*branch", q):
        address = _address(q, view)
        if address is not None:
            return address
    if "forbes" in q:
        return _forbes(view)
    if "join" in q and "online" in q:
        return _join(view)
    if any(x in q for x in ("eligible", "eligibility", "who can join", "become a member")):
        return _membership(view)
    if "student" in q or "university" in q:
        return _student(q, view)
    if "wallet" in q or re.search(r"(?:apple|google|samsung) pay", q):
        return _wallet(view)
    if any(x in q for x in ("update", "change", "correct")) and any(x in q for x in ("contact information", "personal information", "phone number", "mailing address")):
        return _contact_update(view)
    if re.search(r"home\s*\$?\s*tart|homestart", q):
        return _program(q, view)
    if "how many" in q and "branch" in q:
        return _branch_count(view)
    if "volunteer" in q:
        return _volunteer(q, view)
    return _fallback(q, view)
