from __future__ import annotations

import copy
import math
import re
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from urllib.parse import urlparse

from ledger import extract_page
from models import Answer, Conflict, Source


STOP = set('what is the a an on of for to do does can i you your our me my with and or in as at how much please tell current now dupaco rate rates'.split())
NUMBERS = {'six': '6', 'ten': '10', 'twelve': '12', 'seventeen': '17', 'eighteen': '18', 'thirty': '30', 'sixty': '60'}


def norm(text):
    text = text.lower().replace('\u2013', '-').replace('\u2014', '-').replace('\u2019', "'")
    for word, value in NUMBERS.items():
        text = re.sub(r'\b' + word + r'\b', value, text)
    return re.sub(r'\s+', ' ', text).strip()


def words(text):
    return set(re.findall(r'[a-z0-9]+', norm(text))) - STOP


def clean(text):
    text = re.sub(r'!\[[^\]]*\]\([^\n]*?\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    return re.sub(r'\s+', ' ', text.replace('**', '').replace('_', '')).strip(' #-')


def source(fact):
    return Source(fact.url, fact.snapshot_id, fact.quote)


def value_key(value):
    return tuple(str(Decimal(x.replace(',', '')).normalize()) for x in re.findall(r'\d[\d,]*(?:\.\d+)?', value)), re.sub(r'[\d\s,.-]', '', value).lower()


def money_bounds(text):
    values = [float(x.replace(',', '')) for x in re.findall(r'\$?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)', text)]
    if not values:
        return None
    if len(values) > 1:
        return values[0], values[1]
    return (0, values[0]) if 'less' in text else (values[0], float('inf'))


def year_matches(year, label):
    m = re.search(r'(20\d{2})\s*-\s*(\d{2,4})', norm(label))
    if m:
        hi = int(m[2]) if len(m[2]) == 4 else int(m[1][:2] + m[2])
        return int(m[1]) <= year <= hi
    m = re.search(r'20\d{2}', label)
    return bool(m and (year <= int(m[0]) if 'older' in label.lower() else year == int(m[0])))


def fact_key(fact):
    q = fact.qualifiers
    keys = ('term', 'model_year', 'balance', 'audience', 'kind', 'special', 'program', 'amount', 'product', 'day', 'channel', 'branch', 'service', 'weekday', 'mortgage_type', 'frequency', 'phase')
    qualifiers = tuple((k, re.sub(r'[^a-z0-9.]', '', norm(str(q[k])))) for k in keys if q.get(k))
    return norm(fact.entity), fact.attribute, qualifiers


class Knowledge:
    def __init__(self):
        self.views = {}
        self.cache = {}

    def ingest(self, snapshot):
        date.fromisoformat(snapshot.taken_on)
        facts, chunks, pages = [], [], {}
        for page in snapshot.pages:
            pages[page.url] = page
            facts.extend(extract_page(page, snapshot.snapshot_id, snapshot.taken_on))
            md = re.sub(r'!\[[^\]]*\]\([^\n]*?\)', '', page.markdown)
            headings = ''
            for para in re.split(r'\n\s*\n', md):
                if para.startswith('#'):
                    headings = clean(para)
                text = clean(para)
                if not text or len(text) > 3500 or text.startswith('|') or 'data points:' in text:
                    continue
                if len(words(text)) < 3:
                    continue
                chunks.append((page, text, para.strip(), words(text), headings))
        df = Counter(w for chunk in chunks for w in chunk[3])
        self.views[snapshot.taken_on] = dict(sid=snapshot.snapshot_id, facts=facts, chunks=chunks, pages=pages, df=df,
            title_tokens={p.url: words(p.title) for p in snapshot.pages},
            idf={w: math.log(1 + len(chunks) / (1 + n)) for w, n in df.items()})
        self.cache.clear()

    def answer(self, question, as_of=None):
        key = (question, as_of)
        if key not in self.cache:
            self.cache[key] = self._answer(question, as_of)
        return copy.deepcopy(self.cache[key])

    def _answer(self, question, as_of):
        if not self.views:
            return self.decline()
        q = norm(question)
        requested = as_of
        if requested is None:
            match = re.search(r'\bas of\s+(20\d{2}-\d{2}-\d{2})', q)
            if match:
                requested = match[1]
        if requested is not None:
            try:
                date.fromisoformat(requested)
            except (TypeError, ValueError):
                return self.decline('Please supply an ISO calendar date for the historical view.')
        eligible = [d for d in self.views if requested is None or d <= requested]
        if not eligible:
            return self.decline('No snapshot was supplied on or before that date.')
        observed = max(eligible)
        view = self.views[observed]
        at = requested or observed
        if any(x in q for x in ('hours', 'lobby open', 'open sunday')):
            return self.hours(q, view)
        if re.search(r'\bfee\b|replacement|lost debit', q):
            return self.fee(q, view, at)
        if any(x in q for x in ('promotion', 'bonus', 'offer')) and not any(x in q for x in ('credit card', 'loan')):
            promo = self.promotion(q, view, at)
            if promo:
                return promo
        if ('link' in q or 'url' in q) and any(x in q for x in ('certificate', 'cd ', 'locator')):
            topic = 'certificate' if ('certificate' in q or 'cd ' in q) else 'contact'
            return self.link(topic, view)
        entity = None
        if 'auto' in q or re.search(r'\bvehicle\b', q):
            entity = 'auto loan'
        elif 'certificate' in q or re.search(r'\bcds?\b', q):
            entity = 'certificate'
        elif 'mortgage' in q or 'construction loan' in q or 'home loan' in q:
            entity = 'mortgage'
        elif 'personal loan' in q:
            entity = 'personal loan'
        elif 'bright savings' in q:
            entity = 'bright savings'
        elif 'share savings' in q or ('savings tiers' in q):
            entity = 'share savings'
        elif 'checking' in q and any(x in q for x in ('interest', 'apy', 'rate')):
            entity = 'checking'
        elif ('credit card' in q or 'visa' in q) and any(x in q for x in ('apr', 'rate')):
            entity = 'credit card'
        if entity:
            return self.numeric(q, entity, view, at, observed)
        return self.prose(q, view)

    @staticmethod
    def decline(detail=None, sources=None):
        return Answer(detail or "I don't know from the supplied snapshots. Please contact the credit union to confirm.", sources or [], False)

    def numeric(self, q, entity, view, at, observed):
        facts = [f for f in view['facts'] if norm(f.entity) == entity]
        if entity == 'mortgage' and any(x in q for x in ('7/1', 'construction', 'adjustable')):
            facts = [f for f in facts if any(x in norm(f.label) for x in ('7/1', 'construction', 'adjustable'))]
        elif entity == 'mortgage' and not any(x in q for x in ('relief', 'fhlb', 'home$tart')):
            facts = [f for f in facts if f.qualifiers.get('mortgage_type') == 'fixed']
        metric = 'apr' if entity in ('auto loan', 'personal loan', 'credit card') else 'apy'
        if entity == 'mortgage':
            metric = 'apr' if 'apr' in q else 'rate'
        if 'dividend rate' in q:
            metric = 'rate'
        if entity == 'bright savings' and 'apy' not in q:
            wanted_metrics = {'rate', 'apy'}
        else:
            wanted_metrics = {metric}
        facts = [f for f in facts if f.attribute in wanted_metrics and (not f.effective_from or f.effective_from <= at) and (not f.valid_until or f.valid_until >= at)]
        term = re.search(r'\b(\d+)\s*[- ]\s*(month|year)', q)
        if term:
            months = int(term[1]) * (12 if term[2] == 'year' else 1)
            facts = [f for f in facts if str(f.qualifiers.get('term', '')) == str(months)]
        year = re.search(r'\b(20\d{2})\b', re.sub(r'as of.*', '', q))
        if entity == 'auto loan' and year:
            facts = [f for f in facts if year_matches(int(year[1]), f.qualifiers.get('model_year', f.label))]
        audience = 'business' if 'business' in q else 'personal'
        if entity != 'credit card' or any(x in q for x in ('business', 'personal', 'platinum visa', 'rewards visa')):
            facts = [f for f in facts if f.qualifiers.get('audience', 'personal') == audience]
        if entity == 'certificate':
            if 'jumbo' in q:
                facts = [f for f in facts if f.qualifiers.get('kind') == 'jumbo']
            elif 'standard' in q or 'non-jumbo' in q:
                facts = [f for f in facts if f.qualifiers.get('kind') != 'jumbo']
        if entity == 'credit card':
            phase = 'introductory' if any(x in q for x in ('intro', 'balance transfer', 'balance-transfer')) else 'standard'
            facts = [f for f in facts if f.qualifiers.get('phase', 'standard') == phase]
            if 'platinum' in q:
                facts = [f for f in facts if 'platinum' in norm(f.label)]
            if 'rewards' in q:
                facts = [f for f in facts if 'rewards' in norm(f.label)]
        if entity == 'mortgage':
            program = 'refinance' if 'refinan' in q else 'purchase'
            facts = [f for f in facts if f.qualifiers.get('program', program) == program]
        amounts = [float(x.replace(',', '')) for x in re.findall(r'\$([\d,]+(?:\.\d+)?)', q)]
        if amounts:
            amount = amounts[0]
            facts = [f for f in facts if not f.qualifiers.get('balance', f.qualifiers.get('amount')) or (lambda b: b and b[0] <= amount <= b[1])(money_bounds(f.qualifiers.get('balance', f.qualifiers.get('amount', ''))))]
        if facts and entity != 'credit card':
            best_authority = max(f.authority for f in facts)
        if not facts:
            return self.decline()
        if 'highest' in q or ('savings tiers' in q):
            facts = [max(facts, key=lambda f: float(re.search(r'[\d.]+', f.value)[0]))]
        groups = defaultdict(list)
        for fact in facts:
            groups[fact_key(fact)].append(fact)
        selected, conflict, agreement_sources = [], False, []
        for group in groups.values():
            rank = max(f.authority for f in group)
            if entity != 'credit card' and rank < best_authority:
                continue
            top = [f for f in group if f.authority == rank]
            if len({value_key(f.value) for f in top}) > 1:
                return self.decline('The equally authoritative sources disagree for this product and tier. Please contact the credit union to confirm.', [source(f) for f in top])
            chosen = sorted(top, key=lambda f: (f.url, f.quote))[0]
            selected.append(chosen)
            agreement_sources.extend(source(f) for f in top)
            conflict |= len({value_key(f.value) for f in group}) > 1
        # Model-year intervals can overlap on a stale table without being identical.
        if entity == 'auto loan' and year:
            rank = max(f.authority for f in selected)
            top = [f for f in selected if f.authority == rank]
            if len({value_key(f.value) for f in top}) > 1:
                return self.decline('The authoritative auto rates disagree for the requested vehicle and term.', [source(f) for f in top])
            conflict |= len({value_key(f.value) for f in selected}) > 1
            selected = top
        selected.sort(key=lambda f: (int(f.qualifiers.get('term', 0) or 0), money_bounds(f.qualifiers.get('amount', '')) or (0, 0), f.label, f.attribute))
        rendered, sources, seen = [], [], set()
        for fact in selected:
            label = fact.label or fact.entity
            term_label = fact.qualifiers.get('term')
            if term_label and not re.search(r'month|year', label, re.I):
                label += ' (' + term_label + ' months)'
            balance = fact.qualifiers.get('balance')
            if balance and balance not in label:
                label += ', balance ' + balance
            value = fact.value
            line = f'{label}: {value} {fact.attribute.upper() if fact.attribute in ("apy", "apr") else "dividend rate" if entity != "mortgage" else "interest rate"}'
            minimum = fact.qualifiers.get('minimum', fact.qualifiers.get('min_to_earn', ''))
            if minimum:
                line += ', minimum ' + minimum
            if fact.effective_from:
                line += ' (effective ' + fact.effective_from + ')'
            if line not in seen:
                rendered.append(line)
                seen.add(line)
                sources.append(source(fact))
        if not rendered:
            return self.decline()
        text = '; '.join(rendered) + '.'
        if entity in ('auto loan', 'personal loan', 'mortgage'):
            text += ' Published as-low-as rates; approval and other conditions apply.'
        text += ' Snapshot observed ' + observed + '.'
        if entity == 'auto loan' and year:
            conflict |= any(value_key(f.value) not in {value_key(t.value) for t in selected} for f in facts)
        note = 'The official product rate table outranks the conflicting calculator or secondary page.' if conflict else None
        for s in agreement_sources:
            if (s.url, s.quote) not in {(t.url, t.quote) for t in sources}:
                sources.append(s)
        return Answer(text, sources, True, note)

    def fee(self, q, view, at):
        singular = lambda terms: {t[:-1] if t.endswith('s') and len(t) > 3 else t for t in terms}
        query = singular(words(q) - {'fee', 'fees', 'cost', 'charge', 'replacement', 'replace'})
        candidates = []
        for f in view['facts']:
            if f.attribute != 'fee':
                continue
            if f.qualifiers.get('audience', 'personal') != ('business' if 'business' in q else 'personal'):
                continue
            label = singular(words(f.label))
            required = query - {'card', 'debit', 'lost'}
            if required and not required <= label:
                continue
            if len(query & label) < max(1, len(query) - 1):
                continue
            if 'replacement' in q and not any(x in norm(f.label) for x in ('replacement', 'replace', 'lost')):
                continue
            if f.valid_until and f.valid_until < at:
                continue
            if f.effective_from and f.effective_from > at:
                continue
            candidates.append(f)
        if not candidates:
            return self.decline()
        rank = max(f.authority for f in candidates)
        best = [f for f in candidates if f.authority == rank]
        if len({f.value for f in best}) > 1:
            return self.decline('The published fee sources disagree. Please contact the credit union to confirm.', [source(f) for f in best])
        f = best[0]
        return Answer(f.label + ': ' + f.value + '.', [source(f)])

    def promotion(self, q, view, at):
        query = words(q) - {'promotion', 'bonus', 'offer', 'get', 'earn', 'available'}
        matches = []
        for page in view['pages'].values():
            title = words(page.title + ' ' + page.markdown.split('\n')[0] + ' ' + urlparse(page.url).path.replace('-', ' '))
            if len(query & title) < max(1, len(query) - 1):
                continue
            text = page.markdown
            ended = re.search(r'[^\n]*(?:offer has ended|offer ended|offer expires|offer ends|no longer available|offer expired)[^\n]*', text, re.I)
            if ended:
                quote = ended[0]
                from ledger import date_value
                dates = re.findall(r'20\d{2}-\d{2}-\d{2}|[A-Z][a-z]+ \d{1,2},? 20\d{2}|\d{1,2}/\d{1,2}/20\d{2}', quote)
                expiry = date_value(dates[0]) if dates else None
                if 'ended' in quote.lower() or 'expired' in quote.lower() or 'no longer' in quote.lower() or expiry and expiry < at:
                    return Answer('This offer has ended' + ('; stated expiration ' + expiry if expiry else '') + '.', [Source(page.url, view['sid'], quote)], True)
            matches.append(page)
        return None

    def hours(self, q, view):
        named = re.search(r'(?:the\s+)?([a-z][a-z -]*?)\s+branch\b', q)
        name = None
        if named:
            candidate = re.sub(r'.*\b(?:for|at|the)\s+', '', named[1]).strip()
            candidate = re.sub(r'^(?:what are|what is|is|are|can you give me)\s+', '', candidate)
            if candidate not in ('all', 'which', 'your', 'dupaco', 'do all dupaco'):
                name = candidate
        channel = 'drive' if 'drive' in q else 'lobby'
        day = next((d for d in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday') if d in q), None)
        found = []
        for page in view['pages'].values():
            if name and name not in norm(page.title + ' ' + page.markdown[:250]):
                continue
            if not re.search(channel + r'[- ]?(?:up)?\s*(?:hours|schedule)|' + channel + r'\s+will be open', norm(page.markdown)) and not re.search(r'^\s*\*{0,2}' + channel + r'(?:[- ]up)?\*{0,2}\s*$', page.markdown, re.M | re.I):
                continue
            md = page.markdown
            heading_pattern = r'(?:^|\n)([^\n]*(?:Lobby [Hh]ours|Drive[- ]?[Uu]p [Hh]ours)[^\n]*|\s*\*\*(?:Lobby|Drive[- ]up)\*\*\s*)'
            for m in re.finditer(heading_pattern, md):
                if channel not in m[1].lower():
                    continue
                tail = re.split(r'\n(?:#{1,4}\s|\*\*[^\n]+\*\*\s*\n)', md[m.end():m.end()+1100], maxsplit=1)[0]
                block = m[1] + tail
                rows = [x for x in block.splitlines() if re.search(r'monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon-|sat\b|sun\b', x, re.I)]
                if day:
                    rows = [x for x in rows if day in x.lower() or day in ('tuesday', 'wednesday', 'thursday') and re.search('monday.*(?:thursday|friday)', x, re.I)]
                if rows:
                    quote = '\n'.join(rows)
                    historical = any(x in page.url for x in ('newsroom', '/blog/', '/20'))
                    found.append((historical, page, quote))
        if not found:
            # Older announcements sometimes describe a complete schedule in one paragraph.
            for page, text, raw, tokens, heading in view['chunks']:
                if name and name not in norm(page.title + ' ' + text):
                    continue
                if channel in text.lower() and re.search(r'\d[^.]*[ap]\.m\.', text, re.I) and re.search('monday|friday|saturday', text, re.I):
                    found.append((True, page, raw))
        if not found:
            return self.decline('I cannot confirm those branch hours from the supplied snapshots. Please contact the branch.')
        found.sort(key=lambda x: (x[0], x[1].url))
        historical = found[0][0]
        best = [x for x in found if x[0] == historical]
        if name and len({norm(clean(x[2])) for x in best}) > 1:
            return self.decline('The sources disagree on this branch schedule. Please contact the branch to confirm.', [Source(p.url, view['sid'], quote) for _, p, quote in best])
        chosen = best[:3 if not name else 1]
        text = '; '.join(clean(x[2]) for x in chosen)
        if not name:
            text = 'Schedules vary by branch. Published examples: ' + text + '. Which branch do you need?'
        if historical:
            text = 'Only historical branch announcements support these hours; the snapshot does not confirm they remain current. ' + text
        return Answer(text, [Source(p.url, view['sid'], quote) for _, p, quote in chosen], not historical)

    def link(self, topic, view):
        if topic == 'certificate':
            candidates = [f for f in view['facts'] if f.entity == 'certificate']
            if candidates:
                f = max(candidates, key=lambda x: (x.authority, '/personal/' in x.url))
                return Answer(f.url + '#rates', [source(f)])
        else:
            pages = [p for p in view['pages'].values() if urlparse(p.url).path.rstrip('/') == '/contact']
            if pages:
                p = pages[0]
                return Answer(p.url, [Source(p.url, view['sid'], p.markdown.splitlines()[0])])
        return self.decline()

    def prose(self, q, view):
        from prose import answer_prose
        return answer_prose(q, view)

    def conflicts(self):
        if not self.views:
            return []
        view = self.views[max(self.views)]
        groups = defaultdict(list)
        for f in view['facts']:
            if f.attribute not in ('apr', 'apy', 'rate', 'fee'):
                continue
            if f.entity == 'mortgage' and not f.qualifiers.get('term'):
                continue
            if f.valid_until and f.valid_until < max(self.views):
                continue
            if f.effective_from and f.effective_from > max(self.views):
                continue
            groups[fact_key(f)].append(f)
        result = []
        for key, group in sorted(groups.items()):
            values = sorted({value_key(f.value): f.value for f in group}.values())
            if len(values) < 2:
                continue
            rank = max(f.authority for f in group)
            top = [f for f in group if f.authority == rank]
            winning = {value_key(f.value) for f in top}
            resolution = top[0].value if len(winning) == 1 else None
            f = top[0]
            result.append(Conflict(f.label + ' ' + f.attribute.upper() + ' ' + str(f.qualifiers), values, [source(g) for g in group], resolution,
                                   'Official product table outranks secondary sources.' if resolution else 'Equal-authority disagreement; abstain.'))
        # A changed vehicle-year cutoff can still overlap an older table's tier.
        autos = [f for f in view['facts'] if f.entity == 'auto loan' and f.qualifiers.get('model_year') and f.qualifiers.get('term')]
        seen = {(c.topic, tuple(c.values)) for c in result}
        pairs = set()
        for i, first in enumerate(autos):
            for second in autos[i+1:]:
                if first.attribute != second.attribute or first.qualifiers['term'] != second.qualifiers['term']:
                    continue
                if first.qualifiers.get('model_year') == second.qualifiers.get('model_year') or value_key(first.value) == value_key(second.value):
                    continue
                overlap = [y for y in range(1950, 2101) if year_matches(y, first.qualifiers['model_year']) and year_matches(y, second.qualifiers['model_year'])]
                if not overlap:
                    continue
                values = sorted([first.value, second.value])
                signature = (first.attribute, first.qualifiers['term'], min(overlap), max(overlap), tuple(value_key(v) for v in values))
                if signature in pairs:
                    continue
                pairs.add(signature)
                top = first if first.authority > second.authority else second
                resolution = top.value if first.authority != second.authority else None
                topic = f"{first.qualifiers['term']}-month auto loan {first.attribute.upper()}, model years {min(overlap)}-{max(overlap)}"
                result.append(Conflict(topic, values, [source(first), source(second)], resolution,
                    'Product rate table outranks a secondary table with an overlapping model-year tier.' if resolution else 'Equal-authority overlapping tiers disagree; abstain.'))
        return result
