import unittest
import pandas as pd

from mean_reversion import add_mr_indicators, simulate_mr


class MeanReversionTests(unittest.TestCase):
    def setUp(self):
        prices = [100 + i * 0.05 for i in range(30)] + [95, 88, 87, 90, 94, 98, 102, 106]
        index = pd.date_range("2025-01-01", periods=len(prices), freq="D")
        self.frame = pd.DataFrame({
            "Open": prices,
            "High": [x + 0.5 for x in prices],
            "Low": [x - 0.5 for x in prices],
            "Close": prices,
            "Volume": [1000] * len(prices),
        }, index=index)
        self.config = {
            "mr_bollinger_period": 20,
            "mr_bollinger_std": 2,
            "mr_rsi_entry": 10,
            "atr_period": 14,
            "mr_atr_stop_multiple": 2,
            "mr_max_holding_sessions": 10,
            "costs_bps_round_trip": [20, 30, 50],
        }
        self.instrument = {"name": "Synthetic test", "classification": "LEVA_LONG"}

    def test_mr_signal_has_independent_atr(self):
        indicated = add_mr_indicators(self.frame, self.config)
        self.assertTrue(indicated["MR_ENTRY_SIGNAL"].any())
        self.assertTrue(indicated.loc[indicated["MR_ENTRY_SIGNAL"], "ATR14"].notna().all())

    def test_mr_simulation_opens_trade_next_session(self):
        trades = simulate_mr("TEST", self.instrument, self.frame, self.config)
        self.assertGreaterEqual(len(trades), 1)
        self.assertEqual(trades[0]["entry_date"], "2025-02-01")
        self.assertAlmostEqual(trades[0]["entry_price"], 88.0)
        self.assertEqual(trades[0]["strategy"], "MEAN_REVERSION")


if __name__ == "__main__":
    unittest.main()
