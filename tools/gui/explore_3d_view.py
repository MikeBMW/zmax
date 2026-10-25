"""把探索轨迹 JSON 生成自包含 3D HTML (Three.js r128) — 老倪 2026-10-25

老倪: 「放到你的三维视图我看看」

单文件, 数据内联, 双击/手机都能开。r128 是因为 three@0.157 已删 examples/js/OrbitControls.js
(踩过, 404 ⇒ 黑屏)。
"""
import argparse
import json
import os.path as osp

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Z-MAX 自主探索轨迹 · 光模块产线工位</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{background:#080a10;color:#c9d4e3;font:13px/1.5 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;overflow:hidden}
  #c{display:block;width:100vw;height:100vh}
  .panel{position:fixed;background:rgba(14,18,28,.90);border:1px solid #1e2836;border-radius:10px;padding:12px 14px;backdrop-filter:blur(8px)}
  #hud{top:14px;left:14px;min-width:236px}
  #hud h1{font-size:14px;color:#7dd3fc;font-weight:600;margin-bottom:8px;letter-spacing:.4px}
  #hud .row{display:flex;justify-content:space-between;padding:2px 0;font-size:12px}
  #hud .k{color:#64748b}
  #hud .v{color:#e2e8f0;font-variant-numeric:tabular-nums}
  #hud .v.hi{color:#4ade80;font-weight:600}
  #lg{bottom:14px;left:14px}
  #lg .it{display:flex;align-items:center;gap:7px;padding:2px 0;font-size:12px}
  #lg .dot{width:10px;height:10px;border-radius:2px;flex:none}
  #btns{bottom:14px;right:14px;display:flex;gap:8px}
  #btns button{background:#1a2432;color:#93c5fd;border:1px solid #2a3a4f;border-radius:7px;padding:7px 13px;font-size:12px;cursor:pointer;transition:.15s}
  #btns button:hover{background:#22303f;color:#bfdbfe}
  #btns button.on{background:#1e3a5f;color:#7dd3fc;border-color:#3b82f6}
  #tip{position:fixed;top:14px;right:14px;font-size:11px;color:#475569;text-align:right}
  #err{position:fixed;inset:0;display:none;align-items:center;justify-content:center;background:#080a10;color:#f87171;font-size:14px;padding:24px;text-align:center;white-space:pre-wrap}
</style>
</head>
<body>
<canvas id="c"></canvas>

<div class="panel" id="hud">
  <h1>🗺️ 自主探索轨迹</h1>
  <div class="row"><span class="k">场景</span><span class="v" id="v-scene">—</span></div>
  <div class="row"><span class="k">工作台</span><span class="v" id="v-size">—</span></div>
  <div class="row"><span class="k">栅格</span><span class="v" id="v-grid">—</span></div>
  <div class="row"><span class="k">覆盖率</span><span class="v hi" id="v-cov">—</span></div>
  <div class="row"><span class="k">探索轮次</span><span class="v" id="v-rounds">—</span></div>
  <div class="row"><span class="k">航点</span><span class="v" id="v-wp">—</span></div>
  <div class="row"><span class="k">路径长度</span><span class="v" id="v-path">—</span></div>
  <div class="row"><span class="k">算法</span><span class="v" style="font-size:11px;color:#94a3b8">frontier+信息增益+A*</span></div>
</div>

<div class="panel" id="lg">
  <div class="it"><span class="dot" style="background:#166534"></span>已探索 (free)</div>
  <div class="it"><span class="dot" style="background:#1e293b"></span>未探索 (unknown)</div>
  <div class="it"><span class="dot" style="background:#dc2626"></span>障碍 (夹具/围栏)</div>
  <div class="it"><span class="dot" style="background:#fbbf24;border-radius:50%"></span>探索航点</div>
  <div class="it"><span class="dot" style="background:#38bdf8"></span>行驶轨迹</div>
</div>

<div id="btns">
  <button id="b-path" class="on">轨迹</button>
  <button id="b-cone" class="on">视锥</button>
  <button id="b-rot">自动旋转</button>
  <button id="b-top">俯视</button>
</div>
<div id="tip">拖拽旋转 · 滚轮缩放<br>右键平移</div>
<div id="err"></div>

<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
const D = __DATA__;
const showErr = m => { const e=document.getElementById('err'); e.style.display='flex'; e.textContent='加载失败: '+m; };
try {
  if (typeof THREE === 'undefined') throw new Error('THREE 未加载 (检查网络/CDN)');

  const NX = D.nx, NY = D.ny, CELL = D.cell;
  const CX = NX*CELL/2, CY = NY*CELL/2;     // 让工作台居中
  const G = D.grid;                          // G[i][j]: 0=unknown 1=free 2=occ

  // ── 渲染器 ──
  const canvas = document.getElementById('c');
  const renderer = new THREE.WebGLRenderer({canvas, antialias:true});
  renderer.setPixelRatio(Math.min(devicePixelRatio||1, 2));
  renderer.setSize(innerWidth, innerHeight);
  renderer.shadowMap.enabled = true;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x080a10);
  scene.fog = new THREE.Fog(0x080a10, 1.0, 2.6);

  // 引擎 z-up → Three y-up: 栅格 (i,j) → 世界 (i*CELL-CX, 高度, j*CELL-CY)
  const P = (i,j,h=0) => new THREE.Vector3(i*CELL-CX, h, j*CELL-CY);

  const camera = new THREE.PerspectiveCamera(46, innerWidth/innerHeight, 0.01, 20);
  camera.position.set(0.62, 0.72, 0.78);

  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.07;
  controls.target.set(0, 0.04, 0);
  controls.minDistance = 0.25;
  controls.maxDistance = 2.4;
  controls.maxPolarAngle = Math.PI*0.495;   // 不许钻到地面下

  // ── 光 ──
  scene.add(new THREE.AmbientLight(0x8fa4c0, 0.72));
  const key = new THREE.DirectionalLight(0xffffff, 1.05);
  key.position.set(0.7, 1.2, 0.5);
  key.castShadow = true;
  key.shadow.mapSize.set(1024,1024);
  key.shadow.camera.left=-0.8; key.shadow.camera.right=0.8;
  key.shadow.camera.top=0.8;   key.shadow.camera.bottom=-0.8;
  scene.add(key);
  const rim = new THREE.DirectionalLight(0x38bdf8, 0.35);
  rim.position.set(-0.8, 0.5, -0.6);
  scene.add(rim);

  // ── 栅格地面 (逐格着色: 一眼看出探索到哪) ──
  const COL = {0:0x1e293b, 1:0x166534, 2:0xdc2626};
  const tileGeo = new THREE.PlaneGeometry(CELL*0.94, CELL*0.94);
  tileGeo.rotateX(-Math.PI/2);
  for (let i=0;i<NX;i++){
    for (let j=0;j<NY;j++){
      const st = G[i][j];
      const mat = new THREE.MeshLambertMaterial({
        color: COL[st],
        transparent: st===0,          // 未知区半透, 能看见底
        opacity: st===0 ? 0.42 : 1.0
      });
      const m = new THREE.Mesh(tileGeo, mat);
      const p = P(i+0.5, j+0.5, st===2 ? 0.012 : 0.001);
      m.position.copy(p);
      if (st===2){
        m.scale.y = 6;                // 障碍立起来一点, 立体感
        m.position.y = 0.038;
        m.geometry = new THREE.BoxGeometry(CELL*0.94, 0.072, CELL*0.94);
      }
      m.receiveShadow = true;
      scene.add(m);
    }
  }

  // 台面底
  const base = new THREE.Mesh(
    new THREE.PlaneGeometry(NX*CELL*1.06, NY*CELL*1.06),
    new THREE.MeshLambertMaterial({color:0x0c1219})
  );
  base.rotation.x = -Math.PI/2;
  base.position.y = -0.004;
  base.receiveShadow = true;
  scene.add(base);

  // ── 行驶轨迹 (按时间渐变: 深蓝→亮蓝) ──
  const pathPts = D.path.map(([i,j]) => P(i+0.5, j+0.5, 0.020));
  const pathGroup = new THREE.Group();
  const segs = pathPts.length - 1;
  for (let k=0;k<segs;k++){
    const t = k/Math.max(segs-1,1);
    const g = new THREE.BufferGeometry().setFromPoints([pathPts[k], pathPts[k+1]]);
    const c = new THREE.Color().setHSL(0.55 - 0.06*t, 0.85, 0.42 + 0.22*t);
    pathGroup.add(new THREE.Line(g, new THREE.LineBasicMaterial({color:c})));
  }
  scene.add(pathGroup);

  // ── 航点 ──
  const coneGroup = new THREE.Group();
  const wpGroup = new THREE.Group();
  D.waypoints.forEach((w, idx) => {
    const pos = P(w.i+0.5, w.j+0.5, 0.026);
    const isStart = idx===0;
    const sph = new THREE.Mesh(
      new THREE.SphereGeometry(isStart ? 0.014 : 0.011, 16, 12),
      new THREE.MeshLambertMaterial({
        color: isStart ? 0x22d3ee : 0xfbbf24,
        emissive: isStart ? 0x0e7490 : 0x92620a,
        emissiveIntensity: 0.5
      })
    );
    sph.position.copy(pos);
    sph.castShadow = true;
    wpGroup.add(sph);

    // 序号标牌
    const cv = document.createElement('canvas');
    cv.width = cv.height = 64;
    const cx = cv.getContext('2d');
    cx.fillStyle = isStart ? '#0891b2' : '#d97706';
    cx.beginPath(); cx.arc(32,32,30,0,7); cx.fill();
    cx.fillStyle = '#fff'; cx.font = 'bold 34px sans-serif';
    cx.textAlign = 'center'; cx.textBaseline = 'middle';
    cx.fillText(isStart ? 'S' : String(idx), 32, 35);
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({
      map: new THREE.CanvasTexture(cv), depthTest:false, transparent:true
    }));
    sp.position.copy(pos).add(new THREE.Vector3(0, 0.036, 0));
    sp.scale.set(0.030, 0.030, 1);
    wpGroup.add(sp);

    // 相机视锥 (展示每个航点朝哪看)
    const yaw = w.yaw_deg * Math.PI/180;
    const R = D.view_range, half = D.fov_deg*Math.PI/360;
    const apex = pos.clone();
    const p1 = pos.clone().add(new THREE.Vector3(Math.cos(yaw-half)*R, 0, Math.sin(yaw-half)*R));
    const p2 = pos.clone().add(new THREE.Vector3(Math.cos(yaw+half)*R, 0, Math.sin(yaw+half)*R));
    const cg = new THREE.BufferGeometry().setFromPoints([apex, p1, p2, apex]);
    const cone = new THREE.Line(cg, new THREE.LineBasicMaterial({
      color: 0x38bdf8, transparent:true, opacity:0.42
    }));
    coneGroup.add(cone);
    const fill = new THREE.Mesh(
      new THREE.BufferGeometry().setFromPoints([apex, p1, p2]),
      new THREE.MeshBasicMaterial({color:0x38bdf8, transparent:true, opacity:0.085,
                                   side:THREE.DoubleSide})
    );
    coneGroup.add(fill);
  });
  scene.add(wpGroup); scene.add(coneGroup);

  // ── 机械臂底座 (起点位置的示意柱) ──
  const w0 = D.waypoints[0];
  const ped = new THREE.Mesh(
    new THREE.CylinderGeometry(0.022, 0.030, 0.075, 24),
    new THREE.MeshLambertMaterial({color:0x334155})
  );
  ped.position.copy(P(w0.i+0.5, w0.j+0.5, 0.0375));
  ped.castShadow = true;
  scene.add(ped);

  // ── HUD ──
  const setT = (id,v) => document.getElementById(id).textContent = v;
  setT('v-scene', '光模块产线工位');
  setT('v-size', (NX*CELL).toFixed(2)+' × '+(NY*CELL).toFixed(2)+' m');
  setT('v-grid', NX+' × '+NY+' @ '+(CELL*100).toFixed(0)+'cm');
  setT('v-cov', (D.coverage_final*100).toFixed(1)+'%');
  setT('v-rounds', (D.waypoints.length-1)+' 轮');
  setT('v-wp', D.waypoints.length+' 个');
  setT('v-path', (D.path.length-1)+' 步');
  document.title = 'Z-MAX 自主探索 · 覆盖 '+(D.coverage_final*100).toFixed(1)+'%';

  // ── 按钮 ──
  let autoRot = false;
  document.getElementById('b-path').onclick = e => {
    pathGroup.visible = !pathGroup.visible;
    e.target.classList.toggle('on', pathGroup.visible);
  };
  document.getElementById('b-cone').onclick = e => {
    coneGroup.visible = !coneGroup.visible;
    e.target.classList.toggle('on', coneGroup.visible);
  };
  document.getElementById('b-rot').onclick = e => {
    autoRot = !autoRot;
    controls.autoRotate = autoRot;
    controls.autoRotateSpeed = 1.1;
    e.target.classList.toggle('on', autoRot);
  };
  document.getElementById('b-top').onclick = () => {
    const d = 0.95;
    camera.position.set(0, d, 0.001);
    controls.target.set(0, 0.02, 0);
    controls.update();
  };

  addEventListener('resize', () => {
    camera.aspect = innerWidth/innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
  });

  (function loop(){
    requestAnimationFrame(loop);
    controls.update();
    renderer.render(scene, camera);
  })();
  window.__READY__ = true;
} catch (e) {
  showErr(e.message || String(e));
  window.__ERR__ = String(e && e.message || e);
}
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="zmax_data/ss_live/explore_traj.json")
    ap.add_argument("--out", default="zmax_data/ss_live/explore_3d.html")
    a = ap.parse_args()
    d = json.load(open(a.json, encoding="utf-8"))
    html = HTML.replace("__DATA__", json.dumps(d, ensure_ascii=False))
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html)
    print("→ %s (%.1f KB)" % (a.out, osp.getsize(a.out) / 1024.0))


if __name__ == "__main__":
    main()
