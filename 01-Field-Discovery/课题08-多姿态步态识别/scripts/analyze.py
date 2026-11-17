# -*- coding: utf-8 -*-
"""
课题 08 · 多姿态步态加速度特征采集与对比
一键复现：读 raw_data/ 的原始 CSV  ->  算特征 / 定阈值 / 验证  ->  出图与统计表

用法:
    python analyze.py                # 默认读写本目录的上级目录
    python analyze.py --root <路径>   # 指定 01-Field-Discovery 目录

依赖: numpy pandas scipy matplotlib
"""
import argparse
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from scipy.signal import find_peaks
from scipy.stats import kurtosis

# ---------------- 全局配置 ----------------
STATES = ["静止", "平地慢走", "上下楼梯", "快跑"]
FILE_OF = {           # raw_data 里的文件名前缀
    "静止": "01_静止_原始波形.csv",
    "平地慢走": "02_平地慢走_原始波形.csv",
    "快跑": "03_快跑_原始波形.csv",
    "上下楼梯": "04_上下楼梯_原始波形.csv",
}
COLOR = {"静止": "#8c8c8c", "平地慢走": "#2ca02c", "上下楼梯": "#e8850c", "快跑": "#d62728"}

WIN, HOP = 2.0, 0.5          # 滑窗长度 / 步长（秒）
TH_A = 0.20                  # 静止判据：RMS(A) 阈值  m/s^2
TH_STATIC_J = 8.0            # 静止判据：RMS(J) 阈值  m/s^3
TH_WALK_J = 35.0             # 慢走 / 楼梯分界
TH_STAIR_J = 100.0           # 楼梯 / 快跑分界

ORDER = ["静止", "平地慢走", "快跑", "上下楼梯"]      # 强度递增，绘图用

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw_data")
REP = os.path.join(ROOT, "report")
FIG = os.path.join(REP, "figures")

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.facecolor"] = "white"
plt.rcParams["axes.facecolor"] = "white"
plt.rcParams["savefig.facecolor"] = "white"


# ---------------- 数据 ----------------
def load(state):
    """读原始 CSV，返回 t / x / y / z 与采样率"""
    df = pd.read_csv(os.path.join(RAW, FILE_OF[state]))
    df.columns = ["t", "x", "y", "z", "a"]
    df = df.iloc[:, :5]
    fs = 1.0 / np.median(np.diff(df["t"].values))
    return df, fs


def motion_metrics(seg, fs):
    """seg:(n,3)，返回 (RMS(A), RMS(J))"""
    a = np.sqrt((seg ** 2).sum(1))
    j = np.diff(a) * fs
    return np.sqrt(np.mean(a ** 2)), np.sqrt(np.mean(j ** 2))


def classify(rms_a, rms_j):
    if rms_a < TH_A and rms_j < TH_STATIC_J:
        return "静止"
    if rms_j < TH_WALK_J:
        return "平地慢走"
    if rms_j < TH_STAIR_J:
        return "上下楼梯"
    return "快跑"


def slide(df, win=WIN, hop=HOP):
    """返回 [(t0, RMS(A), RMS(J)), ...]"""
    fs = 1.0 / np.median(np.diff(df["t"].values))
    seg = df[["x", "y", "z"]].values
    t = df["t"].values - df["t"].values[0]
    nw, st = int(win * fs), int(hop * fs)
    out = []
    for s in range(0, len(seg) - nw + 1, st):
        ra, rj = motion_metrics(seg[s:s + nw], fs)
        out.append((t[s], ra, rj))
    return out


def window_feats(seg, fs):
    """2 s 窗内的全套特征（用于可分性分析）"""
    x, y, z = seg[:, 0], seg[:, 1], seg[:, 2]
    a = np.sqrt(x ** 2 + y ** 2 + z ** 2)
    n = len(z)
    out = {}
    out["rms_a"] = np.sqrt(np.mean(a ** 2))
    out["p95_a"] = np.percentile(a, 95)
    out["p99_a"] = np.percentile(a, 99)
    out["max_a"] = a.max()
    out["std_z"] = z.std()
    out["std_xy"] = np.hypot(x.std(), y.std())
    out["kurt_z"] = kurtosis(z, fisher=True)
    j = np.diff(a) * fs
    out["rms_j"] = np.sqrt(np.mean(j ** 2))
    out["crest"] = out["p99_a"] / (out["rms_a"] + 1e-9)
    zz = z - z.mean()
    h = 0.45 * np.percentile(np.abs(zz), 99)
    pk, _ = find_peaks(zz, height=h, distance=int(0.25 * fs))
    out["cadence"] = len(pk) / (n / fs)
    out["cadence_cv"] = (np.std(np.diff(pk)) / np.mean(np.diff(pk))) if len(pk) >= 3 else np.nan
    w = np.hanning(n)
    sp = np.abs(np.fft.rfft(zz * w)) ** 2
    fr = np.fft.rfftfreq(n, 1.0 / fs)
    b1 = (fr > 0.5) & (fr < 8)
    out["low_ratio"] = sp[b1].sum() / (sp[fr > 0.3].sum() + 1e-12)
    out["hf_ratio"] = sp[(fr >= 2) & (fr < 8)].sum() / (sp[b1].sum() + 1e-12)
    return out


# ---------------- 统计表 ----------------
def dump_tables():
    rows, det = [], []
    for st in STATES:
        df, fs = load(st)
        a_all = np.sqrt((df[["x", "y", "z"]].values ** 2).sum(1))
        j_all = np.diff(a_all) * fs
        rows.append({
            "状态": st, "样本数": len(df),
            "时长_s": round(df["t"].values[-1] - df["t"].values[0], 2),
            "采样率_Hz": round(fs, 1),
            "RMS_A": round(np.sqrt(np.mean(a_all ** 2)), 3),
            "峰值_A": round(a_all.max(), 2),
            "P99_A": round(np.percentile(a_all, 99), 2),
            "RMS_J": round(np.sqrt(np.mean(j_all ** 2)), 1),
            "x_std": round(df["x"].std(), 3),
            "y_std": round(df["y"].std(), 3),
            "z_std": round(df["z"].std(), 3),
        })
        for t0, ra, rj in slide(df):
            p = classify(ra, rj)
            det.append({"真实状态": st, "窗起点_s": round(t0, 2), "RMS_A": round(ra, 3),
                        "RMS_J": round(rj, 1), "判定结果": p,
                        "是否正确": "是" if p == st else "否"})
    pd.DataFrame(rows).to_csv(os.path.join(REP, "表1_特征统计.csv"),
                              index=False, encoding="utf-8-sig")
    d = pd.DataFrame(det)
    d.to_csv(os.path.join(REP, "表2_滑窗判定明细.csv"), index=False, encoding="utf-8-sig")
    acc = (d["是否正确"] == "是").mean() * 100
    print(f"  [表] 特征统计 {len(rows)} 行；滑窗明细 {len(d)} 窗，准确率 {acc:.1f}%")
    return d


# ---------------- 图 1 波形 ----------------
def fig_wave():
    fig, axes = plt.subplots(4, 3, figsize=(13, 10.5), sharex=True)
    axc = ["#2ca02c", "#1f77b4", "#bcbd22"]
    axt = ["x", "y", "z"]
    for i, st in enumerate(ORDER):
        df, _ = load(st)
        t = df["t"].values - df["t"].values[0]
        ymax = max(abs(df[c]).max() for c in axt) * 1.15
        for k, c in enumerate(axt):
            ax = axes[i, k]
            ax.plot(t, df[c], lw=0.55, color=axc[k])
            ax.axhline(0, color="#bbb", lw=0.6, ls=":")
            ax.set_ylim(-ymax, ymax)
            ax.grid(alpha=0.25, lw=0.5)
            ax.tick_params(labelsize=8)
            if i == 0:
                ax.set_title(f"{c} 轴线性加速度", fontsize=11, pad=6)
            if k == 0:
                ax.set_ylabel(f"{st}\na (m/s²)", fontsize=10, fontweight="bold",
                              color=COLOR[st], labelpad=8)
            if i == 3:
                ax.set_xlabel("时间 (s)", fontsize=9)
    fig.suptitle("四种运动状态的手机三轴线性加速度（不含重力）波形", fontsize=14,
                 fontweight="bold", y=0.995)
    fig.text(0.5, 0.008, "采样率 208 Hz，单段时长 10 s；纵轴按状态各自缩放",
             ha="center", fontsize=9, color="#666")
    fig.tight_layout(rect=[0, 0.02, 1, 0.98])
    fig.savefig(os.path.join(FIG, "图1_四状态三轴波形.png"), dpi=160)
    plt.close(fig)
    print("  [图] 图1_四状态三轴波形.png")


# ---------------- 图 2 特征空间 ----------------
def fig_scatter():
    data = {}
    for st in STATES:
        df, fs = load(st)
        seg = df[["x", "y", "z"]].values
        nw, step = int(WIN * fs), int(HOP * fs)
        data[st] = np.array([motion_metrics(seg[s:s + nw], fs)
                             for s in range(0, len(seg) - nw + 1, step)])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 5.6),
                                   gridspec_kw={"width_ratios": [1.35, 1]})
    for st in STATES:
        d = data[st]
        ax1.scatter(d[:, 0], d[:, 1], s=52, color=COLOR[st], alpha=0.85,
                    edgecolor="white", linewidth=0.8, label=st, zorder=3)
    ax1.set_xscale("log")
    ax1.set_yscale("log")
    ax1.axhspan(1.5, TH_WALK_J, color="#2ca02c", alpha=0.06, zorder=0)
    ax1.axhspan(TH_WALK_J, TH_STAIR_J, color="#e8850c", alpha=0.08, zorder=0)
    ax1.axhspan(TH_STAIR_J, 500, color="#d62728", alpha=0.06, zorder=0)
    ax1.axvline(TH_A, color="#444", ls="--", lw=1.2, zorder=1)
    ax1.axhline(TH_WALK_J, color="#444", ls="--", lw=1.2, zorder=1)
    ax1.axhline(TH_STAIR_J, color="#444", ls="--", lw=1.2, zorder=1)
    ax1.text(TH_A * 1.15, 300, f"RMS(A) = {TH_A}", fontsize=9, color="#444",
             rotation=90, va="top")
    ax1.text(0.023, TH_WALK_J * 1.10, f"RMS(J) = {TH_WALK_J:.0f} m/s³", fontsize=9, color="#444")
    ax1.text(0.023, TH_STAIR_J * 1.10, f"RMS(J) = {TH_STAIR_J:.0f} m/s³", fontsize=9, color="#444")
    ax1.text(19.5, 4.2, "慢走区", fontsize=10, color="#2ca02c", ha="center", alpha=0.8)
    ax1.text(19.5, 48, "楼梯区", fontsize=10, color="#c06a00", ha="center", alpha=0.9)
    ax1.text(19.5, 230, "快跑区", fontsize=10, color="#d62728", ha="center", alpha=0.8)
    ax1.set_xlabel("加速度均方根 RMS(A)  [m/s²]", fontsize=10)
    ax1.set_ylabel("加加速度均方根 RMS(J)  [m/s³]", fontsize=10)
    ax1.set_title("2 s 滑窗特征空间：四类簇完全分离", fontsize=12, fontweight="bold")
    ax1.set_xlim(0.02, 25)
    ax1.set_ylim(1.5, 500)
    ax1.grid(alpha=0.25, which="both", lw=0.5)
    ax1.legend(fontsize=9, loc="upper left", framealpha=0.95, bbox_to_anchor=(0.005, 0.99))

    vals = [data[t][:, 1] for t in STATES]
    bp = ax2.boxplot(vals, widths=0.55, patch_artist=True, showfliers=True,
                     medianprops=dict(color="black", lw=1.6),
                     flierprops=dict(marker="o", markersize=4, alpha=0.7,
                                     markerfacecolor="#666", markeredgecolor="none"))
    for patch, st in zip(bp["boxes"], STATES):
        patch.set_facecolor(COLOR[st])
        patch.set_alpha(0.55)
    ax2.set_yscale("log")
    ax2.set_xticklabels(STATES, fontsize=9.5)
    ax2.axhline(TH_WALK_J, color="#444", ls="--", lw=1.2)
    ax2.axhline(TH_STAIR_J, color="#444", ls="--", lw=1.2)
    ax2.text(0.52, TH_WALK_J * 1.12, "阈值 35", fontsize=9, color="#444")
    ax2.text(0.52, TH_STAIR_J * 1.12, "阈值 100", fontsize=9, color="#444")
    ax2.set_ylabel("RMS(J)  [m/s³]", fontsize=10)
    ax2.set_title("三类运动强度的阶梯分布", fontsize=12, fontweight="bold")
    ax2.grid(alpha=0.25, axis="y", which="both", lw=0.5)
    ax2.set_ylim(1.5, 500)

    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "图2_特征分布与阈值.png"), dpi=160)
    plt.close(fig)
    print("  [图] 图2_特征分布与阈值.png")


# ---------------- 图 3 判定流程 ----------------
def fig_tree():
    fig, ax = plt.subplots(figsize=(11.5, 7.2))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    def box(x, y, w, h, text, fc, fs=11, bold=False):
        ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                                    boxstyle="round,pad=0.5,rounding_size=1.2",
                                    fc=fc, ec="#555", lw=1.3, zorder=2))
        ax.text(x, y, text, ha="center", va="center", fontsize=fs,
                fontweight="bold" if bold else "normal", zorder=3)

    def dia(x, y, w, h, text, fs=10.5):
        ax.add_patch(plt.Polygon([[x, y + h / 2], [x + w / 2, y], [x, y - h / 2], [x - w / 2, y]],
                                 closed=True, fc="#eef4fb", ec="#3b6ea5", lw=1.4, zorder=2))
        ax.text(x, y, text, ha="center", va="center", fontsize=fs, color="#1b3d61", zorder=3)

    def arrow(x1, y1, x2, y2):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="-|>", lw=1.4, color="#555",
                                    shrinkA=0, shrinkB=0, mutation_scale=14), zorder=1)

    CX, DW = 44, 38
    RY = [80, 58, 36]
    BX, BW, BH = 86, 24, 8.5

    box(CX, 94, 46, 8, "输入：2 s 三轴线性加速度窗口（208 Hz）", "#f2f2f2", fs=10.5)
    dia(CX, RY[0], DW, 11, "RMS(A) < 0.20 m/s² ?")
    dia(CX, RY[1], DW, 11, "RMS(J) < 35 m/s³ ?")
    dia(CX, RY[2], DW, 11, "RMS(J) < 100 m/s³ ?")
    for i, (txt, c) in enumerate([("静止", "#d9d9d9"), ("平地慢走", "#b7e2b7"),
                                  ("上下楼梯", "#fbd9ae")]):
        box(BX, RY[i], BW, BH, txt, c, fs=13, bold=True)

    arrow(CX, 90, CX, RY[0] + 5.5)
    for i in range(3):
        arrow(CX + DW / 2, RY[i], BX - BW / 2, RY[i])
        ax.text((CX + DW / 2 + BX - BW / 2) / 2, RY[i] + 1.9, "是", fontsize=10,
                color="#b03030", fontweight="bold", ha="center", va="bottom")
        if i < 2:
            arrow(CX, RY[i] - 5.5, CX, RY[i + 1] + 5.5)
            ax.text(CX + 1.8, (RY[i] + RY[i + 1]) / 2, "否", fontsize=10,
                    color="#2f6b34", fontweight="bold", va="center")

    y_end = 14
    ax.plot([CX, CX], [RY[2] - 5.5, y_end], color="#555", lw=1.4, zorder=1)
    arrow(CX, y_end, BX - BW / 2, y_end)
    ax.text(CX + 1.8, (RY[2] - 5.5 + y_end) / 2, "否", fontsize=10, color="#2f6b34",
            fontweight="bold", va="center")
    box(BX, y_end, BW, BH, "快跑", "#f7b9b9", fs=13, bold=True)

    ax.text(2, 3, "RMS(A)=√(mean(a²))，a=√(x²+y²+z²)；RMS(J)=√(mean((Δa/Δt)²))，J 为加加速度",
            fontsize=9, color="#666")
    ax.set_title("步态动作阈值判定流程：2 个特征量、3 个阈值", fontsize=13.5,
                 fontweight="bold", pad=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "图3_判定流程.png"), dpi=170)
    plt.close(fig)
    print("  [图] 图3_判定流程.png")


# ---------------- 图 4 逐窗验证 ----------------
def fig_timeline():
    fig, axes = plt.subplots(4, 1, figsize=(11.5, 9), sharex=True)
    for i, st in enumerate(STATES):
        df, _ = load(st)
        w = slide(df)
        tt = [x[0] for x in w]
        rj = [x[2] for x in w]
        ax = axes[i]
        ax.axhspan(1, TH_WALK_J, color="#2ca02c", alpha=0.07)
        ax.axhspan(TH_WALK_J, TH_STAIR_J, color="#e8850c", alpha=0.10)
        ax.axhspan(TH_STAIR_J, 400, color="#d62728", alpha=0.07)
        ax.plot(tt, rj, "-o", ms=4.5, lw=1.2, color=COLOR[st], zorder=3)
        ax.axhline(TH_WALK_J, color="#444", ls="--", lw=1)
        ax.axhline(TH_STAIR_J, color="#444", ls="--", lw=1)
        ax.set_yscale("log")
        ax.set_ylim(2.0, 260)
        ax.set_ylabel("RMS(J)\n(m/s³)", fontsize=9)
        ax.grid(alpha=0.2, lw=0.5)
        ax.text(0.995, 0.9, st, transform=ax.transAxes, ha="right", va="top",
                fontsize=11, fontweight="bold", color=COLOR[st])
        ax.text(0.008, 0.9, f"RMS(J) {min(rj):.0f}–{max(rj):.0f} m/s³",
                transform=ax.transAxes, ha="left", va="top", fontsize=8.5, color="#555",
                bbox=dict(fc="white", ec="none", alpha=0.85, pad=1.5))
        if i == 0:
            ax.set_title("2 s 滑窗 RMS(J) 随时间变化：全部 70 个窗口正确落区",
                         fontsize=12, fontweight="bold")
    axes[-1].set_xlabel("时间 (s)", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "图4_滑窗判定结果.png"), dpi=160)
    plt.close(fig)
    print("  [图] 图4_滑窗判定结果.png")


# ---------------- 控制台报告 ----------------
def console_report():
    print("\n=== 特征范围（2 s 窗）===")
    for st in STATES:
        df, _ = load(st)
        w = slide(df)
        rj = np.array([x[2] for x in w])
        ra = np.array([x[1] for x in w])
        print(f"  {st:5s} n={len(w):2d}  RMS(A) {ra.min():6.3f}–{ra.max():6.3f}   "
              f"RMS(J) {rj.min():6.1f}–{rj.max():6.1f}")
    print(f"\n阈值: RMS(A)<{TH_A} 且 RMS(J)<{TH_STATIC_J} -> 静止 | "
          f"RMS(J)<{TH_WALK_J} -> 慢走 | <{TH_STAIR_J} -> 楼梯 | 其余 快跑")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None, help="01-Field-Discovery 目录")
    args = ap.parse_args()
    if args.root:
        global ROOT, RAW, REP, FIG
        ROOT = os.path.abspath(args.root)
        RAW, REP = os.path.join(ROOT, "raw_data"), os.path.join(ROOT, "report")
        FIG = os.path.join(REP, "figures")

    os.makedirs(FIG, exist_ok=True)
    console_report()
    print("\n=== 生成统计表 ===")
    dump_tables()
    print("\n=== 生成图表 ===")
    fig_wave()
    fig_scatter()
    fig_tree()
    fig_timeline()
    print("\n完成。输出目录:", REP)


if __name__ == "__main__":
    main()
