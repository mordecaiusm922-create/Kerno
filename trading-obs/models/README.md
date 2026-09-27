# Models

Only JSON artifacts produced by `kerno train` live here, each registered with
its SHA-256 in `manifest.json`. The API and engine refuse anything else
(pickles, unlisted files, hash mismatches, other feature versions).

The manifest is empty on purpose: the previous `.pkl` models were trained on
features that cannot be reproduced live (see `docs/audit.md`), so no model is
deployed until one is trained on engine-generated data and passes the
validation gate:

    kerno replay --exchange binance --symbol BTCUSDT     # build history of signals
    kerno validate                                       # resolve their outcomes
    kerno train --exchange binance --symbol BTCUSDT      # train, validate, deploy if it passes

Until then every signal is recorded as `UNSCORED` with its full feature vector.
