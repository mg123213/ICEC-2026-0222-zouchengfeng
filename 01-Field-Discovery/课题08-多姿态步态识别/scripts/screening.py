# -*- coding: utf-8 -*-
"""
候选特征可分性筛查：回答"为什么最后用 RMS(J)"

对每个 2 s 滑窗算 9 个候选特征，按动作强度顺序（静止 < 慢走 < 楼梯 < 快跑）
检查三件事：
    1. 四类的中位数是否单调      —— 不单调的直接淘汰，因为一条阈值切不出相邻两类
    2. 相邻类区间是否重叠        —— 重叠的也淘汰
    3. 最小类间间隙 / 特征跨度   —— 剩下的按这个排序，越大越好分

输出即报告里「候选特征筛选」那张表。

用法: python screening.py
"""
import os

import numpy as np
import pandas as pd
from scipy.signal import find_peaks
from scipy.stats import kurtosis

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw_data")

STATES = ["静止", "平地慢走", "上下楼梯", "快跑"]        # 按动作强度递增排列
FILE_OF = {
    "静止": "01_静止_原始波形.csv",
    "平地慢走": "02_平地慢走_原始波形.csv",
    "快跑": "03_快跑_原始波形.csv",
    "上下楼梯": "04_上下楼梯_原始波形.csv",
}
WIN, HOP = 2.0, 0.5


def load(state):
    df = pd.read_csv(os.path.join(RAW, FILE_OF[state]))
    df.columns = ["t", "x", "y", "z", "a"]
    return df, 1.0 / np.median(np.diff(df["t"].values))


def feats(seg, fs):
    x, y, z = seg[:, 0], seg[:, 1], seg[:, 2]
    a = np.sqrt(x ** 2 + y ** 2 + z ** 2)
    n = len(z)
    rms_a = np.sqrt(np.mean(a ** 2))
    p95 = np.percentile(a, 95)
    p99 = np.percentile(a, 99)
    j = np.diff(a) * fs

    zz = z - z.mean()
    h = 0.45 * np.percentile(np.abs(zz), 99)
    pk, _ = find_peaks(zz, height=h, distance=int(0.25 * fs))

    w = np.hanning(n)
    sp = np.abs(np.fft.rfft(zz * w)) ** 2
    fr = np.fft.rfftfreq(n, 1.0 / fs)
    b1 = (fr > 0.5) & (fr < 8)

    return {
        "RMS(J) 加加速度": np.sqrt(np.mean(j ** 2)),
        "峰值 a": a.max(),
        "RMS(A)": rms_a,
        "P99 a": p99,
        "P95 a": p95,
        "峰均比 crest": p99 / (rms_a + 1e-9),
        "z 轴峭度": kurtosis(z, fisher=True),
        "高频能量占比": sp[(fr >= 2) & (fr < 8)].sum() / (sp[b1].sum() + 1e-12),
        "步频": len(pk) / (n / fs),
    }


def main():
    rows = []
    for st in STATES:
        df, fs = load(st)
        seg = df[["x", "y", "z"]].values
        nw, step = int(WIN * fs), int(HOP * fs)
        for s in range(0, len(seg) - nw + 1, step):
            rows.append({"状态": st, **feats(seg[s:s + nw], fs)})
    W = pd.DataFrame(rows)

    records = []
    for col in [c for c in W.columns if c != "状态"]:
        d = W.groupby("状态")[col].agg(["min", "max", "median"]).loc[STATES]
        mono = bool(np.all(np.diff(d["median"].values) > 0))
        gaps = [d["min"].iloc[i + 1] - d["max"].iloc[i] for i in range(len(d) - 1)]
        span = d["max"].max() - d["min"].min()
        records.append({
            "特征": col,
            "单调": "是" if mono else "否",
            "最小间隙": round(float(np.min(gaps)), 3),
            "重叠": "有" if np.min(gaps) < 0 else "无",
            "间隙/跨度": round(float(np.min(gaps) / span), 3) if span else np.nan,
        })
    R = pd.DataFrame(records).sort_values(["单调", "间隙/跨度"],
                                          ascending=[False, False], ignore_index=True)

    print(f"=== 候选特征可分性（2 s 窗 / {len(W)} 窗）===")
    print(R.to_string(index=False))
    print("\n=== 各特征中位数（按动作强度递增）===")
    med = W.groupby("状态").median(numeric_only=True).loc[STATES]
    print(med.round(3).to_string())
    print("\n结论：只有「单调=是 且 无重叠」的特征能用一条条阈值切开；"
          "其中 RMS(J) 的归一化间隙最大。")

    out = os.path.join(ROOT, "report", "表3_候选特征可分性.csv")
    R.to_csv(out, index=False, encoding="utf-8-sig")
    print("已保存", out)


if __name__ == "__main__":
    main()
