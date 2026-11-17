# -*- coding: utf-8 -*-
"""
课题10 · 人工耗时计时器
用秒表方式记录你自己处理每个样本的真实耗时，结果写入 out/人工耗时.csv。

规则（务必照做，否则和 AI 那边不可比）：
    - 一次只做一个样本，做完立刻按 Enter，别攒着
    - 中途不要接电话、不要切窗口看别的
    - 前 1 个样本算热身，默认不计入（可用 --keep-warmup 保留）
    - 时间不够可以只做前 3~5 个，按 q 结束，报告里会按均值外推

用法:
    python manual_timer.py
    python manual_timer.py --keep-warmup
    python manual_timer.py --files S01.csv S02.csv S03.csv
"""
import argparse
import csv
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

SOP = """
================== 人工处理规范（每个样本都照这个走）==================
 1. 打开样本（Excel / 记事本都行）
 2. 看表头：时间是 s 还是 ms？加速度是 m/s^2 还是 g？
 3. 删掉空行、整行重复、以及末尾以 # 开头的备注行
 4. 若加速度单位是 g，全部 ×9.80665 换算成 m/s^2；时间若是 ms，÷1000
 5. 算出 4 个指标并抄进汇总表：
       样本数 = 剩余数据行数
       有效时长 = 末行时间 - 首行时间
       峰值   = max( √(ax²+ay²+az²) )
       RMS    = √( mean( ax²+ay²+az² ) )
=====================================================================
"""


def pause(msg):
    try:
        return input(msg).strip().lower()
    except EOFError:
        return "q"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-warmup", action="store_true")
    ap.add_argument("--files", nargs="*", default=None)
    args = ap.parse_args()

    sdir = os.path.join(BASE, "samples")
    files = args.files or sorted(f for f in os.listdir(sdir)
                                 if f.lower().endswith(".csv") and not f.startswith("_"))
    if not files:
        sys.exit("samples/ 里没有 CSV，先跑 make_samples.py")

    print(SOP)
    print(f"共 {len(files)} 个样本：{', '.join(files)}")
    print("每做完一个样本按 Enter；输入 q 提前结束。\n")

    pause("准备好后按 Enter 开始计时 …")

    recs = []
    t_prev = time.perf_counter()
    for i, name in enumerate(files, 1):
        print(f"[{i:2d}/{len(files)}] 现在处理：{name}")
        ans = pause("       做完按 Enter … ")
        now = time.perf_counter()
        dt = now - t_prev
        t_prev = now
        recs.append({"序号": i, "文件": name, "耗时_s": round(dt, 2),
                     "累计_s": round(sum(r["耗时_s"] for r in recs) + dt, 2)})
        print(f"       记录：{dt:.2f} s（累计 {recs[-1]['累计_s']:.1f} s）\n")
        if ans == "q":
            print("已提前结束。")
            break

    # 第一个样本视为热身
    # 样本少（≤4）时不舍弃热身，否则有效样本太少，外推不稳
    warm = 1 if (len(recs) >= 5 and not args.keep_warmup) else 0
    valid = recs[warm:]
    if warm == 0:
        print("\n（样本数 ≤ 4，未剔除热身样本，第 1 个也计入）")
    if valid:
        mean = sum(r["耗时_s"] for r in valid) / len(valid)
        print(f"\n有效样本 {len(valid)} 个，单样本均值 {mean:.1f} s")
        print(f"按均值外推到 10 个样本：{mean * 10 / 60:.1f} min")

    os.makedirs(os.path.join(BASE, "out"), exist_ok=True)
    path = os.path.join(BASE, "out", "人工耗时.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["序号", "文件", "耗时_s", "累计_s", "是否热身"])
        for r in recs:
            w.writerow([r["序号"], r["文件"], r["耗时_s"], r["累计_s"],
                        "是" if r["序号"] <= warm else "否"])
    print(f"已写入 {path}")
    print("把这份 CSV 留着，报告里的「人工耗时」列会从它算。")


if __name__ == "__main__":
    main()
