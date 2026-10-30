#!/bin/bash
# 对比 550C 与云端 wordpress-seo 的类自动加载
CM=/home/intel/zmax_web/wp-content/plugins/wordpress-seo/vendor/composer/autoload_classmap.php
echo "=== 550C classmap 中 Indexable 条目 ==="
sudo grep -c Indexable "$CM" || true
sudo grep "Models" "$CM" | head -3

cat > /tmp/yoast_probe.php <<'PHP'
<?php
require $argv[1];
var_dump(class_exists('Yoast\WP\SEO\Models\Indexable'));
PHP

echo "=== 550C 实测 ==="
sudo -u www-data php /tmp/yoast_probe.php /home/intel/zmax_web/wp-content/plugins/wordpress-seo/vendor/autoload.php

echo "=== 云端实测 ==="
sudo ssh -i /root/.ssh/id_ed25519 -o StrictHostKeyChecking=no root@47.93.88.143 \
  'php -r "require \"/www/wwwroot/datadrive.world/wp-content/plugins/wordpress-seo/vendor/autoload.php\"; var_dump(class_exists(\"Yoast\\\\WP\\\\SEO\\\\Models\\\\Indexable\"));"'

echo "=== 版本对照 ==="
grep -m1 "Version:" /home/intel/zmax_web/wp-content/plugins/wordpress-seo/wp-seo.php 2>/dev/null
sudo ssh -i /root/.ssh/id_ed25519 -o StrictHostKeyChecking=no root@47.93.88.143 \
  'grep -m1 "Version:" /www/wwwroot/datadrive.world/wp-content/plugins/wordpress-seo/wp-seo.php; php -v | head -1'
php -v | head -1
