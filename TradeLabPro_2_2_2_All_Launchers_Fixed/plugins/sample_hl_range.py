"""Sample TradeLabPro plugin.

Copy this file, rename it, and change PLUGIN_NAME + compute() to make your
own indicator. Once the file is in this ``plugins/`` folder it is picked up
automatically (use "Reload plugins" on the Plugins tab) and becomes usable
as a field in the Scanner's Custom Filters and the Strategy Builder.

Requirements:
- PLUGIN_NAME: a short display name (string).
- compute(df): takes an OHLCV DataFrame (columns Open/High/Low/Close/Volume)
  and returns a pandas Series aligned to df's index.
"""
PLUGIN_NAME = "High-Low Range %"


def compute(df):
    # Daily high-low range as a percent of close - a simple volatility read.
    return (df["High"] - df["Low"]) / df["Close"].replace(0, float("nan")) * 100.0
