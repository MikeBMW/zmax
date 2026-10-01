#!/usr/bin/env bash
# ============================================================================
# 打包「Z-MAX 远程」(手机 APP · com.zmax.room.ctl · 全新包名版) —— 纯 CLI, 无 Gradle
#
# 为什么要有这一份: 手机上有同包名旧包/签名不一致时, 覆盖安装会报「应用未安装」。
#   本包换成 com.zmax.room.ctl + 显示名「Z-MAX 远程」⇒ 全新应用, 与旧版并存, 一定能装上。
#   页面(room.html)与手机壳逻辑跟 ZMAX-Site.apk 完全一样, 只是包名/名字不同。
#
# ★ 顺序铁律: 先 zipalign 再 apksigner; v1+v2+v3 全开
# ★ 打完自动投递 tools/web/dl/ , 并把哈希按 <!--CTL--> 标记写回 room.html
# ============================================================================
set -e
SDK=/home/ubuntu/android-sdk
BT=$SDK/build-tools/34.0.0
PLATFORM=$SDK/platforms/android-34/android.jar
SRC=/home/ubuntu/state3d_app
PROJ=$SRC/room_ctl
BUILD=$PROJ/build
OUT=$PROJ/ZMAX-Control.apk
DL=/home/ubuntu/zmax/tools/web/dl
KS=$SRC/release.keystore
cd "$PROJ"

echo "=== ① 资源/目录准备 ==="
mkdir -p src/main/res/values src/main/res/mipmap-{mdpi,hdpi,xhdpi,xxhdpi,xxxhdpi}
printf '<resources>\n  <string name="app_name">Z-MAX 远程</string>\n</resources>\n' > src/main/res/values/strings.xml
for d in mdpi hdpi xhdpi xxhdpi xxxhdpi; do
  cp -f "$SRC/app/src/main/res/mipmap-$d/ic_launcher.png" "src/main/res/mipmap-$d/ic_launcher.png"
done
echo "  图标数(需 5): $(ls src/main/res/mipmap-*/ic_launcher.png | wc -l)"

echo "=== ② aapt2 compile ==="
rm -rf "$BUILD"; mkdir -p "$BUILD/gen" "$BUILD/obj" "$BUILD/dex"
"$BT/aapt2" compile --dir src/main/res -o "$BUILD/res.zip"

echo "=== ③ aapt2 link ==="
"$BT/aapt2" link -o "$BUILD/app.apk" -I "$PLATFORM" \
  --manifest src/main/AndroidManifest.xml --java "$BUILD/gen" "$BUILD/res.zip"

echo "=== ④ javac ==="
javac -source 8 -target 8 -bootclasspath "$PLATFORM" -d "$BUILD/obj" \
  $(find src/main/java "$BUILD/gen" -name '*.java')

echo "=== ⑤ d8 ==="
"$BT/d8" --release --lib "$PLATFORM" --output "$BUILD/dex" $(find "$BUILD/obj" -name '*.class')

echo "=== ⑥ 组包 + 对齐 ==="
cp -f "$BUILD/app.apk" "$BUILD/unsigned.apk"
( cd "$BUILD/dex" && zip -q "$BUILD/unsigned.apk" classes.dex )
"$BT/zipalign" -f -p 4 "$BUILD/unsigned.apk" "$BUILD/aligned.apk"

echo "=== ⑦ 签名 v1+v2+v3 ==="
if [ -f "$OUT" ]; then cp -f "$OUT" "$BUILD/prev_ZMAX-Control.apk"; fi
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:zmax2026 --key-pass pass:zmax2026 \
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
  --min-sdk-version 24 --out "$OUT" "$BUILD/aligned.apk"
rm -f "$OUT.idsig"

echo "=== ⑧ 验收 ==="
V=$("$BT/apksigner" verify --min-sdk-version 21 --verbose "$OUT" 2>&1)
echo "$V" | grep -E "Verified using v[123]|Verifies" | sed 's/^/  /'
for s in 1 2 3; do
  echo "$V" | grep -q "Verified using v$s scheme.*: true" \
    || { echo "  ✗ v$s 校验未通过 —— 停, 不投递"; exit 1; }
done
echo "  ✓ v1 + v2 + v3 全部校验通过"
"$BT/zipalign" -c -v 4 "$OUT" >/dev/null 2>&1 && echo "  ✓ zipalign 通过" || { echo "  ✗ zipalign 失败"; exit 1; }
"$BT/aapt2" dump badging "$OUT" | grep -E "^package|^sdkVersion|^targetSdk|^application-label|^launchable" | sed 's/^/  /'
echo "  烧进包里的地址: $(unzip -p "$OUT" classes.dex | strings | grep -oE 'https?://[^"]*room[^"]*' | head -3 | tr '\n' ' ')"

echo "=== ⑨ 投递到下载目录 ==="
mkdir -p "$DL"
[ -f "$DL/ZMAX-Control.apk" ] && cp -f "$DL/ZMAX-Control.apk" "$DL/ZMAX-Control.apk.prev"
cp -f "$OUT" "$DL/ZMAX-Control.apk"
sha256sum "$OUT" "$DL/ZMAX-Control.apk" | awk '{print "  "$1"  "$2}'

echo "=== ⑩ 把哈希按 <!--CTL--> 标记写回现场页 ==="
PAGE=/home/ubuntu/zmax/tools/web/room.html
SHA=$(sha256sum "$OUT" | awk '{print $1}')
python3 - "$PAGE" "$SHA" <<'PYEOF'
import re, sys
p, sha = sys.argv[1], sys.argv[2]
s = open(p, encoding="utf-8").read()
m = re.search(r"<!--CTL-->([0-9a-f]{64})", s)
before = m.group(1) if m else "<无标记>"
s = re.sub(r"<!--CTL-->[0-9a-f]{64}", "<!--CTL-->" + sha, s, count=1)
open(p, "w", encoding="utf-8").write(s)
print("  CTL 校验串 %s… → %s…" % (before[:12], sha[:12]))
PYEOF
PAGE_SHA=$(grep -oE "<!--CTL-->[0-9a-f]{64}" "$PAGE" | head -1 | sed 's/<!--CTL-->//')
if [ "$PAGE_SHA" = "$SHA" ]; then echo "  ✓ 页面 CTL 校验串与产物一致"; else echo "  ✗ 页面 CTL(${PAGE_SHA:0:12}…) ≠ 产物(${SHA:0:12}…)"; exit 1; fi
