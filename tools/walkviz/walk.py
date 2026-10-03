"""
RoboCup3D 新手 Demo —— 第 1 层：行走引擎与运动学
=================================================

这个文件是整个 demo 的“物理世界”，故意写得非常小、非常土，
目的是让完全零基础的同学也能一行一行读懂：

    关节角度  --(正运动学)-->  脚/身体的位置
    关节角度序列 --(步态生成器)--> 机器人“走路”

它不依赖 numpy、不依赖 mujoco、不依赖任何东西，只用标准库 math。

读懂这个文件，你就理解了 RoboCup3D 里“机器人怎么动”这件事的本质：
    服务器（仿真器）每 1/50 秒问你的 agent 一次：
        “这条腿的髋关节、膝关节、踝关节各转多少度？”
    你的 agent 必须回答一串角度。走路 = 一串随时间变化的角度。

坐标约定（和 MuJoCo / rcssservermj 一致）
------------------------------------------
    x : 机器人正前方
    y : 机器人左手边
    z : 向上的高度
    原点是机器人躯干（torso）中心

    关节角单位：全部用“度”，正负号遵循右手定则。
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from typing import List, Sequence

# Windows 中文控制台默认是 GBK，输出被重定向时会因中文报
# UnicodeEncodeError。显式转成 UTF-8 一劳永逸。
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 第 0 节：把“机器人”写成数据
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JointLimit:
    """一个关节能转动的范围（度）。超出范围会被仿真器判为非法指令。"""

    name: str
    lo: float
    hi: float

    def clamp(self, value: float) -> float:
        return max(self.lo, min(self.hi, value))


@dataclass(frozen=True)
class Segment:
    """
    一段刚体（大腿 / 小腿 / 脚掌），用来做“正运动学”的几何计算。

    offset : 从父关节原点，到本条肢体末端（也就是下一个关节）的向量，
             单位是米。这里已经包含了“肢体长度”的含义。
    """

    name: str
    offset: tuple


@dataclass
class LegKinematics:
    """
    一条腿的 2D 平面运动学模型（矢状面：x 向前、z 向上）。

    真实的人形机器人一条腿有 6 个自由度（髋 3 + 膝 1 + 踝 2）。
    为了让你第一次就能看懂，这里只保留 3 个关键自由度：

        hip_pitch  : 大腿绕 y 轴摆动（抬腿 / 后蹬）  —— 正 = 向前摆
        knee       : 小腿相对大腿弯曲               —— 正 = 向后弯（人腿就是膝盖向后）
        ankle      : 脚掌相对小腿转动               —— 正 = 脚尖上勾（背屈）

    这 3 个角度决定了脚掌在空间中的位置，也就是走路的核心。
    """

    thigh: float = 0.30  # 大腿长度 30cm
    shank: float = 0.30  # 小腿长度 30cm
    foot: float = 0.10  # 脚掌长度 10cm

    def forward(self, hip_pitch: float, knee: float, ankle: float):
        """
        正运动学：给定 3 个关节角，算出「脚踝」和「脚尖」在躯干坐标系下的位置。

        思路就是把三根棍子首尾相接，每一根的角度都是前面所有角度的累加。
        （这叫做“旋转矩阵连乘”，但这里在 2D 平面里只需要用 sin/cos 加减。）
        """
        hip = math.radians(hip_pitch)
        kne = math.radians(knee)
        ank = math.radians(ankle)

        # 大腿末端 = 膝关节位置
        knee_x = self.thigh * math.sin(hip)
        knee_z = -self.thigh * math.cos(hip)

        # 小腿的绝对角度 = 大腿角度 + 膝关节相对角
        shank_angle = hip + kne
        ankle_x = knee_x + self.shank * math.sin(shank_angle)
        ankle_z = knee_z - self.shank * math.cos(shank_angle)

        # 脚掌的绝对角度 = 小腿角度 + 踝关节相对角
        foot_angle = shank_angle + ank
        toe_x = ankle_x + self.foot * math.sin(foot_angle)
        toe_z = ankle_z - self.foot * math.cos(foot_angle)

        return {
            "knee": (knee_x, knee_z),
            "ankle": (ankle_x, ankle_z),
            "toe": (toe_x, toe_z),
        }

    def inverse(self, target_x: float, target_z: float):
        """
        逆运动学（IK）：反过来——我希望脚踝落在 (x, z)，那关节角该是多少？

        这正是 FCP Portugal 那篇技术报告里强调的思想：
        “不要让神经网络直接输出关节角，让它输出脚掌位置，再用 IK 换成角度。”
        因为脚掌位置天然满足物理约束，而关节角不满足。

        2 连杆 IK 就是一个余弦定理，属于高中知识。
        """
        # 髋关节到目标点的距离
        dist = math.hypot(target_x, target_z)
        max_reach = self.thigh + self.shank - 1e-6
        if dist > max_reach:
            # 够不着！等比缩放到极限位置，防止 math.acos 报 domain error
            scale = max_reach / dist
            target_x, target_z, dist = target_x * scale, target_z * scale, max_reach
        dist = max(dist, 1e-6)

        # 余弦定理求膝关节内角
        cos_knee_inner = (self.thigh**2 + self.shank**2 - dist**2) / (
            2 * self.thigh * self.shank
        )
        cos_knee_inner = max(-1.0, min(1.0, cos_knee_inner))
        knee_inner = math.acos(cos_knee_inner)
        knee = -(math.pi - knee_inner)  # 转成“相对角”，膝盖向后弯

        # 大腿相对「髋->目标点」连线的偏角
        cos_alpha = (self.thigh**2 + dist**2 - self.shank**2) / (2 * self.thigh * dist)
        cos_alpha = max(-1.0, min(1.0, cos_alpha))
        alpha = math.acos(cos_alpha)

        # atan2(x, -z)：因为 z 向下为负，角度从竖直向下方向量起
        hip = math.atan2(target_x, -target_z) + alpha
        return math.degrees(hip), math.degrees(knee)


# ---------------------------------------------------------------------------
# 第 1 节：关节定义（模仿 K1 / T1 人形的命名）
# ---------------------------------------------------------------------------


def default_joints() -> dict:
    """返回一份「关节名 -> 角度范围」的表。名字参考 Booster K1 人形机器人。"""
    spec = [
        # 头部
        ("head_yaw", -90, 90),
        ("head_pitch", -45, 45),
        # 左腿
        ("l_hip_pitch", -100, 100),
        ("l_hip_roll", -45, 45),
        ("l_hip_yaw", -45, 45),
        ("l_knee", -130, 5),
        ("l_ankle_pitch", -40, 40),
        ("l_ankle_roll", -30, 30),
        # 右腿
        ("r_hip_pitch", -100, 100),
        ("r_hip_roll", -45, 45),
        ("r_hip_yaw", -45, 45),
        ("r_knee", -130, 5),
        ("r_ankle_pitch", -40, 40),
        ("r_ankle_roll", -30, 30),
        # 左臂
        ("l_shoulder_pitch", -170, 170),
        ("l_shoulder_roll", -10, 170),
        ("l_elbow", -120, 10),
        # 右臂
        ("r_shoulder_pitch", -170, 170),
        ("r_shoulder_roll", -170, 10),
        ("r_elbow", -120, 10),
    ]
    return {name: JointLimit(name, lo, hi) for name, lo, hi in spec}


# ---------------------------------------------------------------------------
# 第 2 节：步态生成器 —— 让机器人“走起来”
# ---------------------------------------------------------------------------


@dataclass
class GaitParams:
    """
    步态参数。这就是你在 RoboCup3D 里真正要「调」的东西。

    把行走想象成：两条腿各自画一个椭圆，相位差 180 度。
    参数少 = 好调；参数多 = 走得好看但难调。
    真实比赛队伍通常用强化学习（PPO / SAC）自动学出这些参数。
    """

    step_length: float = 0.20  # 步幅（米）：脚往前迈多远
    step_height: float = 0.06  # 抬脚高度（米）：抬太低会绊倒，抬太高浪费能量
    cycle_time: float = 0.60  # 一个完整步态周期（秒）：左右各迈一步
    body_height: float = 0.55  # 躯干高度（米）：越低越稳，但腿弯得更厉害
    sway: float = 0.03  # 左右摇摆幅度（米）：把重心移到支撑脚上，防摔倒
    lean: float = 2.0  # 前倾角度（度）：像人起跑时那样身体前倾


class GaitGenerator:
    """
    最朴素的「正弦步态」生成器。

    它不聪明，但它是所有行走引擎的祖宗。理解它，你就理解了：
      - 为什么走路是周期性的
      - 为什么必须左右摇摆（ZMP / 零力矩点 的直觉）
      - 行走引擎的输出到底是什么

    使用方式：
        g = GaitGenerator(GaitParams())
        for t in range(250):          # 5 秒 @ 50Hz
            joints = g.step(t / 50.0)
    """

    def __init__(self, params: GaitParams | None = None, kine: LegKinematics | None = None):
        self.p = params or GaitParams()
        self.kine = kine or LegKinematics()
        self.limits = default_joints()
        self._phase = 0.0
        self._distance = 0.0  # 累计前进距离（米），用来算“走了多远”

    # -- 单个支撑相 / 摆动相 -------------------------------------------------

    def _foot_trajectory(self, phase: float):
        """
        给定一条腿的相位（0~1），返回这只脚的 (x, y, z) 目标位置。

        相位含义（以左腿为例）：
            0.00 ~ 0.50 : 摆动相（swing）—— 脚离地，从后往前迈
            0.50 ~ 1.00 : 支撑相（stance）—— 脚踩地，身体从后往前压过去
        """
        p = phase % 1.0
        # 前半个周期抬脚前迈，后半个周期贴地向后蹬
        # sin(2*pi*p) 在 p=0.25 处取 +1（最前），p=0.75 处取 -1（最后）
        x = 0.5 * self.p.step_length * math.sin(2 * math.pi * p)

        if p < 0.5:
            # 摆动相：画一个半圆抬脚，用 sin(pi * p*2) 保证起落时高度为 0
            lift = math.sin(math.pi * (p / 0.5))
            z = self.p.step_height * lift
        else:
            # 支撑相：脚牢牢贴地
            z = 0.0

        # 左右方向：摆动时略微外撇，避免两只脚互相踢到
        y = self.p.sway * math.sin(2 * math.pi * p)
        return x, y, z

    # -- 主接口 --------------------------------------------------------------

    def step(self, t: float, direction: tuple = (1.0, 0.0)) -> dict:
        """
        生成 t 时刻所有关节的角度。

        参数
        ----
        t         : 当前时间（秒）
        direction : 行走方向 (dx, dy)，会被归一化。比如
                    (1, 0) 往前走，(0, 1) 往左横移，(-1, 0) 后退。

        返回
        ----
        {关节名: 角度(度)}   —— 可以直接发给仿真器
        """
        dx, dy = direction
        norm = math.hypot(dx, dy)
        if norm < 1e-9:
            dx, dy = 0.0, 0.0
        else:
            dx, dy = dx / norm, dy / norm

        # 整体相位：0 -> 1 循环
        self._phase = (t / self.p.cycle_time) % 1.0

        # 左右腿相位相差半个周期，这是“走路”的定义
        phase_l = self._phase
        phase_r = (self._phase + 0.5) % 1.0

        joints: dict = {}

        for side, ph in (("l", phase_l), ("r", phase_r)):
            fx, _, fz = self._foot_trajectory(ph)

            # 方向映射：前进/后退影响 x，横移影响髋部左右摆
            foot_x = fx * dx
            foot_z = -(self.p.body_height) + fz  # 脚相对躯干的位置，z 向下为负

            # 用逆运动学把「脚的位置」换算成「关节角」
            hip, knee = self.kine.inverse(foot_x, foot_z)
            # 加一个前倾，让重心落在支撑脚前面，走起来更像人
            hip += self.p.lean

            # 横移时靠髋关节左右摆动实现（简化模型）
            hip_roll = dy * 8.0

            joints[f"{side}_hip_pitch"] = self.limits[f"{side}_hip_pitch"].clamp(hip)
            joints[f"{side}_knee"] = self.limits[f"{side}_knee"].clamp(knee)
            joints[f"{side}_hip_roll"] = self.limits[f"{side}_hip_roll"].clamp(hip_roll)
            joints[f"{side}_hip_yaw"] = 0.0

            # 踝关节：让脚掌尽量与地面平行。支撑相时脚要放平，
            # 摆动相时可以稍微勾脚尖，防止绊到地面。
            ankle_target = -(hip + knee)
            if ph >= 0.5:
                ankle_target += 3.0
            joints[f"{side}_ankle_pitch"] = self.limits[f"{side}_ankle_pitch"].clamp(
                ankle_target
            )
            joints[f"{side}_ankle_roll"] = 0.0

        # 躯干左右摇摆：把重心移到当前支撑脚的那一侧。
        # 这就是为什么人走路会左右晃 —— 不晃就会摔倒。
        sway_sign = math.sin(2 * math.pi * self._phase)
        for side in ("l", "r"):
            sign = 1.0 if side == "l" else -1.0
            base = joints[f"{side}_hip_roll"]
            joints[f"{side}_hip_roll"] = self.limits[f"{side}_hip_roll"].clamp(
                base + sign * sway_sign * math.degrees(self.p.sway / 0.3)
            )

        # 手臂反向摆动，抵消腿部角动量（人类走路就是这样）
        swing = 25.0 * math.sin(2 * math.pi * self._phase)
        joints["l_shoulder_pitch"] = -swing
        joints["r_shoulder_pitch"] = swing
        joints["l_elbow"] = -20.0
        joints["r_elbow"] = -20.0
        joints["head_pitch"] = 0.0
        joints["head_yaw"] = 0.0

        # 理想前进速度 = 步幅 / 周期。真实机器人会打滑，所以要乘一个折扣。
        self._distance += (self.p.step_length / self.p.cycle_time) * dx * (1.0 / 50.0) * 0.85

        return joints

    @property
    def distance(self) -> float:
        """已经“走”了多远（米）。理想值，未考虑打滑。"""
        return self._distance

    def reset(self):
        self._phase = 0.0
        self._distance = 0.0


def stance_report(joints: dict) -> dict:
    """
    一个简易的「稳定性体检」：判断当前是不是要摔了。

    真正的比赛队伍会算 ZMP（零力矩点）或者用 IMU 反馈，
    这里只用两个极其朴素的指标，让你有个直观感受：

      support_feet : 有几只脚是接近地面的（0 / 1 / 2）
      com_x        : 重心在前后方向的粗略位置
    """
    l_ankle_z = None
    r_ankle_z = None
    kine = LegKinematics()
    for side in ("l", "r"):
        hip = joints.get(f"{side}_hip_pitch", 0.0)
        knee = joints.get(f"{side}_knee", 0.0)
        pts = kine.forward(hip, knee, 0.0)
        if side == "l":
            l_ankle_z = pts["ankle"][1]
        else:
            r_ankle_z = pts["ankle"][1]

    ground = min(l_ankle_z, r_ankle_z)
    supported = sum(1 for z in (l_ankle_z, r_ankle_z) if z - ground < 0.02)
    return {"support_feet": supported, "lowest_ankle_z": round(ground, 4)}


if __name__ == "__main__":
    # 最简单的自测：走 5 秒，每 0.5 秒打印一次状态
    g = GaitGenerator()
    print(f"{'t(s)':>6} {'左脚x':>9} {'左膝':>8} {'右膝':>8} {'支撑脚':>7} {'已走(m)':>9}")
    print("-" * 56)
    for i in range(250):
        t = i / 50.0
        joints = g.step(t)
        if i % 25 == 0:
            kine = LegKinematics()
            foot = kine.forward(
                joints["l_hip_pitch"], joints["l_knee"], joints["l_ankle_pitch"]
            )
            rep = stance_report(joints)
            print(
                f"{t:6.2f} {foot['ankle'][0]:9.3f} {joints['l_knee']:8.1f} "
                f"{joints['r_knee']:8.1f} {rep['support_feet']:7d} {g.distance:9.3f}"
            )
    print("\nOK: 步态生成器工作正常。下一步请运行 demo.py 看 3D 可视化。")
