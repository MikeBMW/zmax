#!/usr/bin/env bash
# 打包「Z-MAX 数据大屏」APK —— 纯 CLI, 无 Gradle (复制 build_room_apk.sh 的方法)
# 与既有 Z-MAX APK **同一个签名 keystore**, 但包名不同(com.zmax.dash) ⇒ 可与现场/其它 App 并存, 不用先卸载。
# 关键差异: ① 打进包内离线页 src/main/assets/unified_app.html (aapt2 link 需 -A) ② 包名/应用名/产物名。
set -e
SDK=/home/ubuntu/zmax/zmax_data/toolchains/android-sdk
BT=$SDK/build-tools/34.0.0
PLATFORM=$SDK/platforms/android-34/android.jar
SRC=/home/ubuntu/zmax/tools/web/state3d_app
PROJ=$SRC/dash
BUILD=$PROJ/build
OUT=$PROJ/ZMAX-Dash.apk
cd "$PROJ"

echo "=== ① 资源/目录准备 ==="
mkdir -p src/main/res/values src/main/res/mipmap-mdpi src/main/res/mipmap-hdpi \
         src/main/res/mipmap-xhdpi src/main/res/mipmap-xxhdpi src/main/res/mipmap-xxxhdpi \
         src/main/assets
printf '<resources>\n  <string name="app_name">Z-MAX 数据大屏</string>\n</resources>\n' > src/main/res/values/strings.xml
for d in mdpi hdpi xhdpi xxhdpi xxxhdpi; do
  cp -f "$SRC/app/src/main/res/mipmap-$d/ic_launcher.png" "src/main/res/mipmap-$d/ic_launcher.png"
done
ls src/main/res/mipmap-*/ic_launcher.png | wc -l | sed 's/^/  图标数(需 5): /'
ls -la src/main/assets/unified_app.html | awk '{print "  离线页: "$5"B"}'

echo "=== ② aapt2 compile ==="
rm -rf "$BUILD"; mkdir -p "$BUILD/gen" "$BUILD/obj" "$BUILD/dex"
"$BT/aapt2" compile --dir src/main/res -o "$BUILD/res.zip"

echo "=== ③ aapt2 link (带 -A assets; 不带管道, 免得吞掉错误) ==="
"$BT/aapt2" link -o "$BUILD/app.apk" -I "$PLATFORM" \
  --manifest src/main/AndroidManifest.xml --java "$BUILD/gen" \
  -A src/main/assets "$BUILD/res.zip"

echo "=== ④ javac ==="
javac -source 8 -target 8 -bootclasspath "$PLATFORM" -d "$BUILD/obj" \
  $(find src/main/java "$BUILD/gen" -name '*.java')

echo "=== ⑤ d8 ==="
"$BT/d8" --release --lib "$PLATFORM" --output "$BUILD/dex" $(find "$BUILD/obj" -name '*.class')

echo "=== ⑥ 组包 + 对齐 ==="
cp -f "$BUILD/app.apk" "$BUILD/unsigned.apk"
cd "$BUILD/dex" && zip -q "$BUILD/unsigned.apk" classes.dex && cd "$PROJ"
"$BT/zipalign" -f 4 "$BUILD/unsigned.apk" "$BUILD/aligned.apk"

echo "=== ⑦ 签名(复用 release.keystore) ==="
KS=$SRC/release.keystore
# 口令优先从环境变量取(KS_PASS), 缺省沿用仓库既有签名口令(与其它 Z-MAX APK 同 keystore)。
: "${KS_PASS:=zmax2026}"
if [ -f "$OUT" ]; then cp -f "$OUT" "$BUILD/prev_$(basename "$OUT")"; fi   # 覆盖前留档
"$BT/apksigner" sign --ks "$KS" --ks-pass "pass:$KS_PASS" --key-pass "pass:$KS_PASS" \
  --out "$OUT" "$BUILD/aligned.apk"

echo "=== ⑧ 验证 ==="
"$BT/aapt2" dump badging "$OUT" | grep -E "^package|^application-label|launchable-activity" | sed 's/^/  /'
ls -la "$OUT" | awk '{print "  产物: "$5"B"}'
unzip -l "$OUT" | grep -cE 'classes\.dex|ic_launcher' | sed 's/^/  关键文件(应≥6): /'
echo -n "  包内离线页: "; unzip -l "$OUT" | grep -o 'assets/unified_app.html' | head -1
echo -n "  烧进包里的地址: "; unzip -p "$OUT" classes.dex | strings | grep -o 'http://[0-9.]*:8799/unified_app.html' | head -1
echo -n "  sha256: "; sha256sum "$OUT" | awk '{print $1}'
