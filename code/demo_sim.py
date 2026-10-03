"""
RoboCup3D 新手 Demo —— 第 4 层：一个极简的自研仿真器（Loopback World）
======================================================================

**为什么要有这个文件？**

真实的 rcssservermj（MuJoCo）装起来要下几百 MB 依赖、要编译、要配显卡。
零基础的同学第一次执行 `pip install` 就卡住了，然后就放弃了。

所以我们先自己写一个 **极其简化** 的仿真世界，它只做三件事：

    1. 维护球、球员的真值状态（位置、速度）
    2. 按 agent 发出的关节指令推进物理（非常粗略的运动学，不是真物理）
    3. 生成每个 agent 的「感知」（加噪声、加视野限制）

它能让你在 **零安装** 的情况下，完整跑通：
    感知 -> 决策 -> 动作 -> 世界变化 -> 新的感知
这个闭环。

**这个文件不是什么？**

它不是物理引擎，不能替代 MuJoCo。它不模拟关节扭矩、不模拟碰撞、不模拟接触力。
它的唯一目的是让算法层（agent / team / 角色分配 / 队形）能被调试。

**为什么这样设计是对的？**

真实比赛队伍也是这么分工的：
    - 仿真器（rcssservermj）负责物理，你改不了
    - 你的代码只负责「感知 -> 指令」
所以只要你写 agent 时严格遵守 Percept / Command 这两个接口，
以后把 transport.py 从 Loopback 换成真服务器，agent 代码 **一行都不用改**。
这就是工程上的「依赖倒置」。

运行：
    python demo_sim.py                 # 默认跑一场
    python demo_sim.py --cycles 1500   # 跑久一点
    python demo_sim.py --render        # 带 ASCII 动画
    python demo_sim.py --bench 20      # 跑 20 场做基准测试
"""

from __future__ import annotations

import argparse
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Windows 中文控制台兼容（很重要，新手必踩）
# ---------------------------------------------------------------------------
# 中文 Windows 的控制台默认编码是 GBK(cp936)。本文件里有大量中文输出，
# 一旦输出被重定向到文件或管道（比如 `python demo_sim.py > log.txt`
# 或者在别的脚本里调用），Python 会抛：
#     UnicodeEncodeError: 'gbk' codec can't encode character '\u26bd'
# 然后把整个程序搞崩。
# 显式把 stdout 设成 UTF-8 就能彻底避免这个问题。
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "..", "tools", "walkviz"))
sys.path.insert(0, os.path.join(_HERE, "agent"))
sys.path.insert(0, _HERE)

from core import Command, Field, ObjectObs, Percept, Role  # noqa: E402
from agent import MotionConfig, PlayerAgent  # noqa: E402

# ===========================================================================
# 世界状态
# ===========================================================================

CYCLE_DT = 0.02  # 3D 仿真标准是 50Hz，也就是 20ms 一个周期


@dataclass
class Ball:
    x: float = 0.0
    y: float = 0.0
    z: float = Field.BALL_RADIUS
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0

    def step(self, dt: float):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.z += self.vz * dt
        # 重力
        if self.z > Field.BALL_RADIUS:
            self.vz -= 9.81 * dt
        else:
            self.z = Field.BALL_RADIUS
            self.vz = 0.0
            # 地面摩擦：滚动阻力，球会慢慢停下来
            friction = 0.55
            self.vx -= self.vx * friction * dt
            self.vy -= self.vy * friction * dt
        # 边界：球撞墙反弹（真实球场有围栏）
        if abs(self.x) > Field.HALF_LENGTH:
            self.x = math.copysign(Field.HALF_LENGTH, self.x)
            self.vx *= -0.55
        if abs(self.y) > Field.HALF_WIDTH:
            self.y = math.copysign(Field.HALF_WIDTH, self.y)
            self.vy *= -0.55

    @property
    def speed(self) -> float:
        return math.hypot(self.vx, self.vy)


@dataclass
class Robot:
    """仿真世界里的一个机器人（真值，agent 看不到这个）。"""

    player_id: int
    team: str                  # 'own' / 'opp'
    side: int                  # +1 表示该队进攻 +x 方向
    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0
    fallen: bool = False
    fallen_timer: float = 0.0
    agent: Optional[PlayerAgent] = None
    last_cmd: Optional[Command] = None

    # 统计数据
    kicks: int = 0
    distance: float = 0.0


@dataclass
class MatchState:
    cycle: int = 0
    time: float = 0.0
    score_own: int = 0
    score_opp: int = 0
    play_mode: str = "PlayOn"
    events: List[str] = field(default_factory=list)


# ===========================================================================
# 仿真器
# ===========================================================================

class MiniSim:
    """
    极简仿真器。

    物理模型故意写得非常朴素：
        - 机器人不模拟关节动力学，而是把「关节指令」粗略地映射成移动意图
        - 走路的稳定性用一个概率模型代替（步子太大 -> 有概率摔倒）
        - 踢球用「脚到球的距离 + 朝向」判断

    这不是偷懒，而是教学上的必要取舍：
    因为一旦引入真实物理，你就无法区分「是算法错了」还是「是调参错了」。
    先用简单世界验证算法，再上真引擎 —— 这是所有机器人团队的开发顺序。
    """

    def __init__(
        self,
        players_per_team: int = 3,
        noise: float = 0.02,
        fov: float = 120.0,
        seed: int = 42,
        verbose: bool = False,
    ):
        self.rng = random.Random(seed)
        self.players_per_team = players_per_team
        self.noise = noise          # 视觉噪声标准差（米）
        self.fov = fov              # 视野角度（度）。真实机器人视野有限！
        self.verbose = verbose

        self.ball = Ball()
        self.state = MatchState()
        self.robots: List[Robot] = []
        self._pending_messages: Dict[int, List[str]] = {}
        self._build_teams()
        self._reset_positions()

    # ------------------------------------------------------------------

    def _build_teams(self):
        for team, side in (("own", 1), ("opp", -1)):
            for i in range(self.players_per_team):
                agent = None
                if team == "own":
                    agent = PlayerAgent(i, team_side=side, verbose=False)
                self.robots.append(Robot(player_id=i, team=team, side=side, agent=agent))

    def _reset_positions(self):
        """开球站位。真实比赛里这个位置由规则严格规定。"""
        own = [r for r in self.robots if r.team == "own"]
        opp = [r for r in self.robots if r.team == "opp"]

        # 己方：一个在球附近，其他在后方
        formations_own = [(-1.5, 0.0), (-3.5, 2.5), (-3.5, -2.5), (-5.0, 0.0)]
        formations_opp = [(1.5, 0.0), (3.5, 2.5), (3.5, -2.5), (5.0, 0.0)]

        for i, r in enumerate(own):
            fx, fy = formations_own[i % len(formations_own)]
            r.x, r.y = fx, fy
            r.yaw = 0.0
            if r.agent:
                r.agent.home_pos = (fx, fy)
                r.agent.est_pos = (fx, fy)
        for i, r in enumerate(opp):
            fx, fy = formations_opp[i % len(formations_opp)]
            r.x, r.y = fx, fy
            r.yaw = 180.0

        self.ball = Ball()
        self.state.play_mode = "KickOff_Left"

    # ------------------------------------------------------------------
    # 感知生成
    # ------------------------------------------------------------------

    def _observe(self, r: Robot, viewer: Robot) -> List[ObjectObs]:
        """
        生成 viewer 能看到的东西。

        关键：这里模拟了真实比赛的两个残酷约束：
          1. **视野限制** —— 只有前方 fov 度范围内的东西才看得见。
             这就是为什么定位/搜索算法那么重要。
          2. **观测噪声** —— 看到的距离和角度都有误差，
             所以必须靠滤波（卡尔曼滤波 / 粒子滤波）去估计真值。
        """
        obs: List[ObjectObs] = []
        dx = r.x - viewer.x
        dy = r.y - viewer.y
        dist = math.hypot(dx, dy)

        # 世界角度 -> viewer 的本体角度（-180..180）
        world_angle = math.degrees(math.atan2(dy, dx))
        rel = world_angle - viewer.yaw
        while rel > 180:
            rel -= 360
        while rel <= -180:
            rel += 360

        # 视野检查（球门和球比较「大」，更容易被看到，这里简化为同样规则）
        if abs(rel) > self.fov / 2:
            return []

        # 加噪声
        noise_d = self.rng.gauss(0, self.noise * max(1.0, dist))
        noise_a = self.rng.gauss(0, 1.5)
        return [
            ObjectObs(
                name=self._name_of(r),
                dist=max(0.01, dist + noise_d),
                azimuth=rel + noise_a,
                team="own" if r.team == viewer.team else "opp",
                player_id=r.player_id,
            )
        ]

    def _name_of(self, r: Robot) -> str:
        if r.team == "own":
            return f"player_{r.player_id}"
        return f"opp_{r.player_id}"

    def build_percept(self, robot: Robot) -> Percept:
        """把世界真值打包成这个球员「应该感知到」的东西。"""
        obs: List[ObjectObs] = []

        # --- 看球 ---
        bx, by = self.ball.x - robot.x, self.ball.y - robot.y
        bdist = math.hypot(bx, by)
        bang = math.degrees(math.atan2(by, bx)) - robot.yaw
        while bang > 180:
            bang -= 360
        while bang <= -180:
            bang += 360
        if abs(bang) <= self.fov / 2:
            obs.append(
                ObjectObs(
                    "ball",
                    dist=max(0.01, bdist + self.rng.gauss(0, self.noise * max(1.0, bdist))),
                    azimuth=bang + self.rng.gauss(0, 1.5),
                )
            )

        # --- 看球门（左右两根门柱）---
        for label, gx in (("goal_l", -Field.HALF_LENGTH), ("goal_r", Field.HALF_LENGTH)):
            for j, gy in enumerate((-Field.GOAL_HALF_WIDTH, Field.GOAL_HALF_WIDTH)):
                gx2, gy2 = gx - robot.x, gy - robot.y
                gdist = math.hypot(gx2, gy2)
                gang = math.degrees(math.atan2(gy2, gx2)) - robot.yaw
                while gang > 180:
                    gang -= 360
                while gang <= -180:
                    gang += 360
                if abs(gang) <= self.fov / 2:
                    obs.append(
                        ObjectObs(
                            f"{label}_{j}",
                            dist=max(0.01, gdist + self.rng.gauss(0, self.noise)),
                            azimuth=gang + self.rng.gauss(0, 1.0),
                        )
                    )
            # 也给一个「球门中心」的聚合观测，方便上层逻辑使用
            obs.append(
                ObjectObs(
                    label,
                    dist=max(0.01, math.hypot(gx - robot.x, -robot.y)
                             + self.rng.gauss(0, self.noise)),
                    azimuth=self._wrap(
                        math.degrees(math.atan2(-robot.y, gx - robot.x)) - robot.yaw
                    ),
                )
            )

        # --- 看其他球员 ---
        for other in self.robots:
            if other is robot:
                continue
            if math.hypot(other.x - robot.x, other.y - robot.y) > 14.0:
                continue
            obs.extend(self._observe(other, robot))

        # --- 本体感觉 ---
        # 略微加噪声，模拟真实传感器的不完美
        accel_z = -9.81 + self.rng.gauss(0, 0.15)
        if robot.fallen:
            accel_z = self.rng.gauss(0, 0.8)

        p = Percept(
            time=self.state.time,
            cycle=self.state.cycle,
            joint_angles={},
            joint_limits={},
            foot_pressure={"l": 1.0 if not robot.fallen else 0.0},
            gyro=(0.0, 0.0, 0.0),
            accel=(0.0, 0.0, accel_z),
            observations=obs,
            messages=self._pending_messages.pop(robot.player_id, []),
            self_pos=(robot.x, robot.y, 0.55),
            self_yaw=robot.yaw,
            play_mode=self.state.play_mode,
            score_own=self.state.score_own,
            score_opp=self.state.score_opp,
            team_side=robot.side,
        )

        # 简单的「谁离球最近」信息（真实比赛要靠 hear 广播，这里有噪声地模拟）
        return p

    @staticmethod
    def _wrap(deg: float) -> float:
        while deg > 180:
            deg -= 360
        while deg <= -180:
            deg += 360
        return deg

    # ------------------------------------------------------------------
    # 物理推进
    # ------------------------------------------------------------------

    def _apply_command(self, robot: Robot, cmd: Command, dt: float):
        """
        把「关节指令」翻译成「世界状态变化」。

        这是一个非常粗糙的代理模型（surrogate model）：
        我们不真的做正向动力学，而是从关节角里读出「意图」：
            髋关节 pitch 的平均值 -> 我想往前还是往后
            髋关节 roll 的左右差  -> 我想往哪边转
        """
        if robot.agent is None:
            # 对手只是一个占位（真实开发中你可能想接一个 baseline AI）
            return

        ag = robot.agent
        # 从 walk 原语里拿到「规划速度」——这是我们自己在 agent 里算出来的，
        # 直接用它比反解关节角稳定得多。
        vx, vy, w = ag.walk.vx, ag.walk.vy, ag.walk.w

        # 摔倒判定：步子太大 / 没有摆胯 -> 有概率摔
        p_cfg = ag.walk.gait.p if ag.walk.gait else None
        fall_risk = 0.0
        if p_cfg is not None:
            if p_cfg.step_length > 0.32:
                fall_risk += (p_cfg.step_length - 0.32) * 3.0
            if p_cfg.sway < 0.01:
                fall_risk += 0.05
            if p_cfg.cycle_time < 0.32:
                fall_risk += (0.32 - p_cfg.cycle_time) * 0.6
        if self.rng.random() < fall_risk * dt * 8:
            robot.fallen = True
            robot.fallen_timer = 1.5 + self.rng.random()
            self.state.events.append(f"t={self.state.time:.1f} 球员{robot.player_id} 摔倒")
            if robot.agent:
                robot.agent.stats.falls += 1

        if robot.fallen:
            robot.fallen_timer -= dt
            if robot.fallen_timer <= 0:
                robot.fallen = False
            vx = vy = w = 0.0

        # 积分位置
        yaw_rad = math.radians(robot.yaw)
        wx = vx * math.cos(yaw_rad) - vy * math.sin(yaw_rad)
        wy = vx * math.sin(yaw_rad) + vy * math.cos(yaw_rad)
        robot.x += wx * dt
        robot.y += wy * dt
        robot.yaw = self._wrap(robot.yaw + w * dt)
        robot.distance += math.hypot(wx, wy) * dt

        # 场地边界
        robot.x = max(-Field.HALF_LENGTH, min(Field.HALF_LENGTH, robot.x))
        robot.y = max(-Field.HALF_WIDTH, min(Field.HALF_WIDTH, robot.y))

        # --- 踢球判定 ---
        d = math.hypot(self.ball.x - robot.x, self.ball.y - robot.y)
        if d < 0.75 and not robot.fallen:
            # 判断球是不是在身体正前方（真实比赛里踢球必须朝向球，否则踢空）
            bang = self._wrap(
                math.degrees(math.atan2(self.ball.y - robot.y, self.ball.x - robot.x))
                - robot.yaw
            )
            if abs(bang) < 40.0 and ag.state.value == "kick":
                # 踢！
                power = ag.cfg.kick_power
                # 方向：朝对方球门（+ 一点随机误差，模拟踢不准）
                gx, gy = Field.opponent_goal(robot.side)
                aim = math.atan2(gy - self.ball.y, gx - self.ball.x)
                aim += self.rng.gauss(0, 0.10)   # 射门精度
                speed = 6.5 * power
                self.ball.vx = speed * math.cos(aim)
                self.ball.vy = speed * math.sin(aim)
                self.ball.vz = 1.2 * power
                robot.kicks += 1
                self.state.events.append(
                    f"t={self.state.time:.1f} 球员{robot.player_id} 射门 "
                    f"球速={speed:.1f}m/s"
                )

    def _check_goal(self):
        """进球判定。"""
        if abs(self.ball.x) < Field.HALF_LENGTH:
            return
        if abs(self.ball.y) > Field.GOAL_HALF_WIDTH:
            return
        if self.ball.z > Field.GOAL_HEIGHT:
            return
        if self.ball.x > 0:
            self.state.score_own += 1
            who = "我方"
        else:
            self.state.score_opp += 1
            who = "对方"
        self.state.events.append(
            f"t={self.state.time:.1f}  ⚽⚽⚽ {who}进球！ "
            f"比分 {self.state.score_own}:{self.state.score_opp}"
        )
        # 重置到开球
        self._reset_positions()
        self.state.play_mode = "KickOff_Left"

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    def step(self, dt: float = CYCLE_DT):
        self.state.cycle += 1
        self.state.time += dt

        # 0) 计算「谁离球最近」——真实比赛里这个信息要靠 hear 广播获得，
        #    而且有延迟。这里直接给所有人，属于作弊（cheating），
        #    但在教学 demo 里能让你专注在行为逻辑上。
        closest = self._closest_to_ball()

        # 1) 每个己方球员决策
        for robot in self.robots:
            if robot.agent is None:
                continue
            percept = self.build_percept(robot)
            # 打上「我是不是最近的」标记
            robot.agent._is_closest = (robot.player_id == closest)
            cmd = robot.agent.act(percept, dt)
            robot.last_cmd = cmd

        # 1.5) 收广播：把每个球员说的话发给队友。
        #      这是模拟真实比赛的受限通信通道 —— 球员之间不能直接共享内存！
        self._broadcast_messages()

        # 2) 应用指令、推进物理
        for robot in self.robots:
            if robot.last_cmd is not None:
                self._apply_command(robot, robot.last_cmd, dt)

        # 3) 球
        self.ball.step(dt)

        # 4) 裁判
        self._check_goal()

        # 开球模式持续 1 秒后进入 PlayOn
        if self.state.play_mode.startswith("KickOff") and self.state.cycle % 50 == 0:
            self.state.play_mode = "PlayOn"

    def _closest_to_ball(self) -> int:
        """返回离球最近的己方球员 id。"""
        own = [r for r in self.robots if r.team == "own" and not r.fallen]
        if not own:
            own = [r for r in self.robots if r.team == "own"]
        best = min(own, key=lambda r: math.hypot(self.ball.x - r.x, self.ball.y - r.y))
        return best.player_id

    def _broadcast_messages(self):
        """
        把每个球员「要说的话」投递给所有己方球员（下一周期生效）。

        真实 rcssservermj 的通信限制：
          - 每个周期只能发很短的字符串
          - 只发给你自己队
          - 有延迟和丢失
        这里保留了「发字符串」和「只发本队」两点，去掉了延迟。
        """
        for sender in self.robots:
            if sender.team != "own" or sender.last_cmd is None:
                continue
            msg = sender.last_cmd.say
            if not msg:
                continue
            for receiver in self.robots:
                if receiver.team != "own" or receiver.player_id == sender.player_id:
                    continue
                self._pending_messages.setdefault(receiver.player_id, []).append(msg)

    def run(self, cycles: int, render: bool = False, render_every: int = 10):
        t0 = time.time()
        for i in range(cycles):
            self.step()
            if render and i % render_every == 0:
                self.render_ascii()
                time.sleep(0.02)
        return time.time() - t0

    # ------------------------------------------------------------------
    # 可视化：ASCII 俯视图
    # ------------------------------------------------------------------

    def render_ascii(self, width: int = 74, height: int = 20) -> str:
        """
        在终端里画一张球场俯视图。

        这看起来很土，但是极其实用：
        当你 ssh 到服务器上跑训练时，没有图形界面，
        一个 ASCII 渲染器能让你立刻看出「机器人是不是在原地打转」。

        真实比赛用 RoboViz 做 3D 可视化，那是另一个层次的东西了。
        """
        grid = [[" "] * width for _ in range(height)]

        def to_cell(x: float, y: float) -> Tuple[int, int]:
            cx = int((x + Field.HALF_LENGTH) / Field.LENGTH * (width - 1))
            cy = int((Field.HALF_WIDTH - y) / Field.WIDTH * (height - 1))
            return max(0, min(width - 1, cx)), max(0, min(height - 1, cy))

        # 场地边框
        for i in range(width):
            grid[0][i] = "-"
            grid[height - 1][i] = "-"
        for j in range(height):
            grid[j][0] = "|"
            grid[j][width - 1] = "|"
        # 中线
        mid = width // 2
        for j in range(1, height - 1):
            grid[j][mid] = ":"
        # 球门
        g0 = int((Field.HALF_WIDTH - Field.GOAL_HALF_WIDTH) / Field.WIDTH * (height - 1))
        g1 = int((Field.HALF_WIDTH + Field.GOAL_HALF_WIDTH) / Field.WIDTH * (height - 1))
        for j in range(g0, g1 + 1):
            grid[j][0] = "G"
            grid[j][width - 1] = "G"

        # 球
        bx, by = to_cell(self.ball.x, self.ball.y)
        grid[by][bx] = "O"

        # 球员
        for r in self.robots:
            cx, cy = to_cell(r.x, r.y)
            if grid[cy][cx] in ("O",):
                continue
            if r.team == "own":
                grid[cy][cx] = str(r.player_id + 1) if not r.fallen else "x"
            else:
                grid[cy][cx] = "#"

        lines = ["".join(row) for row in grid]
        header = (
            f"  t={self.state.time:6.2f}s  cycle={self.state.cycle:5d}  "
            f"比分 {self.state.score_own}:{self.state.score_opp}  "
            f"球速 {self.ball.speed:4.1f}m/s"
        )
        legend = "  1/2/3=我方球员  x=摔倒  #=对方  O=球  G=球门  :=中线"
        out = "\n".join([header] + lines + [legend])
        print(out)
        return out


# ===========================================================================
# 命令行入口
# ===========================================================================

def run_single(cycles: int, render: bool, verbose: bool):
    print("=" * 78)
    print(" RoboCup3D 新手 Demo —— 闭环仿真（自研极简仿真器，零依赖）")
    print("=" * 78)
    print(" 说明：这不是 MuJoCo，只是用来跑通「感知->决策->动作」闭环的教学工具。")
    print("       真实仿真器请见 docs/03-技术入门.md 里的 rcssservermj。")
    print("=" * 78)

    sim = MiniSim(players_per_team=3, seed=7, verbose=verbose)
    print(f"\n 开始比赛：{cycles} 周期 = {cycles * CYCLE_DT:.1f} 秒仿真时间\n")

    elapsed = sim.run(cycles, render=render, render_every=25)

    print("\n" + "=" * 78)
    print(" 比赛结束 —— 统计报告")
    print("=" * 78)
    print(f" 最终比分          : {sim.state.score_own} : {sim.state.score_opp}")
    print(f" 仿真时间          : {sim.state.time:.1f} s ({sim.state.cycle} 周期)")
    print(f" 实际计算耗时      : {elapsed:.2f} s")
    if elapsed > 0:
        print(f" 实时倍率          : {sim.state.time / elapsed:.1f}x "
              f"(>1 表示比真实时间跑得快)")

    print("\n 各球员统计：")
    print(f" {'球员':<6}{'踢球次数':>10}{'行走距离(m)':>14}{'摔倒次数':>10}"
          f"{'状态切换':>10}")
    print(" " + "-" * 52)
    own = [r for r in sim.robots if r.team == "own"]
    for r in own:
        if r.agent:
            s = r.agent.stats
            print(f" {r.player_id:<6}{r.kicks:>10}{r.distance:>14.2f}"
                  f"{s.falls:>10}{s.state_changes:>10}")

    if sim.state.events:
        print(f"\n 关键事件（最多显示 15 条，共 {len(sim.state.events)} 条）：")
        for e in sim.state.events[:15]:
            print("   " + e)
        if len(sim.state.events) > 15:
            print(f"   ... 还有 {len(sim.state.events) - 15} 条")

    print("\n" + "=" * 78)
    print(" 下一步：")
    print("   python demo_sim.py --render    # 看 ASCII 动画")
    print("   python demo_sim.py --bench 20  # 跑 20 场做基准")
    print("   打开 tools/walkviz/index.html  # 看 3D 步态可视化")
    print("=" * 78)
    return sim


def run_bench(n: int, cycles: int):
    print(f"基准测试：跑 {n} 场，每场 {cycles} 周期...\n")
    print(f" {'场次':<6}{'比分':>10}{'我方射门':>12}{'对方射门':>12}"
          f"{'耗时(s)':>10}")
    print(" " + "-" * 52)
    totals = {"own": 0, "opp": 0, "shots": 0, "elapsed": 0.0}
    for i in range(n):
        sim = MiniSim(players_per_team=3, seed=100 + i)
        el = sim.run(cycles)
        shots = sum(r.kicks for r in sim.robots if r.team == "own")
        print(f" {i+1:<6}{sim.state.score_own:>4}:{sim.state.score_opp:<5}"
              f"{shots:>12}{sum(r.kicks for r in sim.robots if r.team=='opp'):>12}"
              f"{el:>10.2f}")
        totals["own"] += sim.state.score_own
        totals["opp"] += sim.state.score_opp
        totals["shots"] += shots
        totals["elapsed"] += el
    print(" " + "-" * 52)
    print(f" {'合计':<6}{totals['own']:>4}:{totals['opp']:<5}{totals['shots']:>12}"
          f"{'':>12}{totals['elapsed']:>10.2f}")
    print(f"\n 场均进球 {totals['own']/n:.2f} : {totals['opp']/n:.2f}，"
          f"场均射门 {totals['shots']/n:.1f} 次")
    print("\n 这个数字就是你的「基线（baseline）」。")
    print(" 以后你改了 agent 逻辑，就再跑一次 bench 看有没有变好 ——")
    print(" 这就是 RoboCup 开发的标准工作方式。")


def main():
    ap = argparse.ArgumentParser(description="RoboCup3D 新手闭环 Demo")
    ap.add_argument("--cycles", type=int, default=1000,
                    help="跑多少仿真周期（50 周期 = 1 秒）")
    ap.add_argument("--render", action="store_true", help="显示 ASCII 动画")
    ap.add_argument("--bench", type=int, default=0, help="跑 N 场做基准测试")
    ap.add_argument("--verbose", action="store_true", help="打印状态切换细节")
    args = ap.parse_args()

    if args.bench > 0:
        run_bench(args.bench, args.cycles if args.cycles != 1000 else 600)
    else:
        run_single(args.cycles, args.render, args.verbose)


if __name__ == "__main__":
    main()
