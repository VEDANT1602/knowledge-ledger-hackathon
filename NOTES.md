# Implementation notes

I started with the supplied contract and unchanged starter. The aim is a defensible answer: correct value, qualifiers, date, evidence, and uncertainty. The public practice evaluator is a compatibility and failure-analysis tool; it does not establish hidden-set performance.

The implementation uses only Python's standard library and needs no API keys. `solution.py` exposes `build()`, `engine.py` keeps dated views and resolves questions, `ledger.py` extracts qualified facts, and `prose.py` handles bounded prose topics. `models.py` uses the organizer's contract classes when present and local equivalents for standalone tests.

Each ingested snapshot replaces the whole temporal view for its date. Historical questions select the newest available view on or before the requested date. Missing current pages do not inherit older content. Every extracted fact retains its source text and URL, snapshot and observation date, value and unit, qualifiers, and any stated effective or expiration date. Crawl time never substitutes for validity.

Markdown tables are parsed by column; APY, dividend rate, and APR remain distinct. Product, term, balance, model year, and personal or business qualifiers narrow the candidates. Official product tables outrank calculators and older editorial pages. A disagreement between equally authoritative facts remains unresolved. Fee matching requires the named service. Historical branch announcements receive an explicit currency caveat. Lexical retrieval supplies passages for questions outside the structured paths.

`conflicts()` reports qualified numeric disagreements in the newest view with the competing evidence and a resolution where authority supports one. A value changing between views is treated as history. Conflict coverage is limited by extraction coverage; the participant kit supplies no hidden conflict gold.

Tests use invented data. The smoke test uses the local kit without publishing it. The timing script separates first answers from cache hits. Reproduce the public evaluation from the kit folder with:

```text
python harness/run_eval.py --submission ../knowledge-ledger --eval eval/public_eval.jsonl --out ../knowledge-ledger-results
```

Known limits are varied prose, incomplete branch-hour evidence, and facts that the snapshots never publish. The default scorer cannot award correctness to an ordinary item with empty required values without its optional judge. No paid model judge or external model is required or used by this solution.
