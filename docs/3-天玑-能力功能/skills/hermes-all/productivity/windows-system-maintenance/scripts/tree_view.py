#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained collapsible HTML file tree + plain-text twin.

Usage:
    python tree_view.py <root> <out.html> <out.txt> [max_files_per_dir]

Notes:
  - $RECYCLE.BIN and System Volume Information are skipped.
  - Directory levels deeper than the first are collapsed by default so a
    200k-node drive tree still paints fast; click to expand.
  - The search box filters and highlights, auto-expanding matched ancestors.
  - Verify rendering yourself (browser file:/// + screenshot) before shipping.
"""
import os
import sys
import json
import html

root = sys.argv[1] if len(sys.argv) > 1 else '.'
out_html = sys.argv[2] if len(sys.argv) > 2 else os.path.join(root, '_文件树.html')
out_txt = sys.argv[3] if len(sys.argv) > 3 else os.path.join(root, '_文件树.txt')
MAXF = int(sys.argv[4]) if len(sys.argv) > 4 else 300
SKIP = {'$RECYCLE.BIN', 'System Volume Information'}


def build(path):
    node = {'n': os.path.basename(path) or path, 'd': []}
    total = 0
    nfiles = 0
    try:
        entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
    except OSError as ex:
        node['err'] = str(ex)
        return node, 0, 0
    files = []
    for e in entries:
        if e.name in SKIP:
            continue
        try:
            if e.is_dir():
                child, s, c = build(e.path)
                node['d'].append(child)
                total += s
                nfiles += c
            else:
                sz = e.stat().st_size
                total += sz
                nfiles += 1
                files.append((e.name, sz))
        except OSError:
            continue
    if files:
        node['f'] = [[n, s] for n, s in files[:MAXF]]
        if len(files) > MAXF:
            node['more'] = len(files) - MAXF
    node['s'] = total
    node['c'] = nfiles
    return node, total, nfiles


TPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>文件树 - __ROOT__</title>
<style>
:root{--bg:#0f1419;--fg:#d7dde5;--dim:#7d8896;--acc:#4ea1ff;--line:#232b36;--dir:#ffd479;--file:#9fb3c8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.55 "Cascadia Mono",Consolas,"Microsoft YaHei",monospace}
header{position:sticky;top:0;background:#121821;border-bottom:1px solid var(--line);padding:12px 18px;z-index:9}
h1{margin:0 0 8px;font-size:15px;font-weight:600;color:#fff}
h1 small{color:var(--dim);font-weight:400;font-size:12px;margin-left:10px}
#q{width:100%;max-width:420px;padding:6px 10px;background:#0b1016;border:1px solid var(--line);border-radius:5px;color:var(--fg);font:inherit;outline:none}
#q:focus{border-color:var(--acc)}
#wrap{padding:10px 18px 60px}
ul{list-style:none;margin:0;padding-left:16px;border-left:1px dashed #1c2530}
#wrap>ul{border-left:none;padding-left:0}
li{margin:1px 0}
.row{display:flex;align-items:center;gap:6px;padding:1px 4px;border-radius:4px;cursor:default}
.row:hover{background:#182231}
.row.dir{cursor:pointer}
.caret{width:12px;color:var(--dim);display:inline-block;text-align:center;transition:transform .1s}
.open>.row .caret{transform:rotate(90deg)}
.name.dirn{color:var(--dir)}
.name.filen{color:var(--file)}
.meta{color:var(--dim);font-size:11px;margin-left:6px}
.hide{display:none}
mark{background:#4ea1ff33;color:#fff;border-radius:2px}
</style></head><body>
<header>
  <h1>__ROOT__<small>__STAT__</small></h1>
  <input id="q" placeholder="过滤（输入文件名或目录名，实时高亮）">
</header>
<div id="wrap"></div>
<script>
const T = __JSON__;
function fmt(b){ if(b<1024)return b+' B'; if(b<1048576)return (b/1024).toFixed(0)+' KB'; if(b<1073741824)return (b/1048576).toFixed(1)+' MB'; return (b/1073741824).toFixed(2)+' GB'; }
function make(node, depth){
  const li=document.createElement('li');
  const has=(node.d&&node.d.length)||(node.f&&node.f.length);
  const row=document.createElement('div');
  row.className='row'+(node.d&&node.d.length?' dir':'');
  const car=document.createElement('span'); car.className='caret'; car.textContent=(node.d&&node.d.length)?'\u25b8':' ';
  const nm=document.createElement('span'); nm.className='name '+(node.d&&node.d.length?'dirn':'filen'); nm.textContent=node.n;
  const mt=document.createElement('span'); mt.className='meta';
  mt.textContent=(node.c? node.c+' 项 · ':'')+fmt(node.s||0);
  row.append(car,nm,mt); li.appendChild(row);
  if(!has) return li;
  const ul=document.createElement('ul');
  if(node.d) node.d.forEach(c=>ul.appendChild(make(c,depth+1)));
  if(node.f) node.f.forEach(([n,s])=>{
     const l=document.createElement('li'); const r=document.createElement('div'); r.className='row';
     const c=document.createElement('span'); c.className='caret'; c.textContent=' ';
     const a=document.createElement('span'); a.className='name filen'; a.textContent=n;
     const m=document.createElement('span'); m.className='meta'; m.textContent=fmt(s);
     r.append(c,a,m); l.appendChild(r); ul.appendChild(l); });
  if(node.more){
     const l=document.createElement('li'); const r=document.createElement('div'); r.className='row';
     const a=document.createElement('span'); a.className='meta'; a.textContent='\u2026 还有 '+node.more+' 个文件（未展开）';
     r.appendChild(a); l.appendChild(r); ul.appendChild(l); }
  li.appendChild(ul);
  if(node.d&&node.d.length) row.onclick=()=>{ li.classList.toggle('open'); ul.classList.toggle('hide'); };
  if(depth>=1) ul.classList.add('hide');   // 深层默认收起，首屏更快
  return li;
}
function render(){
  const w=document.getElementById('wrap');
  w.innerHTML='';
  const ul=document.createElement('ul');
  ul.appendChild(make(T,0));
  w.appendChild(ul);
  const first=ul.querySelector('li'); if(first) first.classList.add('open');
}
render();
document.getElementById('q').addEventListener('input',e=>{
  const v=e.target.value.trim().toLowerCase();
  document.querySelectorAll('#wrap li').forEach(li=>{
    const nm=li.querySelector('.name');
    if(!nm) return;
    if(nm.dataset.t===undefined) nm.dataset.t=nm.textContent;   // 必须缓存原名，否则清空后名字丢失
    const t=nm.dataset.t;
    const hit=v && t.toLowerCase().includes(v);
    if(hit){
      const i=t.toLowerCase().indexOf(v);
      nm.innerHTML=t.slice(0,i)+'<mark>'+t.slice(i,i+v.length)+'</mark>'+t.slice(i+v.length);
      li.classList.remove('hide');
      let p=li.parentElement;
      while(p&&p!==document.body){
        if(p.tagName==='LI'){ p.classList.remove('hide'); p.classList.add('open');
          const u=p.querySelector(':scope>ul'); if(u) u.classList.remove('hide'); }
        p=p.parentElement; }
    } else {
      nm.textContent=t;
      li.classList.toggle('hide', !!v);
    }
  });
});
</script></body></html>"""


def main():
    tree, total, count = build(root)
    print('扫描完成: %d 文件, %.2f GB' % (count, total / 1e9))
    stat = '%d 个文件 · %.2f GB · 生成于 Python' % (count, total / 1e9)
    doc = (TPL.replace('__ROOT__', html.escape(root))
              .replace('__STAT__', stat)
              .replace('__JSON__', json.dumps(tree, ensure_ascii=False)))
    with open(out_html, 'w', encoding='utf-8') as f:
        f.write(doc)
    print('HTML ->', out_html, round(os.path.getsize(out_html) / 1e6, 2), 'MB')

    with open(out_txt, 'w', encoding='utf-8') as f:
        f.write('%s  %d 个文件  %.2f GB\n\n' % (root, count, total / 1e9))
        for c in tree['d']:
            f.write('%s  [%d 项, %.2f GB]\n' % (c['n'], c['c'], c['s'] / 1e9))
            for cc in c.get('d', []):
                f.write('  |- %s  [%d 项, %.1f MB]\n' % (cc['n'], cc['c'], cc['s'] / 1e6))
            for n, s in c.get('f', [])[:20]:
                f.write('  |- %s  %.1fMB\n' % (n, s / 1e6))
            f.write('\n')
    print('TXT  ->', out_txt)


if __name__ == '__main__':
    main()
