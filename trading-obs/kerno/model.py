"""
Model artifacts: plain JSON, never pickle.

Loading a pickle executes arbitrary code, so a swapped .pkl file is remote code
execution on the server. Kerno's models are standardized logistic regressions
with optional isotonic calibration, which serialize exactly to a handful of
numbers. Inference is pure Python, so the API doesn't even need scikit-learn.

Every artifact must be listed with its SHA-256 in `models/manifest.json`.
Files that are missing from the manifest, fail the hash, or were trained on a
different FEATURE_VERSION are refused.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kerno.features import FEATURE_VERSION

logger = logging.getLogger("kerno.model")

MANIFEST = "manifest.json"


@dataclass
class LinearModel:
    id: str
    stage: int  # 1 = tradability, 2 = direction (continuation vs absorption)
    scope: str  # "exchange:symbol" or "*"
    features: list[str]
    mean: list[float]
    scale: list[float]
    coef: list[float]
    intercept: float
    feature_version: str
    calibration: dict[str, list[float]] | None = None  # {"x": [...], "y": [...]} isotonic
    threshold: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        n = len(self.features)
        if not (len(self.mean) == len(self.scale) == len(self.coef) == n):
            raise ValueError(f"model {self.id}: inconsistent vector lengths")
        if any(s == 0 for s in self.scale):
            raise ValueError(f"model {self.id}: zero scale")
        if self.calibration and len(self.calibration["x"]) != len(self.calibration["y"]):
            raise ValueError(f"model {self.id}: bad calibration table")

    def predict(self, feats: dict[str, float]) -> float:
        z = self.intercept
        for name, m, s, w in zip(self.features, self.mean, self.scale, self.coef):
            z += w * (float(feats[name]) - m) / s
        p = 1.0 / (1.0 + math.exp(-max(min(z, 50.0), -50.0)))
        if self.calibration:
            p = _interp(p, self.calibration["x"], self.calibration["y"])
        return min(max(p, 0.0), 1.0)

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LinearModel:
        return cls(**d)


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    """Piecewise-linear interpolation, clipped at the ends (= IsotonicRegression.predict)."""
    if not xs:
        return x
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect.bisect_right(xs, x)
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ModelRegistry:
    def __init__(self, models: list[LinearModel] | None = None):
        self.models = models or []

    @classmethod
    def load(cls, models_dir: Path) -> ModelRegistry:
        manifest_path = models_dir / MANIFEST
        if not manifest_path.exists():
            logger.warning("no model manifest at %s - signals will be UNSCORED", manifest_path)
            return cls()
        manifest: dict[str, str] = json.loads(manifest_path.read_text(encoding="utf-8"))
        models: list[LinearModel] = []
        for fname, expected in sorted(manifest.items()):
            path = (models_dir / fname).resolve()
            if path.parent != models_dir.resolve() or not path.name.endswith(".json"):
                logger.error("manifest entry %r rejected (must be a .json file inside %s)", fname, models_dir)
                continue
            if not path.exists():
                logger.error("model %s listed in manifest but missing", fname)
                continue
            actual = sha256_file(path)
            if actual != expected:
                logger.error("model %s hash mismatch (manifest %s.., file %s..) - refused", fname, expected[:12], actual[:12])
                continue
            try:
                model = LinearModel.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, TypeError, KeyError) as exc:
                logger.error("model %s invalid: %s", fname, exc)
                continue
            if model.feature_version != FEATURE_VERSION:
                logger.warning("model %s uses %s, engine is %s - skipped", model.id, model.feature_version, FEATURE_VERSION)
                continue
            models.append(model)
            logger.info("loaded model %s (stage %d, scope %s)", model.id, model.stage, model.scope)
        return cls(models)

    def get(self, stage: int, exchange: str, symbol: str) -> LinearModel | None:
        """Most specific model for the stream: exact scope beats '*'."""
        exact = f"{exchange}:{symbol}"
        best = None
        for m in self.models:
            if m.stage != stage:
                continue
            if m.scope == exact:
                return m
            if m.scope == "*":
                best = m
        return best

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "id": m.id,
                "stage": m.stage,
                "scope": m.scope,
                "features": m.features,
                "feature_version": m.feature_version,
                "threshold": m.threshold,
                "metadata": m.metadata,
            }
            for m in self.models
        ]


def save_model(model: LinearModel, models_dir: Path) -> Path:
    """Write the artifact and register its hash in the manifest."""
    models_dir.mkdir(parents=True, exist_ok=True)
    path = models_dir / f"{model.id}.json"
    path.write_text(model.to_json() + "\n", encoding="utf-8")
    manifest_path = models_dir / MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest[path.name] = sha256_file(path)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
