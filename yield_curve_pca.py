"""Yield curve PCA on US Treasuries.

Downloads daily constant-maturity Treasury yields from FRED, runs PCA on the
daily changes, and saves three charts to the charts/ folder.

Run:  python yield_curve_pca.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

START = "2006-01-01"
# FRED series ID -> maturity in years
SERIES = {
    "DGS3MO": 0.25, "DGS6MO": 0.5, "DGS1": 1, "DGS2": 2, "DGS3": 3,
    "DGS5": 5, "DGS7": 7, "DGS10": 10, "DGS20": 20, "DGS30": 30,
}
DATA_FILE = Path("data/treasury_yields.csv")
CHART_DIR = Path("charts")


def load_yields() -> pd.DataFrame:
    """Daily yields in percent, one column per maturity. Cached after first download."""
    if DATA_FILE.exists():
        return pd.read_csv(DATA_FILE, index_col=0, parse_dates=True)
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={','.join(SERIES)}&cosd={START}"
    df = pd.read_csv(url, index_col=0, parse_dates=True, na_values=".")
    df = df.dropna()  # drop holidays and days with any missing maturity
    DATA_FILE.parent.mkdir(exist_ok=True)
    df.to_csv(DATA_FILE)
    return df


def run_pca(yields: pd.DataFrame, n: int = 3):
    """PCA on daily yield changes in basis points."""
    changes = yields.diff().dropna() * 100
    pca = PCA(n_components=n)
    scores = pd.DataFrame(pca.fit_transform(changes), index=changes.index,
                          columns=[f"PC{i + 1}" for i in range(n)])
    loadings = pd.DataFrame(pca.components_.T, index=yields.columns, columns=scores.columns)
    # Sign is arbitrary in PCA: flip so PC1 is "yields up" and PC2 is "curve steeper"
    for pc, sign in [("PC1", loadings["PC1"].sum()),
                     ("PC2", loadings["PC2"].iloc[-1] - loadings["PC2"].iloc[0])]:
        if sign < 0:
            loadings[pc] *= -1
            scores[pc] *= -1
    return pca, loadings, scores


def make_charts(pca, loadings, scores):
    CHART_DIR.mkdir(exist_ok=True)
    names = ["PC1 (level)", "PC2 (slope)", "PC3 (curvature)"]
    maturities = [SERIES[c] for c in loadings.index]

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(names, pca.explained_variance_ratio_ * 100)
    ax.set_ylabel("% of variance explained")
    ax.set_title("Three factors explain almost all curve moves")
    fig.tight_layout(); fig.savefig(CHART_DIR / "variance_explained.png", dpi=150)

    fig, ax = plt.subplots(figsize=(7, 4))
    for col, name in zip(loadings.columns, names):
        ax.plot(maturities, loadings[col], marker="o", label=name)
    ax.axhline(0, color="grey", lw=0.8)
    ax.set_xscale("log"); ax.set_xticks(maturities)
    ax.set_xticklabels([c.replace("DGS", "") for c in loadings.index])
    ax.set_xlabel("Maturity"); ax.set_ylabel("Loading"); ax.legend()
    ax.set_title("Factor loadings by maturity")
    fig.tight_layout(); fig.savefig(CHART_DIR / "loadings.png", dpi=150)

    fig, ax = plt.subplots(figsize=(9, 4))
    scores.cumsum().plot(ax=ax)
    ax.legend(names); ax.set_xlabel(""); ax.set_ylabel("Cumulative factor score (bp)")
    ax.set_title("Factors over time")
    fig.tight_layout(); fig.savefig(CHART_DIR / "factors_over_time.png", dpi=150)


# Fed funds target at 0-0.25%: Dec 2008 to Dec 2015, and Mar 2020 to Mar 2022
ZERO_RATE = [("2008-12-16", "2015-12-16"), ("2020-03-16", "2022-03-16")]
HIKING_ON = "2022-03-17"


def compare_samples(yields: pd.DataFrame):
    """Extension: rerun the PCA without bills, and separately by Fed regime."""
    # diff() across the gap between the two zero-rate periods would create one fake jump
    zero_mask = np.zeros(len(yields), dtype=bool)
    for a, b in ZERO_RATE:
        zero_mask |= (yields.index >= a) & (yields.index <= b)
    changes = yields.diff() * 100

    samples = {
        "Full sample, all maturities": yields,
        "Full sample, 2y to 30y only": yields.loc[:, "DGS2":],
        "Zero-rate years (2008-15, 2020-22)": None,  # handled below
        "2022 onwards": yields.loc[HIKING_ON:],
    }
    rows, pc1 = {}, {}
    for name, sample in samples.items():
        if sample is None:
            ch = changes[zero_mask].dropna()
            pca = PCA(n_components=3).fit(ch)
            load = pd.Series(pca.components_[0], index=yields.columns)
        else:
            pca, loadings, _ = run_pca(sample)
            load = loadings["PC1"]
        if load.sum() < 0:
            load = -load
        rows[name] = np.round(pca.explained_variance_ratio_ * 100, 1)
        pc1[name] = load
    table = pd.DataFrame(rows, index=["PC1", "PC2", "PC3"]).T
    table["Total"] = table.sum(axis=1).round(1)

    fig, ax = plt.subplots(figsize=(7, 4))
    for name in ["Zero-rate years (2008-15, 2020-22)", "2022 onwards"]:
        ax.plot([SERIES[c] for c in pc1[name].index], pc1[name], marker="o", label=name)
    mats = list(SERIES.values())
    ax.set_xscale("log"); ax.set_xticks(mats)
    ax.set_xticklabels([c.replace("DGS", "") for c in SERIES])
    ax.set_ylim(bottom=0); ax.set_xlabel("Maturity"); ax.set_ylabel("PC1 loading"); ax.legend()
    ax.set_title("The level factor by Fed regime")
    fig.tight_layout(); fig.savefig(CHART_DIR / "pc1_by_regime.png", dpi=150)
    return table


if __name__ == "__main__":
    yields = load_yields()
    pca, loadings, scores = run_pca(yields)
    print(f"{len(yields)} days, {yields.index[0].date()} to {yields.index[-1].date()}")
    print("\nVariance explained (%):")
    print(np.round(pca.explained_variance_ratio_ * 100, 1),
          f"total {pca.explained_variance_ratio_.sum() * 100:.1f}")
    print("\nLoadings:")
    print(loadings.round(2))
    make_charts(pca, loadings, scores)
    print("\nVariance explained (%) by sample:")
    print(compare_samples(yields).to_string())
    print(f"\nCharts saved to {CHART_DIR}/")
