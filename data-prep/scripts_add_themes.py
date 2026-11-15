"""Add a `themes` column to tickers.csv (multiple themes separated by ';', empty = no theme)."""
import pandas as pd

T, AI, WAR, ESG, CLEAN, VICE, ROBO = (
    "Tech", "AI", "War", "ESG", "Clean Energy", "Vice", "Robotics",
)

THEMES = {
    # --- ETFs ---
    "AIBF": [AI], "AIQ": [T, AI], "BOTZ": [ROBO, AI], "ROBO": [ROBO, AI],
    "DTCR": [AI, T], "SMH": [T, AI], "QQQ": [T], "VGT": [T], "XLK": [T], "XIT.TO": [T],
    "ITA": [WAR], "SHLD": [WAR, T],
    "ESGU": [ESG], "XESG.TO": [ESG], "NSGE.TO": [ESG], "AQWA": [ESG],
    "ICLN": [CLEAN], "TAN": [CLEAN],
    "BETZ": [VICE], "MSOS": [VICE], "NICO": [VICE],
    # --- Tech / AI stocks ---
    "AAPL": [T], "ADBE": [T], "ADI": [T], "ADSK": [T], "AKAM": [T], "AMAT": [T, AI],
    "AMD": [T, AI], "AMZN": [T, AI], "ANET": [T, AI], "APH": [T, AI], "APP": [T],
    "AVGO": [T, AI], "BB.TO": [T], "CAP.PA": [T], "CDNS": [T], "CDW": [T],
    "CIEN": [T, AI], "CLS.TO": [T, AI], "COHR": [T, AI], "COIN": [T], "CRM": [T],
    "CRWD": [T], "CSCO": [T], "CSU.TO": [T], "CTSH": [T], "DDOG": [T],
    "DELL": [T, AI], "DLR": [AI], "DSG.TO": [T], "DSY.PA": [T], "EQIX": [AI],
    "FFIV": [T], "FICO": [T], "FIS": [T], "FISV": [T], "FTNT": [T], "GDDY": [T],
    "GEN": [T], "GIB-A.TO": [T], "GLW": [T, AI], "GOOG": [T, AI], "GOOGL": [T, AI],
    "GPN": [T], "HOOD": [T], "HPE": [T, AI], "HPQ": [T], "IBM": [T, AI],
    "INTC": [T], "INTU": [T], "JBL": [T], "JKHY": [T], "KEYS": [T],
    "KLAC": [T, AI], "KXS.TO": [T], "LITE": [T, AI], "LRCX": [T, AI], "MCHP": [T],
    "META": [T, AI], "MPWR": [T, AI], "MRVL": [T, AI], "MSFT": [T, AI], "MSI": [T],
    "MU": [T, AI], "NFLX": [T], "NOW": [T, AI], "NTAP": [T], "NVDA": [T, AI],
    "NXPI": [T], "OKTA": [T], "ON": [T], "ORCL": [T, AI], "OTEX.TO": [T],
    "PANW": [T], "PTC": [T], "PYPL": [T], "Q": [T, AI], "QCOM": [T],
    "RDDT": [T], "ROP": [T], "SHOP.TO": [T], "SMCI": [T, AI], "SNDK": [T, AI],
    "SNPS": [T], "STMPA.PA": [T], "STX": [T, AI], "SWKS": [T], "TEL": [T],
    "TRMB": [T], "TTWO": [T], "TWLO": [T], "TXN": [T], "TYL": [T], "UBER": [T],
    "VEEV": [T], "VRSN": [T], "WDAY": [T], "WDC": [T, AI], "XYZ": [T],
    "ZBRA": [T], "VNP.TO": [T],
    # Data-center power / infrastructure
    "VRT": [AI], "ETN": [AI], "SU.PA": [AI], "VST": [AI], "FIX": [AI],
    # --- Robotics ---
    "ISRG": [ROBO], "ROK": [ROBO], "SYK": [ROBO], "TER": [T, ROBO],
    "TSLA": [T, AI, ROBO, CLEAN],
    # --- War / weaponry ---
    "LMT": [WAR], "NOC": [WAR], "GD": [WAR], "RTX": [WAR], "LHX": [WAR],
    "HII": [WAR], "LDOS": [WAR, T], "TDG": [WAR], "TXT": [WAR], "BA": [WAR],
    "AXON": [WAR, T], "PLTR": [T, AI, WAR], "HO.PA": [WAR, T], "SAF.PA": [WAR],
    "AIR.PA": [WAR], "HONA": [WAR], "CAE.TO": [WAR], "TDY": [T, WAR],
    "MDA.TO": [T, WAR],
    # --- Clean energy (renewables, nuclear/uranium, lithium, EV) ---
    "FSLR": [CLEAN], "NEE": [CLEAN], "AES": [CLEAN], "BEP-UN.TO": [CLEAN],
    "NPI.TO": [CLEAN], "AQN.TO": [CLEAN], "ENGI.PA": [CLEAN], "BE": [CLEAN, AI],
    "GEV": [CLEAN, AI], "CEG": [CLEAN, AI], "CCO.TO": [CLEAN], "NXE.TO": [CLEAN],
    "DML.TO": [CLEAN], "EFR.TO": [CLEAN], "ALB": [CLEAN], "NFI.TO": [CLEAN],
    # --- ESG (water, waste & recycling) ---
    "VIE.PA": [ESG], "XYL": [ESG], "AWK": [ESG], "WM": [ESG], "RSG": [ESG],
    "WCN.TO": [ESG], "GFL.TO": [ESG],
    # --- Vice (alcohol, tobacco, cannabis, gambling) ---
    "MO": [VICE], "PM": [VICE], "BF-B": [VICE], "STZ": [VICE], "RI.PA": [VICE],
    "LVS": [VICE], "WYNN": [VICE], "MGM": [VICE], "VICI": [VICE], "CURA.TO": [VICE],
}

df = pd.read_csv("tickers.csv")
unknown = set(THEMES) - set(df["ticker"])
assert not unknown, f"Tickers not in CSV: {unknown}"
df["themes"] = df["ticker"].map(lambda t: ";".join(THEMES[t]) if t in THEMES else None)
df.to_csv("tickers.csv", index=False)
print(df["themes"].notna().sum(), "tagged /", len(df))
print(df["themes"].str.split(";").explode().value_counts())
