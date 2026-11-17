# -*- coding: utf-8 -*-
"""
课题10 · 生成人工耗时估算基线（按步骤分解建模）

用途：在没有秒表实测的情况下，按操作步骤分解估算人工耗时，
     用于跑通分析链路、给出对比量级。属于建模估算，不是秒表实测值。

建模方式：按人工处理的实际步骤分解，各步骤耗时与样本自身的问题数量挂钩
（问题越多的文件，人工也越慢），再叠加学习效应与随机扰动——
这样生成的数与样本的真实属性一致，而不是随机乱数。

    打开文件看清结构   10 s
    判断单位            4 s
    清脏行              6 + 4.5 × (空行 + 重复 + 备注)
    单位换算 g→m/s²    12 s   （仅 g 单位文件）
    时间换算 ms→s       6 s   （仅 ms 时间文件）
    算 4 个指标         25 s   （建辅助列 + 4 个公式）
    抄入汇总表          8 s
    自查核对            6 s
"""
import os
import random

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "out")
random.seed(20261112)

SOP = dict(open_file=10.0, judge_unit=4.0, clean_base=6.0, per_junk=4.5,
           conv_g=12.0, conv_ms=6.0, metrics=25.0, copy=8.0, selfcheck=6.0)


def main():
    log = pd.read_csv(os.path.join(OUT, "异常日志.csv"))
    rows = []
    for i, r in log.iterrows():
        junk = int(r["空行"]) + int(r["重复行"]) + int(r["备注行"])
        t = (SOP["open_file"] + SOP["judge_unit"] + SOP["clean_base"] + SOP["per_junk"] * junk
             + SOP["metrics"] + SOP["copy"] + SOP["selfcheck"])
        if str(r["单位换算"]).startswith("×"):
            t += SOP["conv_g"]
        if r["文件名"] in ("S03.csv", "S07.csv", "S10.csv"):
            t += SOP["conv_ms"]
        t *= 1 - 0.020 * i                      # 学习效应：越做越熟
        t *= random.uniform(0.92, 1.08)         # 手速扰动
        rows.append({"序号": i + 1, "文件": r["文件名"],
                     "耗时_s": round(t, 2), "数据来源": "估算"})

    df = pd.DataFrame(rows)
    df["累计_s"] = df["耗时_s"].cumsum().round(2)
    df["是否热身"] = "否"
    path = os.path.join(OUT, "人工耗时_估算.csv")
    df.to_csv(path, index=False, encoding="utf-8-sig")

    print(df.to_string(index=False))
    print(f"\n合计 {df['耗时_s'].sum():.1f} s = {df['耗时_s'].sum() / 60:.1f} min")
    print(f"单样本均值 {df['耗时_s'].mean():.1f} s")
    print(f"\n已写入 {path}")
    print("拿到实测后跑 manual_timer.py，compare.py 会自动优先读实测数据。")


if __name__ == "__main__":
    main()
