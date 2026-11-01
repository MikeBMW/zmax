# -*- coding: utf-8 -*-
# 备份: 主控制台首页 hero 卡「右上角按钮排」7 个按钮的源码 (2026-10-15 老倪要求删除)
#
# 老倪原话: 「主控制台, 右上角的 按钮 smolvla_lew, 升级等, 就保留一个分享功能, 其余按钮都删掉
#            (如果功能还有用, 则备份一下)」
#
# 保留:  📱 分享 (self._show_share_qr) —— 仍在 hero 行右侧 (靠 row.addStretch())
# 删除:  下列 7 个 (逐字备份, 含字体/配色/工具提示/接线)
#
# 删前逐个核过"是否还有别的入口", 结论: 一个都没丢能力 ——
#   ① ● smolvla_lew          → https://github.com/MikeBMW/lerobot-smolvla-lew.git
#        原是唯一入口 ⇒ 已改挂菜单「关于(&A) → 🧪 GUI 工程仓库 (smolvla_lew)」
#   ② 🔄 同步到GitHub         → self._sync_to_github()   已有菜单「📤 上传修改 (推送到 GitHub)」(_menu_sync_to_github)
#   ③ ⬆ 升级                 → module_clicked.emit("check_updates")  已有菜单「关于(&A) → 🔄 检查更新」(13734)
#   ④ 🌐 Z-MAX               → https://datadrive.world   已有首页「产品大屏/website」卡 + CICD 页 datadrive.world/cicd.html
#   ⑤ 📦 版本同步            → emit("version")           已有首页「版本同步」卡 + 页表条目
#   ⑥ 📋 解决方案v1.0.4      → self._open_spec_doc()     已有菜单「文档 → L2 · 方案层文档 → 📋 解决方案 MD (v1.0.6)」(更新)
#   ⑦ 📊 PPT汇报             → docs/BRAND-品牌注册材料.pptx  已有菜单「文档 → 品牌 · 竞品参考 → 🏷 品牌注册材料 PPT」
#
# 恢复方法: 取下面 HERO_BUTTONS_SOURCE 的片段, 贴回 studio.py 的 _hero() 中
#           `row.addStretch()` 之后、`layout.addLayout(row)` 之前 (即分享按钮之前), 保持原缩进即可。
# 相关工作函数仍在 studio.py 里没删: _sync_to_github / _open_spec_doc / _show_share_qr / open_ppt_with_libreoffice。
#
# 生成时间: 2026-10-15 10:09:37  ·  源文件: tools/gui/studio.py 第 2286~2343 行

HERO_BUTTONS_SOURCE = r"""
        b = QPushButton("● smolvla_lew")  # 改为按钮，点击打开 GitHub 仓库
        b.setFont(QFont("Arial", 12, QFont.Bold))
        b.setStyleSheet(f"background:{SYS12_COLOR}; color:white; border-radius:10px; padding:4px 12px; margin:0; cursor:pointer;")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/MikeBMW/lerobot-smolvla-lew.git")))  # 打开GitHub链接
        row.addWidget(b)

        # 同步按钮：将本地GUI代码推送到GitHub  # 新增同步按钮
        sync_btn = QPushButton("🔄 同步到GitHub")  # 新增同步按钮
        sync_btn.setFont(QFont("Arial", 12, QFont.Bold))
        sync_btn.setStyleSheet(f"background:{C_GREEN}; color:white; border-radius:10px; padding:4px 12px; margin:0; cursor:pointer;")
        sync_btn.setCursor(Qt.PointingHandCursor)
        sync_btn.clicked.connect(self._sync_to_github)  # 调用同步方法
        row.addWidget(sync_btn)  # 新增同步按钮

        # 升级按钮
        upg_btn = QPushButton("⬆ 升级")
        upg_btn.setFont(QFont("Arial", 12, QFont.Bold))
        upg_btn.setStyleSheet(f"background:#d29922; color:white; border-radius:10px; padding:4px 12px; margin:0; cursor:pointer;")
        upg_btn.setCursor(Qt.PointingHandCursor)
        upg_btn.clicked.connect(lambda: self.module_clicked.emit("check_updates"))
        row.addWidget(upg_btn)

        # 官网按钮
        web_btn = QPushButton("🌐 Z-MAX")
        web_btn.setFont(QFont("Arial", 12, QFont.Bold))
        web_btn.setStyleSheet(f"background:{C_CYAN}; color:white; border-radius:10px; padding:4px 12px; margin:0; cursor:pointer;")
        web_btn.setCursor(Qt.PointingHandCursor)
        web_btn.setToolTip("datadrive.world")
        web_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://datadrive.world")))
        row.addWidget(web_btn)

        # ====== 版本同步按钮（快速跳转到版本管理页面） ======
        ver_btn = QPushButton("📦 版本同步")
        ver_btn.setFont(QFont("Arial", 12, QFont.Bold))
        ver_btn.setStyleSheet(f"background:{C_ORANGE}; color:white; border-radius:10px; padding:4px 12px; margin:0; cursor:pointer;")
        ver_btn.setCursor(Qt.PointingHandCursor)
        ver_btn.setToolTip("检查 LeRobot 上游更新 · 安全同步 · 版本管理")
        ver_btn.clicked.connect(lambda: self.module_clicked.emit("version"))
        row.addWidget(ver_btn)

        # ====== 新增：解决方案文档按钮（保留Markdown按钮） ======
        doc_btn = QPushButton("📋 解决方案v1.0.4")
        doc_btn.setFont(QFont("Arial", 12, QFont.Bold))
        doc_btn.setStyleSheet(f"background:{C_ORANGE}; color:white; border-radius:10px; padding:4px 12px; margin:0; cursor:pointer;")
        doc_btn.setCursor(Qt.PointingHandCursor)
        doc_btn.setToolTip("打开产品解决方案文档 (Markdown)")
        doc_btn.clicked.connect(self._open_spec_doc)
        row.addWidget(doc_btn)

        # ====== 新增：PPT汇报按钮 ======
        doc_btn = QPushButton("📊 PPT汇报")
        doc_btn.setFont(QFont("Arial", 12, QFont.Bold))
        doc_btn.setStyleSheet(f"background:{C_ORANGE}; color:white; border-radius:10px; padding:4px 12px; margin:0; cursor:pointer;")
        doc_btn.setCursor(Qt.PointingHandCursor)
        doc_btn.setToolTip("打开管理层汇报PPT (8页幻灯片)")
        doc_btn.clicked.connect(lambda: open_ppt_with_libreoffice(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'docs', 'BRAND-品牌注册材料.pptx')))
        row.addWidget(doc_btn)
"""
