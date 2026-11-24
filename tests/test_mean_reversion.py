import unittest
import pandas as pd

from mean_reversion import add_mr_indicators, simulate_mr, simulate_mr_variant
from unittest.mock import patch


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


    def test_variant_b_waits_for_two_of_three_recovery_closes(self):
        frame = self.frame.iloc[:8].copy()
        fake = frame.copy()
        fake["ATR14"] = 1.0
        fake["MR_BB_MID"] = 200.0
        fake["MR_BB_LOWER"] = 95.0
        fake["MR_RSI2"] = 5.0
        fake["MR_ENTRY_SIGNAL"] = False
        fake.iloc[1, fake.columns.get_loc("MR_ENTRY_SIGNAL")] = True
        fake.iloc[2, fake.columns.get_loc("Close")] = 96.0
        fake.iloc[3, fake.columns.get_loc("Close")] = 97.0
        fake.iloc[4, fake.columns.get_loc("Open")] = 104.0
        with patch("mean_reversion.add_mr_indicators", return_value=fake):
            trades = simulate_mr_variant("TEST", self.instrument, frame, self.config, "B")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["signal_date"], str(fake.index[1].date()))
        self.assertEqual(trades[0]["entry_date"], str(fake.index[4].date()))
        self.assertAlmostEqual(trades[0]["entry_price"], 104.0)
        self.assertEqual(trades[0]["variant"], "B")

    def test_variant_c_requires_lower_band_walk_and_enters_next_open(self):
        frame = self.frame.iloc[:6].copy()
        fake = frame.copy()
        fake["ATR14"] = 1.0
        fake["MR_BB_MID"] = 200.0
        fake["MR_BB_LOWER"] = [103.0, 102.0, 101.0, 100.0, 99.0, 98.0]
        fake["MR_RSI2"] = 5.0
        fake["MR_ENTRY_SIGNAL"] = False
        fake.iloc[4, fake.columns.get_loc("MR_ENTRY_SIGNAL")] = True
        fake.iloc[5, fake.columns.get_loc("Open")] = 105.0
        fake.iloc[3, fake.columns.get_loc("Close")] = 100.5
        fake.iloc[4, fake.columns.get_loc("Close")] = 99.5
        fake.iloc[5, fake.columns.get_loc("Close")] = 97.5
        with patch("mean_reversion.add_mr_indicators", return_value=fake):
            trades = simulate_mr_variant("TEST", self.instrument, frame, self.config, "C")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["entry_date"], str(fake.index[5].date()))
        self.assertAlmostEqual(trades[0]["entry_price"], 105.0)
        self.assertEqual(trades[0]["variant"], "C")



    def test_variant_d_stages_two_addons_after_fresh_walking_confirmations(self):
        frame = self.frame.iloc[:11].copy()
        fake = frame.copy()
        fake["ATR14"] = 1.0
        fake["MR_BB_MID"] = 200.0
        fake["MR_BB_LOWER"] = [110,109,108,107,106,105,104,103,102,101,100]
        fake["MR_RSI2"] = 5.0
        fake["MR_ENTRY_SIGNAL"] = False
        fake.iloc[2, fake.columns.get_loc("MR_ENTRY_SIGNAL")] = True
        # Entry 40% at row 3. First fresh 2/3 lower-band walk at row 5
        # schedules 30% at row 6. A reset follows; a second fresh walk at row 9
        # schedules the final 30% at row 10.
        fake["Close"] = [115,115,109,120,106,105,115,116,102,101,100]
        fake["Low"] = fake["Close"] - 0.2
        fake.iloc[3, fake.columns.get_loc("Open")] = 100.0
        fake.iloc[6, fake.columns.get_loc("Open")] = 99.0
        fake.iloc[10, fake.columns.get_loc("Open")] = 98.5
        cfg = dict(self.config, mr_d_tranche_weights=[0.4, 0.3, 0.3], mr_walking_tolerance=0.015)
        with patch("mean_reversion.add_mr_indicators", return_value=fake):
            trades = simulate_mr_variant("TEST", self.instrument, frame, cfg, "D")
        self.assertEqual(len(trades), 1)
        trade = trades[0]
        self.assertEqual(trade["variant"], "D")
        self.assertEqual(trade["tranche_count"], 3)
        self.assertEqual(trade["tranche_weights_pct"], [40.0, 30.0, 30.0])
        self.assertEqual(trade["tranche_entry_dates"], [
            str(fake.index[3].date()), str(fake.index[5].date()), str(fake.index[10].date())
        ])
        self.assertAlmostEqual(trade["deployed_weight_pct"], 100.0)
        self.assertIn("regime", trade)
        self.assertIn("net_30bps_on_deployed_pct", trade)
        self.assertAlmostEqual(
            trade["net_30bps_on_deployed_pct"],
            trade["net_30bps_pct"] / (trade["deployed_weight_pct"] / 100.0),
            places=4
        )

if __name__ == "__main__":
    unittest.main()
