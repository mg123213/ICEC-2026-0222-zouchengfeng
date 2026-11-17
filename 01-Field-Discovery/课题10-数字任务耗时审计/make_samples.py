# -*- coding: utf-8 -*-
"""
课题10 · 生成 10 个「脏」样本 + 标准答案

任务背景：把 10 份来自不同采集批次的加速度记录汇总成一张表。
每个样本都带同样 3 类问题（表头格式不统一 / 混入无效行 / 单位不同），
只是具体参数不同 —— 保证「人工单样本耗时」可比。

产物：
    samples/S01.csv … S10.csv     供人和脚本处理的样本
    samples/_truth.json           标准答案（人工不提供，仅用于评分脚本正确性）
"""
import json
import os

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
# 源数据随仓库一起提供（课题08 的原始采集，取自其中四段）
SRC_DIR = os.path.join(BASE, "samples", "_source")
SRC = ["01_静止_原始波形.csv", "02_平地慢走_原始波形.csv",
       "03_快跑_原始波形.csv", "04_上下楼梯_原始波形.csv"]

N_ROWS = 600          # 每个样本的有效数据行数（约 2.9 s）
G = 9.80665
rng = np.random.default_rng(20261112)

# 10 个样本的格式配置：表头语言 / 时间单位 / 加速度单位 / 无效行数 / 分隔符
CONFIG = [
    # (表头风格, 时间单位, 加速度单位, 空行数, 重复行数, 尾部备注, 分隔符)
    ("en", "s",  "ms2", 1, 0, False, ","),
    ("cn", "s",  "g",   2, 1, True,  ","),
    ("en", "ms", "ms2", 1, 1, False, ","),
    ("cn", "s",  "ms2", 3, 0, True,  ","),
    ("en", "s",  "g",   2, 1, True,  ","),
    ("en", "s",  "ms2", 0, 1, True,  "semicolon"),
    ("cn", "ms", "g",   2, 0, False, ","),
    ("en", "s",  "ms2", 1, 2, False, ","),
    ("cn", "s",  "g",   1, 1, True,  "semicolon"),
    ("en", "ms", "ms2", 2, 1, True,  ","),
]

HEADER = {
    ("en", "s",  "ms2"): ["Time (s)", "ax (m/s^2)", "ay (m/s^2)", "az (m/s^2)"],
    ("en", "s",  "g"):   ["Time (s)", "ax (g)", "ay (g)", "az (g)"],
    ("en", "ms", "ms2"): ["Time (ms)", "ax (m/s^2)", "ay (m/s^2)", "az (m/s^2)"],
    ("en", "ms", "g"):   ["Time (ms)", "ax (g)", "ay (g)", "az (g)"],
    ("cn", "s",  "ms2"): ["时间(s)", "X轴加速度(m/s2)", "Y轴加速度(m/s2)", "Z轴加速度(m/s2)"],
    ("cn", "s",  "g"):   ["时间(s)", "X轴加速度(g)", "Y轴加速度(g)", "Z轴加速度(g)"],
    ("cn", "ms", "ms2"): ["时间(ms)", "X轴加速度(m/s2)", "Y轴加速度(m/s2)", "Z轴加速度(m/s2)"],
    ("cn", "ms", "g"):   ["时间(ms)", "X轴加速度(g)", "Y轴加速度(g)", "Z轴加速度(g)"],
}


def load_sources():
    dfs = []
    for name in SRC:
        d = pd.read_csv(os.path.join(SRC_DIR, name))
        d.columns = ["t", "x", "y", "z", "a"]
        dfs.append(d[["t", "x", "y", "z"]].values)
    return dfs


def main():
    pool = load_sources()
    truth = {}
    for i, (lang, tunit, aunit, n_blank, n_dup, footer, sep) in enumerate(CONFIG, 1):
        tag = f"S{i:02d}"
        src = pool[(i - 1) % len(pool)]
        start = rng.integers(0, len(src) - N_ROWS - 5)
        seg = src[start:start + N_ROWS].copy()

        # 时间轴从 0 起，按目标单位换算
        t = seg[:, 0] - seg[0, 0]
        t = t * 1000.0 if tunit == "ms" else t
        acc = seg[:, 1:4].copy()

        # 标准答案（m/s^2，未换算前的真实值）
        a_mag = np.sqrt((acc ** 2).sum(1))
        truth[tag] = {
            "file": f"{tag}.csv",
            "n_rows": int(N_ROWS),
            "duration_s": round(float(seg[-1, 0] - seg[0, 0]), 4),
            "peak_a": round(float(a_mag.max()), 4),
            "rms_a": round(float(np.sqrt(np.mean(a_mag ** 2))), 4),
            "time_unit": tunit,
            "acc_unit": aunit,
        }

        # 按目标单位改写数值
        out_acc = acc / G if aunit == "g" else acc

        rows = [list(np.column_stack([t, out_acc])[k]) for k in range(N_ROWS)]

        # 注入无效行：空行 / 整行重复 / 尾部备注
        for _ in range(n_blank):
            pos = int(rng.integers(5, len(rows) - 5))
            rows.insert(pos, [None, None, None, None])
        for _ in range(n_dup):
            pos = int(rng.integers(5, len(rows) - 5))
            rows.insert(pos, list(rows[pos]))

        sep_char = ";" if sep == "semicolon" else ","
        lines = [sep_char.join(HEADER[(lang, tunit, aunit)])]
        for r in rows:
            if r[0] is None:
                lines.append("")
            else:
                lines.append(sep_char.join(
                    f"{r[0]:.6f}" if k == 0 else f"{r[k]:.9f}" for k in range(4)))
        if footer:
            lines.append("")
            lines.append(f"# 采集批次 {tag} / 导出时间 2026-11-12 / 合计 {N_ROWS} 条")

        path = os.path.join(BASE, "samples", f"{tag}.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            f.write("\n".join(lines) + "\n")

        print(f"{tag}  {lang}/{tunit}/{aunit}  空行{n_blank} 重复{n_dup} "
              f"尾注{int(footer)} 分隔[{sep_char}]  → {len(lines)} 行")

    with open(os.path.join(BASE, "samples", "_truth.json"), "w", encoding="utf-8") as f:
        json.dump(truth, f, ensure_ascii=False, indent=2)
    print("\n标准答案已写入 samples/_truth.json")


if __name__ == "__main__":
    main()
