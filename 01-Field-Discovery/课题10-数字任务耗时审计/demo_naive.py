# -*- coding: utf-8 -*-
"""
课题10 · 反例演示：用最直观的写法处理同样的样本会发生什么

这是"不懂数据会长什么样"时的默认写法：
    pd.read_csv(path)                 # 默认逗号
    a = sqrt(x^2+y^2+z^2)             # 直接算，不换算单位
    取峰值 / RMS                       # 不做任何校验

跑 S06（分号分隔）和 S02（g 单位）会得到与标准答案不符的结果，
而整个过程**不会抛出任何异常** —— 这就是本课题要防的那种错。

用法: python demo_naive.py
"""
import json
import os

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
TRUTH = json.load(open(os.path.join(BASE, "samples", "_truth.json"), encoding="utf-8"))


def naive(path):
    df = pd.read_csv(path, encoding="utf-8-sig")     # 默认只认逗号
    if df.shape[1] < 4:
        return None, df.shape
    x = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    y = pd.to_numeric(df.iloc[:, 2], errors="coerce")
    z = pd.to_numeric(df.iloc[:, 3], errors="coerce")
    a = np.sqrt(x ** 2 + y ** 2 + z ** 2)
    return {"样本数": int(len(df)), "峰值_a": float(np.nanmax(a)),
            "RMS_a": float(np.sqrt(np.nanmean(a ** 2)))}, df.shape


def main():
    print("=== 直观写法的结果 vs 标准答案 ===\n")
    for tag in ["S06.csv", "S02.csv"]:
        path = os.path.join(BASE, "samples", tag)
        got, shape = naive(path)
        t = TRUTH[tag[:-4]]
        print(f"[{tag}]  读入后列数 = {shape[1]}（应为 4：时间 + 三轴）")
        if got is None:
            print("  → 整行被挤进 1 列，一行也算不出来。程序不报错，只是结果表里这一行是空的。\n")
            continue
        print(f"  峰值  naive={got['峰值_a']:9.4f}   真值={t['peak_a']:9.4f}   "
              f"变成 {got['峰值_a'] / t['peak_a']:.3f} 倍")
        print(f"  RMS   naive={got['RMS_a']:9.4f}   真值={t['rms_a']:9.4f}   "
              f"变成 {got['RMS_a'] / t['rms_a']:.3f} 倍")
        print(f"  样本数 naive={got['样本数']:6d}   真值={t['n_rows']:6d}\n")

    print("结论：两类错误都没有抛出异常，脚本会正常退出、正常写出表格。")
    print("      单看输出看不出来，只有跟标准答案比才会暴露 —— 所以必须有 L2 异常登记与 L3 抽样复核。")


if __name__ == "__main__":
    main()
