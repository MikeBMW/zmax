"""SE(3) 安全策略(影子): 模型只提议相位推进, 目标点由"录制轨迹按 s 插值"给出, 闸门管真实下发量。

口径(这版是修过的, 旧版有几处概念错):
  ① 位置/姿态 = 录制轨迹在 s_tgt 处的插值(线性 + slerp), 不是把模型坐标当结果
  ② 闸门检查的是**真正要下发的量**: 单拍位移 dp、swing(摆开工具轴)、twist(绕工具轴滚转)
     —— 不是拿模型预测的旋转向量的"轴"去和 k 轴比(那是旧版的错)
  ③ 偏轨用**横向距离**(到轨迹折线的垂距)比管半径, 不是"到下一个参考点的距离"
     —— 后者天然等于一个步长(30+mm), 会把 96% 的正常步判成越界(旧版实测 blocked 172/214)
  ④ 无真值/真值陈旧 ⇒ 直接拒(红线)
"""
import argparse, json, math, sys
import numpy as np
import torch

REPO = "/home/ubuntu/zmax"
TRAJ = REPO + "/tools/web/real_traj_joints.json"
PHASE = REPO + "/zmax_data/rokae_sdk/traj_phase.json"
CKPT = REPO + "/zmax_data/rokae_sdk/se3_predictor.pt"
POSE = REPO + "/zmax_data/rokae_sdk/tcp_out/latest.json"
OUT = REPO + "/zmax_data/rokae_sdk/se3_policy_shadow.json"

DT_TICK = 0.10          # 控制节拍
V_MAX = 100.0           # mm/s(flow 最高档); 操作区由 zone 表降速
V_ZONE = {"near_stop": 60.0}
DP_MAX_MM = V_MAX * DT_TICK * 1.5   # 15mm/拍 —— 与速度上限同源, 不是拍脑袋常数
SWING_MAX_DEG = 10.0
TWIST_MAX_DEG = 12.0
DS_MAX = 0.02           # 相位增量上限(≈157mm)
AGE_MAX_S = 1.0
R_TUBE_MM = 20.0


def qmul(a, b):
    w1, x1, y1, z1 = a; w2, x2, y2, z2 = b
    return np.array([w1*w2-x1*x2-y1*y2-z1*z2, w1*x2+x1*w2+y1*z2-z1*y2,
                     w1*y2-x1*z2+y1*w2+z1*x2, w1*z2+x1*y2-y1*x2+z1*w2])


def qnorm(q):
    q = np.asarray(q, float); m = np.linalg.norm(q) or 1.0
    return q / m


def qlog_rel(qa, qb):
    qa, qb = qnorm(qa), qnorm(qb)
    qd = qmul(np.array([qa[0], -qa[1], -qa[2], -qa[3]]), qb)
    if qd[0] < 0:
        qd = -qd
    v = qd[1:]; s = float(np.linalg.norm(v))
    if s < 1e-12:
        return np.zeros(3)
    return v / s * math.degrees(2.0 * math.atan2(s, qd[0]))


def qexp(r_deg):
    r = np.asarray(r_deg, float); a = float(np.linalg.norm(r))
    if a < 1e-12:
        return np.array([1.0, 0.0, 0.0, 0.0])
    ax = r / a; h = math.radians(a) / 2.0
    return np.concatenate([[math.cos(h)], ax * math.sin(h)])


def hopf(q):
    w, x, y, z = qnorm(q)
    n = np.array([2*(x*z+w*y), 2*(y*z-w*x), w*w+z*z-x*x-y*y])
    return n / (np.linalg.norm(n) or 1.0), (2.0 * math.atan2(z, w)) % (2.0 * math.pi)


def fr_q(f):
    return qnorm(np.array([f["q"][3], f["q"][0], f["q"][1], f["q"][2]], float))


def fr_p(f):
    return np.asarray(f["p"], float) * 1000.0


def load_all():
    fr = json.load(open(TRAJ, encoding="utf-8"))["frames"]
    ph = json.load(open(PHASE, encoding="utf-8"))["frames"]
    ck = torch.load(CKPT, map_location="cpu", weights_only=False)
    sys.path.insert(0, REPO + "/tools")
    from importlib import import_module
    m = import_module("train_se3_predictor")
    net = m.Net(ck["d_in"]); net.load_state_dict(ck["state"]); net.eval()
    return fr, ph, net, ck


def featurize(f, s, prev_r):
    q = fr_q(f); p = fr_p(f)
    j = np.degrees(np.asarray(f["j"], float))[:6]
    return np.concatenate([j / 180.0, p / 1000.0, q,
                           [math.sin(2*math.pi*s), math.cos(2*math.pi*s)], [s], prev_r / 10.0])


def interp_at(fr, ph, s_tgt):
    """按弧长相位插值(位置线性 + 姿态 slerp)。取整帧会带来 ~27mm 量化误差。"""
    n = len(fr); ss = [r["s"] for r in ph]
    j = 0
    for k in range(n - 1):
        if ss[k] <= s_tgt <= ss[k + 1]:
            j = k; break
    else:
        j = n - 2 if s_tgt >= ss[-1] else 0
    span = max(ss[j + 1] - ss[j], 1e-9)
    frac = min(1.0, max(0.0, (s_tgt - ss[j]) / span))
    p = fr_p(fr[j]) + (fr_p(fr[j + 1]) - fr_p(fr[j])) * frac
    q0, q1 = fr_q(fr[j]), fr_q(fr[j + 1])
    if float(np.dot(q0, q1)) < 0:
        q1 = -q1
    th = math.acos(min(1.0, abs(float(np.dot(q0, q1)))))
    q = qnorm(q0 + (q1 - q0) * frac) if th < 1e-6 else qnorm(
        (math.sin((1 - frac) * th) * q0 + math.sin(frac * th) * q1) / math.sin(th))
    return j, frac, p, q


def lateral_mm(fr, p_now, j, half=4):
    """到轨迹折线的垂距(横向偏差)。对比管半径看的应该是这个, 而不是到下一个点的距离。"""
    n = len(fr)
    best = 1e9
    for k in range(max(0, j - half), min(n - 1, j + half)):
        a, b = fr_p(fr[k]), fr_p(fr[k + 1])
        ab = b - a; L2 = float(np.dot(ab, ab))
        t = 0.0 if L2 < 1e-9 else max(0.0, min(1.0, float(np.dot(p_now - a, ab)) / L2))
        best = min(best, float(np.linalg.norm(p_now - (a + ab * t))))
    return best


def tube_radius(fr, i):
    n = len(fr)
    a, b, c = fr_p(fr[max(0, i - 1)]), fr_p(fr[i]), fr_p(fr[min(n - 1, i + 1)])
    ab, bc = b - a, c - b
    area = 0.5 * float(np.linalg.norm(np.cross(ab, bc)))
    la = float(np.linalg.norm(b - a)); lb = float(np.linalg.norm(c - b)); lc = float(np.linalg.norm(a - c))
    if area < 1e-9 or la * lb * lc < 1e-9:
        return R_TUBE_MM
    kappa = 4.0 * area / (la * lb * lc)          # 曲率 κ = 1/R
    return float(min(R_TUBE_MM, 1.0 / (2.0 * max(kappa, 1e-6))))


def propose(fr, ph, net, ck, i, prev_r):
    xin = (featurize(fr[i], ph[i]["s"], prev_r) - ck["mu"]) / ck["sd"]
    with torch.no_grad():
        pr = net(torch.from_numpy(xin.astype(np.float32)[None, :])).numpy()[0]
    return pr[:3], float(pr[3] / 1000.0)


def safe_target(fr, ph, net, ck, i, prev_r, pose_now=None, q_now=None, age_s=0.0, ds_force=None, s_now=None):
    r_pred, ds_pred = propose(fr, ph, net, ck, i, prev_r)
    if ds_force is not None:
        ds_pred = float(ds_force)
    gate = {"ds_model": round(float(ds_pred), 5), "r_model_deg": round(float(np.linalg.norm(r_pred)), 3),
            "age_s": round(float(age_s), 3), "ds_max": DS_MAX, "dp_max_mm": DP_MAX_MM,
            "swing_max": SWING_MAX_DEG, "twist_max": TWIST_MAX_DEG}
    if pose_now is not None and age_s > AGE_MAX_S:
        return {"ok": False, "why": "真值帧龄 %.2fs > %.1fs —— 无真值不出位姿" % (age_s, AGE_MAX_S), "gate": gate}
    # ① 相位推进(环绕 + 限幅)
    if abs(ds_pred) > DS_MAX:
        gate["clip_ds"] = "%.4f → %.4f" % (ds_pred, math.copysign(DS_MAX, ds_pred))
        ds_pred = math.copysign(DS_MAX, ds_pred)
    s_now = float(ph[i]["s"] if s_now is None else s_now)
    s_tgt = (s_now + ds_pred) % 1.0
    j, frac, p_ref, q_ref = interp_at(fr, ph, s_tgt)
    gate.update({"s_now": round(s_now, 5), "s_tgt": round(s_tgt, 5), "j_ref": j, "frac": round(frac, 3)})
    # ② 闸门: 只看真正要下发的量
    if pose_now is not None:
        dp = float(np.linalg.norm(np.asarray(p_ref) - np.asarray(pose_now, float)))
        gate["dp_mm"] = round(dp, 2)
        r_t = tube_radius(fr, j)
        lat = lateral_mm(fr, np.asarray(pose_now, float), j)
        gate["lateral_mm"], gate["r_tube_mm"] = round(lat, 2), round(r_t, 1)
        if lat > r_t:
            return {"ok": False, "why": "横向偏轨 %.1fmm > 管半径 %.1fmm —— 先重锚, 不许硬拉" % (lat, r_t), "gate": gate}
        if dp > DP_MAX_MM:
            return {"ok": False, "why": "单拍位移 %.1fmm > %.0fmm —— 跳变, 不许下发" % (dp, DP_MAX_MM), "gate": gate}
        if q_now is not None:
            dr = qlog_rel(q_now, q_ref)
            n_tool, _ = hopf(q_now)
            tw = n_tool * float(np.dot(dr, n_tool))
            sw = dr - tw
            gate["twist_deg"], gate["swing_deg"] = round(float(np.linalg.norm(tw)), 2), round(float(np.linalg.norm(sw)), 2)
            if abs(gate["twist_deg"]) > TWIST_MAX_DEG or gate["swing_deg"] > SWING_MAX_DEG:
                return {"ok": False, "why": "姿态单拍超闸(swing %.1f°/%.0f 或 twist %.1f°/%.0f)"
                        % (gate["swing_deg"], SWING_MAX_DEG, gate["twist_deg"], TWIST_MAX_DEG), "gate": gate}
    cmd = {"src": "se3_safe_policy", "i_ref": j, "s": round(s_tgt, 6),
           "x": round(float(p_ref[0]), 2), "y": round(float(p_ref[1]), 2), "z": round(float(p_ref[2]), 2),
           "qx": round(float(q_ref[1]), 6), "qy": round(float(q_ref[2]), 6),
           "qz": round(float(q_ref[3]), 6), "qw": round(float(q_ref[0]), 6)}
    return {"ok": True, "cmd": cmd, "gate": gate, "why": "模型提议 + 闸门 + 参考收口通过"}


def plan_tick(fr, ph, net, ck, s, prev_r, v_cap, ds_max_tick):
    """一拍规划: 姿态/位移超闸 ⇒ 就地折半降速重算(最多 4 次), 折到 20% 以下才判"真跳变"拒绝。

    这样输出的是**速度剖面**(把 31° 的断层自动走成慢速), 而不是"检测到就停"。
    """
    j, frac, p_true, q_true = interp_at(fr, ph, s)
    ds = ds_max_tick
    last = None
    for _ in range(4):
        out = safe_target(fr, ph, net, ck, j, prev_r, pose_now=p_true, q_now=q_true,
                          age_s=0.0, ds_force=ds, s_now=s)
        last = out
        if out["ok"]:
            return out, ds, j, p_true, q_true
        if "姿态单拍超闸" in out["why"] or "单拍位移" in out["why"]:
            ds *= 0.5
            continue
        return out, 0.0, j, p_true, q_true      # 偏轨/无真值等不可靠降速解决
    if ds < 0.2 * ds_max_tick:
        return {"ok": False, "why": "折速到 20%% 仍超闸 —— 视为跳变: " + last["why"], "gate": last["gate"]}, 0.0, j, p_true, q_true
    return last, ds, j, p_true, q_true


def shadow(use_model_ds=True):
    """按控制节拍(DT_TICK)沿弧长推进的仿真回放。

    🔴 口径关键: 录制帧是**采样**(单步 33~157mm), 不是控制步。拿"下一帧"当一步去做闸门,
    必然把正常快段判成跳变(旧版 blocked 101/214 全是这个假象)。控制步应由速度上限×节拍给出。
    """
    fr, ph, net, ck = load_all()
    L = 7861.8
    rows, prev_r, perr, aerr, blocked = [], np.zeros(3), [], [], 0
    s, t_acc = 0.0, 0.0
    stops_idx = [9, 125, 151, 172, 205]
    while s < 0.9995 and len(rows) < 8000:
        j, frac, p_true, q_true = interp_at(fr, ph, s)
        v_cap = V_ZONE["near_stop"] if min(abs(j - k) for k in stops_idx) <= 3 else V_MAX
        ds_kin = v_cap * DT_TICK / L                       # 运动学步长(参考模式用)
        if use_model_ds:                                   # 模型给"每帧增量" ⇒ 换算成速率(帧节拍 0.2s)再乘控制节拍
            r_pred, ds_frame = propose(fr, ph, net, ck, j, prev_r)
            ds_des = min(max(0.0, ds_frame / 0.2 * DT_TICK), ds_kin)
        else:
            ds_des = ds_kin
        out, ds_des, j, p_true, q_true = plan_tick(fr, ph, net, ck, s, prev_r, v_cap, ds_des)
        if not out["ok"]:
            blocked += 1; rows.append({"s": round(s, 5), "ok": False, "why": out["why"], "gate": out["gate"]})
            s = min(0.9995, s + ds_kin); t_acc += DT_TICK
            continue
        if ds_des <= 0:                                    # 到停留点: 原地驻留(夹爪/AOI 动作时间)
            t_acc += DT_TICK * 3
            s = min(0.9995, s + ds_kin * 0.05)
            rows.append({"s": round(s, 5), "ok": True, "ds": 0.0, "hold": True, "gate": out["gate"]})
            continue
        c = out["cmd"]
        p_cmd = np.array([c["x"], c["y"], c["z"]], float)
        q_cmd = np.array([c["qw"], c["qx"], c["qy"], c["qz"]], float)
        s_cmd = (s + ds_des) % 1.0
        _, _, p_truth, q_truth = interp_at(fr, ph, s_cmd)  # 指令点应当落在录制轨迹上 ⇒ 跟踪误差
        perr.append(float(np.linalg.norm(p_cmd - p_truth)))
        aerr.append(float(np.linalg.norm(qlog_rel(q_cmd, q_truth))))
        prev_r = qlog_rel(q_true, q_truth)
        rows.append({"s": round(s, 5), "ok": True, "ds": round(ds_des, 6), "gate": out["gate"]})
        s = s_cmd
        t_acc += DT_TICK
    st = lambda v: {"median": round(float(np.median(v)), 4), "p95": round(float(np.percentile(v, 95)), 4),
                    "max": round(float(max(v)), 4)} if v else {}
    why = {}
    for r in rows:
        if not r["ok"]:
            k = r["why"].split("——")[0][:22]; why[k] = why.get(k, 0) + 1
    ds_series = [r["ds"] for r in rows if r.get("ok")]
    rep = {"mode": ("模型相位(速率换算)" if use_model_ds else "参考相位"),
           "ticks": len(rows), "blocked": blocked, "passed": len(rows) - blocked, "blocked_reasons": why,
           "sim_time_s": round(t_acc, 1), "final_s": round(s, 5),
           "ds_tick_per_mm": {"median": round(float(np.median(ds_series)) * 7861.8, 3),
                              "max": round(float(max(ds_series)) * 7861.8, 3)} if ds_series else {},
           "pos_err_mm_to_next_frame": st(perr), "rot_err_deg_to_next_frame": st(aerr),
           "gates": {"dp_max_mm": DP_MAX_MM, "swing_max": SWING_MAX_DEG, "twist_max": TWIST_MAX_DEG,
                     "ds_max": DS_MAX, "tube_mm": R_TUBE_MM, "age_max_s": AGE_MAX_S}}
    json.dump({"report": rep, "rows": rows}, open(OUT, "w"), ensure_ascii=False)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


def once():
    fr, ph, net, ck = load_all()
    tcp = json.load(open(POSE, encoding="utf-8"))
    age = float(__import__("time").time() - float(tcp.get("ts") or 0))
    q_now = qnorm(np.array([tcp["qw"], tcp["qx"], tcp["qy"], tcp["qz"]], float))
    out = safe_target(fr, ph, net, ck, ph[-1]["i"], np.zeros(3),
                      pose_now=[tcp["x"]*1000, tcp["y"]*1000, tcp["z"]*1000], q_now=q_now, age_s=age)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--shadow", action="store_true")
    ap.add_argument("--shadow-ref", action="store_true")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    sys.exit(shadow(True) if a.shadow else (shadow(False) if a.shadow_ref else (once() if a.once else 0)))
