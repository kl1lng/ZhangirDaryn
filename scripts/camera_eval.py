"""Measure hand-only gesture matching on Slovo (20 signers per word) and compare matching variants.

  python scripts/camera_eval.py            # needs data/slovo/handset.npz from scripts/slovo_handset.py
Reference = one training recording per word (like our library: one clip per word); queries = recordings of the held-out
signers (the dataset's own train/test split is by signer). Reports top-1 and top-5 accuracy over 1000 words.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
rng = np.random.default_rng(7)

pack = np.load(ROOT / "data" / "slovo" / "handset.npz")
labels, train, data = pack["labels"], pack["train"], pack["data"].astype(np.float32)  # (N, 24, 2, 21, 3)
words = sorted(set(labels))
print(len(labels), "recordings,", len(words), "words, train", int(train.sum()), "test", int((~train).sum()))


def pick(mask, per_word, seed):
    r = np.random.default_rng(seed)
    out = []
    for w in words:
        idx = np.flatnonzero(mask & (labels == w))
        if len(idx):
            out += list(r.choice(idx, size=min(per_word, len(idx)), replace=False))
    return np.array(out)


refs = pick(train, 1, 1)
queries = pick(~train, 2, 2)
print("references", len(refs), "queries", len(queries))


def visible(x):  # x (..., 21, 3) -> bool: hand present
    return np.linalg.norm(x[..., 1:, :2] - x[..., :1, :2], axis=-1).max(axis=-1) > 0.012


# ---------- baseline: what the browser does today (absolute position, shared scale, L1, banded DTW) ----------
def resample_steps(seq, steps):
    pos = np.linspace(0, seq.shape[0] - 1, steps)
    lo = np.floor(pos).astype(int)
    hi = np.minimum(lo + 1, seq.shape[0] - 1)
    w = (pos - lo).reshape(-1, *([1] * (seq.ndim - 1)))
    return seq[lo] * (1 - w) + seq[hi] * w


def baseline_prepare(sample):
    flat = sample.reshape(sample.shape[0], 2, 63)
    vis = visible(sample)  # (T, 2)
    scale = 0.0
    for t in range(sample.shape[0]):
        for s in range(2):
            if vis[t, s]:
                pts = sample[t, s]
                d = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=-1).max()
                scale = max(scale, d)
    if scale < 1e-8:
        return np.zeros((16, 2, 63), np.float32), np.zeros((16, 2), bool)
    norm = flat.copy().reshape(sample.shape[0], 2, 21, 3)
    norm[..., :2] -= 0.5
    norm /= scale
    norm[~vis] = 0
    return resample_steps(norm.reshape(sample.shape[0], 2, 63), 16), resample_steps(vis.astype(np.float32), 16) > 0.5


def baseline_dtw(q, qv, refs_arr, refs_vis):
    R = refs_arr.shape[0]
    cost = np.full((R, 17, 17), np.inf)
    length = np.zeros((R, 17, 17))
    cost[:, 0, 0] = 0
    for i in range(1, 17):
        for j in range(max(1, i - 3), min(16, i + 3) + 1):
            total = np.zeros(R)
            weight = np.zeros(R)
            for s in range(2):
                both = qv[i - 1, s] & refs_vis[:, j - 1, s]
                one = (qv[i - 1, s] ^ refs_vis[:, j - 1, s])
                err = np.abs(q[i - 1, s][None, :] - refs_arr[:, j - 1, s, :]).sum(-1) / 63
                total += np.where(both, err, 0) + np.where(one, 0.25, 0)
                weight += both * 1.0 + one * 0.5
            step = np.where(weight > 0, total / np.maximum(weight, 1e-9), 0.5)
            prev = np.stack([cost[:, i - 1, j - 1], cost[:, i - 1, j], cost[:, i, j - 1]])
            plen = np.stack([length[:, i - 1, j - 1], length[:, i - 1, j], length[:, i, j - 1]])
            k = prev.argmin(0)
            cost[:, i, j] = np.take_along_axis(prev, k[None], 0)[0] + step
            length[:, i, j] = np.take_along_axis(plen, k[None], 0)[0] + 1
    return cost[:, 16, 16] / length[:, 16, 16]


def evaluate(name, scores_fn, sub=None):
    t0 = time.time()
    qs = queries if sub is None else queries[:sub]
    top1 = top5 = 0
    for q in qs:
        d = scores_fn(q)  # distance to each reference, lower is better
        order = np.argsort(d)
        got = labels[refs[order[:5]]]
        top1 += got[0] == labels[q]
        top5 += labels[q] in got
    print(f"{name:<44} top-1 {100*top1/len(qs):5.1f}%  top-5 {100*top5/len(qs):5.1f}%  ({len(qs)} queries, {time.time()-t0:.0f}s)")
    return top1 / len(qs)


if __name__ == "__main__":
    prepared = [baseline_prepare(data[i]) for i in refs]
    ref_arr = np.stack([p[0] for p in prepared])
    ref_vis = np.stack([p[1] for p in prepared])
    cache = {}

    def baseline(q):
        if q not in cache:
            cache[q] = baseline_prepare(data[q])
        a, v = cache[q]
        return baseline_dtw(a, v, ref_arr, ref_vis)

    print("chance level: %.2f%%" % (100 / len(words)))
    evaluate("baseline (current browser algorithm)", baseline, sub=400)
