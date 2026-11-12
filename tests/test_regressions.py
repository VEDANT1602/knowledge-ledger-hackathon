"""Behavior checks built from invented pages and deliberately changed rates."""

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from solution import build


@dataclass(frozen=True)
class Page:
    url: str
    title: str
    markdown: str
    fetched_at: str


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    taken_on: str
    pages: list[Page]


BASE = "https://example-cu.test"


def page(path, text, title="Official product information", fetched_at="2026-06-20"):
    return Page(BASE + path, title, text, fetched_at)


def snap(date, *pages):
    return Snapshot("test_" + date, date, list(pages))


def certificate(apy, dividend="3.11", term="6"):
    return (
        "# Certificate Rates\n\n"
        "| Certificate | Minimum Balance | Dividend Rate | Annual Percentage Yield |\n"
        "| --- | --- | --- | --- |\n"
        f"| {term}-Month Fixed Certificate | $1,000 | {dividend}% | {apy}% |\n\n"
        "Rates effective as of 06/01/2026.\n"
    )


def autos(rate="5.80", older="6.10"):
    return (
        "# Auto Loans\n\n"
        "| Loan Program | Term | Annual Percentage Rate (As Low As) |\n"
        "| --- | --- | --- |\n"
        f"| 2024-27 Model Year | 60 Months | {rate}% APR |\n"
        "| 2024-27 Model Year | 84 Months | 6.20% APR |\n"
        f"| 2021-23 Model Year | 60 Months | {older}% APR |\n\n"
        "Rates are effective as of 06/01/2026. All loans are subject to approval.\n"
    )


class RegressionTests(unittest.TestCase):
    def system(self, *snapshots):
        ks = build()
        for snapshot in snapshots:
            ks.ingest(snapshot)
        return ks

    def require_value(self, answer, value, excluded=()):
        self.assertTrue(answer.confident, answer.text)
        self.assertIn(value, answer.text)
        for other in excluded:
            self.assertNotIn(other, answer.text)
        self.assertTrue(answer.sources, "A confident answer needs supporting evidence")
        self.assertTrue(answer.sources[0].snapshot_id)
        self.assertTrue(answer.sources[0].quote)

    def test_temporal_view_uses_latest_snapshot_on_or_before_date(self):
        ks = self.system(
            snap("2026-06-01", page("/rates/certificates", certificate("3.25"))),
            snap("2026-07-01", page("/rates/certificates", certificate("3.75"))),
        )
        a = ks.answer("What is the 6-month certificate APY?", as_of="2026-06-25")
        self.require_value(a, "3.25%", ("3.75%", "3.11%"))
        self.assertEqual("test_2026-06-01", a.sources[0].snapshot_id)
        self.require_value(ks.answer("What is the 6-month certificate APY?"), "3.75%", ("3.25%",))

    def test_date_before_first_snapshot_abstains(self):
        ks = self.system(snap("2026-06-01", page("/rates/certificates", certificate("3.25"))))
        self.assertFalse(ks.answer("What is the 6-month certificate APY?", as_of="2026-05-31").confident)

    def test_future_effective_date_does_not_equal_observation_date(self):
        text = certificate("3.25").replace("06/01/2026", "07/01/2026")
        ks = self.system(snap("2026-06-20", page("/rates/certificates", text)))
        self.assertFalse(ks.answer("What is the 6-month certificate APY?").confident)

    def test_page_missing_from_current_full_snapshot_is_not_carried_forward(self):
        ks = self.system(
            snap("2026-06-01", page("/rates/certificates", certificate("3.25"))),
            snap("2026-07-01", page("/contact", "# Contact\nPlease contact a member adviser.")),
        )
        self.assertFalse(ks.answer("What is the 6-month certificate APY?").confident)
        self.require_value(ks.answer("What is the 6-month certificate APY?", as_of="2026-06-10"), "3.25%")

    def test_adjacent_rate_and_apy_cells_remain_separate(self):
        ks = self.system(snap("2026-06-20", page("/rates/certificates", certificate("3.25", dividend="3.11"))))
        self.require_value(ks.answer("What is the 6-month certificate APY?"), "3.25%", ("3.11%",))
        self.require_value(ks.answer("What is the dividend rate on the 6-month certificate?"), "3.11%", ("3.25%",))

    def test_term_and_model_year_are_part_of_fact_identity(self):
        ks = self.system(snap("2026-06-20", page("/personal/loans/auto-motorcycle-loans", autos())))
        self.require_value(ks.answer("What is the APR for a 60-month auto loan on a 2025 vehicle?"), "5.80%", ("6.10%", "6.20%"))
        self.require_value(ks.answer("What is the APR for an 84-month auto loan on a 2025 vehicle?"), "6.20%", ("5.80%", "6.10%"))
        self.require_value(ks.answer("What is the APR for a 60-month auto loan on a 2022 vehicle?"), "6.10%", ("5.80%", "6.20%"))

    def test_balance_tiers_are_not_contradictions(self):
        text = """# Share Savings Rates

| Account | Balance | Dividend Rate | Annual Percentage Yield |
| --- | --- | --- | --- |
| Share Savings | $100-$9,999.99 | 0.08% | 0.08% |
| Share Savings | $10,000-$24,999.99 | 0.18% | 0.18% |
| Share Savings | $25,000 and up | 0.28% | 0.28% |
"""
        ks = self.system(snap("2026-06-20", page("/personal/savings-account", text)))
        self.require_value(ks.answer("What Share Savings APY do I earn with a $15,000 balance?"), "0.18%", ("0.08%", "0.28%"))
        self.assertEqual([], ks.conflicts())

    def test_official_rate_table_outranks_calculator(self):
        ks = self.system(snap(
            "2026-06-20",
            page("/personal/loans/auto-motorcycle-loans", autos("5.80")),
            page("/calculators/vehicle-affordability", autos("5.70"), "Vehicle Affordability Calculator"),
        ))
        a = ks.answer("What is the APR for a 60-month auto loan on a 2025 vehicle?")
        self.require_value(a, "5.80%", ("5.70%",))
        self.assertTrue(a.conflict_note)
        conflicts = ks.conflicts()
        self.assertTrue(any("5.70%" in c.values and "5.80%" in c.values for c in conflicts))

    def test_equal_authority_disagreement_requires_uncertainty(self):
        ks = self.system(snap(
            "2026-06-20",
            page("/rates/certificates", certificate("3.25")),
            page("/rates/certificates-alternate", certificate("3.75")),
        ))
        self.assertFalse(ks.answer("What is the 6-month certificate APY?").confident)
        self.assertTrue(any(c.resolution is None for c in ks.conflicts()))

    def test_numerically_equal_rates_are_not_a_conflict(self):
        ks = self.system(snap(
            "2026-06-20",
            page("/rates/certificates", certificate("3.5")),
            page("/rates/certificates-alternate", certificate("3.50")),
        ))
        answer = ks.answer("What is the 6-month certificate APY?")
        self.assertTrue(answer.confident, answer.text)
        self.assertEqual([], ks.conflicts())

    def test_dedicated_rate_table_outranks_promotion_landing_table(self):
        ks = self.system(snap(
            "2026-06-20",
            page("/personal/loans/auto-motorcycle-loans", autos("5.80")),
            page("/promotions/switch-bonus", autos("5.70"), "Switch and Earn Promotion"),
        ))
        self.require_value(ks.answer("What is the APR for a 60-month auto loan on a 2025 vehicle?"), "5.80%", ("5.70%",))

    def test_wallet_question_does_not_trigger_card_rate_list(self):
        rates = "# Credit Cards\n\n| Card | APR |\n| --- | --- |\n| Platinum Visa | 13.50% |\n| Rewards Visa | 17.50% |"
        wallet = "# Digital Wallet\n\nAdd your debit and credit cards to Apple Pay, Google Pay or Samsung Pay."
        ks = self.system(snap(
            "2026-06-20",
            page("/personal/credit-cards", rates),
            page("/personal/digital-wallet", wallet, "Digital Wallet"),
        ))
        answer = ks.answer("Can I add credit cards to a mobile wallet?")
        self.assertTrue(answer.confident, answer.text)
        for provider in ("Apple Pay", "Google Pay", "Samsung Pay"):
            self.assertIn(provider, answer.text)
        self.assertNotIn("13.50%", answer.text)
        self.assertNotIn("17.50%", answer.text)

    def test_history_without_same_view_disagreement_is_not_a_conflict(self):
        ks = self.system(
            snap("2026-06-01", page("/rates/certificates", certificate("3.25"))),
            snap("2026-07-01", page("/rates/certificates", certificate("3.75"))),
        )
        self.assertEqual([], ks.conflicts())

    def test_expired_promotion_does_not_become_current_when_recrawled(self):
        text = "# Summer Savings Promotion\n\nSummer Savings special: 6-month certificate APY 4.85%. Offer expires June 15, 2026."
        ks = self.system(
            snap("2026-06-01", page("/promotions/summer-savings", text)),
            snap("2026-06-20", page("/promotions/summer-savings", text)),
        )
        self.require_value(ks.answer("What is the 6-month certificate APY?", as_of="2026-06-10"), "4.85%")
        answer = ks.answer("What is the 6-month certificate APY?")
        self.assertTrue(not answer.confident or any(word in answer.text.lower() for word in ("expired", "ended", "no longer")), answer.text)
        self.assertNotIn("can get 4.85%", answer.text.lower())

    def test_unknown_named_fee_cannot_borrow_an_unrelated_fee(self):
        ks = self.system(snap("2026-06-20", page("/fees", "# Fees\n\nLost debit card replacement fee: $4.50\n\nWire transfer fee: $19.00")))
        a = ks.answer("What is the international inheritance certification fee?")
        self.assertFalse(a.confident)
        self.assertNotIn("$4.50", a.text)
        self.assertNotIn("$19.00", a.text)

    def test_branch_weekday_schedule_is_not_replaced_with_general_hours(self):
        text = """# Oak Branch

## Lobby Hours

| Day | Hours |
| --- | --- |
| Monday-Thursday | 8:30 a.m.-5 p.m. |
| Friday | 8:30 a.m.-6 p.m. |
| Saturday | 9 a.m.-noon |
| Sunday | Closed |
"""
        ks = self.system(snap("2026-06-20", page("/branches/oak", text, "Oak Branch")))
        friday = ks.answer("What are Oak Branch lobby hours on Friday?")
        self.assertTrue(friday.confident, friday.text)
        self.assertIn("6", friday.text)
        self.assertNotIn("noon", friday.text.lower())
        sunday = ks.answer("Is the Oak Branch lobby open Sunday?")
        self.assertTrue(sunday.confident, sunday.text)
        self.assertIn("closed", sunday.text.lower())

    def test_named_unpublished_branch_abstains(self):
        ks = self.system(snap("2026-06-20", page("/branches/oak", "# Oak Branch\n\nLobby Hours: Monday-Friday 9 a.m.-5 p.m.")))
        self.assertFalse(ks.answer("What are the lobby hours at the Pine Branch?").confident)

    def test_different_branch_schedules_are_separate_facts(self):
        oak = "# Oak Branch\n\n## Lobby Hours\n\n| Day | Hours |\n| --- | --- |\n| Friday | 8:30 a.m.-6 p.m. |"
        pine = "# Pine Branch\n\n## Lobby Hours\n\n| Day | Hours |\n| --- | --- |\n| Friday | 9 a.m.-5 p.m. |"
        ks = self.system(snap("2026-06-20", page("/branches/oak", oak, "Oak Branch"), page("/branches/pine", pine, "Pine Branch")))
        self.assertEqual([], ks.conflicts())
        answer = ks.answer("What are Oak Branch lobby hours on Friday?")
        self.assertTrue(answer.confident, answer.text)
        self.assertIn("6", answer.text)

    def test_paraphrases_and_repeats_keep_the_same_supported_value(self):
        ks = self.system(snap("2026-06-20", page("/rates/certificates", certificate("3.25"))))
        questions = (
            "What is the 6-month certificate APY?",
            "Current APY on a six month share certificate?",
            "How much annual percentage yield does a 6 month certificate pay?",
        )
        for question in questions:
            with self.subTest(question=question):
                a = ks.answer(question)
                self.require_value(a, "3.25%", ("3.11%",))
                self.assertEqual(a.text, ks.answer(question).text)

    def test_answer_mutation_does_not_poison_cache(self):
        ks = self.system(snap("2026-06-20", page("/rates/certificates", certificate("3.25"))))
        q = "What is the 6-month certificate APY?"
        first = ks.answer(q)
        original = first.text
        first.text = "Caller changed this answer."
        first.sources.clear()
        second = ks.answer(q)
        self.assertEqual(original, second.text)
        self.assertTrue(second.sources)

    def test_ingesting_new_snapshot_invalidates_previous_current_answer(self):
        ks = self.system(snap("2026-06-01", page("/rates/certificates", certificate("3.25"))))
        q = "What is the 6-month certificate APY?"
        self.require_value(ks.answer(q), "3.25%")
        ks.ingest(snap("2026-07-01", page("/rates/certificates", certificate("3.75"))))
        self.require_value(ks.answer(q), "3.75%", ("3.25%",))


if __name__ == "__main__":
    unittest.main()
