package com.zmax.room;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.content.SharedPreferences;
import android.net.http.SslError;
import android.os.Bundle;
import android.view.View;
import android.view.WindowManager;
import android.webkit.ConsoleMessage;
import android.webkit.CookieManager;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.Toast;

/**
 * 📱 Z-MAX 现场 · 人机在环 (2026-09-27 老倪; 2026-10-01 加手机远程操作)
 *
 * 「veh.5.010 状态空间的 HIL 人机在环节点, 接入我的手机 APP … 把工位总揽的所有摄像头推流到 APP,
 *   像开视频会议一样选任意视角/全看/远程操作机器人」→ 2026-10-01: 「远程控制app检查一下, 要实现手机远程操作」
 *
 * 地址口径(v1.2 起): **公网优先, 局域网兜底**
 *   ① https://datadrive.world/st/room?k=zmax-live —— 公网只读闸门上的手机控制页。
 *      这一版闸门开了 `--allow-ctl`, 只放行 /room 页 + POST /ctl/arm · /ctl/move · /ctl/gs_map;
 *      页面里所有接口都走**同源 https**(/st/...), 所以不会撞"https 页面拉 http MJPEG"的混合内容红线。
 *      口令: ?k=zmax-live 打开一次即种 zmaxk cookie, 之后同源请求都带着 ⇒ 所以必须开 CookieManager。
 *   ② http://10.163.146.78:8791/room —— 手机在产线网里时直连工位机(最快, 且不受公网影响)。
 *   主框架加载失败会自动试下一个候选; 长按屏幕可手改地址并记住。
 *
 * 安全口径不变: 公网能点的按钮只是"发起"; **真动仍要 8793 的两步确认 + 10 分钟自动失效**,
 * 未授权时 /ctl/move 会如实回"演练(未下发)", 机械臂不动。
 */
public class MainActivity extends Activity {

    /** 候选地址: 公网 → 产线网。按顺序试, 第一个能打开主框架的就用。 */
    private static final String[] CANDIDATES = {
            "https://datadrive.world/st/room?k=zmax-live",   // 公网(手机在外面就能用)
            "http://10.163.146.78:8791/room",                // 产线网内直连工位机
    };
    private static final String DEFAULT_URL = CANDIDATES[0];
    private static final String VER = "1.2";                 // 换版本 ⇒ 覆盖旧手机里存的老地址

    private WebView webView;
    private SharedPreferences sp;
    private int candIdx = -1;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);     // 现场看画面别锁屏

        sp = getSharedPreferences("zmax_room", Context.MODE_PRIVATE);
        CookieManager.getInstance().setAcceptCookie(true);                        // 让 ?k= 种下的口令跟着走

        webView = new WebView(this);
        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(true);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                if (req != null && req.isForMainFrame()) {                        // 只报主框架失败, 别为素材刷屏
                    if (!nextCandidate()) {                                       // 公网不通 ⇒ 自动退产线网
                        Toast.makeText(MainActivity.this,
                                "打不开 " + req.getUrl() + "\n" + err.getDescription()
                                        + "\n(长按屏幕可改地址)", Toast.LENGTH_LONG).show();
                    }
                }
            }

            @Override
            public void onReceivedSslError(WebView v, SslErrorHandler h, SslError e) {
                h.proceed();                                                      // 现场自签/内网证书
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                sp.edit().putString("url", url).apply();                          // 记住这次真正打开的那个
                Toast.makeText(MainActivity.this,
                        url.startsWith("https") ? "已连上公网控制页" : "已连上工位机(产线网)",
                        Toast.LENGTH_SHORT).show();
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onConsoleMessage(ConsoleMessage m) {
                return true;                                                      // 静音, 不弹窗
            }
        });

        webView.setOnLongClickListener(new View.OnLongClickListener() {           // 长按改地址
            @Override
            public boolean onLongClick(View v) {
                askUrl();
                return true;
            }
        });

        setContentView(webView);

        String saved = sp.getString("url", DEFAULT_URL);
        if (!VER.equals(sp.getString("v", ""))) {                                 // 装了新版 ⇒ 用新口径, 别被老地址卡住
            saved = DEFAULT_URL;
            sp.edit().putString("v", VER).putString("url", saved).apply();
        }
        for (int i = 0; i < CANDIDATES.length; i++) {
            if (CANDIDATES[i].equals(saved)) candIdx = i;
        }
        webView.loadUrl(saved);
    }

    /** 主框架打不开时按候选表顺着试下一个; 全试过返回 false。 */
    private boolean nextCandidate() {
        for (int i = (candIdx < 0 ? 0 : candIdx + 1); i < CANDIDATES.length; i++) {
            if (i == candIdx) continue;
            candIdx = i;
            Toast.makeText(this, "换一个地址再试…", Toast.LENGTH_SHORT).show();
            webView.loadUrl(CANDIDATES[i]);
            return true;
        }
        return false;
    }

    private void askUrl() {
        final EditText e = new EditText(this);
        e.setText(sp.getString("url", DEFAULT_URL));
        new AlertDialog.Builder(this)
                .setTitle("现场页地址")
                .setView(e)
                .setPositiveButton("打开", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int w) {
                        String u = e.getText().toString().trim();
                        if (!u.startsWith("http")) u = "http://" + u;
                        candIdx = -1;
                        sp.edit().putString("url", u).apply();
                        webView.loadUrl(u);
                    }
                })
                .setNeutralButton("恢复默认", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int w) {
                        candIdx = 0;
                        sp.edit().putString("url", DEFAULT_URL).apply();
                        webView.loadUrl(DEFAULT_URL);
                    }
                })
                .setNegativeButton("取消", null)
                .show();
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
