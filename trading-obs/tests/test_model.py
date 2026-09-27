import json

import pytest

from kerno.model import MANIFEST, LinearModel, ModelRegistry, save_model


def _m(**kw):
    base = dict(id="m1", stage=2, scope="binance:BTCUSDT", features=["a", "b"], mean=[1.0, 2.0], scale=[2.0, 4.0],
                coef=[0.5, -1.0], intercept=0.1, feature_version="fv2")
    base.update(kw)
    return LinearModel(**base)


def test_matches_sklearn():
    np = pytest.importorskip("numpy")
    sk = pytest.importorskip("sklearn.linear_model")
    from sklearn.isotonic import IsotonicRegression
    from sklearn.preprocessing import StandardScaler

    rng = np.random.default_rng(0)
    X = rng.normal(size=(500, 3)) * [1, 5, 0.1] + [0, 10, 1]
    y = (X[:, 0] + 0.2 * X[:, 1] + rng.normal(size=500) > 2).astype(int)
    sc = StandardScaler().fit(X)
    clf = sk.LogisticRegression().fit(sc.transform(X), y)
    iso = IsotonicRegression(out_of_bounds="clip").fit(clf.predict_proba(sc.transform(X))[:, 1], y)
    m = LinearModel(id="x", stage=1, scope="*", features=["f0", "f1", "f2"], mean=list(sc.mean_), scale=list(sc.scale_),
                    coef=list(clf.coef_[0]), intercept=float(clf.intercept_[0]), feature_version="fv2",
                    calibration={"x": list(iso.X_thresholds_), "y": list(iso.y_thresholds_)})
    expected = iso.predict(clf.predict_proba(sc.transform(X))[:, 1])
    got = [m.predict({"f0": r[0], "f1": r[1], "f2": r[2]}) for r in X]
    assert max(abs(a - b) for a, b in zip(expected, got)) < 1e-9


def test_registry_verifies_hashes(tmp_path):
    save_model(_m(), tmp_path)
    save_model(_m(id="other", stage=1, scope="*"), tmp_path)
    reg = ModelRegistry.load(tmp_path)
    assert reg.get(2, "binance", "BTCUSDT").id == "m1"
    assert reg.get(1, "okx", "BTC-USDT").id == "other"
    assert reg.get(2, "okx", "BTC-USDT") is None
    # tampering with an artifact after it was registered => refused
    p = tmp_path / "m1.json"
    d = json.loads(p.read_text())
    d["coef"] = [100.0, 100.0]
    p.write_text(json.dumps(d))
    assert [m.id for m in ModelRegistry.load(tmp_path).models] == ["other"]


def test_registry_rejects_traversal_and_other_feature_versions(tmp_path):
    save_model(_m(feature_version="fv1"), tmp_path)
    manifest = json.loads((tmp_path / MANIFEST).read_text())
    manifest["../evil.json"] = "0" * 64
    manifest["model.pkl"] = "0" * 64
    (tmp_path / MANIFEST).write_text(json.dumps(manifest))
    assert ModelRegistry.load(tmp_path).models == []
    assert ModelRegistry.load(tmp_path / "missing").models == []


def test_repo_models_dir_has_no_pickles():
    from kerno.config import DEFAULT_MODELS_DIR

    assert not list(DEFAULT_MODELS_DIR.parent.glob("**/*.pkl"))
