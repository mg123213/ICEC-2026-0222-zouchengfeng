# -*- coding: utf-8 -*-
"""
课题10 · 正确性校验
把 batch.py 的结果与 _truth.json 逐项比对，输出逐样本误差与总错误率。
（batch.py 本身不读标准答案，避免"既当运动员又当裁判"）
"""
import json
import os

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
TOL = 1e-3          # 数值相对误差容差 0.1%
FIELDS = [("样本数", "n_rows", 0), ("有效时长_s", "duration_s", TOL),
          ("峰值_a", "peak_a", TOL), ("RMS_a", "rms_a", TOL)]


def main():
    truth = json.load(open(os.path.join(BASE, "samples", "_truth.json"), encoding="utf-8"))
    got = pd.read_csv(os.path.join(BASE, "out", "汇总表.csv")).set_index("文件名")

    rows, bad = [], 0
    for tag, t in truth.items():
        name = t["file"]
        rec = {"文件": name}
        ok_all = True
        for col, key, tol in FIELDS:
            g = float(got.loc[name, col])
            e = float(t[key])
            if tol == 0:
                ok = int(g) == int(e)
                err = abs(g - e)
            else:
                err = abs(g - e) / max(abs(e), 1e-9)
                ok = err <= tol
            ok_all &= ok
            rec[col] = f"{g:g}"
            rec[col + "_误差"] = f"{err:.2e}"
            rec[col + "_判定"] = "✓" if ok else "✗"
        rec["整行判定"] = "✓" if ok_all else "✗"
        bad += 0 if ok_all else 1
        rows.append(rec)

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(BASE, "out", "校验明细.csv"), index=False, encoding="utf-8-sig")

    n_cell = len(truth) * len(FIELDS)
    n_ok = df[[f"{c}_判定" for c, _, _ in FIELDS]].stack().eq("✓").sum()
    print(df[["文件"] + [f"{c}_判定" for c, _, _ in FIELDS] + ["整行判定"]]
          .to_string(index=False))
    print(f"\n字段级：{n_ok}/{n_cell} 正确 = {n_ok / n_cell * 100:.1f}%")
    print(f"整行级：{len(truth) - bad}/{len(truth)} 正确 = {(len(truth) - bad) / len(truth) * 100:.1f}%")
    return bad


if __name__ == "__main__":
    main()
