"""Train the hand-only gesture classifier used by the camera mode and export it for the browser.

  .venv-pwa\\Scripts\\python.exe scripts/camera_train.py [--final]

Data: data/slovo/handset.npz (scripts/slovo_handset.py) + scripts/slovo_kk_words.txt (the words shown on the site).
Without --final the model is fitted on the training signers and scored on held-out signers; with --final it is fitted on
everyone and written to pwa/public/camera/model.json + model.bin.
The feature code here must match pwa/lib/camera-classifier.ts exactly (see pwa/tests/camera-classifier.test.ts).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
STEPS = 12
FEATURES = STEPS * (126 + 6 + 3)


def read_words():
    words = {}
    for line in (ROOT / "scripts" / "slovo_kk_words.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        ru, rest = (part.strip() for part in line.split("=", 1))
        kk = rest.partition("|")[0].strip()
        words[ru.casefold()] = kk[:1].upper() + kk[1:]
    return words


def resample(array: np.ndarray, steps: int) -> np.ndarray:
    position = np.linspace(0, len(array) - 1, steps)
    lower = np.floor(position).astype(int)
    upper = np.minimum(lower + 1, len(array) - 1)
    weight = (position - lower).reshape(-1, *([1] * (array.ndim - 1)))
    return array[lower] * (1 - weight) + array[upper] * weight


def features(sample: np.ndarray, aspect: float) -> np.ndarray:
    """sample (T, 2, 21, 3) in image units, zero = no hand. Returns FEATURES numbers."""
    sample = sample.astype(np.float32).copy()
    sample[..., 0] *= aspect  # isotropic units (height = 1)
    sample[..., 2] *= aspect
    present = (np.abs(sample[:, :, 0, :2]).sum(-1) > 0)  # wrist exists
    count = len(sample)
    shape = np.zeros((count, 2, 21, 3), np.float32)
    wrist = np.zeros((count, 2, 3), np.float32)
    palm = np.zeros((count, 2), np.float32)
    for t in range(count):
        for s in range(2):
            if present[t, s]:
                hand = sample[t, s]
                p = float(np.hypot(hand[9, 0] - hand[0, 0], hand[9, 1] - hand[0, 1])) + 1e-6
                shape[t, s] = (hand - hand[0]) / p
                wrist[t, s] = hand[0]
                palm[t, s] = p
    scale = float(np.median(palm[present])) if present.any() else 1.0
    traj = np.zeros((count, 2, 3), np.float32)
    for s in range(2):
        if present[:, s].any():
            mean = wrist[present[:, s], s].mean(0)
            traj[:, s] = np.where(present[:, s][:, None], (wrist[:, s] - mean) / scale, 0)
    inter = np.where((present[:, 0] & present[:, 1])[:, None], (wrist[:, 1] - wrist[:, 0]) / scale, 0)
    return np.concatenate([
        resample(shape.reshape(count, -1), STEPS).ravel(),
        resample(traj.reshape(count, -1), STEPS).ravel(),
        resample(inter, STEPS).ravel(),
    ]).astype(np.float32)


def mirrored(sample: np.ndarray, aspect_width: float = 1.0) -> np.ndarray:
    """Left-right mirror in normalised image x, then re-order the two hands by wrist x."""
    out = sample.copy()
    live = np.abs(out[:, :, 0, :2]).sum(-1) > 0
    out[..., 0] = np.where(live[:, :, None], 1.0 - out[..., 0], 0.0)
    out[..., 2] = np.where(live[:, :, None], -out[..., 2], 0.0)
    for t in range(len(out)):
        if live[t, 0] and live[t, 1] and out[t, 0, 0, 0] > out[t, 1, 0, 0]:
            out[t] = out[t][::-1]
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final", action="store_true")
    parser.add_argument("--hidden", type=int, default=512)
    parser.add_argument("--iterations", type=int, default=40)
    args = parser.parse_args()

    pack = np.load(ROOT / "data" / "slovo" / "handset.npz")
    ids, labels, train, data = pack["ids"], pack["labels"], pack["train"], pack["data"].astype(np.float32)
    rows = {r["attachment_id"]: r for r in csv.DictReader(open(ROOT / "data/slovo/annotations.csv", encoding="utf-8"), delimiter="\t")}
    aspect = np.array([int(rows[i]["width"]) / int(rows[i]["height"]) for i in ids], np.float32)

    mapping = read_words()
    kk = np.array([mapping.get(label.casefold(), "") for label in labels])
    keep = np.flatnonzero(kk != "")
    classes = sorted(set(kk[keep]))
    index = {c: i for i, c in enumerate(classes)}
    print(len(keep), "recordings,", len(classes), "classes")

    started = time.time()
    X, y, is_train = [], [], []
    for i in keep:
        base = data[i]
        for variant in (base, mirrored(base)):
            X.append(features(variant, aspect[i]))
            y.append(index[kk[i]])
            is_train.append(bool(train[i]))
    X, y, is_train = np.stack(X), np.array(y), np.array(is_train)
    print("features", X.shape, f"{time.time() - started:.0f}s")

    fit_mask = np.ones(len(X), bool) if args.final else is_train
    scaler = StandardScaler().fit(X[fit_mask])
    scaler.scale_ = np.where(scaler.scale_ < 1e-3, 1.0, scaler.scale_)
    model = MLPClassifier(hidden_layer_sizes=(args.hidden,), alpha=1e-3, batch_size=256, max_iter=args.iterations,
                          random_state=0)
    started = time.time()
    model.fit(scaler.transform(X[fit_mask]), y[fit_mask])
    print(f"fitted in {time.time() - started:.0f}s")

    if not args.final:
        test = ~is_train
        # score only the real (not mirrored) held-out recordings
        real = np.zeros(len(X), bool)
        real[0::2] = True
        test &= real
        p = model.predict_proba(scaler.transform(X[test]))
        top = np.argsort(-p, axis=1)[:, :5]
        truth = y[test]
        print(f"held-out signers: top-1 {(top[:, 0] == truth).mean() * 100:.1f}%  "
              f"top-5 {np.mean([truth[i] in top[i] for i in range(len(truth))]) * 100:.1f}%  ({test.sum()} recordings, {len(classes)} words)")
        confidence = p.max(1)
        for t in (0.2, 0.3, 0.4, 0.5, 0.6):
            sel = confidence >= t
            if sel.any():
                print(f"  confidence >= {t:.1f}: answers {sel.mean() * 100:4.0f}% of clips, top-1 correct {(top[sel, 0] == truth[sel]).mean() * 100:4.1f}%")
        return

    out = ROOT / "pwa" / "public" / "camera"
    w1, w2 = model.coefs_
    b1, b2 = model.intercepts_
    blob = b"".join(a.astype("<f2").tobytes() for a in (w1, b1, w2, b2))
    (out / "model.bin").write_bytes(blob)
    meta = {"schema": 1, "steps": STEPS, "features": FEATURES, "hidden": int(args.hidden), "classes": classes,
            "mean": [round(float(v), 5) for v in scaler.mean_], "scale": [round(float(v), 5) for v in scaler.scale_],
            "threshold": 0.4}
    (out / "model.json").write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("exported", out / "model.bin", f"{len(blob) / 1e6:.1f} MB", "classes", len(classes))


if __name__ == "__main__":
    main()
