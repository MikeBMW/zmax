'use strict';
/*
 * Z-MAX 550B 工位 —— VSCode 版 (标定 / 测量 / 诊断 / 配置)
 *
 * 设计红线 (与主工程一致):
 *  1. 本扩展只是"又一个前端": 只做 取真源 + 展示 + 触发, 不复制任何业务逻辑。
 *  2. 真源唯一: 本机 8793 的只读接口 (/station/status 等) + 仓库里的配置真源文件。
 *  3. 写操作 (授权/点位/切档) 一律走后端闸门 (默认未授权, 两步确认, 5 分钟窗口),
 *     扩展不新开旁路、不静默写。
 *  4. 任何标"当前"的数值都带帧龄/时间戳 (age_s / log_age_s), 不隐藏新鲜度。
 *  5. 只对 550B (调试档, vscode_debug=true) 生效 —— 档位读取自 config/platform/zmax_product.json。
 */
const vscode = require('vscode');
const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');

let out = null;
function log(msg) {
    if (!out) out = vscode.window.createOutputChannel('Z-MAX 550B');
    out.appendLine(`[${new Date().toLocaleTimeString()}] ${msg}`);
}
module.exports = { activate, deactivate };

/* ------------------------------------------------------------------ 配置 / 路径 */
function cfg() { return vscode.workspace.getConfiguration('zmax550b'); }
function baseUrl() { return String(cfg().get('baseUrl') || 'http://127.0.0.1:8793').replace(/\/+$/, ''); }
function arUrl() { return String(cfg().get('arUrl') || 'http://127.0.0.1:8797').replace(/\/+$/, ''); }
function refreshMs() { return Math.max(1, Number(cfg().get('refreshSeconds')) || 2) * 1000; }

function repoRoot() {
    const c = String(cfg().get('repoRoot') || '');
    if (c && fs.existsSync(path.join(c, 'config', 'platform', 'zmax_product.json'))) return c;
    const starts = [];
    for (const f of vscode.workspace.workspaceFolders || []) starts.push(f.uri.fsPath);
    if (!starts.length) starts.push(process.cwd());
    for (const s of starts) {
        let d = s;
        for (let i = 0; i < 6; i++) {
            if (fs.existsSync(path.join(d, 'config', 'platform', 'zmax_product.json'))) return d;
            const up = path.dirname(d);
            if (up === d) break;
            d = up;
        }
    }
    return starts[0];
}
function repoFile(rel) { return path.join(repoRoot(), rel); }

/* ------------------------------------------------------------------ HTTP */
function httpJson(method, url, body, timeoutMs) {
    return new Promise((resolve) => {
        let u;
        try { u = new URL(url); } catch (e) { return resolve({ ok: false, err: `URL 非法: ${url}` }); }
        const lib = u.protocol === 'https:' ? https : http;
        const payload = body === undefined || body === null ? null : JSON.stringify(body);
        const req = lib.request({
            hostname: u.hostname, port: u.port || (u.protocol === 'https:' ? 443 : 80),
            path: u.pathname + u.search, method,
            headers: payload ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(payload) } : {},
            timeout: timeoutMs || 8000,
        }, (res) => {
            const chunks = [];
            res.on('data', (c) => chunks.push(c));
            res.on('end', () => {
                const raw = Buffer.concat(chunks).toString('utf8');
                let json = null;
                try { json = JSON.parse(raw); } catch (e) { /* 非 JSON 原样返回 */ }
                resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, status: res.statusCode, raw, json, bytes: Buffer.byteLength(raw) });
            });
        });
        req.on('timeout', () => { req.destroy(new Error('超时')); });
        req.on('error', (e) => resolve({ ok: false, err: e.message }));
        if (payload) req.write(payload);
        req.end();
    });
}

/* ------------------------------------------------------------------ 状态缓存 */
const status = { json: null, ts: 0, ok: false, err: '', bytes: 0 };
let statusBar = null;
const providers = {};

async function pullStatus() {
    const t0 = Date.now();
    const r = await httpJson('GET', `${baseUrl()}/station/status`, null, 6000);
    if (r.ok && r.json) {
        status.json = r.json; status.ok = true; status.err = ''; status.bytes = r.bytes || 0;
    } else {
        status.ok = false;
        status.err = r.err || `HTTP ${r.status}`;
    }
    status.ts = Date.now();
    status.latencyMs = Date.now() - t0;
    status.pullN = (status.pullN || 0) + 1;
    if (status.pullN <= 3) {                       // 自证: 扩展在 VSCode 里真的激活并拉到真源 (可离线核对)
        const c = (status.json || {}).ctl || {};
        const line = `状态#${status.pullN}: ${status.ok ? '在线' : `离线(${status.err})`} · TCP 帧龄 ${ageStr((c.tcp || {}).age_s)} · 授权 ${(c.auth || {}).armed ? 'on' : 'off'} · 撞车 ${(c.collisions || []).length} · ${status.bytes}B / ${status.latencyMs}ms`;
        if (!out) out = vscode.window.createOutputChannel('Z-MAX 550B');
        out.appendLine(line);
        try { fs.appendFileSync('/tmp/zmax550b_ext.log', `${new Date().toISOString()} ${line}\n`); } catch (e) { /* 无盘可写也不致命 */ }
    }
    return status;
}
function ageStr(sec) {
    if (sec === null || sec === undefined || isNaN(sec)) return '—';
    const s = Number(sec);
    if (s < 1) return `${s.toFixed(2)}s`;
    if (s < 60) return `${s.toFixed(1)}s`;
    if (s < 3600) return `${(s / 60).toFixed(1)}min`;
    return `${(s / 3600).toFixed(1)}h`;
}
function cacheAgeStr() { return status.ts ? `${((Date.now() - status.ts) / 1000).toFixed(1)}s 前` : '未取到'; }
function S() { return status.json || {}; }
function ctl() { return S().ctl || {}; }

/* ------------------------------------------------------------------ 状态栏 */
function buildStatusBar(context) {
    statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    statusBar.command = 'zmax550b.status.json';
    context.subscriptions.push(statusBar);
    statusBar.show();
}
function renderStatusBar() {
    if (!statusBar) return;
    if (!status.ok) {
        statusBar.text = `$(debug-disconnect) Z-MAX 550B 离线`;
        statusBar.tooltip = `${baseUrl()}/station/status 取不到: ${status.err}\n(点开看原始状态 JSON)`;
        statusBar.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
        return;
    }
    const c = ctl();
    const tcp = (c.tcp || {}).age_s;
    const auth = c.auth || {};
    const armed = !!auth.armed;
    const left = auth.left_s;
    const nColl = Array.isArray(c.collisions) ? c.collisions.length : 0;
    const exec = c.exec || {};
    const parts = [`$(pulse) TCP ${ageStr(tcp)}`];
    parts.push(armed ? `$(unlock) 授权 ${Math.round(left || 0)}s` : `$(lock) 未授权`);
    if (nColl) parts.push(`$(warning) 撞车 ${nColl}`);
    if (exec.online === false) parts.push(`$(circle-slash) 控制台停`);
    statusBar.text = parts.join('  ');
    statusBar.tooltip = [
        `工位控制 ${baseUrl()} · 状态 ${ageStr((Date.now() - status.ts) / 1000)} 前 (HTTP ${status.latencyMs}ms / ${status.bytes}B)`,
        `真机 TCP 帧龄 ${ageStr(tcp)} · 新鲜度 = 判断"臂是否真的在动"的唯一依据`,
        `授权 ${armed ? `已授权 ${Math.round(left || 0)}s · ip=${auth.ip || '?'}` : '未授权 (点方向键只算目标, 不动臂)'}`,
        `撞车候选 ${nColl} · 控制台 exec ${exec.online === false ? '停' : '在'}${exec.pid ? ` (pid ${exec.pid})` : ''}`,
        `日志帧龄 ${ageStr(exec.log_age_s)} · 点这里看原始 JSON`,
    ].join('\n');
    statusBar.backgroundColor = armed ? new vscode.ThemeColor('statusBarItem.warningBackground') : undefined;
}

/* ------------------------------------------------------------------ 树辅助 */
function item(label, opts) {
    const o = opts || {};
    const it = new vscode.TreeItem(label, o.state === undefined ? vscode.TreeItemCollapsibleState.None : o.state);
    if (o.desc !== undefined) it.description = o.desc;
    if (o.tip !== undefined) it.tooltip = o.tip;
    if (o.icon) it.iconPath = new vscode.ThemeIcon(o.icon);
    if (o.cmd) it.command = o.cmd;
    if (o.ctx) it.contextValue = o.ctx;
    if (o.color) it.iconPath = new vscode.ThemeIcon(o.icon || 'circle-filled', new vscode.ThemeColor(o.color));
    return it;
}
function yes(ok) { return ok ? '$(pass-filled)' : '$(error)'; }

/* ------------------------------------------------------------------ 1. 诊断 */
class DiagnoseProvider {
    constructor() { this._em = new vscode.EventEmitter(); this.onDidChangeTreeData = this._em.event; }
    refresh() { this._em.fire(); }
    getTreeItem(e) { return e; }
    async getChildren(el) {
        if (el && el._kids) return el._kids;
        const c = ctl();
        const exec = c.exec || {};
        const gate = c.gate || {};
        const coll = Array.isArray(c.collisions) ? c.collisions : [];
        const last = c.last_cmd || {};
        const robot = c.robot || {};
        const kids = [];

        kids.push(item(`工位控制 8793`, {
            desc: status.ok ? `✅ ${status.bytes}B / ${status.latencyMs}ms / 状态 ${cacheAgeStr()}` : `❌ ${status.err}`,
            icon: status.ok ? 'pass-filled' : 'error',
            tip: `${baseUrl()}/station/status\n状态本身也有新鲜度: ${cacheAgeStr()}`,
            cmd: { command: 'zmax550b.status.json', title: '打开原始 JSON' },
        }));
        kids.push(item(`控制台 exec`, {
            desc: exec.online === false ? `停` : `在 · pid ${exec.pid || '?'} · 技能 ${exec.skills || '?'} · 日志帧龄 ${ageStr(exec.log_age_s)}`,
            icon: exec.online === false ? 'circle-slash' : 'play-circle',
            tip: 'exec = 执行侧进程 (l2_daemon / 引擎) 的存活与日志新鲜度',
        }));
        kids.push(item(`安全闸 gate`, {
            desc: `fast=${gate.fast} warn_only=${gate.warn_only} slow=${gate.slow_enabled}`,
            icon: 'shield',
            tip: gate.line || '闸门分层状态; 动作被拦时先看这里',
        }));
        kids.push(item(`真机 TCP 真值`, {
            desc: `帧龄 ${ageStr((c.tcp || {}).age_s)} · xyz=(${((c.tcp || {}).xyz || []).map((v) => Number(v).toFixed(4)).join(', ') || '—'})`,
            icon: 'location', tip: '位姿真源 tcp_out/latest.json; 全 0 = 陈旧, 不能当"臂给面子"的依据',
        }));
        kids.push(item(`机械臂状态`, {
            desc: `${robot.ok ? 'ok' : '异常'} · power=${robot.power} · ${robot.operation || ''}${robot.error_code ? ` · err ${robot.error_code}` : ''}`,
            icon: robot.ok && !robot.has_error ? 'pass-filled' : 'warning',
        }));
        kids.push(item(`动作台账 ledger`, {
            desc: '8793 /station/ledger (与动作同一时间线)',
            icon: 'history', cmd: { command: 'zmax550b.diagnose.ledger', title: '打开台账' },
        }));
        const collKids = coll.slice(0, 12).map((x, i) => item(`#${i + 1}`, {
            desc: typeof x === 'string' ? x : JSON.stringify(x).slice(0, 90),
            icon: 'warning',
        }));
        kids.push(item(`撞车候选 ${coll.length}`, { state: collKids.length ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None, icon: 'warning', _kids: collKids, desc: coll.length ? '点开看明细' : '无' }));
        kids.push(item(`最近一条指令`, {
            desc: last.t ? `${last.t} · ${last.skill} · dry=${last.dry} · ok=${last.ok}` : '无',
            tip: last.msg || '', icon: 'terminal',
        }));
        const scripts = listVerifyScripts();
        const scKids = scripts.map((s) => item(path.basename(s), {
            desc: '点击运行 (集成终端)',
            icon: 'beaker',
            cmd: { command: 'zmax550b.diagnose.chain', title: '跑', arguments: [s] },
        }));
        kids.push(item(`判据脚本 ${scripts.length} 个`, {
            state: scKids.length ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None,
            icon: 'beaker', _kids: scKids, desc: 'tools/verify_*.py',
            tip: '链路核验判据 (只读断言脚本), 在集成终端里跑, 输出可复制',
        }));
        kids.push(item(`尾随控制台日志`, { icon: 'output', cmd: { command: 'zmax550b.diagnose.tail', title: '尾随' } }));
        return kids;
    }
}
function listVerifyScripts() {
    try {
        const dir = repoFile('tools');
        return fs.readdirSync(dir)
            .filter((f) => /^verify.*\.py$/.test(f) && !/__/.test(f))
            .slice(0, 30)
            .map((f) => path.join(dir, f));
    } catch (e) { return []; }
}

/* ------------------------------------------------------------------ 2. 测量 */
class MeasureProvider {
    constructor() { this._em = new vscode.EventEmitter(); this.onDidChangeTreeData = this._em.event; }
    refresh() { this._em.fire(); }
    getTreeItem(e) { return e; }
    async getChildren(el) {
        if (el && el._kids) return el._kids;
        const s = S(); const c = ctl();
        const stats = s.stats || {};
        const kids = [];
        kids.push(item(`测量面板 (四路画面 + 数值)`, {
            icon: 'open-preview', desc: '在编辑器里看实时画面',
            cmd: { command: 'zmax550b.measure.panel', title: '打开' },
        }));
        kids.push(item(`抓一帧快照`, { icon: 'device-camera', cmd: { command: 'zmax550b.measure.snapshot', title: '抓帧' } }));
        const camKids = [];
        for (const [k, v] of Object.entries(stats)) {
            const st = v || {};
            const camLabel = ((s.labels || {})[k]) || k;
            camKids.push(item(`${k}${camLabel && camLabel !== k ? ` · ${camLabel}` : ''}`, {
                desc: st.online ? `${st.fps}fps · 帧 ${ageStr(st.age_s)} · ${st.kb_per_frame}kB ÷${st.compress_x || '—'}` : `离线 · 帧 ${ageStr(st.age_s)}`,
                icon: st.online ? 'pass-filled' : 'circle-slash',
                tip: `每帧 ${st.kb_per_frame}kB (原始 ${st.raw_kb_per_frame}kB, 压缩 ${st.compress_x}x) · 帧龄 ${ageStr(st.age_s)}`,
                cmd: { command: 'zmax550b.measure.snapshot', title: '抓帧', arguments: [k] },
            }));
        }
        kids.push(item(`相机 ${Object.keys(stats).length} 路`, { state: vscode.TreeItemCollapsibleState.Expanded, icon: 'device-camera', _kids: camKids, desc: '带帧龄' }));
        const tcp = c.tcp || {};
        const xyz = (tcp.xyz || []).map((v) => Number(v).toFixed(4)).join(', ');
        kids.push(item(`TCP 位姿`, {
            desc: `xyz=(${xyz || '—'}) · 帧龄 ${ageStr(tcp.age_s)}`,
            tip: `abc(rad)=${(tcp.abc_rad || []).join(', ')}\nabc(deg)=${(tcp.abc_deg || []).join(', ')}\nsrc=${tcp.abc_src || '?'}`,
            icon: 'location',
        }));
        const d = c.depth || {};
        kids.push(item(`深度`, {
            desc: d.depth_scale ? `${d.w}x${d.h} · unit ${d.depth_scale}mm · ${d.fps}fps · ${d.frames}帧` : '—',
            icon: 'ruler',
            tip: 'D405 深度单位 0.1mm (4013 = 401mm); 帧龄见相机行',
        }));
        const aoi = s.aoi || {};
        const aoiKids = Object.entries(aoi).map(([k, v]) => {
            const vv = v || {};
            return item(`${k}`, {
                desc: vv.ok ? `✅ ${vv.src || ''} ${vv.http || ''} · ${vv.t || ''}` : `❌ ${vv.err || ''}`,
                icon: vv.ok ? 'pass-filled' : 'error',
                tip: `url=${vv.url || '—'}\nerr=${vv.err || '—'}`,
            });
        });
        kids.push(item(`AOI 检测 (金手指/表面)`, { state: aoiKids.length ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None, icon: 'eye', _kids: aoiKids, desc: '8793 代理的远端判定' }));
        const m = c.motion || {};
        kids.push(item(`运动状态`, { desc: m.ok ? `${m.skill} · dir=${m.dir} · Δ${m.delta} · 帧龄 ${ageStr(m.age_s)}` : '空闲/无', icon: 'symbol-event' }));
        return kids;
    }
}

/* ------------------------------------------------------------------ 3. 标定 */
const CALIB_CANDIDATES = [
    'flows/calib_closure.json',
    'zmax_data/calib.json',
    'zmax_data/params/calib.json',
    'config/calib.json',
];
class CalibProvider {
    constructor() { this._em = new vscode.EventEmitter(); this.onDidChangeTreeData = this._em.event; }
    refresh() { this._em.fire(); }
    getTreeItem(e) { return e; }
    async getChildren(el) {
        if (el && el._kids) return el._kids;
        const kids = [];
        const found = CALIB_CANDIDATES.map((r) => repoFile(r)).find((p) => fs.existsSync(p));
        if (found) {
            let obj = null;
            try { obj = JSON.parse(fs.readFileSync(found, 'utf8')); } catch (e) { /* 非法 JSON */ }
            kids.push(item(`标定真源 ${path.relative(repoRoot(), found)}`, {
                desc: obj ? `${Object.keys(obj).length} 个顶层键 · ${(fs.statSync(found).size / 1024).toFixed(1)}kB` : '解析失败',
                icon: 'json',
                cmd: { command: 'vscode.open', title: '打开', arguments: [vscode.Uri.file(found)] },
                tip: '标定真源: 引擎每次运行按真源重载 (改真源 → 下次运行生效)',
            }));
            if (obj) kids.push(...jsonKids(obj, '  '));
        } else {
            kids.push(item(`未找到标定真源`, { desc: CALIB_CANDIDATES.join(' / '), icon: 'warning', tip: `在 ${repoRoot()} 下未找到候选路径; 用命令"标定: 打开标定真源"手工定位` }));
        }
        const impl = repoFile('src/lerobot/calibration/calibration_layer.py');
        kids.push(item(`标定实现 calibration_layer.py`, {
            desc: fs.existsSync(impl) ? `${(fs.statSync(impl).size / 1024).toFixed(1)}kB` : '未找到',
            icon: 'code', cmd: { command: 'zmax550b.calib.openSource', title: '打开源码' },
            tip: 'apply_to_engine: 精确写回引擎源码字面量 (Kp / u_clip / STAGE_V_CAP / 校正K ...)',
        }));
        const pts = [
            item(`记录当前点位`, { icon: 'add', desc: '8793 /ctl/record_point (需授权)', cmd: { command: 'zmax550b.calib.recordPoint', title: '记录' } }),
            item(`清除已记录点位`, { icon: 'trash', desc: '8793 /ctl/clear_point (需授权)', cmd: { command: 'zmax550b.calib.clearPoint', title: '清除' } }),
            item(`增量建图 45s/轮`, { icon: 'map', desc: '8793 /ctl/gs_map (需授权)', cmd: { command: 'zmax550b.calib.gsMap', title: '建图' } }),
        ];
        kids.push(item(`点位 / 建图 (真机)`, { state: vscode.TreeItemCollapsibleState.Expanded, icon: 'map', _kids: pts, desc: '写操作走 8793 授权闸' }));
        const a = ctl().auth || {};
        kids.push(item(`当前授权`, {
            desc: a.armed ? `已授权 ${Math.round(a.left_s || 0)}s · ip=${a.ip || '?'}` : '未授权 (点方向键只算目标, 臂不动)',
            icon: a.armed ? 'unlock' : 'lock',
            tip: '授权默认关闭, 两步确认, 5 分钟自动失效; 撤销随时可用',
        }));
        return kids;
    }
}
function jsonKids(obj, indent, depth) {
    const d = depth === undefined ? 0 : depth;
    const kids = [];
    if (d > 2) return kids;
    for (const [k, v] of Object.entries(obj)) {
        if (v && typeof v === 'object' && !Array.isArray(v)) {
            const sub = jsonKids(v, indent, d + 1);
            const it = item(`${indent}${k}`, { state: vscode.TreeItemCollapsibleState.Collapsed, icon: 'symbol-field', desc: `{${Object.keys(v).length}}` });
            it._kids = sub;
            kids.push(it);
        } else if (Array.isArray(v)) {
            const sub = v.slice(0, 20).map((x, i) => item(`[${i}]`, { desc: typeof x === 'object' ? JSON.stringify(x).slice(0, 80) : String(x) }));
            const it = item(`${indent}${k}`, { state: vscode.TreeItemCollapsibleState.Collapsed, icon: 'symbol-array', desc: `[${v.length}]` });
            it._kids = sub;
            kids.push(it);
        } else {
            kids.push(item(`${indent}${k}`, { desc: String(v) }));
        }
    }
    return kids;
}

/* ------------------------------------------------------------------ 4. 配置 */
class ConfigProvider {
    constructor() { this._em = new vscode.EventEmitter(); this.onDidChangeTreeData = this._em.event; }
    refresh() { this._em.fire(); }
    getTreeItem(e) { return e; }
    async getChildren(el) {
        if (el && el._kids) return el._kids;
        const kids = [];
        const pf = repoFile('config/platform/zmax_product.json');
        let prof = null, prod = null;
        if (fs.existsSync(pf)) {
            try {
                const raw = JSON.parse(fs.readFileSync(pf, 'utf8'));
                prod = raw.products || raw;
                const cur = raw.current || raw.active || null;
                prof = (prod && (prod['550B'] || prod[cur])) || null;
            } catch (e) { /* ignore */ }
        }
        const dp = (prof && (prof.dev_profile || prof)) || {};
        const swKids = Object.entries(dp).map(([k, v]) => item(k, { desc: String(v), icon: 'settings-gear' }));
        kids.push(item(`产品档位 550B (调试档)`, {
            desc: dp && dp.topics ? `topics=${dp.topics} comm=${dp.comm}` : (fs.existsSync(pf) ? '解析失败' : '未找到真源'),
            state: swKids.length ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.None,
            icon: 'symbol-enum', _kids: swKids,
            tip: '真源 config/platform/zmax_product.json (人可编·进 git);\n读取口 tools/zmax_profile.py; 本扩展只对 550B 生效',
        }));
        kids.push(item(`打开档位真源`, { icon: 'json', cmd: { command: 'zmax550b.config.openProfile', title: '打开' } }));
        kids.push(item(`参数规格 param_spec.json`, {
            desc: fs.existsSync(repoFile('config/platform/param_spec.json')) ? `${(fs.statSync(repoFile('config/platform/param_spec.json')).size / 1024).toFixed(0)}kB` : '未找到',
            icon: 'list-unordered', cmd: { command: 'zmax550b.config.openParamSpec', title: '打开' },
        }));
        const cs = S().cam_src || {};
        kids.push(item(`相机源`, {
            desc: cs.ok ? `${cs.ch || ''} · ${cs.label || cs.name || ''} (dev ${cs.dev}) · ${cs.kind || ''}` : '未取到',
            icon: 'device-camera-video',
            cmd: { command: 'zmax550b.config.camSrc', title: '查看/切换' },
            tip: cs.note || '8793 /cam/src —— 切换是写操作, 扩展只给命令与确认, 不静默改',
        }));
        const ap = S().aoi_auto || {};
        kids.push(item(`AOI 自动取景`, { desc: Object.entries(ap).map(([k, v]) => `${k}=${v ? '开' : '关'}`).join(' · ') || '—', icon: 'sync' }));
        return kids;
    }
}

/* ------------------------------------------------------------------ 测量面板 (Webview) */
let panel = null;
function openMeasurePanel(context) {
    if (panel) { panel.reveal(); return; }
    panel = vscode.window.createWebviewPanel('zmax550bMeasure', 'Z-MAX 测量面板', vscode.ViewColumn.Beside, { enableScripts: true, retainContextWhenHidden: true });
    panel.onDidDispose(() => { panel = null; });
    const refresh = () => { if (panel) panel.webview.html = measureHtml(); };
    const timer = setInterval(refresh, 2000);
    panel.onDidDispose(() => clearInterval(timer));
    refresh();
}
function measureHtml() {
    const s = S(), c = ctl();
    const stats = s.stats || {};
    const cams = ['arm', 'local', 'local2', 'depth', 'ov_local'].filter((k) => stats[k]);
    const t = Date.now();
    const cards = cams.map((k) => {
        const st = stats[k] || {};
        const online = st.online;
        const stale = Number(st.age_s) > 10;
        return `<figure>
  <img src="${baseUrl()}/snapshot/${k}.jpg?t=${t}" alt="${k}" onerror="this.style.display='none';this.insertAdjacentHTML('afterend','<div style=&quot;padding:24px 8px;text-align:center;font-size:12px;opacity:.75;background:#111&quot;>该路无帧 —— 后端原文: 该路还没有帧(检查相机/源)</div>')" />
  <figcaption><b>${k}</b> ${online ? '✅' : '❌'} ${st.fps || '—'}fps · 帧 <span class="${stale ? 'stale' : ''}">${ageStr(st.age_s)}</span> · ${st.kb_per_frame || '—'}kB</figcaption>
</figure>`;
    }).join('\n');
    const tcp = c.tcp || {};
    const row = (a, b) => `<tr><th>${a}</th><td>${b}</td></tr>`;
    const a = c.auth || {};
    return `<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${baseUrl()} data:; style-src 'unsafe-inline';">
<style>
 body{font-family:var(--vscode-font-family);color:var(--vscode-foreground);background:var(--vscode-editor-background);margin:12px}
 h2{font-size:14px;margin:14px 0 6px}
 .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px}
 figure{margin:0;border:1px solid var(--vscode-panel-border);border-radius:6px;overflow:hidden}
 img{width:100%;display:block;background:#111}
 figcaption{font-size:11px;padding:4px 6px;opacity:.9}
 table{border-collapse:collapse;font-size:12px}
 th{text-align:left;padding:2px 10px 2px 0;opacity:.75;font-weight:600}
 td{padding:2px 0;font-variant-numeric:tabular-nums}
 .stale{color:#e5a30a}
</style></head><body>
<h2>测量 · 四路画面 (每 2s 自动刷新 · 时间 ${new Date().toLocaleTimeString()})</h2>
<div class="grid">${cards || '<p>无相机数据 (8793 未通?)</p>'}</div>
<h2>真机与状态</h2>
<table>
${row('TCP xyz', `(${(tcp.xyz || []).map((v) => Number(v).toFixed(4)).join(', ')})`)}
${row('TCP abc (deg)', `${(tcp.abc_deg || []).join(', ')}`)}
${row('TCP 帧龄', `<span class="${Number(tcp.age_s) > 3 ? 'stale' : ''}">${ageStr(tcp.age_s)}</span>`)}
${row('授权', a.armed ? `已授权 ${Math.round(a.left_s || 0)}s · ip ${a.ip || '?'}` : '未授权')}
${row('控制台 exec', (c.exec || {}).online === false ? '停' : `在 · pid ${(c.exec || {}).pid || '?'} · 日志帧龄 ${ageStr((c.exec || {}).log_age_s)}`)}
${row('撞车候选', (c.collisions || []).length)}
${row('状态本身', `${ageStr((Date.now() - status.ts) / 1000)} 前 · ${status.bytes}B · HTTP ${status.latencyMs}ms`)}
</table>
<p style="font-size:11px;opacity:.7">帧龄是判断"画面还活着"的唯一依据; 快照为 8793 /snapshot/*.jpg 即时抓取。</p>
</body></html>`;
}

/* ------------------------------------------------------------------ 命令 */
async function guardAuthorize(context) {
    const a = ctl().auth || {};
    if (a.armed) return true;
    const step1 = await vscode.window.showWarningMessage('授权真动? 真机机械臂将可被指令驱动。', { modal: true }, '继续');
    if (step1 !== '继续') return false;
    const step2 = await vscode.window.showWarningMessage('再确认一次: 现场无人、夹具已就位?', { modal: true }, '确认 (现场安全)');
    if (step2 !== '确认 (现场安全)') return false;
    const r = await httpJson('POST', `${baseUrl()}/ctl/arm`, { on: true, note: 'VSCode 550B 扩展' }, 8000);
    log(`授权请求 → HTTP ${r.status} ${r.raw ? r.raw.slice(0, 200) : r.err}`);
    await pullStatus();
    if (!r.ok) { vscode.window.showErrorMessage(`授权失败: ${r.err || r.raw}`); return false; }
    vscode.window.showInformationMessage(`已授权 ${Math.round((ctl().auth || {}).left_s || 0)}s`);
    return true;
}

function registerCommands(context) {
    const reg = (id, fn) => context.subscriptions.push(vscode.commands.registerCommand(id, fn));

    reg('zmax550b.refresh', async () => { await pullStatus(); renderStatusBar(); for (const p of Object.values(providers)) if (p && p.refresh) p.refresh(); });

    reg('zmax550b.status.json', async () => {
        await pullStatus();
        if (!status.ok) return vscode.window.showErrorMessage(`8793 取不到状态: ${status.err}`);
        const doc = await vscode.workspace.openTextDocument({ content: JSON.stringify(status.json, null, 2), language: 'json' });
        vscode.window.showTextDocument(doc, { preview: false });
    });

    reg('zmax550b.openStation', () => vscode.env.openExternal(vscode.Uri.parse(`${baseUrl()}/station.html`)));
    reg('zmax550b.open3d', () => vscode.env.openExternal(vscode.Uri.parse(`${arUrl()}/`)));
    reg('zmax550b.measure.panel', () => openMeasurePanel(context));

    reg('zmax550b.measure.snapshot', async (which) => {
        const key = typeof which === 'string' ? which : 'arm';
        if (typeof which === 'object' && which && which.label) { /* 树里传对象时的兼容 */ }
        const url = `${baseUrl()}/snapshot/${key}.jpg`;
        const r = await new Promise((resolve) => {
            const u = new URL(url);
            http.get({ hostname: u.hostname, port: u.port, path: u.pathname, timeout: 8000 }, (res) => {
                if (res.statusCode !== 200) { res.resume(); return resolve({ ok: false, err: `HTTP ${res.statusCode}` }); }
                const chunks = []; res.on('data', (c) => chunks.push(c));
                res.on('end', () => resolve({ ok: true, buf: Buffer.concat(chunks) }));
            }).on('error', (e) => resolve({ ok: false, err: e.message }));
        });
        if (!r.ok) return vscode.window.showErrorMessage(`抓帧失败 ${key}: ${r.err}`);
        const dir = path.join(repoRoot(), 'zmax_data', 'ss_live', 'vscode_snap');
        fs.mkdirSync(dir, { recursive: true });
        const f = path.join(dir, `${key}_${new Date().toISOString().replace(/[:.]/g, '-')}.jpg`);
        fs.writeFileSync(f, r.buf);
        vscode.window.showInformationMessage(`已抓帧 ${key} → ${f} (${(r.buf.length / 1024).toFixed(0)}kB)`);
        vscode.commands.executeCommand('vscode.open', vscode.Uri.file(f));
    });

    reg('zmax550b.diagnose.chain', (script) => {
        const s = typeof script === 'string' ? script : null;
        const term = vscode.window.createTerminal({ name: 'Z-MAX 判据', cwd: repoRoot() });
        term.show();
        if (s) term.sendText(`./gui-venv311/bin/python ${path.relative(repoRoot(), s)}`);
        else {
            const list = listVerifyScripts().slice(0, 6);
            vscode.window.showQuickPick(list.map((p) => path.basename(p)), { placeHolder: '选一个判据脚本跑' }).then((pick) => {
                if (pick) term.sendText(`./gui-venv311/bin/python tools/${pick}`);
            });
        }
    });

    reg('zmax550b.diagnose.tail', () => {
        const term = vscode.window.createTerminal({ name: 'Z-MAX 日志', cwd: repoRoot() });
        term.show();
        term.sendText('tail -n 80 -F /tmp/studio_launch.log');
    });

    reg('zmax550b.diagnose.ledger', () => vscode.env.openExternal(vscode.Uri.parse(`${baseUrl()}/station/ledger`)));

    reg('zmax550b.calib.openData', () => {
        const found = CALIB_CANDIDATES.map((r) => repoFile(r)).find((p) => fs.existsSync(p));
        if (!found) return vscode.window.showWarningMessage(`未找到标定真源, 候选: ${CALIB_CANDIDATES.join(' / ')}`);
        vscode.commands.executeCommand('vscode.open', vscode.Uri.file(found));
    });
    reg('zmax550b.calib.openSource', () => {
        const f = repoFile('src/lerobot/calibration/calibration_layer.py');
        if (!fs.existsSync(f)) return vscode.window.showWarningMessage(`未找到 ${f}`);
        vscode.commands.executeCommand('vscode.open', vscode.Uri.file(f));
    });
    reg('zmax550b.calib.recordPoint', async () => {
        if (!(await guardAuthorize(context))) return;
        const r = await httpJson('POST', `${baseUrl()}/ctl/record_point`, { note: 'VSCode 550B 扩展' }, 10000);
        log(`记录点位 → HTTP ${r.status} ${r.raw ? r.raw.slice(0, 300) : r.err}`);
        if (r.ok) vscode.window.showInformationMessage(`点位已记录: ${(r.raw || '').slice(0, 160)}`);
        else vscode.window.showErrorMessage(`记录失败: ${r.err || r.raw}`);
        for (const p of Object.values(providers)) if (p && p.refresh) p.refresh();
    });
    reg('zmax550b.calib.clearPoint', async () => {
        if (!(await guardAuthorize(context))) return;
        const ok = await vscode.window.showWarningMessage('清除所有已记录点位? 不可撤销。', { modal: true }, '清除');
        if (ok !== '清除') return;
        const r = await httpJson('POST', `${baseUrl()}/ctl/clear_point`, {}, 10000);
        log(`清除点位 → HTTP ${r.status} ${r.raw ? r.raw.slice(0, 300) : r.err}`);
        if (r.ok) vscode.window.showInformationMessage('点位已清除');
        else vscode.window.showErrorMessage(`清除失败: ${r.err || r.raw}`);
    });
    reg('zmax550b.calib.gsMap', async () => {
        if (!(await guardAuthorize(context))) return;
        const r = await httpJson('POST', `${baseUrl()}/ctl/gs_map`, { mode: 'auto', note: 'VSCode 550B 扩展' }, 15000);
        log(`增量建图 → HTTP ${r.status} ${r.raw ? r.raw.slice(0, 300) : r.err}`);
        if (r.ok) vscode.window.showInformationMessage(`建图已触发: ${(r.raw || '').slice(0, 160)}`);
        else vscode.window.showErrorMessage(`建图失败: ${r.err || r.raw}`);
    });

    reg('zmax550b.config.openProfile', () => vscode.commands.executeCommand('vscode.open', vscode.Uri.file(repoFile('config/platform/zmax_product.json'))));
    reg('zmax550b.config.openParamSpec', () => vscode.commands.executeCommand('vscode.open', vscode.Uri.file(repoFile('config/platform/param_spec.json'))));

    reg('zmax550b.config.camSrc', async () => {
        const r = await httpJson('GET', `${baseUrl()}/cam/src`, null, 6000);
        if (!r.ok || !r.json) return vscode.window.showErrorMessage(`取相机源失败: ${r.err || r.status}`);
        const cs = r.json;
        const opts = cs.options || [];
        const picked = await vscode.window.showQuickPick(
            opts.map((o) => (typeof o === 'string' ? { label: o } : { label: o.label || o.name || JSON.stringify(o), description: o.description || '' })),
            { placeHolder: `当前: ${cs.label || cs.name || cs.ch} (dev ${cs.dev}) —— 选择只给出切换命令, 不静默改` });
        if (!picked) return;
        const cmd = `curl -s -X POST ${baseUrl()}/cam/src -H 'Content-Type: application/json' -d '{"src":"${picked.label}"}'`;
        await vscode.env.clipboard.writeText(cmd);
        vscode.window.showInformationMessage(`切换命令已复制 (切换是写操作, 由你确认后执行): ${cmd}`, { modal: false }, '在终端执行').then((sel) => {
            if (sel) {
                const term = vscode.window.createTerminal({ name: 'Z-MAX 相机源', cwd: repoRoot() });
                term.show(); term.sendText(cmd);
            }
        });
    });

    reg('zmax550b.gate.arm', async () => { await guardAuthorize(context); renderStatusBar(); });
    reg('zmax550b.gate.disarm', async () => {
        const r = await httpJson('POST', `${baseUrl()}/ctl/arm`, { on: false, note: 'VSCode 550B 扩展撤销' }, 8000);
        log(`撤销授权 → HTTP ${r.status} ${r.raw ? r.raw.slice(0, 200) : r.err}`);
        await pullStatus(); renderStatusBar();
        if (r.ok) vscode.window.showInformationMessage('授权已撤销');
        else vscode.window.showErrorMessage(`撤销失败: ${r.err || r.raw}`);
    });
}

/* ------------------------------------------------------------------ activate */
function activate(context) {
    log(`激活 · 工位 ${baseUrl()} · 仓库 ${repoRoot()}`);
    buildStatusBar(context);

    const mk = (id, prov) => {
        providers[id] = prov;
        const view = vscode.window.createTreeView(id, { treeDataProvider: prov, showCollapseAll: true });
        context.subscriptions.push(view);
    };
    mk('zmax550b.diagnose', new DiagnoseProvider());
    mk('zmax550b.measure', new MeasureProvider());
    mk('zmax550b.calib', new CalibProvider());
    mk('zmax550b.config', new ConfigProvider());

    registerCommands(context);

    const tick = async () => {
        await pullStatus();
        renderStatusBar();
        for (const p of Object.values(providers)) if (p && p.refresh) p.refresh();
    };
    tick();
    const t = setInterval(tick, refreshMs());
    context.subscriptions.push({ dispose: () => clearInterval(t) });
    context.subscriptions.push(vscode.workspace.onDidChangeConfiguration((e) => { if (e.affectsConfiguration('zmax550b')) tick(); }));
}

function deactivate() { if (panel) panel.dispose(); }
