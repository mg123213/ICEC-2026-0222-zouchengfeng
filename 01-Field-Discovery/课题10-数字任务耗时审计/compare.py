# -*- coding: utf-8 -*-
"""
课题10 · 生成耗时对比表与对比图
需要先跑过 manual_timer.py（人工实测）或 simulate_manual.py（人工估算），以及 bench.py（AI 耗时）。

用法: python compare.py
输出: out/耗时对比表.csv, out/图1_耗时对比.png
"""
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "out")
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def load_manual():
    """优先读秒表实测；没有实测则退到步骤分解估算，并返回来源标记"""
    real = os.path.join(OUT, "人工耗时.csv")
    est = os.path.join(OUT, "人工耗时_估算.csv")
    if os.path.exists(real):
        df = pd.read_csv(real)
        df = df[df["是否热身"] != "是"].reset_index(drop=True)
        return df, "实测"
    if os.path.exists(est):
        return pd.read_csv(est), "估算"
    sys.exit("找不到人工耗时数据 —— 先跑 manual_timer.py 或 simulate_manual.py")


def load_ai():
    p = os.path.join(OUT, "耗时_AI.csv")
    if not os.path.exists(p):
        sys.exit("找不到 out/耗时_AI.csv —— 先跑 python bench.py")
    df = pd.read_csv(p)
    med = df[df["运行序号"] == "中位数"]
    return float(med["总耗时_s"].iloc[0]), float(med["单样本均摊_s"].iloc[0])


def main():
    man, src = load_manual()
    ai_total, ai_each = load_ai()

    n_man = len(man)
    man_mean = man["耗时_s"].mean()
    # 样本数不足 10 时按均值外推
    man_total = man["耗时_s"].sum() if n_man >= 10 else man_mean * 10

    rows = []
    for i in range(10):
        s = man["耗时_s"].iloc[i] if i < n_man else man_mean
        rows.append({"样本": f"S{i + 1:02d}", "人工_s": round(float(s), 2),
                     "AI_s": round(ai_each, 4),
                     "加速倍数": round(float(s) / ai_each, 1),
                     "数据来源": src if i < n_man else f"{src}(均值外推)"})
    t = pd.DataFrame(rows, columns=["样本", "人工_s", "AI_s", "加速倍数", "数据来源"])
    t.loc[len(t)] = ["合计", round(man_total, 2), round(ai_total, 4),
                     round(man_total / ai_total, 1),
                     f"人工{src} {n_man} 个" if n_man >= 10 else f"人工{src} {n_man} 个，余按均值外推"]
    t.to_csv(os.path.join(OUT, "耗时对比表.csv"), index=False, encoding="utf-8-sig")

    print(t.to_string(index=False))
    print(f"\n人工单样本均值 {man_mean:.1f} s，AI 单样本均摊 {ai_each * 1000:.1f} ms")
    print(f"总耗时：人工 {man_total / 60:.1f} min  vs  AI {ai_total:.2f} s，"
          f"加速 {man_total / ai_total:.0f} 倍")


    # ---- 图 ----
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.2),
                                   gridspec_kw={"width_ratios": [1.25, 1]})
    x = np.arange(10)
    s_man = [float(man["耗时_s"].iloc[i]) if i < n_man else man_mean for i in range(10)]
    ax1.bar(x - 0.19, s_man, 0.38, label="人工", color="#d62728", alpha=0.85)
    ax1.bar(x + 0.19, [ai_each] * 10, 0.38, label="AI 脚本", color="#2ca02c", alpha=0.85)
    ax1.set_yscale("log")
    ax1.set_xticks(x)
    ax1.set_xticklabels([f"S{i + 1:02d}" for i in range(10)])
    ax1.set_ylabel("单样本耗时 (s，对数轴)")
    ax1.set_title("单样本耗时：人工 vs AI", fontsize=12, fontweight="bold")
    ax1.grid(alpha=0.25, axis="y", which="both")
    ax1.legend()

    ax2.plot(range(1, 11), np.cumsum(s_man), "-o", color="#d62728", lw=1.8,
             ms=5, label="人工累计")
    ax2.plot(range(1, 11), [ai_total / 10 * k for k in range(1, 11)], "-s",
             color="#2ca02c", lw=1.8, ms=4, label="AI 累计")
    ax2.set_xlabel("已处理样本数")
    ax2.set_ylabel("累计耗时 (s，对数轴)")
    ax2.set_yscale("log")
    ax2.set_title(f"累计耗时：处理 10 个样本省下 {man_total / 60:.1f} 分钟",
                  fontsize=12, fontweight="bold")
    ax2.grid(alpha=0.25, which="both")
    ax2.legend()

    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "图1_耗时对比.png"), dpi=170)
    print("已生成 out/图1_耗时对比.png")


if __name__ == "__main__":
    main()
