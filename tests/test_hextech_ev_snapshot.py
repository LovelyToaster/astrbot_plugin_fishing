"""Regression bounds using the anonymized read-only server snapshot."""
import json
from pathlib import Path
import unittest

from core.services.hextech_gacha_balance import (
    expected_cycle_value, expected_cycle_probabilities,
    max_chance_for_budget, max_weight_multiplier_for_budget,
)
from core.services.hextech_game_balance import expected_best_value, budgeted_chance


class ServerSnapshotBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = json.loads((Path(__file__).parent / "fixtures" /
                                   "hextech_ev_snapshot.json").read_text(encoding="utf-8"))

    def test_real_pool_value_and_unpriced_probability_bounds(self):
        for pool in self.snapshot["pools"]:
            items = pool["entries"]
            rarity = lambda item: item["rarity"]
            value = lambda item: item["reference_value"]
            pity = 80 if pool["paid"] else 0
            baseline = expected_cycle_value(items, rarity, value, pity)
            probabilities = expected_cycle_probabilities(items, rarity, pity)
            for budget in (0.05, 0.065, 0.08, 0.04, 0.055, 0.07, 0.01, 0.01375, 0.0175):
                for effect in ("C27", "P13", "G13"):
                    with self.subTest(pool=pool["name"], budget=budget, effect=effect):
                        chance, multiplier = 0.0, 1.0
                        if effect == "G13":
                            multiplier = max_weight_multiplier_for_budget(
                                items, rarity, value, budget, 1.15, pity)
                        else:
                            chance = max_chance_for_budget(
                                items, rarity, value, budget, 1.0, pity, effect)
                        if baseline is not None:
                            adjusted = expected_cycle_value(
                                items, rarity, value, pity, effect, chance, multiplier)
                            self.assertLessEqual(adjusted, baseline * (1 + budget) + 1e-6)
                        else:
                            adjusted = expected_cycle_probabilities(
                                items, rarity, pity, effect, chance, multiplier)
                            for key, probability in probabilities.items():
                                self.assertLessEqual(adjusted.get(key, 0),
                                                     probability * (1 + budget) + 1e-10)

    def test_real_inventory_selectors_stay_in_budget(self):
        for rows in self.snapshot["ponds"]:
            values = [row["transfer_value"] for row in rows]
            baseline = sum(values) / len(values)
            for draws in (2, 3):
                gain = expected_best_value(values, draws) - baseline
                for budget in (0.05, 0.065, 0.08, 0.04, 0.055, 0.07, 0.01, 0.01375, 0.0175):
                    chance = budgeted_chance(baseline, gain, budget)
                    self.assertLessEqual(chance * gain, budget * baseline + 1e-6)


if __name__ == "__main__":
    unittest.main()
