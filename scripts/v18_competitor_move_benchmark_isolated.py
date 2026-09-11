#!/usr/bin/env python3
"""Run the V18 competitor benchmark with a cold Stockfish TT for every root probe.

The base benchmark deliberately keeps all selection, clock reconstruction, scoring and reporting in
one place.  This wrapper changes only the oracle state policy: before every unrestricted or
root-restricted Stockfish analysis it presses Stockfish's UCI `Clear Hash` button.  Historical and
candidate moves therefore receive genuinely independent equal-node searches, regardless of analysis
order or whether the historical move matched the previous unrestricted PV.
"""
from __future__ import annotations

from typing import Any

import v18_competitor_move_benchmark as base


class IsolatedStockfishTeacher(base.StockfishTeacher):
    def analyse(self, *args: Any, **kwargs: Any) -> Any:
        if self.engine is None:
            raise RuntimeError("teacher must be used as a context manager")
        self.engine.configure({"Clear Hash": None})
        return super().analyse(*args, **kwargs)


def main() -> int:
    base.StockfishTeacher = IsolatedStockfishTeacher
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
