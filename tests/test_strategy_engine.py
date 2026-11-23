import unittest
import pandas as pd
from strategy import add_indicators
from paper_engine import blank_state, process_bar

CFG={"atr_period":14,"donchian_period":20,"bollinger_period":20,"bollinger_std":2,
     "walking_tolerance":0.015,"walking_window":3,"walking_required_bars":2,
     "atr_stop_multiple":2,"max_holding_sessions":10}

class StrategyTests(unittest.TestCase):
    def test_donchian_excludes_current_bar(self):
        idx=pd.date_range("2025-01-01",periods=30,freq="B")
        close=[100.0+i*.1 for i in range(30)]
        df=pd.DataFrame({"Open":close,"High":[x+.2 for x in close],
                         "Low":[x-.2 for x in close],"Close":close},index=idx)
        out=add_indicators(df,CFG)
        self.assertAlmostEqual(out.iloc[-1].DONCHIAN20_UPPER,max(df.High.iloc[-21:-1]))

    def test_paper_entry_is_next_open(self):
        s=blank_state()
        inst={"classification":"LEVA_LONG","name":"Test ETP"}
        row=lambda op,lo,cl,signal,atr=1,walk=True: type("Bar",(),{
            "Open":op,"Low":lo,"Close":cl,"ENTRY_SIGNAL":signal,"ATR14":atr,
            "WALKING":walk,"DONCHIAN20_UPPER":cl-0.1,"WALKING_BAR":True})()
        process_bar(s,"T",inst,"2026-01-02",row(100,99,100,True),CFG)
        self.assertIn("T",s["pending_entries"])
        self.assertNotIn("T",s["positions"])
        process_bar(s,"T",inst,"2026-01-05",row(102,101,103,False),CFG)
        self.assertEqual(s["positions"]["T"]["entry_price"],102)

    def test_atr_stop(self):
        s=blank_state(); inst={"classification":"LEVA_SHORT","name":"Inverse"}
        row=lambda op,lo,cl,signal,atr=1,walk=True: type("Bar",(),{
            "Open":op,"Low":lo,"Close":cl,"ENTRY_SIGNAL":signal,"ATR14":atr,
            "WALKING":walk,"DONCHIAN20_UPPER":cl-0.1,"WALKING_BAR":True})()
        process_bar(s,"T",inst,"2026-01-02",row(100,99,100,True,2),CFG)
        process_bar(s,"T",inst,"2026-01-05",row(101,100,102,False),CFG)
        self.assertEqual(s["positions"]["T"]["stop_price"],97)
        process_bar(s,"T",inst,"2026-01-06",row(98,96,97,False),CFG)
        self.assertEqual(s["trades"][0]["exit_reason"],"ATR14_X2_STOP")

if __name__=="__main__": unittest.main()
