# ICEC 2026 · 阶段作业仓库

| | |
|---|---|
| **姓名** | 邹承丰 |
| **学号** | 2024400222 |
| **仓库** | `ICEC-2026-0222-zouchengfeng` |
| **当前进度** | 阶段一 ✅ ｜ 阶段二 ⏳ ｜ 阶段三 ⏳ |

---

## 一、选题说明

**课题 08：多姿态步态加速度特征采集与对比**

用手机传感器（HONOR AAK-AN00 + Phyphox）采集平地慢走、快跑、上下楼梯、静止
四种状态的三轴加速度，回答一个问题：

> 能不能只用几条阈值规则，把四种日常姿态分开？

答案是能，而且只需要两个特征量：

| 状态 | RMS(A) m/s² | RMS(J) m/s³ | 判定规则 |
|---|---|---|---|
| 静止 | 0.024 | 2.6 | `RMS(A) < 0.20` 且 `RMS(J) < 8` |
| 平地慢走 | 2.24 | 22.9 | `RMS(J) < 35` |
| 上下楼梯 | 3.82 | 65.9 | `35 ≤ RMS(J) < 100` |
| 快跑 | 8.34 | 146.8 | `RMS(J) ≥ 100` |

其中 `RMS(J)` 是**加加速度（jerk）的均方根**——它不是"动得多大"，而是"动得多急"。
这一步是整套规则的关键：只比幅值的话，慢走上界 2.86 与楼梯下界 3.04 只差 6%，
阈值根本无法落笔；换到 jerk 之后间隙拉到 71%，阈值放在中间两头都还剩 30% 余量。

**这三条线是怎么提炼出来的**，报告里写成了完整四步：
① 9 个候选特征算可分性，按"是否单调 + 归一化间隙"筛掉 4 个不单调的、再在剩下的里挑出 RMS(J)；
② 用 2 s 滑窗统计每类的取值区间（阈值只能从区间缝隙里取，不能从波形上看）；
③ 阈值取相邻区间边界的**几何中点**，保证两侧相对余量对称；
④ 逐窗回测，确认没有窗口踩线。

**验证结果**：2 s 滑窗切出 70 个窗口，全部 4 类判定正确（70/70）。
1 s 窗下 76/78，两个误判都出现在起跑加速与收尾减速的过渡段——不是规则失效，
而是那两段确实处于两种动作之间。

完整分析见 [`01-Field-Discovery/report/课题08_阈值规则说明.md`](01-Field-Discovery/report/课题08_阈值规则说明.md)。

---

## 二、目录结构

```
ICEC-2026-0222-zouchengfeng/
├── README.md                     # 本文件：个人简介与选题说明
├── 01-Field-Discovery/           # 阶段一：现场发现
│   ├── report/                   #   分析报告 + 图表 + 统计表
│   ├── photos/                   #   Phyphox 采集界面截图
│   └── raw_data/                 #   4 份原始 CSV 波形 + 合并表
├── 02-20Days-Challenge/          # 阶段二：20 天挑战
│   ├── src/                      #   源码
│   ├── process_logs/             #   每日过程日志
│   └── iterations/               #   迭代版本留档
└── 03-AI-Collaboration/          # 阶段三：AI 协作记录
    └── README.md                 #   关键提问与排障对话
```

---

## 三、快速查看

| 想看的 | 点这里 |
|---|---|
| 四状态波形对比 | [图1](01-Field-Discovery/report/figures/图1_四状态三轴波形.png) |
| 特征空间与阈值线 | [图2](01-Field-Discovery/report/figures/图2_特征分布与阈值.png) |
| 判定流程图 | [图3](01-Field-Discovery/report/figures/图3_判定流程.png) |
| 70 个窗口逐窗验证 | [图4](01-Field-Discovery/report/figures/图4_滑窗判定结果.png) |
| 原始波形数据 | [`01-Field-Discovery/raw_data/`](01-Field-Discovery/raw_data/) |

原始 CSV 与 Phyphox 导出的 `Raw Data.csv` **逐字节一致**（MD5 校验），仅重命名。
列声明：`Time (s)` / `Linear Acceleration x,y,z (m/s^2)` / `Absolute acceleration (m/s^2)`，
采样率 **208.2 Hz**，单段约 10 s。注意这是**已去重力**的线性加速度，
末列最小值为 0、曲线围绕 0 摆动，没有 ±9.8 的重力基线。

---

## 四、复现

分析链路不依赖任何机器学习框架，只需要 numpy / pandas / matplotlib / scipy。
一条命令即可从原始 CSV 重新算出全部图表与统计表：

```bash
pip install numpy pandas matplotlib scipy

cd 01-Field-Discovery
python scripts/analyze.py       # 重算 表1/表2 与四张图
python scripts/screening.py     # 重算 表3（候选特征可分性排序）
```

`analyze.py` 会读 `raw_data/` 里的四份原始 CSV，重算特征、套用阈值、逐窗验证，
把 `表1` / `表2` 和四张图重新写回 `report/`；
控制台会打印各状态的实测范围与最终准确率（应为 70/70 = 100%）。
`screening.py` 打印的就是"为什么最后用 RMS(J)"那张筛选表，可以拿自己的数对着核。

---

## 五、进度

- [x] **阶段一 · Field Discovery** — 四状态数据采集、特征提取、阈值规则提炼与验证
- [ ] **阶段二 · 20 Days Challenge** — 待开始
- [x] **阶段三 · AI Collaboration** — 关键提问记录已归档（随阶段二持续补充）

---

<sub>本仓库为 ICEC 2026 课程作业，数据为本人实测采集。</sub>
