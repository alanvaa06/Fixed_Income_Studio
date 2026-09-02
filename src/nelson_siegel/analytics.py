"""
Fixed-income analytics on top of a fitted curve or a yield panel.

Everything here is model-agnostic: a *curve* is any object with
``predict(maturities)`` returning continuously compounded zero yields in
decimals (Nelson-Siegel, Svensson, Vasicek, CIR ... all qualify), or a plain
callable with the same signature.

Contents
--------
- :class:`Bond` and the pricing toolkit: price from a curve, yield to maturity,
  price from yield, Macaulay/modified duration, convexity, DV01, z-spread,
  key-rate durations (tent bumps of the zero curve).
- :func:`carry_roll_down` - expected return of riding the curve, split into
  carry and roll-down for a grid of maturities.
- :func:`forward_rate_table` - the forwards traders quote (1y1y, 2y1y, 5y5y ...).
- :func:`curve_spreads` - 2s10s, 5s30s, 3m10y and the 2s5s10s butterfly from a
  curve or as time series from a panel.
- :func:`rich_cheap` - residuals ranked as cheap/rich versus the model curve.
- :func:`pca_yield_changes` - principal components of yield changes (the
  empirical level/slope/curvature).
- :func:`curve_changes` - moves over standard look-backs for a market monitor.

Rates are decimals; ``*_bps`` helpers convert to basis points.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
from scipy.optimize import brentq

Curve = Union[Callable[[np.ndarray], np.ndarray], object]
BP = 1e-4


def _zero(curve: Curve, t: np.ndarray) -> np.ndarray:
    """Zero yields from a model (``predict``) or a callable."""
    t = np.asarray(t, dtype=float)
    fn = getattr(curve, "predict", None)
    if fn is None:
        fn = curve  # type: ignore[assignment]
    return np.asarray(fn(t), dtype=float)


def discount_factors(curve: Curve, t: np.ndarray) -> np.ndarray:
    t = np.asarray(t, dtype=float)
    return np.exp(-t * _zero(curve, t))


# --------------------------------------------------------------------------- #
# Bond definition and cash flows
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Bond:
    """A plain fixed-coupon bullet bond.

    ``coupon`` is the annual coupon rate (decimal), paid ``frequency`` times a
    year; ``maturity`` in years from today (fractional first period allowed).
    """

    maturity: float
    coupon: float = 0.0
    frequency: int = 2
    face: float = 100.0

    def __post_init__(self) -> None:
        if self.maturity <= 0:
            raise ValueError("maturity must be positive")
        if self.frequency < 1:
            raise ValueError("frequency must be at least 1")
        if self.coupon < 0:
            raise ValueError("coupon cannot be negative")

    def cash_flows(self) -> Tuple[np.ndarray, np.ndarray]:
        """``(times, amounts)`` of remaining cash flows, times in years ascending."""
        step = 1.0 / self.frequency
        n = int(np.ceil(self.maturity / step - 1e-9))
        times = self.maturity - step * np.arange(n)[::-1]
        times = times[times > 1e-9]
        amounts = np.full(len(times), self.face * self.coupon * step)
        amounts[-1] += self.face
        return times, amounts


def price_from_curve(bond: Bond, curve: Curve) -> float:
    """Present value of the cash flows discounted on the zero curve."""
    times, amounts = bond.cash_flows()
    return float(np.sum(amounts * discount_factors(curve, times)))


def price_from_yield(bond: Bond, ytm: float) -> float:
    """Price for a yield to maturity compounded ``bond.frequency`` times a year."""
    times, amounts = bond.cash_flows()
    return float(np.sum(amounts / (1.0 + ytm / bond.frequency) ** (times * bond.frequency)))


def yield_to_maturity(bond: Bond, price: float) -> float:
    """Yield (``frequency``-compounded) that reprices the bond."""
    if price <= 0:
        raise ValueError("price must be positive")
    f = lambda y: price_from_yield(bond, y) - price  # noqa: E731
    return float(brentq(f, -0.99 * bond.frequency + 1e-9, 5.0, xtol=1e-12, maxiter=200))


def duration_convexity(bond: Bond, ytm: float) -> Dict[str, float]:
    """Macaulay and modified duration, convexity, DV01 and price at ``ytm``."""
    times, amounts = bond.cash_flows()
    k = bond.frequency
    disc = (1.0 + ytm / k) ** (-times * k)
    pv = amounts * disc
    price = float(pv.sum())
    macaulay = float(np.sum(times * pv) / price)
    modified = macaulay / (1.0 + ytm / k)
    convexity = float(np.sum(pv * times * (times + 1.0 / k)) / price / (1.0 + ytm / k) ** 2)
    return {
        "price": price,
        "ytm": float(ytm),
        "macaulay_duration": macaulay,
        "modified_duration": modified,
        "convexity": convexity,
        "dv01": modified * price * BP,
    }


def z_spread(bond: Bond, price: float, curve: Curve) -> float:
    """Constant spread over the zero curve that reprices the bond (decimal)."""
    times, amounts = bond.cash_flows()
    z = _zero(curve, times)

    def pv(s: float) -> float:
        return float(np.sum(amounts * np.exp(-(z + s) * times))) - price

    return float(brentq(pv, -0.5, 1.0, xtol=1e-12, maxiter=200))


def key_rate_durations(
    bond: Bond,
    curve: Curve,
    key_tenors: Sequence[float] = (0.25, 1, 2, 3, 5, 7, 10, 20, 30),
    bump: float = BP,
) -> pd.Series:
    """Key-rate durations from tent-shaped bumps of the zero curve.

    Each key rate is shocked by ``bump`` with linear interpolation to zero at
    the neighbouring key tenors (flat beyond the ends); the durations sum to
    approximately the modified duration measured on the zero curve.
    """
    keys = np.asarray(sorted(float(k) for k in key_tenors))
    times, amounts = bond.cash_flows()
    base_z = _zero(curve, times)
    base_price = float(np.sum(amounts * np.exp(-base_z * times)))
    out = {}
    for i, k in enumerate(keys):
        # Tent weight: 1 at the key tenor, 0 at the neighbouring keys, flat beyond the ends.
        xp = [k]
        fp = [1.0]
        if i > 0:
            xp = [keys[i - 1]] + xp
            fp = [0.0] + fp
        if i + 1 < len(keys):
            xp = xp + [keys[i + 1]]
            fp = fp + [0.0]
        w = np.interp(times, xp, fp)
        up = float(np.sum(amounts * np.exp(-(base_z + bump * w) * times)))
        down = float(np.sum(amounts * np.exp(-(base_z - bump * w) * times)))
        out[k] = -(up - down) / (2.0 * bump * base_price)
    return pd.Series(out, name="key_rate_duration")


def bond_report(bond: Bond, curve: Curve, price: Optional[float] = None, key_tenors: Optional[Sequence[float]] = None) -> Dict[str, object]:
    """One-stop analytics: model price, yield, risk measures, spread, key-rate durations."""
    model_price = price_from_curve(bond, curve)
    market = model_price if price is None else float(price)
    ytm = yield_to_maturity(bond, market)
    risk = duration_convexity(bond, ytm)
    krd = key_rate_durations(bond, curve, key_tenors or (0.25, 1, 2, 3, 5, 7, 10, 20, 30))
    return {
        "model_price": model_price,
        "market_price": market,
        "ytm": ytm,
        "model_ytm": yield_to_maturity(bond, model_price),
        "z_spread": z_spread(bond, market, curve),
        **{k: v for k, v in risk.items() if k not in {"price", "ytm"}},
        "key_rate_durations": krd,
        "cash_flows": bond.cash_flows(),
    }


# --------------------------------------------------------------------------- #
# Curve-riding, forwards, spreads
# --------------------------------------------------------------------------- #
def carry_roll_down(
    curve: Curve,
    maturities: Sequence[float] = (2, 3, 5, 7, 10, 20, 30),
    horizon: float = 1.0,
) -> pd.DataFrame:
    """Expected return of holding zero-coupon bonds for ``horizon`` years if the curve does not move.

    Maturities at or below the horizon are dropped. Per maturity ``T`` (basis points, annualised over the horizon):
    ``carry`` = ``y(T) - y(h)`` (yield pickup over funding at the horizon rate),
    ``roll_down`` = ``(y(T) - y(T-h)) * (T-h) / h`` (price gain from sliding down
    the curve), ``total`` = carry + roll_down. Also reports the forward yield
    ``f(h, T)`` the market implies for the same bond at the horizon: when the
    curve is expected to realise the forwards the total return is exactly the
    horizon rate, so ``total`` is the reward for betting against the forwards.
    """
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    mats = np.asarray([float(m) for m in maturities if float(m) > horizon])
    if mats.size == 0:
        raise ValueError("no maturity exceeds the horizon")
    y_T = _zero(curve, mats)
    y_h = float(_zero(curve, np.array([horizon]))[0])
    y_roll = _zero(curve, mats - horizon)
    carry = (y_T - y_h)
    roll = (y_T - y_roll) * (mats - horizon) / horizon
    forward = (mats * y_T - horizon * y_h) / (mats - horizon)
    return pd.DataFrame(
        {
            "yield": y_T,
            "horizon_yield": y_roll,
            "forward_yield": forward,
            "carry_bps": carry / BP,
            "roll_down_bps": roll / BP,
            "total_bps": (carry + roll) / BP,
        },
        index=pd.Index(mats, name="maturity"),
    )


def forward_rate(curve: Curve, start: float, end: float) -> float:
    """Continuously compounded forward between ``start`` and ``end`` (years)."""
    if end <= start:
        raise ValueError("end must exceed start")
    if start <= 0:
        return float(_zero(curve, np.array([end]))[0])
    y_s, y_e = _zero(curve, np.array([start, end]))
    return float((end * y_e - start * y_s) / (end - start))


def forward_rate_table(
    curve: Curve,
    pairs: Sequence[Tuple[float, float]] = ((1, 1), (2, 1), (3, 2), (5, 5), (10, 10), (1, 2), (2, 3)),
) -> pd.DataFrame:
    """Forwards in trader notation: ``(start, tenor)`` -> e.g. ``5y5y``."""
    rows = []
    for start, tenor in pairs:
        rows.append(
            {
                "label": f"{_fmt_tenor(start)}{_fmt_tenor(tenor)}",
                "start": float(start),
                "tenor": float(tenor),
                "forward": forward_rate(curve, float(start), float(start + tenor)),
                "spot_to_end": float(_zero(curve, np.array([start + tenor]))[0]),
            }
        )
    frame = pd.DataFrame(rows).set_index("label")
    frame["spread_vs_spot_bps"] = (frame["forward"] - frame["spot_to_end"]) / BP
    return frame


def _fmt_tenor(years: float) -> str:
    years = float(years)
    if years < 1:
        return f"{int(round(years * 12))}m"
    return f"{int(years) if float(years).is_integer() else years}y"


SPREAD_DEFINITIONS: Dict[str, Tuple[Tuple[float, float], ...]] = {
    "3m10y": ((10.0, 1.0), (0.25, -1.0)),
    "2s5s": ((5.0, 1.0), (2.0, -1.0)),
    "2s10s": ((10.0, 1.0), (2.0, -1.0)),
    "5s30s": ((30.0, 1.0), (5.0, -1.0)),
    "10s30s": ((30.0, 1.0), (10.0, -1.0)),
    "2s5s10s": ((5.0, 2.0), (2.0, -1.0), (10.0, -1.0)),
    "5s10s30s": ((10.0, 2.0), (5.0, -1.0), (30.0, -1.0)),
}


def curve_spreads(source: Union[Curve, pd.DataFrame], definitions: Optional[Dict[str, Tuple[Tuple[float, float], ...]]] = None) -> Union[pd.Series, pd.DataFrame]:
    """Standard curve spreads and butterflies in basis points.

    From a curve model: a Series (one value per spread). From a panel
    (columns = maturities in years, linearly interpolated): a DataFrame with
    one column per spread over time.
    """
    defs = definitions or SPREAD_DEFINITIONS
    if isinstance(source, pd.DataFrame):
        from .term_premium import interpolate_maturities

        needed = sorted({m for legs in defs.values() for m, _ in legs})
        grid = interpolate_maturities(source, needed)
        out = {}
        for name, legs in defs.items():
            out[name] = sum(w * grid[float(m)] for m, w in legs) / BP
        return pd.DataFrame(out, index=source.index)
    out_s = {}
    for name, legs in defs.items():
        out_s[name] = float(sum(w * _zero(source, np.array([m]))[0] for m, w in legs)) / BP
    return pd.Series(out_s, name="spread_bps")


def rich_cheap(curve: Curve, maturities: Sequence[float], observed: Sequence[float]) -> pd.DataFrame:
    """Residuals versus the model curve, ranked from cheapest to richest.

    ``residual_bps`` = observed - fitted; positive means the bond yields more
    than the curve (cheap), negative means rich. ``z`` scales by the
    cross-sectional residual standard deviation.
    """
    mats = np.asarray(maturities, dtype=float)
    obs = np.asarray(observed, dtype=float)
    fitted = _zero(curve, mats)
    resid = (obs - fitted) / BP
    sd = float(np.std(resid, ddof=1)) if len(resid) > 1 else float("nan")
    frame = pd.DataFrame(
        {
            "observed": obs,
            "fitted": fitted,
            "residual_bps": resid,
            "z": resid / sd if sd and np.isfinite(sd) and sd > 0 else np.nan,
            "verdict": np.where(resid > 0, "cheap", "rich"),
        },
        index=pd.Index(mats, name="maturity"),
    )
    frame["rank"] = frame["residual_bps"].rank(ascending=False).astype(int)
    return frame.sort_values("residual_bps", ascending=False)


# --------------------------------------------------------------------------- #
# Panel analytics
# --------------------------------------------------------------------------- #
def pca_yield_changes(panel: pd.DataFrame, n_components: int = 3, diff: bool = True) -> Dict[str, object]:
    """Principal components of yield changes (or levels with ``diff=False``).

    Returns explained variance ratios, loadings (maturity x component, with
    the sign convention level > 0, slope rising with maturity, curvature
    positive in the belly), and the component scores over time in basis points.
    """
    data = panel.dropna(how="any")
    if diff:
        data = data.diff().dropna()
    if len(data) < n_components + 2:
        raise ValueError("Not enough observations for PCA")
    X = data.to_numpy(dtype=float)
    X = X - X.mean(axis=0)
    U, S, Vt = np.linalg.svd(X, full_matrices=False)
    k = min(n_components, Vt.shape[0])
    loadings = Vt[:k].T.copy()  # maturities x k
    mats = np.asarray([float(c) for c in data.columns])
    for j in range(k):
        v = loadings[:, j]
        if j == 0 and v.sum() < 0:
            loadings[:, j] = -v
        elif j == 1 and (v[-1] - v[0]) < 0:
            loadings[:, j] = -v
        elif j == 2 and (v[len(v) // 2] - 0.5 * (v[0] + v[-1])) < 0:
            loadings[:, j] = -v
    scores = X @ loadings
    ratio = (S**2 / np.sum(S**2))[:k]
    names = ["Level", "Slope", "Curvature"][:k] + [f"PC{j + 1}" for j in range(3, k)]
    return {
        "explained_variance": [float(v) for v in ratio],
        "loadings": pd.DataFrame(loadings, index=pd.Index(mats, name="maturity"), columns=names),
        "scores": pd.DataFrame(scores / BP, index=data.index, columns=names),
        "n_obs": int(len(data)),
        "on_changes": bool(diff),
    }


def curve_changes(panel: pd.DataFrame, lookbacks: Sequence[int] = (1, 5, 21, 63, 252)) -> pd.DataFrame:
    """Latest curve and its changes (bps) versus ``lookbacks`` observations ago."""
    data = panel.dropna(how="all")
    if data.empty:
        raise ValueError("empty panel")
    latest = data.iloc[-1]
    out = pd.DataFrame({"yield": latest})
    for lb in lookbacks:
        if len(data) > lb:
            out[f"chg_{lb}_bps"] = (latest - data.iloc[-1 - lb]) / BP
        else:
            out[f"chg_{lb}_bps"] = np.nan
    out.index = pd.Index([float(c) for c in out.index], name="maturity")
    out.attrs["as_of"] = data.index[-1]
    return out


__all__ = [
    "BP",
    "Bond",
    "SPREAD_DEFINITIONS",
    "bond_report",
    "carry_roll_down",
    "curve_changes",
    "curve_spreads",
    "discount_factors",
    "duration_convexity",
    "forward_rate",
    "forward_rate_table",
    "key_rate_durations",
    "pca_yield_changes",
    "price_from_curve",
    "price_from_yield",
    "rich_cheap",
    "yield_to_maturity",
    "z_spread",
]
