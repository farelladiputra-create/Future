"""Buffett: a value-investing screener and daily briefing agent for US equities.

Pipeline: universe -> audited fundamentals (SEC EDGAR XBRL) -> quality gates ->
intrinsic value triangulation -> margin of safety -> fractional Kelly sizing ->
tranche schedule -> Claude memo -> report + notification.
"""

__version__ = "1.0.0"
