# -*- coding: utf-8 -*-
"""
课题10 · AI 批处理脚本
把 samples/ 里的脏 CSV 汇总成一张表，并记录每个文件被修正了什么。

用法:
    python batch.py                # 处理 samples/ -> out/
    python batch.py --samples X --out Y

输出:
    out/汇总表.csv     每个文件一行：样本数 / 时长 / 峰值 / RMS
    out/异常日志.csv    每个文件被修正的问题：空行、重复行、备注行、单位换算
"""
import argparse
import hashlib
import os
import re
import sys
import time

import numpy as np
import pandas as pd

G = 9.80665
BASE = os.path.dirname(os.path.abspath(__file__))


def sniff_delimiter(first_line):
    return ";" if first_line.count(";") > first_line.count(",") else ","


def parse_units(header):
    """从表头文本读单位：时间 s/ms，加速度 m/s^2 或 g"""
    h = " ".join(header).lower()
    t_unit = "ms" if re.search(r"\(\s*ms\s*\)|（\s*ms\s*）", h) else "s"
    if re.search(r"\(\s*g\s*\)|（\s*g\s*）", h):
        a_unit = "g"
    elif re.search(r"m/s", h):
        a_unit = "m/s2"
    else:
        raise ValueError(f"无法识别加速度单位：{header}")
    return t_unit, a_unit


def process_one(path):
    t0 = time.perf_counter()

    with open(path, "r", encoding="utf-8-sig") as f:
        first = f.readline().strip()

    sep = sniff_delimiter(first)
    header = [c.strip() for c in first.split(sep)]
    t_unit, a_unit = parse_units(header)

    # 读数据：跳过空行、丢弃 # 注释行与可能存在的尾注
    df = pd.read_csv(path, sep=sep, encoding="utf-8-sig", skip_blank_lines=True,
                     comment="#", header=0)
    df.columns = ["t", "ax", "ay", "az"]
    n_raw = len(df)

    df = df.dropna(how="all")
    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.dropna(how="any")

    n_blank = 0  # 空行被 read_csv 的 skip_blank_lines 直接吞掉，单独统计
    with open(path, "r", encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    n_blank = sum(1 for l in lines if not l.strip())
    n_comment = sum(1 for l in lines if l.lstrip().startswith("#"))

    n_before = len(df)
    df = df.drop_duplicates()
    n_dup = n_before - len(df)

    # 单位换算
    if a_unit == "g":
        df[["ax", "ay", "az"]] *= G
    if t_unit == "ms":
        df["t"] /= 1000.0

    df = df.sort_values("t").reset_index(drop=True)

    a = np.sqrt(df[["ax", "ay", "az"]].pow(2).sum(1).values)
    row = {
        "文件名": os.path.basename(path),
        "样本数": len(df),
        "原始行数": n_raw,
        "有效时长_s": round(float(df["t"].iloc[-1] - df["t"].iloc[0]), 4),
        "峰值_a": round(float(a.max()), 4),
        "RMS_a": round(float(np.sqrt(np.mean(a ** 2))), 4),
        "原时间单位": t_unit,
        "原加速度单位": a_unit,
    }
    issues = {
        "文件名": os.path.basename(path),
        "空行": n_blank,
        "重复行": n_dup,
        "备注行": n_comment,
        "单位换算": "×9.80665" if a_unit == "g" else "—",
        "耗时_ms": round((time.perf_counter() - t0) * 1000, 3),
    }
    return row, issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=os.path.join(BASE, "samples"))
    ap.add_argument("--out", default=os.path.join(BASE, "out"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    files = sorted(f for f in os.listdir(args.samples)
                   if f.lower().endswith(".csv") and not f.startswith("_"))
    if not files:
        sys.exit(f"{args.samples} 里没有 CSV")

    t_start = time.perf_counter()
    rows, issues = [], []
    for name in files:
        r, i = process_one(os.path.join(args.samples, name))
        rows.append(r)
        issues.append(i)
        print(f"  {name}  {r['样本数']:>4} 行  {r['有效时长_s']:>7.3f} s  "
              f"峰值 {r['峰值_a']:>7.3f}  RMS {r['RMS_a']:>7.3f}  "
              f"({i['耗时_ms']:.1f} ms)")
    total = (time.perf_counter() - t_start) * 1000

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(args.out, "汇总表.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame(issues).to_csv(os.path.join(args.out, "异常日志.csv"),
                                index=False, encoding="utf-8-sig")

    # 运行留痕
    h = hashlib.sha256()
    for name in files:
        with open(os.path.join(args.samples, name), "rb") as f:
            h.update(f.read())
    log = (f"time={time.strftime('%Y-%m-%d %H:%M:%S')}\n"
           f"script_sha256={hashlib.sha256(open(__file__, 'rb').read()).hexdigest()[:16]}\n"
           f"input_sha256={h.hexdigest()[:16]}\n"
           f"files={len(files)}\n"
           f"total_ms={total:.1f}\n"
           f"per_file_mean_ms={total / len(files):.3f}\n")
    with open(os.path.join(args.out, "run.log"), "w", encoding="utf-8") as f:
        f.write(log)

    print(f"\n合计 {len(files)} 个文件，总耗时 {total:.1f} ms，"
          f"单文件均 {total / len(files):.2f} ms")
    print(f"输出：{args.out}")


if __name__ == "__main__":
    main()
