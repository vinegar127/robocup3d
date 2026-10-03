"""
RoboCup3D 新手 Demo —— 第 2 层：Agent 的核心数据结构
=====================================================

一个 agent（智能体）在比赛里干的全部事情，可以浓缩成一句话：

    服务器发给我「我感知到了什么」  -->  我回给服务器「关节该怎么动」

所以只要定义清楚这一进一出两个数据结构，剩下的全是业务逻辑。

    Percept  （感知）: 服务器 -> 我     看得见什么？球在哪？队友在哪？我摔了吗？
    Command  （指令）: 我 -> 服务器     每个关节转多少度？要不要说话？

这个约定和真实的 rcssservermj / SimSpark 完全一致，只是真实协议的字段
更多、还有 UDP 打包解包。等你把这套逻辑跑通，再换成真协议，
需要改的只有 transport.py 一个文件。

坐标约定（右-handed，和 MuJoCo 一致）
-------------------------------------
    x : 前方（对方球门在 +x 方向）
    y : 左方
    z : 上
    角度单位：度。yaw 为绕 z 轴旋转，逆时针为正。

球场尺寸（RoboCup 3D 仿真标准，2026 规则可能有微调，以官方规则为准）
    长度 18 m（x 从 -9 到 +9）
    宽度 12 m（y 从 -6 到 +6）
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ===========================================================================
# 球场常量
# ===========================================================================

class Field:
    """球场几何常量。改这里就能适配不同尺寸的场地。"""

    LENGTH = 18.0          # 全场长度（米）
    WIDTH = 12.0           # 全场宽度（米）
    HALF_LENGTH = 9.0      # 半场长度
    HALF_WIDTH = 6.0       # 半场宽度
    GOAL_HALF_WIDTH = 1.5  # 球门半宽（球门宽 3 米）
    GOAL_HEIGHT = 1.2      # 球门高
    CIRCLE_RADIUS = 2.0    # 中圈半径
    LINE_WIDTH = 0.05      # 白线宽度
    BALL_RADIUS = 0.07     # 球半径（约 7 厘米）

    @classmethod
    def clamp_position(cls, x: float, y: float) -> Tuple[float, float]:
        """把坐标限制在场地（含少量缓冲）内。"""
        m = 0.5
        return (
            max(-cls.HALF_LENGTH - m, min(cls.HALF_LENGTH + m, x)),
            max(-cls.HALF_WIDTH - m, min(cls.HALF_WIDTH + m, y)),
        )

    @classmethod
    def opponent_goal(cls, own_side: int) -> Tuple[float, float]:
        """对方球门中心。own_side=+1 表示我方在 -x 半场，进攻 +x 方向。"""
        return (cls.HALF_LENGTH * own_side, 0.0)

    @classmethod
    def own_goal(cls, own_side: int) -> Tuple[float, float]:
        return (-cls.HALF_LENGTH * own_side, 0.0)


# ===========================================================================
# 感知数据
# ===========================================================================

@dataclass
class ObjectObs:
    """
    一次观测到的物体。

    在真实仿真里，agent 看不到全局真值（除了调试模式），
    只能看到「以自己为中心的相对坐标」，而且带噪声、有视野限制。
    这里刻意保留「相对坐标 + 噪声」的形式，就是为了提醒你：
    定位（localization）才是 3D 仿真最难的部分之一。
    """

    name: str                      # 'ball' / 'goal_l' / 'goal_r' / 'player_3' ...
    dist: float                    # 距离（米）
    azimuth: float                 # 水平角（度），0 = 正前方，逆时针为正
    elevation: float = 0.0         # 垂直角（度）
    team: Optional[str] = None     # 'own' / 'opp' / None
    player_id: Optional[int] = None

    def to_local_xy(self) -> Tuple[float, float]:
        """把极坐标观测转成机器人本体坐标系下的 (x, y)。"""
        a = math.radians(self.azimuth)
        return (self.dist * math.cos(a), self.dist * math.sin(a))


@dataclass
class Percept:
    """
    仿真服务器在一个周期内发给 agent 的全部信息。

    对应真实协议里的各种 perceptors：
        HJ   (Hinge Joint)     —— 每个关节的当前角度
        HJI  (Hinge Joint Info)—— 每个关节的范围/速度
        FRP  (Force Resistive) —— 脚底压力传感器（判断脚是否着地）
        Gyro / Accelerometer   —— IMU，判断身体姿态
        See                    —— 视觉，看到球/球门/队友/对手
        Hear                   —— 听到的语音（受限通信！）
    """

    time: float                                    # 仿真时间（秒）
    cycle: int                                     # 已经过了多少个周期

    # --- 本体感觉（proprioception）---
    joint_angles: Dict[str, float] = field(default_factory=dict)      # HJ
    joint_limits: Dict[str, Tuple[float, float]] = field(default_factory=dict)  # HJI
    foot_pressure: Dict[str, float] = field(default_factory=dict)     # FRP，>0 表示着地
    gyro: Tuple[float, float, float] = (0.0, 0.0, 0.0)                # 角速度 (deg/s)
    accel: Tuple[float, float, float] = (0.0, 0.0, 0.0)               # 加速度 (m/s^2)

    # --- 视觉 ---
    observations: List[ObjectObs] = field(default_factory=list)

    # --- 通信 ---
    messages: List[str] = field(default_factory=list)

    # --- 自身状态 ---
    self_pos: Tuple[float, float, float] = (0.0, 0.0, 0.0)   # 真值位置（仅调试用！）
    self_yaw: float = 0.0                                    # 朝向（度）

    # --- 比赛状态 ---
    play_mode: str = "PlayOn"     # PlayOn / KickOff_Left / Goal_Left / ...
    score_own: int = 0
    score_opp: int = 0
    team_side: int = 1            # +1 = 我方在 -x 半场

    # ---------------- 便捷查询 ----------------

    def find(self, name: str) -> Optional[ObjectObs]:
        """按名字找最近的一个观测。"""
        best = None
        for o in self.observations:
            if o.name == name and (best is None or o.dist < best.dist):
                best = o
        return best

    def find_prefix(self, prefix: str) -> List[ObjectObs]:
        return [o for o in self.observations if o.name.startswith(prefix)]

    @property
    def ball(self) -> Optional[ObjectObs]:
        return self.find("ball")

    @property
    def is_fallen(self) -> bool:
        """
        判断是否摔倒。真实比赛用的是躯干高度 + 姿态角。
        这里用加速度计的 z 分量做粗略判断：
        站直时重力方向加速度约 -9.81，躺下时接近 0。
        """
        return abs(self.accel[2]) < 5.0 and self.time > 0.5

    @property
    def uprightness(self) -> float:
        """
        「站得有多直」，0（躺着）~ 1（笔直）。
        真实队伍会把这个量写进奖励函数（reward），惩罚摔倒。
        """
        return min(1.0, abs(self.accel[2]) / 9.81)


# ===========================================================================
# 控制指令
# ===========================================================================

@dataclass
class Command:
    """
    agent 回给服务器的指令。

    这是整个比赛里 agent 唯一能「施加影响」的出口。
    你所有的智能，最后都必须变成这一串数字。
    """

    joint_targets: Dict[str, float] = field(default_factory=dict)  # 目标关节角（度）
    say: Optional[str] = None          # 要说的话（有带宽限制！）
    reset: bool = False                # 摔倒后请求站起来

    def clamp_to(self, limits: Dict[str, Tuple[float, float]]) -> "Command":
        """把指令裁剪到关节允许范围内 —— 防止把非法值发给服务器被判罚。"""
        for k, v in list(self.joint_targets.items()):
            if k in limits:
                lo, hi = limits[k]
                self.joint_targets[k] = max(lo, min(hi, v))
        return self


# ===========================================================================
# 角色与状态机
# ===========================================================================

class Role(str, Enum):
    """
    球员角色。动态角色分配（Dynamic Role Assignment）是 RoboCup 的经典问题：
    固定「1号前锋 2号后卫」太僵硬 —— 万一球滚到守门员脚边呢？
    所以真实队伍会每周期重新计算「谁离球最近谁上」。
    """

    GOALKEEPER = "goalkeeper"
    DEFENDER = "defender"
    MIDFIELDER = "midfielder"
    STRIKER = "striker"


class BehaviorState(str, Enum):
    """单个球员的行为状态机。状态机是所有比赛队伍的基本骨架。"""

    STAND_UP = "stand_up"      # 摔倒了，先站起来
    SEARCH = "search"          # 找不到球，转头找
    APPROACH = "approach"      # 朝球跑过去
    ALIGN = "align"            # 到位了，调整身体朝向球门
    KICK = "kick"              # 踢！
    SUPPORT = "support"        # 不是我的球，去接应位置
    RETURN_HOME = "return_home"  # 回防


@dataclass
class Situation:
    """
    把一堆原始感知，提炼成「我现在该干什么」的高层判断。
    这个「感知 -> 态势 -> 行为」的分层，
    就是 FCP Portugal 那篇技术报告里 Skill-Set-Primitives 思想的简化版。
    """

    ball_dist: float = 999.0
    ball_azimuth: float = 0.0
    ball_visible: bool = False
    goal_dist: float = 999.0
    goal_azimuth: float = 0.0
    goal_visible: bool = False
    opponent_goal_angle: float = 0.0   # 从球的位置看，对方球门在哪个方向
    is_closest_to_ball: bool = True
    ball_to_goal_dist: float = 999.0
    in_shooting_range: bool = False

    @classmethod
    def from_percept(cls, p: Percept, role: Role) -> "Situation":
        s = cls()
        ball = p.ball
        if ball is not None:
            s.ball_visible = True
            s.ball_dist = ball.dist
            s.ball_azimuth = ball.azimuth

        # 对方球门：按自己的半场方向判断哪个 goal 是「对方」的
        goal_name = "goal_r" if p.team_side > 0 else "goal_l"
        goal = p.find(goal_name)
        if goal is not None:
            s.goal_visible = True
            s.goal_dist = goal.dist
            s.goal_azimuth = goal.azimuth

        # 判断是否在射门范围内：球近 + 朝向球门
        if s.ball_visible:
            s.in_shooting_range = s.ball_dist < 0.75 and abs(s.ball_azimuth) < 35.0
        return s


if __name__ == "__main__":
    # 自测：构造一个假的感知，看看一切都工作
    p = Percept(
        time=1.0,
        cycle=50,
        joint_angles={"l_knee": -30.0},
        accel=(0.0, 0.0, -9.8),
        observations=[
            ObjectObs("ball", dist=2.0, azimuth=15.0),
            ObjectObs("goal_r", dist=6.0, azimuth=-40.0),
        ],
        play_mode="PlayOn",
    )
    print("球可见:", p.ball is not None, "距离:", p.ball.dist)
    print("摔倒？", p.is_fallen, " 直立度:", round(p.uprightness, 2))
    sit = Situation.from_percept(p, Role.STRIKER)
    print("态势:", sit)
    print("\nOK: 数据结构工作正常。下一步运行 demo_sim.py 看完整闭环。")
