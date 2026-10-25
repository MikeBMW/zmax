#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工程数据库云端备份(压缩)工具  cloud_backup_engineering_db.py
==========================================================
把工程数据库**真源** data/database/zmax/ (含 zmax_space.proj / zmax_engineering.db / sources/)
压缩成单个归档, 生成 .sha256 与 manifest.md, 上传 ECS 并在**远端回读 sha256 比对**后才算成功,
最后落一份报告 reports/cloud_backup_<date>.md + .json。

老倪 (2026-10-13): "工程数据库要能一键云端备份, 压缩率要真实的, 传上去要能核验, 别自说自话。"

设计要点
--------
* 命名: zmax_data/cloud/zmax_engineering_db_<版本>_<日期>.tar.zst (无 zstd 则 .tar.gz)
* 幂等: 同 (版本,日期) 归档已存在且校验通过 → 复用不重压; 远端已有且 sha 一致 → 跳过上传
* 远端回读: ssh 进 ECS 跑 ls -l + sha256sum, 本地比对, 输出原样存进报告
* 凭据: 优先环境变量 ZMAX_ECS_PW; 无则读 zmax_data/secrets/zmax.env 的 ZMAX_ECS_PW;
        也支持**免密**(已配 SSH key)。密钥一律用 sshpass -e (SSHPASS 环境变量), 不进命令行/日志。
* --dry-run: 只压缩+出报告, 不联网, 不上传

用法
----
  gui-venv311/bin/python tools/cloud_backup_engineering_db.py            # 真跑: 压缩+上传+回读
  gui-venv311/bin/python tools/cloud_backup_engineering_db.py --dry-run  # 只压缩, 不传
  ZMAX_ECS_PW set 亦可; 免密主机直接跑即可。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# ----------------------------------------------------------------------------
REPO = Path(__file__).resolve().parent.parent
DEFAULT_SRC = REPO / "data" / "database" / "zmax"
DEFAULT_OUTDIR = REPO / "zmax_data" / "cloud"
DEFAULT_REPORTDIR = REPO / "reports"
DEFAULT_ECS_HOST = os.environ.get("ZMAX_ECS_HOST", "47.93.88.143")
DEFAULT_ECS_USER = os.environ.get("ZMAX_ECS_USER", "root")
DEFAULT_ECS_PATH = os.environ.get(
    "ZMAX_ECS_PATH", "/www/wwwroot/datadrive.world/backup/zmax/"
)
SECRET_ENV = REPO / "zmax_data" / "secrets" / "zmax.env"
GITIGNORE_HINT_MB = 5.0  # 大文件红线: 超过不入库
SSH_OPTS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "ConnectTimeout=15",
    "-o", "ServerAliveInterval=10",
    "-o", "BatchMode=no",
]


# ----------------------------------------------------------------------------
def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str, code: int = 1):
    log(f"❌ {msg}")
    sys.exit(code)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def human(nbytes: int) -> str:
    x = float(nbytes)
    for u in ("B", "KB", "MB", "GB"):
        if x < 1024 or u == "GB":
            return f"{x:.2f} {u}" if u != "B" else f"{int(x)} B"
        x /= 1024
    return f"{x:.2f} GB"


# ----------------------------------------------------------------------------
def detect_version() -> tuple[str, str]:
    """返回 (版本, 来源)。真源优先: zmax_space.proj 的 zmax_version, 再 git describe, 再 unknown。"""
    proj = DEFAULT_SRC / "zmax_space.proj"
    if proj.exists():
        try:
            d = json.loads(proj.read_text(encoding="utf-8"))
            v = d.get("zmax_version")
            if v:
                return str(v).lstrip("v"), "zmax_space.proj:zmax_version"
        except Exception:
            pass
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO), "describe", "--tags", "--always"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().lstrip("v"), "git describe"
    except Exception:
        pass
    return "unknown", "fallback"


def pick_compressor() -> tuple[str, str]:
    """返回 (扩展名, 压缩命令名)。优先 zstd -19, 退化 gzip -9。"""
    if shutil.which("zstd"):
        return ".tar.zst", "zstd"
    if shutil.which("gzip"):
        return ".tar.gz", "gzip"
    die("既无 zstd 也无 gzip, 无法压缩")


def load_ecs_pw() -> str:
    """凭据: 环境变量优先, 其次 zmax_data/secrets/zmax.env。返回值只在内存使用。"""
    pw = os.environ.get("ZMAX_ECS_PW", "")
    if pw:
        return pw
    if SECRET_ENV.exists():
        for line in SECRET_ENV.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("ZMAX_ECS_PW="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


# ----------------------------------------------------------------------------
def build_tar(src: Path, out: Path, comp: str) -> None:
    """tar -C <src.parent> <src.name> | <compressor> > out。归档内顶层目录即 src.name。"""
    if out.exists():
        out.unlink()
    tar_cmd = ["tar", "-C", str(src.parent), "-cf", "-", src.name]
    if comp == "zstd":
        comp_cmd = ["zstd", "-19", "-T0", "-q", "-o", str(out)]
    else:
        comp_cmd = ["gzip", "-9", "-c"]
        out_fh = open(out, "wb")
    p_tar = subprocess.Popen(tar_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if comp == "zstd":
        p_comp = subprocess.Popen(comp_cmd, stdin=p_tar.stdout, stderr=subprocess.PIPE)
        p_tar.stdout.close()  # noqa
        _, cerr = p_comp.communicate()
        terr = p_tar.stderr.read()
        p_tar.wait()
        if p_tar.returncode != 0:
            die(f"tar 失败: {terr.decode(errors='ignore')[:400]}")
        if p_comp.returncode != 0:
            die(f"{comp} 失败: {cerr.decode(errors='ignore')[:400]}")
    else:  # gzip
        p_comp = subprocess.Popen(comp_cmd, stdin=p_tar.stdout, stdout=out_fh)
        p_tar.stdout.close()  # noqa
        p_comp.communicate()
        out_fh.close()
        terr = p_tar.stderr.read()
        p_tar.wait()
        if p_tar.returncode != 0:
            die(f"tar 失败: {terr.decode(errors='ignore')[:400]}")


def iter_files(src: Path):
    for p in sorted(src.rglob("*")):
        if p.is_file() and not p.is_symlink():
            yield p


def write_sha256file(archive: Path) -> str:
    digest = sha256_file(archive)
    sha_path = archive.with_suffix(archive.suffix + ".sha256")
    sha_path.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return digest


def build_manifest(src: Path, archive: Path, sha: str, comp: str, version: str,
                   date: str, src_bytes: int, files: list, compressible: str) -> dict:
    arch_bytes = archive.stat().st_size
    ratio_keep = arch_bytes / src_bytes if src_bytes else 0.0
    ratio_saved = (1 - ratio_keep) * 100 if src_bytes else 0.0
    ratio_x = (src_bytes / arch_bytes) if arch_bytes else 0.0
    m = {
        "version": version,
        "date": date,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "source_dir": str(src),
        "archive": archive.name,
        "archive_path": str(archive),
        "archive_size": arch_bytes,
        "archive_sha256": sha,
        "compressor": comp,
        "files": files,
        "file_count": len(files),
        "source_bytes": src_bytes,
        "compression": {
            "ratio_kept_pct": round(ratio_keep * 100, 2),   # 压后占原体积 %
            "saved_pct": round(ratio_saved, 2),             # 省下 %
            "ratio_x": round(ratio_x, 3),                   # 原/压 倍数
        },
        "compressible": compressible,
    }
    md = [
        f"# 工程数据库云端备份 · manifest",
        "",
        f"- 版本: **{version}**",
        f"- 日期: {date}",
        f"- 生成时间: {m['generated_at']}",
        f"- 真源目录: `{src}`",
        f"- 归档文件: `{archive.name}` ({human(arch_bytes)})",
        f"- 归档 SHA-256: `{sha}`",
        f"- 压缩器: {comp}",
        f"- 文件数: {len(files)} · 原始合计 {human(src_bytes)}",
        f"- **压缩率: 压后 {ratio_keep*100:.2f}% (省下 {ratio_saved:.2f}%) · 等效 {ratio_x:.2f}×**",
        f"- 压缩可选性: {compressible}",
        "",
        "## 逐文件 SHA-256",
        "",
        "| 相对路径 | 大小 | 说明 | SHA-256 |",
        "|---|---:|---|---|",
    ]
    for f in files:
        md.append(
            f"| `{f['path']}` | {human(f['size'])} | {f['role']} | `{f['sha256']}` |"
        )
    md.append("")
    manifest_txt = "\n".join(md)
    mp = archive.with_suffix(archive.suffix + ".manifest.md")
    mp.write_text(manifest_txt, encoding="utf-8")
    m["manifest_path"] = str(mp)
    return m


ROLE_MAP = {
    "zmax_space.proj": "状态空间工程(真源)",
    "zmax_engineering.db": "工程数据库(生成物)",
    "config_meta.json": "配置元数据",
    "feature.dbc": "特征能力库",
    "README.md": "工程数据手册",
}


def classify(rel: str) -> str:
    base = os.path.basename(rel)
    if base in ROLE_MAP:
        return ROLE_MAP[base]
    if rel.startswith("sources/"):
        return "真源文件"
    if rel.startswith("archive/"):
        return "历史快照(留档)"
    return "其他"


# ----------------------------------------------------------------------------
def ssh_base(pw: str) -> list:
    """构造 ssh 前缀。有密码用 sshpass -e (走 SSHPASS 环境变量, 不进命令行)。"""
    if pw:
        if not shutil.which("sshpass"):
            die("需要密码但未安装 sshpass")
        return ["sshpass", "-e", "ssh"]
    return ["ssh"]


def scp_base(pw: str) -> list:
    if pw:
        if not shutil.which("sshpass"):
            die("需要密码但未安装 sshpass")
        return ["sshpass", "-e", "scp"]
    return ["scp"]


def run_remote(pw: str, host: str, user: str, remote_cmd: str, timeout=60):
    env = dict(os.environ)
    if pw:
        env["SSHPASS"] = pw
    cmd = ssh_base(pw) + SSH_OPTS + [f"{user}@{host}", remote_cmd]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    return r


def upload(pw: str, host: str, user: str, remote_dir: str, local: Path):
    env = dict(os.environ)
    if pw:
        env["SSHPASS"] = pw
    cmd = scp_base(pw) + SSH_OPTS + [str(local), f"{user}@{host}:{remote_dir}"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env)
    return r


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="工程数据库云端备份(压缩)工具")
    ap.add_argument("--dry-run", action="store_true", help="只压缩, 不联网不上传")
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--outdir", default=str(DEFAULT_OUTDIR))
    ap.add_argument("--reportdir", default=str(DEFAULT_REPORTDIR))
    ap.add_argument("--host", default=DEFAULT_ECS_HOST)
    ap.add_argument("--user", default=DEFAULT_ECS_USER)
    ap.add_argument("--remote-path", default=DEFAULT_ECS_PATH)
    ap.add_argument("--force", action="store_true", help="强制重压 (忽略已有归档)")
    ap.add_argument("--date", default=None, help="覆盖日期 YYYYMMDD")
    args = ap.parse_args()

    src = Path(args.src).resolve()
    outdir = Path(args.outdir).resolve()
    reportdir = Path(args.reportdir).resolve()
    if not src.is_dir():
        die(f"真源目录不存在: {src}")
    outdir.mkdir(parents=True, exist_ok=True)
    reportdir.mkdir(parents=True, exist_ok=True)

    date = args.date or _dt.datetime.now().strftime("%Y%m%d")
    version, v_src = detect_version()
    ext, comp = pick_compressor()

    archive = outdir / f"zmax_engineering_db_{version}_{date}{ext}"
    sha_path = archive.with_suffix(archive.suffix + ".sha256")
    log(f"════════════════════════════════════════════════════════")
    log(f"📦 工程数据库云端备份")
    log(f"   真源   : {src}")
    log(f"   版本   : {version}  (来源 {v_src})")
    log(f"   归档   : {archive}")
    log(f"   压缩器 : {comp}")
    log(f"   dry-run: {args.dry_run}")
    log(f"════════════════════════════════════════════════════════")

    # ── 1) 压缩 (幂等) ──
    files = list(iter_files(src))
    src_bytes = sum(f.stat().st_size for f in files)
    reused = False
    if archive.exists() and sha_path.exists() and not args.force:
        existing = sha_path.read_text().split()[0]
        cur = sha256_file(archive)
        if cur == existing:
            reused = True
            log(f"♻️  归档已存在且校验一致, 复用(幂等): {archive.name}")
    if not reused:
        log(f"🗜️  压缩 {len(files)} 个文件 ({human(src_bytes)}) → {archive.name} …")
        build_tar(src, archive, comp)
    archive_size = archive.stat().st_size

    sha = sha256_file(archive)
    sha_path.write_text(f"{sha}  {archive.name}\n", encoding="utf-8")
    ratio_keep = archive_size / src_bytes if src_bytes else 0
    ratio_saved = (1 - ratio_keep) * 100
    compressible = "低(含大量二进制网格/STL, 已接近熵下限)" if ratio_keep > 0.5 else "中高"
    log(f"   归档大小: {human(archive_size)} · 原始 {human(src_bytes)} "
        f"· 压后 {ratio_keep*100:.2f}% (省 {ratio_saved:.2f}%)")
    log(f"   SHA-256 : {sha}")

    # ── 2) 逐文件 manifest ──
    file_recs = []
    for p in files:
        rel = str(p.relative_to(src))
        file_recs.append({
            "path": rel,
            "size": p.stat().st_size,
            "role": classify(rel),
            "sha256": sha256_file(p),
        })
    manifest = build_manifest(src, archive, sha, comp, version, date,
                              src_bytes, file_recs, compressible)
    log(f"   manifest: {manifest['manifest_path']}")

    # ── 3) 上传 + 远端回读 ──
    result = {
        "ok": False,
        "remote_path": None,
        "remote_sha256": None,
        "match": None,
        "ls_l": None,
        "sha256sum_out": None,
        "skipped_upload": False,
        "error": None,
    }
    uploaded = False
    if args.dry_run:
        log("🧪 dry-run: 跳过上传与远端回读")
        result["error"] = "dry-run: 未上传"
    else:
        pw = load_ecs_pw()
        mode = "sshpass(密码)" if pw else "免密(SSH key)"
        log(f"🔐 连接方式: {mode} · {args.user}@{args.host}")
        remote_dir = args.remote_path.rstrip("/")
        remote_file = f"{remote_dir}/{archive.name}"
        result["remote_path"] = remote_file
        try:
            # 确保远端目录存在
            mk = run_remote(pw, args.host, args.user, f"mkdir -p {remote_dir}", timeout=40)
            if mk.returncode != 0:
                raise RuntimeError(f"远端 mkdir 失败: {mk.stderr.strip()[:300]}")

            # 幂等: 远端已有且 sha 一致 → 跳过上传
            pre = run_remote(pw, args.host, args.user,
                             f"sha256sum {remote_file} 2>/dev/null | awk '{{print $1}}'",
                             timeout=40)
            remote_pre_sha = pre.stdout.strip()
            if remote_pre_sha == sha and not args.force:
                result["skipped_upload"] = True
                log(f"♻️  远端已存在且 sha 一致, 跳过上传")
            else:
                log(f"📤 上传 {archive.name} → {args.user}@{args.host}:{remote_dir}/ …")
                up = upload(pw, args.host, args.user, remote_dir, archive)
                if up.returncode != 0:
                    raise RuntimeError(f"scp 上传失败: {up.stderr.strip()[:300]}")
                uploaded = True

            # 远端回读: ls -l + sha256sum
            ev = run_remote(
                pw, args.host, args.user,
                f"cd {remote_dir} && ls -l {archive.name} && sha256sum {archive.name}",
                timeout=60,
            )
            if ev.returncode != 0:
                raise RuntimeError(f"远端回读失败: {ev.stderr.strip()[:300]}")
            out = ev.stdout.strip()
            result["ls_l"] = out
            remote_sha = ""
            for line in out.splitlines():
                if line.strip().endswith(archive.name) and len(line.split()) >= 2:
                    remote_sha = line.split()[0]
            result["remote_sha256"] = remote_sha
            result["match"] = (remote_sha == sha)
            result["ok"] = bool(remote_sha == sha)
            log(f"   ── 远端回读 ──\n{out}")
            if result["match"]:
                log(f"✅ 远端 sha256 与本地一致: {remote_sha}")
            else:
                log(f"❌ 远端 sha256 不一致! 本地 {sha} / 远端 {remote_sha}")
        except Exception as e:  # noqa
            result["error"] = f"{type(e).__name__}: {e}"
            log(f"❌ 上传/回读失败: {result['error']}")
            result["ok"] = False

    # ── 4) 报告 ──
    ok = result["ok"]
    status = ("✅ 成功" if ok else ("🧪 dry-run" if args.dry_run else "❌ 失败"))
    rpt_md = reportdir / f"cloud_backup_{date}.md"
    rpt_json = reportdir / f"cloud_backup_{date}.json"

    lines = [
        f"# 工程数据库云端备份报告 · {date}",
        "",
        f"- 状态: **{status}**",
        f"- 生成时间: {_dt.datetime.now().isoformat(timespec='seconds')}",
        f"- 版本: {version} ({v_src})",
        f"- 真源: `{src}` · {len(file_recs)} 文件 · {human(src_bytes)}",
        "",
        "## 归档",
        "",
        f"- 路径: `{archive}`",
        f"- 大小: {human(archive_size)} ({archive_size} 字节)",
        f"- SHA-256: `{sha}`",
        f"- 压缩器: {comp}",
        f"- **压缩率: 压后 {ratio_keep*100:.2f}% · 省下 {ratio_saved:.2f}% · 等效 {src_bytes/archive_size:.2f}×**",
        f"- 幂等复用: {'是' if reused else '否(本次重压)'}",
        f"- manifest: `{manifest['manifest_path']}`",
        f"- sha256 文件: `{sha_path}`",
        "",
        "## 云端",
        "",
        f"- 目标: `{args.user}@{args.host}:{args.remote_path}`",
    ]
    if args.dry_run:
        lines += ["- ⚠️ **dry-run: 未上传, 无远端回读证据**", ""]
    else:
        lines += [
            f"- 远端路径: `{result['remote_path']}`",
            f"- 本地 sha256 : `{sha}`",
            f"- 远端 sha256 : `{result['remote_sha256']}`",
            f"- 回读一致: **{'✅ 一致' if result['match'] else '❌ 不一致/未取到'}**",
            f"- 跳过上传(远端已存在): {'是' if result['skipped_upload'] else '否'}",
            f"- 错误: {result['error'] or '无'}",
            "",
            "### 远端回读原文 (`ls -l` + `sha256sum`)",
            "",
            "```",
            result["ls_l"] or "(无 — 未取得)",
            "```",
            "",
        ]
    lines += [
        "## 逐文件 SHA-256",
        "",
        "| 相对路径 | 大小 | 说明 | SHA-256 |",
        "|---|---:|---|---|",
    ]
    for f in file_recs:
        lines.append(f"| `{f['path']}` | {human(f['size'])} | {f['role']} | `{f['sha256']}` |")
    lines.append("")
    rpt_md.write_text("\n".join(lines), encoding="utf-8")

    payload = {
        "status": status,
        "ok": ok,
        "date": date,
        "version": version,
        "version_source": v_src,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "src_dir": str(src),
        "file_count": len(file_recs),
        "source_bytes": src_bytes,
        "archive_path": str(archive),
        "archive_size": archive_size,
        "archive_sha256": sha,
        "compressor": comp,
        "compression": {
            "ratio_kept_pct": round(ratio_keep * 100, 2),
            "saved_pct": round(ratio_saved, 2),
            "ratio_x": round(src_bytes / archive_size, 3) if archive_size else 0,
        },
        "manifest_path": str(manifest["manifest_path"]),
        "sha256_file": str(sha_path),
        "reused": reused,
        "remote": {
            "host": args.host,
            "user": args.user,
            "path": args.remote_path,
            "remote_file": result["remote_path"],
            "remote_sha256": result["remote_sha256"],
            "match": result["match"],
            "skipped_upload": result["skipped_upload"],
            "ls_l": result["ls_l"],
            "error": result["error"],
            "uploaded_now": uploaded,
        },
        "git_note": (
            "小于 5MB 可入 git; 否则按大文件规矩不入库"
            + (" ; 本包 " + human(archive_size) + (" < 5MB 可入库" if archive_size < GITIGNORE_HINT_MB * 1024 * 1024 else " > 5MB 不入库"))
        ),
        "files": file_recs,
    }
    rpt_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"📄 报告: {rpt_md}")
    log(f"📄 JSON : {rpt_json}")

    # 机器可读收尾 (供 shell 抓取)
    log("⇢BACKUP_RESULT⇠ " + json.dumps({
        "ok": ok,
        "archive": str(archive),
        "size": archive_size,
        "sha256": sha,
        "ratio_kept_pct": round(ratio_keep * 100, 2),
        "remote_file": result["remote_path"],
        "remote_sha256": result["remote_sha256"],
        "report_md": str(rpt_md),
        "report_json": str(rpt_json),
        "manifest": str(manifest["manifest_path"]),
        "dry_run": args.dry_run,
    }, ensure_ascii=False))

    sys.exit(0 if (ok or args.dry_run) else 3)


if __name__ == "__main__":
    main()
