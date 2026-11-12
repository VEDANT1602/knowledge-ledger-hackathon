"""Exercise the public interface with invented pages or a local organizer kit."""

import argparse
import importlib.util
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@dataclass
class Page:
    url: str
    title: str
    markdown: str
    fetched_at: str


@dataclass
class Snapshot:
    snapshot_id: str
    taken_on: str
    pages: list


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kit', type=Path)
    args = parser.parse_args()
    if args.kit:
        harness = args.kit.resolve() / 'harness'
        sys.path.insert(0, str(harness))
        spec = importlib.util.spec_from_file_location('organizer_runner', harness / 'run_eval.py')
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        system = runner.load_submission(ROOT)
        snapshots = runner.load_snapshots(args.kit.resolve() / 'snapshots')
        assert snapshots, 'The local kit contains no snapshots.'
        for snapshot in snapshots:
            system.ingest(snapshot)
        questions = [json.loads(line) for line in (args.kit / 'eval/public_eval.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
        for item in questions:
            answer = system.answer(item['question'], item.get('as_of'))
            assert isinstance(answer.text, str)
            assert isinstance(answer.confident, bool)
            for source in answer.sources:
                assert source.url and source.snapshot_id and source.quote
        conflicts = system.conflicts()
        assert isinstance(conflicts, list)
        for conflict in conflicts:
            assert conflict.topic and len(set(conflict.values)) > 1 and conflict.sources
            assert conflict.resolution is None or conflict.resolution in conflict.values
        print(json.dumps(dict(status='PASS', mode='local_organizer_kit', snapshots=len(snapshots), questions=len(questions), conflicts=len(conflicts))))
    else:
        from solution import build
        system = build()
        table = '# Certificate Rates\n\n| Certificate | APY |\n| --- | --- |\n| 8 Month | 3.65% |'
        first = Page('https://example-cu.test/rates/certificates', 'Certificate rates', table, '2026-06-01')
        stale = Page('https://example-cu.test/calculators/certificate', 'Certificate calculator', table.replace('3.65%', '3.15%'), '2026-06-01')
        system.ingest(Snapshot('smoke-2026-06', '2026-06-01', [first, stale]))
        answer = system.answer('What is the 8-month certificate APY?')
        assert answer.confident and '3.65%' in answer.text and '3.15%' not in answer.text
        conflicts = system.conflicts()
        assert any(c.resolution == '3.65%' for c in conflicts)
        assert not system.answer('What is the 8-month certificate APY?', '2026-05-01').confident
        print(json.dumps(dict(status='PASS', mode='synthetic', stages=['build', 'ingest', 'answer', 'conflicts'], conflicts=len(conflicts))))


if __name__ == '__main__':
    main()
