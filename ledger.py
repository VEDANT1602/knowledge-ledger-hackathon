"""Extract qualified facts without discarding their source or observation date."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from html import unescape


@dataclass
class Fact:
    entity: str
    attribute: str
    qualifiers: dict[str, str]
    value: str
    unit: str
    observed_on: str
    snapshot_id: str
    url: str
    quote: str
    effective_from: str | None = None
    valid_until: str | None = None
    authority: int = 50
    label: str = ""
    context: str = ""

    @property
    def identity(self):
        return self.entity, self.attribute, tuple(sorted(self.qualifiers.items()))


def plain(text):
    text = re.sub(r"!\[[^]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    return unescape(re.sub(r"[*_`\\]", "", text)).replace("\u00a0", " ").strip()


def norm(text):
    return re.sub(r"\s+", " ", plain(text).lower().replace("–", "-").replace("—", "-"))


def value_key(value):
    if "%" in value or "$" in value:
        numbers = re.findall(r"\d[\d,]*(?:\.\d+)?", value)
        return ("%" if "%" in value else "$", tuple(str(Decimal(x.replace(",", "")).normalize()) for x in numbers))
    return norm(value)


def date_value(text):
    text = text.strip().rstrip(".,")
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


DATE = r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|[A-Z][a-z]+\s+\d{1,2},?\s+\d{4})"


def validity(text):
    effective = re.search(r"(?:effective(?:\s+as\s+of)?|rates?\s+as\s+of)\s*:?\s*(" + DATE + r")", text, re.I)
    expires = re.search(r"(?:offer\s+ended|expired|expires?|expiration(?:\s+date)?|ends?|valid\s+(?:through|until)|available\s+(?:through|until)|open\s+now\s+through)\s*:?\s*(" + DATE + r")", text, re.I)
    return date_value(effective.group(1)) if effective else None, date_value(expires.group(1)) if expires else None


def source_authority(url, title="", entity="", is_table=False):
    text = norm(url + " " + title)
    if any(x in text for x in ("calculator", "calculators", "affordability")):
        return 25
    if any(x in text for x in ("/learn/blog/", "/blog/", "/newsroom/", "/press/", "newsletter")):
        return 35
    if any(x in text for x in ("/switch-and-earn", "/earn-more", "/promotions/", "/offers/", "/campaign", "promotion")):
        return 55
    if entity == "fee" and any(x in text for x in ("fee-schedule", "fee schedule", "fees")):
        return 100
    if entity == "branch" and any(x in text for x in ("branch", "contact", "location")):
        return 100
    if is_table and any(x in text for x in ("rates", "savings", "loan", "credit-card", "credit card", "checking", "certificate")):
        return 100
    if any(x in text for x in ("/rates/", "rate sheet")):
        return 100
    return 70 if is_table else 60


def entity_for(label, context, url=""):
    a, t = norm(label), norm(label + " " + context + " " + url)
    if any(x in t for x in ("recreational loan", "recreational-loan", "boat & rv loan", "boat and rv loan", "atv, snowmobile", "jet ski loan")):
        return "recreational loan"
    if "model year" in a:
        return "auto loan"
    if "certificate" in a or re.search(r"\bcd\b", a):
        return "certificate"
    if "visa" in a:
        return "credit card"
    if "share savings" in a:
        return "share savings"
    if "bright savings" in a:
        return "bright savings"
    if "checking" in a:
        return "checking"
    if "savings" in a or "money market" in a:
        return re.sub(r"^business\s+", "", a)
    if "conventional" in a:
        return "mortgage"
    if "certificate" in t or re.search(r"\bcd\b", t):
        return "certificate"
    if any(x in t for x in ("auto loan", "auto-loan", "auto-motorcycle", "vehicle-affordability", "motorcycle loan")):
        return "auto loan"
    if "credit card" in t or "credit-card" in t or re.search(r"\b(?:platinum|rewards)\s+visa\b", t):
        return "credit card"
    if any(x in t for x in ("heloc", "home equity", "home-equity")):
        return "home equity loan"
    if any(x in t for x in ("home improvement", "home-improvement")):
        return "home improvement loan"
    if any(x in t for x in ("recreational loan", "recreational-loan")):
        return "recreational loan"
    if "mortgage" in t or "home-loan" in t:
        return "mortgage"
    if "personal loan" in t or "personal-loan" in t:
        return "personal loan"
    if "fee" in t or "charge" in t:
        return "fee"
    if "branch" in t and any(x in t for x in ("hours", "lobby", "drive")):
        return "branch"
    return a


def qualifiers_for(label, context, headers, cells, entity, url=""):
    text = norm(label + " " + context)
    q = {"audience": "business" if "business" in norm(label + " " + url) else "personal"}
    q["product"] = norm(label)
    term = re.search(r"(\d+)\s*[- ]?\s*(month|year)s?\b", norm(label))
    if not term:
        for h, c in zip(headers, cells):
            if "term" in norm(h):
                term = re.search(r"(\d+)\s*[- ]?\s*(month|year)s?\b", norm(c))
                if term:
                    break
    if term:
        q["term"] = str(int(term.group(1)) * (12 if term.group(2) == "year" else 1))
    if entity == "certificate":
        q["product"] = "certificate"
        q["kind"] = "jumbo" if "jumbo" in norm(label + " " + context) else "standard"
        q["special"] = "true" if "special" in norm(label + " " + context) else "false"
    if entity == "personal loan":
        q["product"] = "personal loan"
    if entity == "credit card":
        cards = re.findall(r"(?:business\s+)?(?:platinum|rewards)\s+visa", norm(label + " " + context))
        card = cards[0] if re.search(r"\bvisa\b", norm(label)) else cards[-1] if cards else norm(label)
        q["card"] = card
        q["product"] = card
        q["phase"] = "introductory" if "introductory" in norm(label) or "balance transfer" in norm(label) else "standard"
    if entity in ("auto loan", "recreational loan"):
        yr = re.search(r"(20\d{2})(?:\s*[-–]\s*(\d{2,4}))?\s+model\s+year(?:\s*\(and older\))?", norm(label))
        if not yr:
            yr = re.search(r"model\s+year\s+(20\d{2})(?:\s*[-–]\s*(\d{2,4}))?", norm(label))
        if yr:
            end = yr.group(2)
            end = yr.group(1)[:2] + end if end and len(end) == 2 else end
            if end:
                q["model_year"] = "-".join(sorted((yr.group(1), end)))
            else:
                q["model_year"] = yr.group(1) + ("-older" if "older" in norm(label) else "")
            q["product"] = entity
    for h, c in zip(headers, cells):
        n = norm(h)
        if "balance" in n and "minimum" not in n and "min." not in n:
            q["balance"] = plain(c)
        if "loan amount" in n:
            q["amount"] = plain(c)
        if "min." in n or "minimum" in n:
            if "earn" in n or "balance" in n:
                q["minimum"] = re.sub(r"[^\d.,$]", "", c)
    if entity == "mortgage":
        q["product"] = "mortgage"
        q["program"] = "rate relief" if "rate relief" in norm(label) else "refinance" if "refinance" in norm(label) else "purchase"
        q["mortgage_type"] = "fixed" if "fixed" in norm(label) else "adjustable" if any(x in norm(label) for x in ("arm", "adjustable")) else "unspecified"
        amount = re.search(r"\$([\d,]+)(?:\.\d+)?\s*(?:or less|and under|maximum)?", label)
        if amount:
            q["amount"] = amount.group(1).replace(",", "")
    if entity == "branch":
        branch = re.search(r"([A-Za-z][A-Za-z '\-]*?)\s+Branch\b", plain(context))
        q["branch"] = norm(branch.group(1)) if branch else norm(url.rstrip("/").rsplit("/", 1)[-1])
        q["service"] = "drive-up" if re.search(r"drive[- ]?up", text) else "lobby" if "lobby" in text else "hours"
        q["weekday"] = norm(label)
    return q


def metric_for(header, value):
    h = norm(header)
    if "apy" in h or "percentage yield" in h:
        return "apy"
    if "apr" in h or "percentage rate" in h:
        return "apr"
    if "rate" in h:
        return "rate"
    if any(x in h for x in ("fee", "charge", "cost")):
        return "fee"
    if "hour" in h:
        return "hours"
    return None


def metric_values(cell, metric):
    cell = plain(cell)
    if metric in ("rate", "apr", "apy"):
        values = re.findall(r"\d+(?:\.\d+)?\s*%", cell)
        if values:
            return [" - ".join(v.replace(" ", "") for v in values)]
    if metric == "fee":
        m = re.search(r"\$\d[\d,]*(?:\.\d{1,2})?", cell)
        if m:
            return [m.group()]
        if re.search(r"\bfree\b|no charge", cell, re.I):
            return ["Free"]
    if metric == "hours" and cell:
        return [cell]
    return []


def split_cells(line):
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def extract_page(page, snapshot_id, taken_on):
    facts = []
    lines = page.markdown.splitlines()
    headings = []
    consumed = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            headings = [x for x in headings if x[0] < level] + [(level, plain(line.lstrip("# ")))]
        if "|" not in line or i + 1 >= len(lines) or not re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            i += 1
            continue
        headers = split_cells(line)
        start, end = i, i + 2
        while end < len(lines) and "|" in lines[end] and lines[end].strip():
            end += 1
        context = " ".join(t for _, t in headings)
        preceding = [plain(x) for x in lines[max(0, start - 5):start] if x.strip() and not x.startswith(("|", "[", "!"))]
        if preceding:
            context += " " + " ".join(preceding[-2:])
        after = "\n".join(lines[end:min(len(lines), end + 7)])
        effective, expires = validity(after)
        if not effective:
            effective, _ = validity("\n".join(lines[max(0, start - 4):start]))
        for ri in range(i + 2, end):
            cells = split_cells(lines[ri])
            if len(cells) != len(headers) or not cells:
                continue
            label = plain(cells[0])
            entity = entity_for(label, context, page.url)
            qualifiers = qualifiers_for(label, context, headers, cells, entity, page.url)
            if entity == "credit card" and qualifiers.get("card"):
                label = qualifiers["card"].title().replace("Visa", "Visa")
                if qualifiers.get("phase") == "introductory":
                    label += " introductory balance-transfer rate"
            quote = line + "\n" + lines[ri]
            for header, cell in zip(headers, cells):
                metric = metric_for(header, cell)
                if metric is None and entity == "fee" and norm(header) in ("amount", "price", "cost"):
                    metric = "fee"
                if metric == "fee" and entity != "fee":
                    continue
                if metric is None:
                    continue
                for value in metric_values(cell, metric):
                    qualified = dict(qualifiers)
                    h = norm(header)
                    if "after promotional" in h or "after introductory" in h:
                        qualified["phase"] = "standard"
                    elif "1st" in h or "introductory" in h or "promotional" in h:
                        qualified["phase"] = "introductory"
                    facts.append(Fact(entity, metric, qualified, value, "%" if metric in ("rate", "apr", "apy") else "$" if value.startswith("$") else "hours" if metric == "hours" else "", taken_on, snapshot_id, page.url, quote, effective, expires, source_authority(page.url, page.title, entity, True), label, context))
        consumed.update(range(start, end))
        i = end
    # Plain rate declarations retain local product identity and the stated metric.
    context = page.title
    for i, line in enumerate(lines):
        if i in consumed:
            continue
        if line.startswith("#"):
            context = plain(line.lstrip("# "))
            continue
        clean = plain(line)
        lower = norm(clean)
        if not clean or len(clean) > 1200 or clean.startswith("["):
            continue
        if len(clean) < 80 and "$" not in clean and re.search(r"^(?:deposit services|debit card service charges|online service charges|research fees|other service charges|teller and cash handling|safe.deposit box)\b", lower):
            context = clean
        for m in re.finditer(r"\b(APY|APR|dividend rate|interest rate)\s*(?:of|:|is|=)?\s*(\d+(?:\.\d+)?\s*%)", clean, re.I):
            label = re.sub(r"\s*(?:APY|APR|dividend rate|interest rate).*", "", clean[:m.end()], flags=re.I).strip(" :;.-")
            entity = entity_for(label, context, page.url)
            if entity == "credit card":
                continue
            if entity == label.lower() and not any(x in lower for x in ("certificate", "loan", "savings", "visa")):
                continue
            metric = "apy" if m.group(1).lower() == "apy" else "apr" if m.group(1).lower() == "apr" else "rate"
            qualifiers = qualifiers_for(label, context, [], [], entity, page.url)
            if entity == "certificate" and "term" not in qualifiers:
                continue
            effective, expires = validity(clean)
            facts.append(Fact(entity, metric, qualifiers, m.group(2).replace(" ", ""), "%", taken_on, snapshot_id, page.url, line.strip(), effective, expires, source_authority(page.url, page.title, entity), label, context))
        for m in re.finditer(r"(\d+(?:\.\d+)?\s*%)\s*(APY|APR)\b", clean, re.I):
            label = clean[:m.start()].strip(" :;.-") or context
            entity = entity_for(label, context, page.url)
            if entity == "credit card":
                continue
            if entity not in ("certificate", "auto loan", "personal loan", "mortgage", "credit card", "share savings", "bright savings"):
                continue
            qualifiers = qualifiers_for(label, context, [], [], entity, page.url)
            if entity == "certificate" and "term" not in qualifiers:
                continue
            effective, expires = validity(clean)
            facts.append(Fact(entity, m.group(2).lower(), qualifiers, m.group(1).replace(" ", ""), "%", taken_on, snapshot_id, page.url, line.strip(), effective, expires, source_authority(page.url, page.title, entity), label, context))
        # Fee schedules often arrive as PDF text with one named service per line.
        if any(x in norm(page.url + " " + page.title) for x in ("fee", "charge")) or "fee" in lower:
            m = re.search(r"\$\d[\d,]*(?:\.\d{1,2})?", clean)
            if m and m.start() > 3 and len(clean) < 260:
                label = clean[:m.start()].strip(" :*-()")
                if label and not label.lower().startswith(("you will", "maximum", "minimum", "rates", "all loans", "the following")):
                    qualifiers = {"product": norm(label), "audience": "business" if "business" in norm(context + " " + label) else "personal"}
                    frequency = re.search(r"\bper\s+(item|month|year|hour|roll|transaction|inquiry)\b|\beach\b", clean[m.end():], re.I)
                    if frequency:
                        qualifiers["frequency"] = norm(frequency.group())
                    effective, expires = validity("\n".join(lines[:15]))
                    facts.append(Fact("fee", "fee", qualifiers, m.group(), "$", taken_on, snapshot_id, page.url, line.strip(), effective, expires, source_authority(page.url, page.title, "fee"), label, context))
    unique = {}
    for fact in facts:
        key = fact.identity, fact.value, fact.url, fact.effective_from, fact.valid_until
        unique.setdefault(key, fact)
    return list(unique.values())
