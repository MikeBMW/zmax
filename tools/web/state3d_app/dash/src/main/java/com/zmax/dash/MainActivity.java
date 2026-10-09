package com.zmax.dash;

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
 * 📊 Z-MAX 数据大屏 (2026-10-10) —— 「产品大屏」链的手机入口。
 *
 * 与 Z-MAX 现场(com.zmax.room)/其它 Z-MAX APK **同一个签名 keystore, 但包名不同** ⇒ 可并存, 不用先卸载。
 *
 * 内容: 加载 tools/web/unified_app.html —— 版本 / GPU / 数据资产 / 模型 / 场景 / 远程端点 / 同源判定,
 *       数据时间与帧龄置顶; 关键数字点一下即复制。
 *
 * 地址口径(公网优先 → 局域网 → 离线兜底):
 *   ① http://10.163.146.78:8799/unified_app.html  —— 工位机 dashboard_server(只读静态, 与在役 8791 互不影响)。
 *   ② file:///android_asset/unified_app.html       —— 打进包里的离线副本(页内含真实数据快照, 无网也能看)。
 * 主框架加载失败会自动试下一个候选; 长按屏幕可手改地址并记住。
 */
public class MainActivity extends Activity {

    /** 候选地址: 工位机数据服务 → 包内离线副本。按顺序试, 第一个能打开的就用。 */
    private static final String[] CANDIDATES = {
            "http://10.163.146.78:8799/unified_app.html",     // 工位机 dashboard_server
            "file:///android_asset/unified_app.html",         // 离线兜底(包内快照)
    };
    private static final String DEFAULT_URL = CANDIDATES[0];
    private static final String VER = "1.0";                 // 换版本 ⇒ 覆盖旧手机里存的老地址

    private WebView webView;
    private SharedPreferences sp;
    private int candIdx = -1;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        sp = getSharedPreferences("zmax_dash", Context.MODE_PRIVATE);
        CookieManager.getInstance().setAcceptCookie(true);

        webView = new WebView(this);
        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(true);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setAllowFileAccess(true);                              // 读 file:///android_asset 离线副本
        s.setAllowFileAccessFromFileURLs(true);                  // 离线副本里 fetch('./dashboard.json') 兜底

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                if (req != null && req.isForMainFrame()) {
                    if (!nextCandidate()) {
                        Toast.makeText(MainActivity.this,
                                "打不开 " + req.getUrl() + "\n" + err.getDescription()
                                        + "\n(长按屏幕可改地址)", Toast.LENGTH_LONG).show();
                    }
                }
            }

            @Override
            public void onReceivedSslError(WebView v, SslErrorHandler h, SslError e) {
                h.proceed();
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                sp.edit().putString("url", url).apply();
                Toast.makeText(MainActivity.this,
                        url.startsWith("file:") ? "已打开离线数据大屏" : "已连上工位机数据大屏",
                        Toast.LENGTH_SHORT).show();
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onConsoleMessage(ConsoleMessage m) {
                return true;
            }
        });

        webView.setOnLongClickListener(new View.OnLongClickListener() {
            @Override
            public boolean onLongClick(View v) {
                askUrl();
                return true;
            }
        });

        setContentView(webView);

        String saved = sp.getString("url", DEFAULT_URL);
        if (!VER.equals(sp.getString("v", ""))) {
            saved = DEFAULT_URL;
            sp.edit().putString("v", VER).putString("url", saved).apply();
        }
        for (int i = 0; i < CANDIDATES.length; i++) {
            if (CANDIDATES[i].equals(saved)) candIdx = i;
        }
        webView.loadUrl(saved);
    }

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
                .setTitle("数据大屏地址")
                .setView(e)
                .setPositiveButton("打开", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int w) {
                        String u = e.getText().toString().trim();
                        if (!u.startsWith("http") && !u.startsWith("file")) u = "http://" + u;
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
