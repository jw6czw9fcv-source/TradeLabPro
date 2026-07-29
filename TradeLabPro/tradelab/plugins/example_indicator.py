PLUGIN_NAME = "Example Relative Volume"

def compute(df):
    return df["Volume"] / df["Volume"].rolling(20).mean()
