"""Compact supervised advisory DNN (Stage A of DNN_ADVISORY_DESIGN.md).

A small MLP trunk feeds multiple heads producing the required structured
outputs. Implemented in NumPy so the model trains + serves with no heavy
dependency and runs fully offline. (An optional PyTorch trainer can be added at
ml_factor/train_torch.py; the serving format here is the portable champion.)

Heads:
  - direction  : 5-class softmax -> signed dnn_action_bias + dnn_confidence
  - edge       : regression      -> dnn_expected_edge
  - regime     : 5-class softmax -> dnn_regime_label
  - risk       : logistic        -> dnn_risk_flag
  - scale      : sigmoid         -> dnn_position_scale_hint (capped by caller)
"""
from __future__ import annotations

import numpy as np

from .features import N_FEATURES

DIRECTION_CLASSES = ["strong_sell", "sell", "hold", "buy", "strong_buy"]
DIRECTION_BIAS = np.array([-1.0, -0.5, 0.0, 0.5, 1.0])
REGIME_CLASSES = ["trend_down", "chop", "trend_up", "high_vol", "low_vol"]

HIDDEN = 16


def _relu(x):
    return np.maximum(0.0, x)


def _softmax(z):
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _fit(p: dict, X: np.ndarray, Yd: np.ndarray, Yr: np.ndarray,
         y_edge: np.ndarray, y_risk: np.ndarray, y_scale: np.ndarray,
         epochs: int, lr: float = 0.05) -> dict:
    """The one gradient loop, shared by the synthetic bootstrap and the real
    trainer so the two cannot drift. X must already be in the scale forward()
    will see (normalized by the caller when a normalizer is fitted)."""
    n = X.shape[0]
    for _ in range(epochs):
        H = _relu(X @ p["W1"] + p["b1"])
        dmask = (X @ p["W1"] + p["b1"]) > 0
        dp = _softmax(H @ p["Wd"] + p["bd"])
        gd = (dp - Yd) / n
        rp = _softmax(H @ p["Wr"] + p["br"])
        gr = (rp - Yr) / n
        ep = H @ p["We"] + p["be"]
        ge = (ep - y_edge) / n
        kp = H @ p["Wk"] + p["bk"]
        gk = (_sigmoid(kp) - y_risk) / n
        sp = H @ p["Ws"] + p["bs"]
        gs = (_sigmoid(sp) - y_scale) / n
        dWd = H.T @ gd; dbd = gd.sum(0)
        dWr = H.T @ gr; dbr = gr.sum(0)
        dWe = H.T @ ge; dbe = ge.sum(0)
        dWk = H.T @ gk; dbk = gk.sum(0)
        dWs = H.T @ gs; dbs = gs.sum(0)
        dH = (gd @ p["Wd"].T + gr @ p["Wr"].T + ge @ p["We"].T +
              gk @ p["Wk"].T + gs @ p["Ws"].T)
        dH = dH * dmask
        dW1 = X.T @ dH; db1 = dH.sum(0)
        for key, grad in [("Wd", dWd), ("bd", dbd), ("Wr", dWr), ("br", dbr),
                          ("We", dWe), ("be", dbe), ("Wk", dWk), ("bk", dbk),
                          ("Ws", dWs), ("bs", dbs), ("W1", dW1), ("b1", db1)]:
            p[key] = p[key] - lr * grad
    return p


def _init_params(rng: np.random.Generator) -> dict:
    def init(a, b):
        return rng.normal(0, 1.0 / np.sqrt(a), size=(a, b))

    return {
        "W1": init(N_FEATURES, HIDDEN), "b1": np.zeros(HIDDEN),
        "Wd": init(HIDDEN, 5), "bd": np.zeros(5),
        "We": init(HIDDEN, 1), "be": np.zeros(1),
        "Wr": init(HIDDEN, 5), "br": np.zeros(5),
        "Wk": init(HIDDEN, 1), "bk": np.zeros(1),
        "Ws": init(HIDDEN, 1), "bs": np.zeros(1),
    }


class DnnModel:
    """Serving + training container for the advisory DNN.

    An artifact carries THREE things beyond weights (2026-07-18): the feature
    signature it was trained on (names, in order), the feature-set version,
    and the fitted normalizer (mean/std per feature). A model must never be
    servable without the normalization it was trained with, so forward()
    applies it and the serving path refuses an artifact whose signature does
    not match what serving builds (ml_factor/factor.py).
    """

    def __init__(self, params: dict, model_id: str = "dnn-0.0.0",
                 feature_names: list[str] | None = None,
                 feature_set_version: str = "",
                 norm_mean: np.ndarray | None = None,
                 norm_std: np.ndarray | None = None):
        self.p = params
        self.model_id = model_id
        self.feature_names = feature_names
        self.feature_set_version = feature_set_version
        self.norm_mean = norm_mean
        self.norm_std = norm_std

    def signature_matches(self, expected: list[str]) -> tuple[bool, str]:
        """Whether this artifact's recorded signature is exactly what the
        serving path builds. A legacy artifact with no recorded signature does
        NOT match: refusing is the fail-closed direction."""
        if not self.feature_names:
            return False, (f"artifact {self.model_id} records no feature "
                           f"signature (pre bars-v2)")
        if list(self.feature_names) != list(expected):
            return False, (f"artifact {self.model_id} signature "
                           f"{list(self.feature_names)} != serving "
                           f"{list(expected)}")
        if self.norm_mean is None or self.norm_std is None:
            return False, (f"artifact {self.model_id} has no persisted "
                           f"normalizer")
        return True, "ok"

    # ---- serving ----
    def _normalize(self, X: np.ndarray) -> np.ndarray:
        if self.norm_mean is None or self.norm_std is None:
            return X
        std = np.where(self.norm_std > 0, self.norm_std, 1.0)
        return (X - self.norm_mean) / std

    def _trunk(self, X: np.ndarray) -> np.ndarray:
        return _relu(X @ self.p["W1"] + self.p["b1"])

    def forward(self, feats: list[float]) -> dict:
        X = self._normalize(np.asarray(feats, dtype=float).reshape(1, -1))
        H = self._trunk(X)
        dir_p = _softmax(H @ self.p["Wd"] + self.p["bd"])[0]
        bias = float(DIRECTION_BIAS @ dir_p)
        # Confidence: calibrated from class probability mass minus entropy.
        max_p = float(dir_p.max())
        entropy = float(-(dir_p * np.log(dir_p + 1e-9)).sum())
        confidence = max(0.0, min(1.0, 0.5 * max_p + 0.5 * (1.0 - entropy / np.log(5))))
        edge = float((H @ self.p["We"] + self.p["be"])[0, 0])
        regime_p = _softmax(H @ self.p["Wr"] + self.p["br"])[0]
        regime = REGIME_CLASSES[int(regime_p.argmax())]
        risk_flag = int(_sigmoid((H @ self.p["Wk"] + self.p["bk"])[0, 0]) > 0.5)
        scale = float(_sigmoid((H @ self.p["Ws"] + self.p["bs"])[0, 0]))
        return {
            "dnn_action_bias": round(max(-1.0, min(1.0, bias)), 4),
            "dnn_confidence": round(confidence, 4),
            "dnn_expected_edge": round(max(0.0, edge), 4),
            "dnn_regime_label": regime,
            "dnn_risk_flag": risk_flag,
            "dnn_position_scale_hint": round(max(0.0, min(1.0, scale)), 4),
        }

    # ---- persistence ----
    _META_KEYS = ("model_id", "feature_names", "feature_set_version",
                  "norm_mean", "norm_std")

    def save(self, path: str) -> None:
        meta = {"model_id": np.array(self.model_id)}
        if self.feature_names is not None:
            meta["feature_names"] = np.array(list(self.feature_names))
        if self.feature_set_version:
            meta["feature_set_version"] = np.array(self.feature_set_version)
        if self.norm_mean is not None:
            meta["norm_mean"] = np.asarray(self.norm_mean, dtype=float)
        if self.norm_std is not None:
            meta["norm_std"] = np.asarray(self.norm_std, dtype=float)
        np.savez(path, **meta, **self.p)

    @classmethod
    def load(cls, path: str) -> "DnnModel":
        data = np.load(path, allow_pickle=True)
        params = {k: data[k] for k in data.files if k not in cls._META_KEYS}
        model_id = str(data["model_id"]) if "model_id" in data.files else "dnn"
        names = ([str(s) for s in data["feature_names"]]
                 if "feature_names" in data.files else None)
        version = (str(data["feature_set_version"])
                   if "feature_set_version" in data.files else "")
        mean = data["norm_mean"] if "norm_mean" in data.files else None
        std = data["norm_std"] if "norm_std" in data.files else None
        return cls(params, model_id=model_id, feature_names=names,
                   feature_set_version=version, norm_mean=mean, norm_std=std)

    # ---- training (Stage A supervised) ----
    @classmethod
    def train_synthetic(cls, n: int = 4000, epochs: int = 250, seed: int = 7,
                        model_id: str = "dnn-0.1.0") -> "DnnModel":
        """Train a tiny model on a deterministic synthetic task.

        The synthetic 'truth' is a fixed linear score over the features; the
        model learns to recover directional class + edge + regime, giving a
        real, input-responsive advisory signal for the demo. Reproducible.
        """
        rng = np.random.default_rng(seed)
        X = rng.normal(0, 1, size=(n, N_FEATURES))
        w_true = rng.normal(0, 1, size=N_FEATURES)
        score = X @ w_true
        # Direction labels by quintile of the latent score.
        qs = np.quantile(score, [0.2, 0.4, 0.6, 0.8])
        y_dir = np.digitize(score, qs)            # 0..4
        # Regime label from volatility feature (index 2) + trend sign.
        vol = X[:, 2]
        y_reg = np.where(vol > 1.0, 3,            # high_vol
                 np.where(vol < -1.0, 4,          # low_vol
                 np.where(score > 0.5, 2,         # trend_up
                 np.where(score < -0.5, 0, 1))))  # trend_down / chop
        y_edge = np.maximum(0.0, score * 0.03).reshape(-1, 1)
        y_risk = (vol > 0.8).astype(float).reshape(-1, 1)
        y_scale = _sigmoid(np.abs(score)).reshape(-1, 1)

        # Normalize with the fitted stats, train on the NORMALIZED X, and
        # persist the normalizer: forward() applies it identically at serve
        # time, so the model is never served without the normalization it was
        # trained with.
        mean = X.mean(axis=0)
        std = X.std(axis=0)
        Xn = (X - mean) / np.where(std > 0, std, 1.0)
        p = _fit(_init_params(rng), Xn, np.eye(5)[y_dir], np.eye(5)[y_reg],
                 y_edge, y_risk, y_scale, epochs)
        from .features import FEATURE_NAMES, FEATURE_SET_VERSION
        return cls(p, model_id=model_id,
                   feature_names=list(FEATURE_NAMES),
                   feature_set_version=FEATURE_SET_VERSION,
                   norm_mean=mean, norm_std=std)

    @classmethod
    def train_real_supervised(cls, X_rows: list[list[float]],
                              y_forward: list[float],
                              model_id: str, seed: int = 11,
                              epochs: int = 250) -> "DnnModel":
        """Train on REAL canonical features and forward returns.

        X_rows come from the same builder serving uses (features_at over real
        bars), so train and serve see one distribution. The normalizer is
        fitted here and persisted in the artifact. Labels derive from the
        forward return: direction by quintile (balanced by construction),
        edge as the clipped positive return, risk and scale from return
        magnitude, regime from the feature's own regime column.
        """
        X = np.asarray(X_rows, dtype=float)
        y = np.asarray(y_forward, dtype=float)
        if X.ndim != 2 or X.shape[1] != N_FEATURES or X.shape[0] != y.shape[0]:
            raise ValueError(
                f"train_real_supervised: X {X.shape} vs y {y.shape}, "
                f"expected (_, {N_FEATURES})")
        rng = np.random.default_rng(seed)
        mean = X.mean(axis=0)
        std = X.std(axis=0)
        Xn = (X - mean) / np.where(std > 0, std, 1.0)

        qs = np.quantile(y, [0.2, 0.4, 0.6, 0.8])
        y_dir = np.digitize(y, qs)
        # Regime label from the canonical regime feature (index 4): direction
        # of trend, chop in the middle, vol classes from atr_norm (index 2).
        regime_col = X[:, 4]
        atr_col = X[:, 2]
        atr_hi = np.quantile(atr_col, 0.8)
        atr_lo = np.quantile(atr_col, 0.2)
        y_reg = np.where(atr_col > atr_hi, 3,
                 np.where(atr_col < atr_lo, 4,
                 np.where(regime_col > 0.2, 2,
                 np.where(regime_col < -0.2, 0, 1))))
        y_edge = np.maximum(0.0, y).reshape(-1, 1)
        y_risk = (np.abs(y) > np.quantile(np.abs(y), 0.8)).astype(
            float).reshape(-1, 1)
        y_std = float(y.std()) or 1.0
        y_scale = _sigmoid(np.abs(y) / y_std).reshape(-1, 1)

        p = _fit(_init_params(rng), Xn, np.eye(5)[y_dir], np.eye(5)[y_reg],
                 y_edge, y_risk, y_scale, epochs)
        from .features import FEATURE_NAMES, FEATURE_SET_VERSION
        return cls(p, model_id=model_id,
                   feature_names=list(FEATURE_NAMES),
                   feature_set_version=FEATURE_SET_VERSION,
                   norm_mean=mean, norm_std=std)
