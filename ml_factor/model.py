"""Compact supervised advisory DNN (Stage A of DNN_RL_DESIGN.md).

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


class DnnModel:
    """Serving + training container for the advisory DNN."""

    def __init__(self, params: dict, model_id: str = "dnn-0.0.0"):
        self.p = params
        self.model_id = model_id

    # ---- serving ----
    def _trunk(self, X: np.ndarray) -> np.ndarray:
        return _relu(X @ self.p["W1"] + self.p["b1"])

    def forward(self, feats: list[float]) -> dict:
        X = np.asarray(feats, dtype=float).reshape(1, -1)
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
    def save(self, path: str) -> None:
        np.savez(path, model_id=np.array(self.model_id), **self.p)

    @classmethod
    def load(cls, path: str) -> "DnnModel":
        data = np.load(path, allow_pickle=True)
        params = {k: data[k] for k in data.files if k != "model_id"}
        model_id = str(data["model_id"]) if "model_id" in data.files else "dnn"
        return cls(params, model_id=model_id)

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

        # Init params.
        def init(a, b):
            return rng.normal(0, 1.0 / np.sqrt(a), size=(a, b))

        p = {
            "W1": init(N_FEATURES, HIDDEN), "b1": np.zeros(HIDDEN),
            "Wd": init(HIDDEN, 5), "bd": np.zeros(5),
            "We": init(HIDDEN, 1), "be": np.zeros(1),
            "Wr": init(HIDDEN, 5), "br": np.zeros(5),
            "Wk": init(HIDDEN, 1), "bk": np.zeros(1),
            "Ws": init(HIDDEN, 1), "bs": np.zeros(1),
        }
        lr = 0.05
        Yd = np.eye(5)[y_dir]
        Yr = np.eye(5)[y_reg]
        for _ in range(epochs):
            H = _relu(X @ p["W1"] + p["b1"])
            dmask = (X @ p["W1"] + p["b1"]) > 0
            # direction
            dp = _softmax(H @ p["Wd"] + p["bd"])
            gd = (dp - Yd) / n
            # regime
            rp = _softmax(H @ p["Wr"] + p["br"])
            gr = (rp - Yr) / n
            # edge / risk / scale (regression-ish)
            ep = H @ p["We"] + p["be"]
            ge = (ep - y_edge) / n
            kp = H @ p["Wk"] + p["bk"]
            gk = (_sigmoid(kp) - y_risk) / n
            sp = H @ p["Ws"] + p["bs"]
            gs = (_sigmoid(sp) - y_scale) / n

            # grads to heads
            dWd = H.T @ gd; dbd = gd.sum(0)
            dWr = H.T @ gr; dbr = gr.sum(0)
            dWe = H.T @ ge; dbe = ge.sum(0)
            dWk = H.T @ gk; dbk = gk.sum(0)
            dWs = H.T @ gs; dbs = gs.sum(0)
            # backprop into trunk (sum of head contributions)
            dH = (gd @ p["Wd"].T + gr @ p["Wr"].T + ge @ p["We"].T +
                  gk @ p["Wk"].T + gs @ p["Ws"].T)
            dH = dH * dmask
            dW1 = X.T @ dH; db1 = dH.sum(0)

            for key, grad in [("Wd", dWd), ("bd", dbd), ("Wr", dWr), ("br", dbr),
                              ("We", dWe), ("be", dbe), ("Wk", dWk), ("bk", dbk),
                              ("Ws", dWs), ("bs", dbs), ("W1", dW1), ("b1", db1)]:
                p[key] = p[key] - lr * grad

        return cls(p, model_id=model_id)
