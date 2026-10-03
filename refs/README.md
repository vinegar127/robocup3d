# refs · 参考资料

本目录存放备赛过程中的原始参考资料。

---

## 文件说明

| 文件 | 说明 | 来源 |
|------|------|------|
| `队内资料调研-RoboCup3D.pdf` | 队内整理的 RoboCup3D 资料调研文档，包含比赛信息、规则、论文解读、可用代码库清单 | 队内自建 |

> 📌 **本文档是本仓库 `docs/03-技术入门.md` 的重要来源之一。**
> `docs/03-技术入门.md` 里的论文导读部分，主要基于这份调研文档展开。

---

## PDF 里提到的论文清单

按调研文档的编号（详细解读见 `docs/03-技术入门.md` 第 3 节）：

| # | 论文 | 年份 | 主题 |
|---|------|------|------|
| 1 | 6D Localization and Kicking for Humanoid Robotic Soccer | 2021 | 6D 定位 + 移动中踢球 |
| 2 | Learning Humanoid Robot Running Motions with Symmetry Incentive through PPO | 2021 | 端到端 PPO 学跑步 |
| 3 | Deep Reinforcement Learning for Humanoid Robot Behaviors | 2022 | 分层架构：RL 规划 + Walking Engine |
| 4 | Learning Push Recovery Behaviors for Humanoid Walking Using Deep RL | 2022 | 抗推力恢复 |
| 5 | A survey of research on several problems in the RoboCup3D simulation environment | 2025 | 综述（南京大学） |
| 6 | Designing a Skilled Soccer Team for RoboCup: Exploring Skill-Set-Primitives through RL | 2025 | FC Portugal 技术报告（22/23 冠军） |

### 建议阅读顺序

**不要按年份读。**

```
① 论文 5（综述）        —— 先建立全局地图
② 论文 6（冠军技术报告）—— 看冠军队伍怎么组织工程
③ 按你的分工选读 1~4
```

详细的论文导读（每篇解决什么问题、方法是什么、结论是什么）
见 **`docs/03-技术入门.md`**。

---

## 怎么获取这些论文

| 途径 | 说明 |
|------|------|
| Google Scholar | 搜标题即可 |
| arXiv | 大部分有预印本 |
| RoboCup 官方论文库 | <https://archive.robocup.info/> |
| 各队技术报告（TDP） | <https://archive.robocup.info/> 有历届全部队伍的 TDP |
| 学校图书馆 VPN | 通过学校订阅的数据库访问 IEEE / Springer |

> ★ **强烈推荐 <https://archive.robocup.info/>**。
> 历届所有队伍的技术报告都能下载。
> **读 5 篇往届 TDP 的收获，超过读 50 篇中文博客。**

---

## 阅读论文的正确方法

**不要试图「复现论文」** —— 那是博士做了几年的成果，你复现不出来。

正确的用法是三步：

```
1. 读摘要 + 引言 → 它解决什么问题？为什么这个问题重要？
2. 读方法章节     → 核心洞见是什么？（通常只有一两句话）
3. 跳过实验细节   → 只看结论：效果提升了多少？
```

然后问自己：**「这个核心洞见，我能不能用最简单的方式实现一遍？」**

**举例**：

| 论文 | 核心洞见（一句话） | 你能怎么用 |
|------|------------------|-----------|
| 论文 1 | 先估垂直姿态，定位问题就会大幅简化 | 用加速度计粗略判断 pitch/roll，就已赚到 |
| 论文 2 | 左右对称是强先验，能加速收敛 | 让你的步态左右腿参数严格对称 |
| 论文 3 | 控制问题传统方法已解决，不必引入深度学习 | 别急着用 RL 替换行走引擎 |
| 论文 6 | 让所有动作共享一个底层步态，切换才连续 | 你的 walk/turn/kick 应该有共同的底层状态 |

> 💡 **判断你是否读懂了一篇论文的标准**：
> 你能否用**一句话**说清它的核心洞见，并且说出
> **「如果我来做，最简版本是什么样」**。
> 如果不能，说明你还没读懂，只是「看过」。

---

## 相关官方资源

| 内容 | 链接 | 说明 |
|------|------|------|
| RoboCup 3D 仿真官方服务器文档 | <https://robocup-sim.gitlab.io/rcssservermj/> | **最重要**，2026 起的技术依据 |
| 仿真组官方总站 | <https://ssim.robocup.org/> | 3D 子页：`/3d-simulation/`（含 rules / history / tools） |
| 历届论文与规则存档 | <https://archive.robocup.info/> | 历年规则 PDF + 技术报告 |
| **官方技术报告（TDP）库** | <https://tdp.robocup.org/> | 历届队伍技术报告，**强烈推荐** |
| 中国赛区规则与通知 | <https://rcccaa.drct-caa.org.cn/> | 国内赛事官方 |
| 国际 RoboCup 官网 | <https://www.robocup.org/> | — |
| 2D 仿真官方手册 | <https://rcsoccersim.readthedocs.io/> | 2D 方向的权威文档 |
| 2D 仿真官方站点 | <https://rcsoccersim.github.io/> | — |

### 高校课程与讲义（系统性最好）

| 资源 | 链接 | 适合 |
|------|------|------|
| **中科大中文教材《仿真机器人足球：设计与实现》** | <https://wrighteagle2d.github.io/materials/USTC_Material.pdf> | ★ **中文入门首推**（2D 方向，但多智能体部分通用） |
| Wits 大学 RoboCup 课程 | <https://courses.ms.wits.ac.za/~branden/RoboCup/> | 感知器/效应器的逐条讲解 |
| UT Austin cs344M 3D 讲义 | <https://www.cs.utexas.edu/~patmac/cs344m/assignments/3DNotes.html> | 3D 仿真的系统性说明 |
| RoboNewbie 教学框架讲义 | <https://www2.informatik.hu-berlin.de/~naoth/RoboNewbie/> | 面向新手的 3D 基座（SimSpark 时代） |
| 3D 仿真组访谈（讲现状与门槛） | <https://aihub.org/2025/07/15/tackling-the-3d-simulation-league-an-interview-with-klaus-dorer-and-stefan-glaser/> | 建立合理预期 |

> ⚠️ **关于社区博客（CSDN / 知乎等）**：
> 中文社区里有不少 RoboCup 教程，但**质量差异很大，
> 而且其中相当一部分是 AI 批量生成的内容**。
> 引用时请标注「社区博客，非官方」，并**优先相信官方文档**。
>
> ⚠️ **关于 B 站视频教程**：本仓库没有找到可确认质量的 3D 仿真中文视频教程，
> 所以**不做推荐** —— 与其推荐一个可能误导你的视频，不如说「没找到」。
