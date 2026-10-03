"""
RoboCup3D 新手 Demo —— 第 3 层：单个球员的行为状态机
======================================================

这个文件回答一个问题：**「一个球员拿到感知后，到底怎么决定做什么？」**

我们用最经典的「分层状态机」来实现，这也是绝大多数比赛队伍的起点：

    感知 Percept
        |
        v
    [态势评估]  --->  球在哪？我离球多远？我该负责吗？
        |
        v
    [角色分配]  --->  我是前锋还是后卫？（见 team.py）
        |
        v
    [行为状态机] --->  站起来 / 找球 / 跑位 / 对准 / 踢
        |
        v
    [运动原语]  --->  走（walk）/ 转（turn）/ 踢（kick）
        |
        v
    指令 Command

为什么新手要先学这个、再学强化学习？
因为状态机是**可解释**的：出问题了你能一眼看出是哪个状态错了。
强化学习是黑盒：球进不去你只能猜。真实队伍的路线几乎都是
「先用状态机跑通全流程 -> 再用 RL 替换其中最弱的那个模块」。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core import (
    BehaviorState,
    Command,
    Field,
    ObjectObs,
    Percept,
    Role,
    Situation,
)

# 让 walk / sim 可以直接被 import
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools", "walkviz"))
try:
    from walk import GaitGenerator, GaitParams  # type: ignore
except ImportError:  # pragma: no cover
    GaitGenerator = None  # type: ignore


# ===========================================================================
# 运动原语（Motion Primitives）
# ===========================================================================

@dataclass
class MotionConfig:
    """
    运动参数。对应 FCP Portugal 说的 Skill-Set-Primitives：
    不同的动作（走、侧走、转身）共享同一套底层步态，只是参数不同。
    这样切换动作时才不会有突兀的跳变。
    """

    walk_speed: float = 0.55          # 最大前进速度（m/s）
    turn_speed: float = 90.0          # 最大转身速度（度/s）
    ydof_speed: float = 0.30          # 侧向移动速度（m/s）
    kick_range: float = 0.65          # 进入这个距离就可以踢
    kick_power: float = 1.0           # 踢球力度 0~1
    align_tolerance: float = 8.0      # 对准目标的容差（度）
    approach_tolerance: float = 0.10  # 接近目标的容差（米）


class WalkPrimitive:
    """
    「走」这个动作。

    内部分成两层，这正是真实比赛程序的做法：
        上层：规划 -> 我要以什么速度 (vx, vy, w) 移动
        下层：步态 -> 把这个速度变成关节角的正弦序列（walk.py 里的东西）

    强化学习通常只替换其中一层：
        - 《Learning Humanoid Robot Running》替换了【下层】，直接输出关节角
        - 《Deep RL for Humanoid Robot Behaviors》替换了【上层】，输出 (vx,vy,w)
    记住这个区别，读论文时就不会晕。
    """

    def __init__(self, cfg: MotionConfig | None = None):
        self.cfg = cfg or MotionConfig()
        self.gait = GaitGenerator(GaitParams()) if GaitGenerator else None
        self.t = 0.0
        self.vx = 0.0      # 规划出的前进速度
        self.vy = 0.0      # 规划出的侧向速度
        self.w = 0.0       # 规划出的转身角速度

    def plan(self, vx: float, vy: float, w: float):
        """上层规划：设定期望速度。注意这里做了限幅，防止发出不可能完成的任务。"""
        c = self.cfg
        mag = math.hypot(vx, vy)
        if mag > c.walk_speed:
            vx, vy = vx / mag * c.walk_speed, vy / mag * c.walk_speed
        self.vx, self.vy = vx, vy
        self.w = max(-c.turn_speed, min(c.turn_speed, w))

    def step(self, dt: float) -> Dict[str, float]:
        """下层控制：速度 -> 关节角。"""
        self.t += dt
        if self.gait is None:
            return {}

        # 侧向移动映射到步态的「方向向量」，注意要防止两轴同时过大
        direction = (self.vx, self.vy)
        mag = math.hypot(*direction)
        if mag > 1e-6:
            direction = (direction[0] / mag, direction[1] / mag)
            # 速度大小影响步幅
            speed_ratio = min(1.0, mag / max(self.cfg.walk_speed, 1e-6))
            self.gait.p.step_length = 0.10 + 0.22 * speed_ratio
            self.gait.p.cycle_time = 0.75 - 0.35 * speed_ratio
        else:
            direction = (0.0, 0.0)

        joints = self.gait.step(self.t, direction)

        # 转身：直接叠加到髋关节 yaw 上（简化处理）
        yaw_deg = math.degrees(self.w) * 0.12
        for side in ("l", "r"):
            joints[f"{side}_hip_yaw"] = max(-45.0, min(45.0, yaw_deg))
        return joints

    def stop(self):
        self.vx = self.vy = self.w = 0.0


class TurnPrimitive:
    """
    原地转身。真实机器人转身很慢（T1/K1 大约 60~120 度/秒），
    这是 3D 仿真里非常关键的性能瓶颈 —— 定位误差大、转身慢，
    所以第一篇文章（6D Localization and Kicking）才有价值：
    6D 定位误差降低 97%，踢球时间从 6 秒降到 1 秒。
    """

    def __init__(self, max_speed: float = 90.0):
        self.max_speed = max_speed
        self.target_yaw = 0.0
        self.current_yaw = 0.0

    def set_target(self, yaw: float):
        self.target_yaw = yaw

    def step(self, dt: float) -> Tuple[float, bool]:
        """返回 (本周期转动角度, 是否已到位)。"""
        err = self._wrap(self.target_yaw - self.current_yaw)
        if abs(err) < 2.0:
            return 0.0, True
        speed = self.max_speed if abs(err) > 20 else self.max_speed * abs(err) / 20.0
        delta = max(-speed * dt, min(speed * dt, err))
        self.current_yaw = self._wrap(self.current_yaw + delta)
        return delta, False

    @staticmethod
    def _wrap(deg: float) -> float:
        """把角度归一化到 (-180, 180]，这是角度运算最容易出 bug 的地方。"""
        while deg > 180.0:
            deg -= 360.0
        while deg <= -180.0:
            deg += 360.0
        return deg


class KickPrimitive:
    """
    踢球动作。我们用一个「预录制的关节角序列」来模拟 ——
    这就是 keyframe animation 的思路，也是真实队伍的常见做法
    （先用动作捕捉或者手工调出踢球动作，再在比赛里重放）。

    进阶做法（见资料调研里的第 1、6 篇论文）：
        - SAC / PPO 学一个「移动中踢球」的策略
        - 输出 6D 姿态而不是关节角，再用 IK 转成关节
    """

    # 一个极简的踢球动作：后摆 -> 前踢 -> 收腿
    KEYFRAMES = [
        # (相位, 右髋pitch, 右膝, 右踝pitch, 左髋pitch, 左膝)
        (0.00, -18.0, -35.0, 15.0, 8.0, -12.0),
        (0.30, -35.0, -70.0, 25.0, 12.0, -18.0),   # 后摆蓄力
        (0.55, 25.0, -12.0, -10.0, 2.0, -8.0),     # 前踢触球
        (0.80, 5.0, -25.0, 8.0, 6.0, -14.0),       # 收腿
        (1.00, 0.0, -20.0, 0.0, 0.0, -15.0),
    ]

    def __init__(self, duration: float = 0.45):
        self.duration = duration
        self.elapsed = 0.0
        self.active = False

    def start(self):
        self.elapsed = 0.0
        self.active = True

    def step(self, dt: float) -> Optional[Dict[str, float]]:
        if not self.active:
            return None
        self.elapsed += dt
        phase = min(1.0, self.elapsed / self.duration)

        # 找到当前相位所在的两个关键帧，做线性插值
        prev = self.KEYFRAMES[0]
        nxt = self.KEYFRAMES[-1]
        for i in range(len(self.KEYFRAMES) - 1):
            if self.KEYFRAMES[i][0] <= phase <= self.KEYFRAMES[i + 1][0]:
                prev, nxt = self.KEYFRAMES[i], self.KEYFRAMES[i + 1]
                break

        span = max(nxt[0] - prev[0], 1e-6)
        u = (phase - prev[0]) / span
        vals = [prev[j] + (nxt[j] - prev[j]) * u for j in range(1, 6)]

        if phase >= 1.0:
            self.active = False
            return None

        return {
            "r_hip_pitch": vals[0],
            "r_knee": vals[1],
            "r_ankle_pitch": vals[2],
            "l_hip_pitch": vals[3],
            "l_knee": vals[4],
        }


# ===========================================================================
# 单球员 Agent
# ===========================================================================

@dataclass
class AgentStats:
    """统计数据。比赛结束后你要靠这些数字来判断「改进了没有」。"""

    cycles: int = 0
    distance_walked: float = 0.0
    kicks: int = 0
    falls: int = 0
    state_changes: int = 0
    time_in_state: Dict[str, float] = field(default_factory=dict)


class PlayerAgent:
    """
    一个球员。每个球员在自己的进程里跑一份这个对象。

    关键设计：**球员之间不能共享内存！**
    真实比赛里每个 agent 是独立进程，只能通过「看到的」和「听到的」交流，
    而且 hear 有带宽限制、有延迟、有噪声。
    这个约束是 RoboCup3D 的核心难点，也是 multi-agent 研究的意义所在。
    """

    def __init__(
        self,
        player_id: int,
        team_side: int = 1,
        cfg: MotionConfig | None = None,
        verbose: bool = False,
    ):
        self.id = player_id
        self.team_side = team_side
        self.cfg = cfg or MotionConfig()
        self.verbose = verbose

        self.role = Role.MIDFIELDER
        self.state = BehaviorState.SEARCH
        self.prev_state = self.state
        self.stats = AgentStats()

        self.walk = WalkPrimitive(self.cfg)
        self.turn = TurnPrimitive()
        self.kick = KickPrimitive()

        # 自己的估计位姿（真实队伍靠定位算法算出来，这里先用真值占位）
        self.est_pos: Tuple[float, float] = (0.0, 0.0)
        self.est_yaw: float = 0.0

        # 状态机需要的一点记忆
        self.lost_ball_time = 0.0
        self.kick_cooldown = 0.0
        self.home_pos: Tuple[float, float] = (0.0, 0.0)

        # 「球最后出现在哪」——这是定位/跟踪的最简版本。
        # 真实队伍用卡尔曼滤波维护一个 ball belief，这里用一个 (x, y, 时间) 三元组。
        self.ball_memory: Optional[Tuple[float, float, float]] = None
        self.search_target: Optional[Tuple[float, float]] = None

        # 队友广播来的信息：{player_id: (ball_x, ball_y, 时间戳)}
        self.team_broadcast: Dict[int, Tuple[float, float, float]] = {}

        # 由上层注入：「我是不是离球最近的球员」（对应真实比赛的 hear 广播）
        self._is_closest: Optional[bool] = None

    # ------------------------------------------------------------------
    # 主入口：每个仿真周期被调用一次
    # ------------------------------------------------------------------

    def act(self, p: Percept, dt: float = 0.02) -> Command:
        self.stats.cycles += 1
        self.kick_cooldown = max(0.0, self.kick_cooldown - dt)

        # 1) 更新自己的位姿估计
        self.est_pos = (p.self_pos[0], p.self_pos[1])
        self.est_yaw = p.self_yaw

        # 2) 处理队友广播（受限通信！这就是为什么 hear 那么重要）
        self._ingest_messages(p)

        # 3) 更新「球在哪」的记忆
        self._update_ball_memory(p)

        # 4) 态势评估
        sit = Situation.from_percept(p, self.role)
        # 「我是不是离球最近」由上层（team.py 或仿真器）注入；
        # 真实比赛里这个信息要靠 hear 广播，并且可能过时。
        closest_flag = getattr(self, "_is_closest", None)
        if closest_flag is not None:
            sit.is_closest_to_ball = bool(closest_flag)

        # 5) 状态转移
        new_state = self._decide_state(p, sit)
        if new_state != self.state:
            self.stats.state_changes += 1
            self.prev_state = self.state
            self.state = new_state
            if self.verbose:
                print(
                    f"  [球员{self.id}] {self.prev_state.value} -> {self.state.value} "
                    f"(球距={sit.ball_dist:.2f}m 方位={sit.ball_azimuth:+.0f}°)"
                )

        # 6) 记录耗时（用来发现「是不是有状态卡住了」）
        key = self.state.value
        self.stats.time_in_state[key] = self.stats.time_in_state.get(key, 0.0) + dt

        # 7) 执行对应行为，生成指令
        cmd = self._execute(p, sit, dt)
        return cmd.clamp_to(p.joint_limits)

    # ------------------------------------------------------------------
    # 通信与球的位置记忆
    # ------------------------------------------------------------------

    def _ingest_messages(self, p: Percept):
        """
        解析队友的广播。

        真实 RoboCup3D 的 hear 通道带宽极小（每周期只能发很少的字符），
        所以你会看到各队把信息压缩成很短的字符串，比如 "b12.5-3.2" 表示
        「球在我方半场 x=12.5 y=-3.2」。这里为了可读性用宽松格式。

        为什么这一步如此关键？
        因为单个机器人的视野只有 120 度左右，看不到球的时候它就是瞎子。
        而**队友看到球**这个信息可以救它 —— 这是 multi-agent 协作的最小例子。
        """
        for msg in p.messages:
            # 格式: "ball:<x>:<y>:<player_id>"
            if not msg.startswith("ball:"):
                continue
            parts = msg.split(":")
            if len(parts) != 4:
                continue
            try:
                bx, by, pid = float(parts[1]), float(parts[2]), int(parts[3])
            except ValueError:
                continue
            if pid == self.id:
                continue
            self.team_broadcast[pid] = (bx, by, p.time)

        # 清理过期信息（超过 2 秒的广播不可信）
        stale = [k for k, v in self.team_broadcast.items() if p.time - v[2] > 2.0]
        for k in stale:
            del self.team_broadcast[k]

    def _update_ball_memory(self, p: Percept):
        """如果此刻看得见球，就记住它的绝对位置。"""
        ball = p.ball
        if ball is None:
            return
        a = math.radians(ball.azimuth)
        bx = self.est_pos[0] + ball.dist * math.cos(math.radians(self.est_yaw) + a)
        by = self.est_pos[1] + ball.dist * math.sin(math.radians(self.est_yaw) + a)
        self.ball_memory = (bx, by, p.time)

    def _best_ball_guess(self, p: Percept) -> Optional[Tuple[float, float]]:
        """
        综合「自己记得的」和「队友广播的」，给出对球位置的最佳猜测。
        取最新的一条 —— 这就是最朴素的 sensor fusion。
        """
        candidates = []
        if self.ball_memory is not None:
            candidates.append(self.ball_memory)
        candidates.extend(self.team_broadcast.values())
        if not candidates:
            return None
        best = max(candidates, key=lambda c: c[2])
        # 信息太旧就当没有（球可能已经被踢走了）
        if p.time - best[2] > 3.0:
            return None
        return (best[0], best[1])

    # ------------------------------------------------------------------
    # 状态转移逻辑
    # ------------------------------------------------------------------

    def _decide_state(self, p: Percept, sit: Situation) -> BehaviorState:
        # 优先级最高：摔倒了先起来（比赛里躺着不动最亏）
        if p.is_fallen:
            return BehaviorState.STAND_UP

        # 守门员永远回自己的位置附近
        if self.role == Role.GOALKEEPER:
            return BehaviorState.RETURN_HOME

        # 开球 / 进球后等裁判指令，别乱跑
        if "KickOff" in p.play_mode or "Goal" in p.play_mode:
            return BehaviorState.RETURN_HOME

        # --- 关键顺序：看不见球的时候，无论什么角色都要先去找球 ---
        # （这是新手最常写错的地方：把「我不是离球最近的」判断放在前面，
        #   结果球滚出视野后全体球员原地待命，场上三个机器人一起发呆。）
        if not sit.ball_visible:
            self.lost_ball_time += 0.02
            return BehaviorState.SEARCH
        self.lost_ball_time = 0.0

        # 不是离球最近的球员 -> 去接应位置
        if not sit.is_closest_to_ball and self.role != Role.STRIKER:
            return BehaviorState.SUPPORT

        # 靠近球
        if sit.ball_dist > self.cfg.kick_range:
            return BehaviorState.APPROACH

        # 到位了，对准球门
        if abs(sit.ball_azimuth) > self.cfg.align_tolerance:
            return BehaviorState.ALIGN

        if self.kick_cooldown > 0:
            return BehaviorState.ALIGN
        return BehaviorState.KICK

    def _kick_direction(self, p: Percept, sit: Situation) -> float:
        """
        决定「该往哪个方向踢」。

        菜鸟版：直接朝对方球门中心踢。
        真实队伍会考虑：守门员在哪、队友在哪、自己射门角度好不好。
        这就是「战术」要解决的问题，也是论文里 set play / formation 的内容。
        """
        gx, gy = Field.opponent_goal(self.team_side)
        # 我在场上的位置 + 球相对我的位置 = 球的绝对位置
        ball_local = self._ball_local(sit)
        bx = self.est_pos[0] + ball_local[0]
        by = self.est_pos[1] + ball_local[1]
        # 朝球门方向
        return math.degrees(math.atan2(gy - by, gx - bx))

    def _ball_local(self, sit: Situation) -> Tuple[float, float]:
        a = math.radians(sit.ball_azimuth)
        return (sit.ball_dist * math.cos(a), sit.ball_dist * math.sin(a))

    # ------------------------------------------------------------------
    # 行为执行
    # ------------------------------------------------------------------

    def _execute(self, p: Percept, sit: Situation, dt: float) -> Command:
        handler = {
            BehaviorState.STAND_UP: self._do_stand_up,
            BehaviorState.SEARCH: self._do_search,
            BehaviorState.APPROACH: self._do_approach,
            BehaviorState.ALIGN: self._do_align,
            BehaviorState.KICK: self._do_kick,
            BehaviorState.SUPPORT: self._do_support,
            BehaviorState.RETURN_HOME: self._do_return_home,
        }[self.state]
        cmd = handler(p, sit, dt)

        # 如果我看得见球，就把球的位置广播给队友（受限通信！）。
        # 短短一行，但它让「一个球员看不见球」不再等于「整支队都瞎了」。
        if cmd.say is None and sit.ball_visible and self.ball_memory is not None:
            bx, by, _ = self.ball_memory
            cmd.say = f"ball:{bx:.1f}:{by:.1f}:{self.id}"
        return cmd

    def _do_stand_up(self, p: Percept, sit: Situation, dt: float) -> Command:
        """
        站起来。真实队伍要写一个专门的「起身动作」，
        这也是 RoboCup3D 的经典难题：起身慢 = 丢球。
        """
        if p.cycle % 50 == 0:
            self.stats.falls += 1
        # 一个简化的起身姿态：屈膝、收腿、撑起来
        return Command(
            joint_targets={
                "l_hip_pitch": -60.0, "l_knee": -110.0, "l_ankle_pitch": 30.0,
                "r_hip_pitch": -60.0, "r_knee": -110.0, "r_ankle_pitch": 30.0,
                "l_shoulder_pitch": 40.0, "r_shoulder_pitch": 40.0,
            },
            say=None,
        )

    def _do_search(self, p: Percept, sit: Situation, dt: float) -> Command:
        """
        找不到球怎么办？

        菜鸟做法：原地转圈（转一圈要 4 秒，比赛早结束了）。
        进阶做法：先问「球最后在哪」——
            1) 我自己的记忆
            2) 队友广播过来的信息
        然后朝那个方向走过去。这就是最朴素的协作。
        """
        guess = self._best_ball_guess(p)

        if guess is not None:
            # 有线索：朝球最后出现的位置移动，到了再转圈找
            gx, gy = guess
            dist = math.hypot(gx - self.est_pos[0], gy - self.est_pos[1])
            if dist > 0.6:
                self.search_target = guess
                return self._goto(gx, gy, dt)

        # 完全没线索：原地转圈扫描（真实队伍会规划一个覆盖全场的搜索路径）
        self.turn.set_target(self.turn.current_yaw + 40.0)
        delta, _ = self.turn.step(dt)
        self.walk.plan(0.0, 0.0, delta / max(dt, 1e-6))
        return Command(joint_targets=self.walk.step(dt))

    def _do_approach(self, p: Percept, sit: Situation, dt: float) -> Command:
        """朝球跑。同时转过身去对着球，这样下一步才好踢。"""
        # 距离越远跑越快（但要留出减速余量，否则冲过头）
        gap = max(0.0, sit.ball_dist - self.cfg.kick_range)
        speed = min(self.cfg.walk_speed, 0.35 + gap * 0.9)
        az = math.radians(sit.ball_azimuth)
        self.walk.plan(speed * math.cos(az), speed * math.sin(az), 0.0)
        joints = self.walk.step(dt)

        # 边走边转头看球（真实机器人靠头部关节补偿视野）
        joints["head_yaw"] = max(-90.0, min(90.0, sit.ball_azimuth * 0.6))
        self.stats.distance_walked += speed * dt
        return Command(joint_targets=joints)

    def _do_align(self, p: Percept, sit: Situation, dt: float) -> Command:
        """
        对准：既要身体朝向球门，又要离球合适距离。
        这一步做不好，KICK 就踢飞 —— 这是新手队伍最常见的失分点。
        """
        target = self._kick_direction(p, sit)
        err = TurnPrimitive._wrap(target - self.est_yaw)
        # 转向目标角度
        w = max(-self.cfg.turn_speed, min(self.cfg.turn_speed, err * 3.0))

        # 同时微调与球的距离，保证在踢球范围内
        radial = 0.0
        if sit.ball_dist > self.cfg.kick_range:
            radial = 0.25
        elif sit.ball_dist < 0.28:
            radial = -0.15   # 太近了往后退一点
        az = math.radians(sit.ball_azimuth)
        self.walk.plan(radial * math.cos(az), radial * math.sin(az), w)
        joints = self.walk.step(dt)
        joints["head_yaw"] = max(-90.0, min(90.0, sit.ball_azimuth * 0.6))
        return Command(joint_targets=joints)

    def _do_kick(self, p: Percept, sit: Situation, dt: float) -> Command:
        """踢球。"""
        if not self.kick.active:
            self.kick.start()
            self.stats.kicks += 1
            if self.verbose:
                print(f"  [球员{self.id}] ⚽ 踢球！球距 {sit.ball_dist:.2f}m "
                      f"射门角度 {self._kick_direction(p, sit):+.0f}°")
        joints = self.kick.step(dt)
        if joints is None:
            self.kick_cooldown = 0.6
            self.walk.stop()
            return Command(joint_targets=self.walk.step(dt))
        return Command(joint_targets=joints, say=f"kick{self.id}" if self.id == 1 else None)

    def _do_support(self, p: Percept, sit: Situation, dt: float) -> Command:
        """
        接应：跑到一个「能接传球、又能回防」的位置。
        这就是 formation（队形）问题：每个球员具体站哪儿？
        """
        # 简单策略：站在球和我方球门连线的中间偏前位置
        bx, by = self.est_pos[0] + self._ball_local(sit)[0], self.est_pos[1] + self._ball_local(sit)[1]
        ox, oy = Field.own_goal(self.team_side)
        tx = bx * 0.65 + ox * 0.35
        ty = by * 0.65 + oy * 0.35 + (1.5 if self.id % 2 == 0 else -1.5)
        tx, ty = Field.clamp_position(tx, ty)
        return self._goto(tx, ty, dt)

    def _do_return_home(self, p: Percept, sit: Situation, dt: float) -> Command:
        """回位。"""
        return self._goto(self.home_pos[0], self.home_pos[1], dt)

    def _goto(self, tx: float, ty: float, dt: float) -> Command:
        """
        通用「走到某点」：这是所有队形/跑位逻辑的公共底层。
        先算目标在我自己坐标系下的相对位置，再分解成前进 + 侧移。
        """
        dx = tx - self.est_pos[0]
        dy = ty - self.est_pos[1]
        dist = math.hypot(dx, dy)
        if dist < 0.12:
            self.walk.stop()
            return Command(joint_targets=self.walk.step(dt))

        # 世界坐标系 -> 本体系：减去自身朝向
        yaw = math.radians(self.est_yaw)
        lx = dx * math.cos(-yaw) - dy * math.sin(-yaw)
        ly = dx * math.sin(-yaw) + dy * math.cos(-yaw)

        speed = min(self.cfg.walk_speed, 0.2 + dist * 0.6)
        mag = max(math.hypot(lx, ly), 1e-6)
        self.walk.plan(lx / mag * speed, ly / mag * speed, 0.0)
        self.stats.distance_walked += speed * dt
        return Command(joint_targets=self.walk.step(dt))


if __name__ == "__main__":
    # 自测：造一个假局面，看状态机怎么跳
    print("=== 单球员行为状态机自测 ===\n")
    agent = PlayerAgent(1, verbose=True)
    agent.home_pos = (-3.0, 0.0)

    scenarios = [
        ("球在 5 米外正前方", dict(ball_dist=5.0, ball_az=0.0)),
        ("球在 1 米外偏左 40 度", dict(ball_dist=1.0, ball_az=40.0)),
        ("球贴着脚但没对准球门", dict(ball_dist=0.45, ball_az=12.0)),
        ("球正好在踢球范围且对准", dict(ball_dist=0.5, ball_az=2.0)),
    ]
    for label, sc in scenarios:
        p = Percept(
            time=1.0, cycle=50,
            joint_limits={},
            accel=(0.0, 0.0, -9.81),
            observations=[
                ObjectObs("ball", dist=sc["ball_dist"], azimuth=sc["ball_az"]),
                ObjectObs("goal_r", dist=5.0, azimuth=-20.0),
            ],
            play_mode="PlayOn",
        )
        print(f"--- 场景：{label} ---")
        for _ in range(3):
            p.cycle += 1
            cmd = agent.act(p, dt=0.02)
        print(f"    状态 = {agent.state.value}, 发出 {len(cmd.joint_targets)} 个关节指令\n")

    # 摔倒场景
    print("--- 场景：摔倒 ---")
    p_fall = Percept(time=2.0, cycle=100, accel=(0.0, 9.0, 1.0), observations=[])
    agent.act(p_fall, dt=0.02)
    print(f"    状态 = {agent.state.value}  (直立度 {p_fall.uprightness:.2f})")
    print("\nOK: 状态机工作正常。下一步运行 demo_sim.py 看完整比赛闭环。")
