# -*- coding: utf-8 -*-
"""
课题10 · 人工耗时「秒表轨」

用途：给人工耗时补一份**独立于 Excel 实录**的读数——一次掐一个样本，
      做完立刻按 Enter，工具把这一次的真实墙钟记下来。两套并存：
        out/人工耗时.csv       ← Excel 实录（10 个样本，逐步截图）
        out/人工耗时_秒表.csv   ← 本工具（3~5 个样本即可，秒表口径）

规则（务必照做，否则和 AI 那边不可比）：
    - 一次只做一个样本，做完立刻按 Enter，别攒着
    - 中途不要接电话、不要切窗口看别的
    - 第 1 个样本算热身，默认不计入（可用 --keep-warmup 保留）
    - 时间不够可以只做 3~5 个，按 q 结束，compare.py 会按均值外推

用法:
    python manual_timer.py                 # 做完 10 个
    python manual_timer.py --keep-warmup
    python manual_timer.py --files S01.csv S02.csv S03.csv
"""
import argparse
import csv
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "out")
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
 6. 和标准答案对一眼，一致才做下一个
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

    print("=" * 68)
    print(" 课题10 · 人工耗时「秒表轨」")
    print(" 这是给 out/人工耗时.csv（Excel 操作实录）做交叉验证的第二条计时线。")
    print(" 建议只做 3~5 个样本；结果写 out/人工耗时_秒表.csv，不覆盖实录。")
    print("=" * 68)
    print(SOP)
    print(f"共 {len(files)} 个样本：{', '.join(files)}")
    print("每做完一个样本按 Enter；输入 q 提前结束。")
    print("（建议只做 3~5 个：这一轨是给「Excel 实录」做交叉验证的，不必做完 10 个）\n")

    pause("准备好后按 Enter 开始计时 …")

    recs = []
    t_prev = time.perf_counter()
    for i, name in enumerate(files, 1):
        print(f"[{i:2d}/{len(files)}] 现在处理：{name}   {time.strftime('%H:%M:%S')}")
        ans = pause("       做完按 Enter … ")
        now = time.perf_counter()
        dt = now - t_prev
        t_prev = now
        recs.append({"序号": i, "文件": name, "耗时_s": round(dt, 2),
                     "结束时刻": time.strftime("%H:%M:%S"),
                     "累计_s": round(sum(r["耗时_s"] for r in recs) + dt, 2)})
        print(f"       记录：{dt:.2f} s（累计 {recs[-1]['累计_s']:.1f} s）\n")
        if ans == "q":
            print("已提前结束。")
            break

    # 第一个样本视为热身；样本少（≤4）时不舍弃，否则有效样本太少，外推不稳
    warm = 1 if (len(recs) >= 5 and not args.keep_warmup) else 0
    valid = recs[warm:]
    if warm == 0:
        print("\n（样本数 ≤ 4，未剔除热身样本，第 1 个也计入）")
    if valid:
        mean = sum(r["耗时_s"] for r in valid) / len(valid)
        print(f"\n有效样本 {len(valid)} 个，单样本均值 {mean:.1f} s")
        print(f"按均值外推到 10 个样本：{mean * 10 / 60:.1f} min")

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "人工耗时_秒表.csv")
    started = time.strftime("%Y-%m-%d %H:%M")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["序号", "文件", "耗时_s", "累计_s", "结束时刻", "是否热身"])
        for r in recs:
            w.writerow([r["序号"], r["文件"], r["耗时_s"], r["累计_s"],
                        r["结束时刻"], "是" if r["序号"] <= warm else "否"])
    print(f"\n会话时间：{started} 起")
    print(f"已写入 {path}")
    print("接着跑 python compare.py —— 这份秒表数据会自动并进对比表（多一列「秒表_s」）。")


if __name__ == "__main__":
    main()
