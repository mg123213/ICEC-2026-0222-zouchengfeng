# -*- coding: utf-8 -*-
"""
课题10 · 计时基准
把 batch.py 当作黑盒跑 N 次（含解释器启动），取中位数作为「AI 处理 10 个样本」的耗时。
重复多次是为了避开首次运行的冷启动（导入 pandas / 读盘缓存）。

用法: python bench.py [--runs 7]
输出: out/耗时_AI.csv
"""
import argparse
import os
import shutil
import statistics
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "out")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=7)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    script = os.path.join(BASE, "batch.py")
    samples = os.path.join(BASE, "samples")
    tmp = os.path.join(OUT, "_bench_tmp")

    walls = []
    for k in range(args.runs):
        t0 = time.perf_counter()
        subprocess.run([sys.executable, script, "--samples", samples, "--out", tmp],
                       check=True, stdout=subprocess.DEVNULL)
        walls.append(time.perf_counter() - t0)
        print(f"  第 {k + 1} 次：{walls[-1] * 1000:.0f} ms")

    med = statistics.median(walls)
    print(f"\n运行 {args.runs} 次：中位数 {med * 1000:.0f} ms，"
          f"最快 {min(walls) * 1000:.0f} ms，最慢 {max(walls) * 1000:.0f} ms")
    print(f"单样本均摊 {med / 10 * 1000:.1f} ms")

    import csv
    with open(os.path.join(OUT, "耗时_AI.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["运行序号", "总耗时_s", "单样本均摊_s"])
        for i, v in enumerate(walls, 1):
            w.writerow([i, f"{v:.4f}", f"{v / 10:.5f}"])
        w.writerow(["中位数", f"{med:.4f}", f"{med / 10:.5f}"])
    shutil.rmtree(tmp, ignore_errors=True)   # 清掉基准过程中的临时输出
    print(f"已写入 {os.path.join(OUT, '耗时_AI.csv')}")


if __name__ == "__main__":
    main()
