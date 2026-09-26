package uz.epropos.app;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.BroadcastReceiver;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.res.AssetManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.print.PrintAttributes;
import android.print.PrintDocumentAdapter;
import android.print.PrintManager;
import android.provider.MediaStore;
import android.provider.Settings;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * EproPos Android ilovasi. Dasturning o'zi (Python server + ma'lumotlar bazasi) telefonda ishlaydi,
 * shuning uchun internet yoki kompyuter shart emas. Kompyuter bilan bitta Wi-Fi'da bo'lganda
 * server o'zi kompyuterdagi EproPos bilan ma'lumot almashadi (Sozlamalar → Sinxronlash).
 */
public class MainActivity extends Activity {

    private static final int BG = Color.rgb(15, 26, 20);
    private static final int ACCENT = Color.rgb(62, 205, 86);
    private static final int MUTED = Color.rgb(169, 181, 174);
    private static final int FILE_REQUEST = 1;

    /** Ichki server porti (jarayon tirik ekan - qayta ishga tushirilmaydi) */
    private static volatile int serverPort = 0;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private WebView web;
    private LinearLayout splash;
    private TextView splashText;
    private ProgressBar spinner;
    private ValueCallback<Uri[]> fileCallback;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(BG);
        getWindow().setNavigationBarColor(BG);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(BG);
        web = createWebView();
        web.setVisibility(View.INVISIBLE);
        root.addView(web, new FrameLayout.LayoutParams(-1, -1));
        splash = createSplash();
        root.addView(splash, new FrameLayout.LayoutParams(-1, -1));
        setContentView(root);

        if (serverPort != 0) {
            openApp();
        } else {
            new Thread(this::startServer, "epropos-start").start();
        }
    }

    // ------------------------------------------------------------ ichki server

    private void startServer() {
        try {
            File data = new File(getFilesDir(), "data");
            File stat = new File(getFilesDir(), "static");
            copyStatic(stat);
            if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
            PyObject main = Python.getInstance().getModule("mobile_main");
            serverPort = main.callAttr("start", data.getAbsolutePath(), stat.getAbsolutePath(), 8100,
                    versionCode()).toInt();
            ui.post(this::openApp);
        } catch (Throwable e) {
            String msg = String.valueOf(e.getMessage());
            ui.post(() -> {
                spinner.setVisibility(View.GONE);
                splashText.setTextColor(Color.rgb(255, 138, 122));
                splashText.setText("Dasturni ishga tushirib bo'lmadi:\n" + msg);
            });
        }
    }

    /** static/ (sahifa, uslub, rasm) fayllari ilova yangilanganda qayta nusxalanadi */
    private void copyStatic(File dir) throws Exception {
        SharedPreferences prefs = getSharedPreferences("epropos", MODE_PRIVATE);
        long version = getPackageManager().getPackageInfo(getPackageName(), 0).lastUpdateTime;
        if (dir.isDirectory() && prefs.getLong("static_version", 0) == version) return;
        copyAssetDir(getAssets(), "static", dir);
        prefs.edit().putLong("static_version", version).apply();
    }

    @SuppressWarnings("deprecation")
    private long versionCode() {
        try {
            android.content.pm.PackageInfo info = getPackageManager().getPackageInfo(getPackageName(), 0);
            return Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode;
        } catch (Exception e) {
            return 0;
        }
    }

    private static void copyAssetDir(AssetManager assets, String path, File dest) throws Exception {
        String[] children = assets.list(path);
        if (children == null || children.length == 0) {  // fayl
            dest.getParentFile().mkdirs();
            try (InputStream in = assets.open(path); OutputStream out = new FileOutputStream(dest)) {
                byte[] buf = new byte[16384];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            }
            return;
        }
        dest.mkdirs();
        for (String child : children) copyAssetDir(assets, path + "/" + child, new File(dest, child));
    }

    private String base() {
        return "http://127.0.0.1:" + serverPort;
    }

    private void openApp() {
        if (web.getUrl() == null) web.loadUrl(base() + "/");
        web.setVisibility(View.VISIBLE);
        splash.setVisibility(View.GONE);
    }

    // ------------------------------------------------------------ WebView

    private WebView createWebView() {
        WebView w = new WebView(this);
        w.setBackgroundColor(BG);
        WebSettings s = w.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setTextZoom(100);
        s.setAllowFileAccess(false);
        CookieManager.getInstance().setAcceptCookie(true);
        w.addJavascriptInterface(new Bridge(), "EproPosApp");

        w.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return openExternalIfForeign(request.getUrl());
            }

            @Override
            @SuppressWarnings("deprecation")
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return openExternalIfForeign(Uri.parse(url));
            }
        });

        // Mahsulot rasmi va Excel faylini tanlash
        w.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                try {
                    startActivityForResult(params.createIntent(), FILE_REQUEST);
                } catch (Exception e) {
                    fileCallback = null;
                    return false;
                }
                return true;
            }
        });

        // Excel shablon/hisobotni yuklab olish -> "Yuklanmalar" papkasi
        w.setDownloadListener((url, userAgent, disposition, mime, length) ->
                new Thread(() -> download(url, disposition, mime)).start());
        return w;
    }

    private boolean openExternalIfForeign(Uri uri) {
        if ("127.0.0.1".equals(uri.getHost())) return false;
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (Exception ignored) {
        }
        return true;
    }

    /** Sahifadagi JavaScript uchun: window.EproPosApp */
    private class Bridge {
        @JavascriptInterface
        public void print() {
            ui.post(MainActivity.this::printPage);
        }

        @JavascriptInterface
        public boolean isApp() {
            return true;
        }

        @JavascriptInterface
        public long versionCode() {
            return MainActivity.this.versionCode();
        }

        /** Yangi versiya APK sini yuklab olib, o'rnatish oynasini ochadi */
        @JavascriptInterface
        public void installApk(String url) {
            ui.post(() -> downloadApk(url));
        }
    }

    // ------------------------------------------------------------ ilovani yangilash

    private long apkDownload = -1;
    private BroadcastReceiver apkReceiver;

    private void downloadApk(String url) {
        if (Build.VERSION.SDK_INT >= 26 && !getPackageManager().canRequestPackageInstalls()) {
            toast("EproPos'ga ilova o'rnatishga ruxsat bering, keyin \"Yangilash\" ni qayta bosing");
            try {
                startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:" + getPackageName())));
            } catch (Exception ignored) {
            }
            return;
        }
        File old = new File(getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), "EproPos.apk");
        if (old.exists()) old.delete();
        DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
        DownloadManager.Request req = new DownloadManager.Request(Uri.parse(url))
                .setTitle("EproPos yangilanishi")
                .setMimeType("application/vnd.android.package-archive")
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setDestinationInExternalFilesDir(this, Environment.DIRECTORY_DOWNLOADS, "EproPos.apk");
        apkDownload = dm.enqueue(req);
        if (apkReceiver == null) {
            apkReceiver = new BroadcastReceiver() {
                @Override
                public void onReceive(Context context, Intent intent) {
                    long id = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1);
                    if (id == apkDownload) installDownloaded(id);
                }
            };
            IntentFilter filter = new IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE);
            if (Build.VERSION.SDK_INT >= 33) registerReceiver(apkReceiver, filter, Context.RECEIVER_EXPORTED);
            else registerReceiver(apkReceiver, filter);
        }
        toast("Yangi versiya yuklab olinmoqda...");
    }

    private void installDownloaded(long id) {
        DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
        Uri uri = dm.getUriForDownloadedFile(id);
        if (uri == null) {
            toast("Yuklab bo'lmadi. Internetni tekshirib, qayta urining");
            return;
        }
        Intent install = new Intent(Intent.ACTION_VIEW);
        install.setDataAndType(uri, "application/vnd.android.package-archive");
        install.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            startActivity(install);
        } catch (Exception e) {
            toast("O'rnatish oynasini ochib bo'lmadi: " + e.getMessage());
        }
    }

    /** Chekni chop etish: Android chop etish oynasi (Bluetooth/Wi-Fi printer yoki PDF) */
    private void printPage() {
        PrintManager pm = (PrintManager) getSystemService(Context.PRINT_SERVICE);
        PrintDocumentAdapter adapter = web.createPrintDocumentAdapter("EproPos chek");
        pm.print("EproPos chek", adapter, new PrintAttributes.Builder().build());
    }

    private void download(String url, String disposition, String mime) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection();
            String cookie = CookieManager.getInstance().getCookie(url);
            if (cookie != null) c.setRequestProperty("Cookie", cookie);
            if (c.getResponseCode() != 200) throw new Exception("HTTP " + c.getResponseCode());
            String type = c.getContentType() != null ? c.getContentType() : mime;
            String name = URLUtil.guessFileName(url, c.getHeaderField("Content-Disposition"), type);
            String where;
            try (InputStream in = c.getInputStream()) {
                if (Build.VERSION.SDK_INT >= 29) {
                    ContentValues v = new ContentValues();
                    v.put(MediaStore.Downloads.DISPLAY_NAME, name);
                    v.put(MediaStore.Downloads.MIME_TYPE, type);
                    Uri item = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                    try (OutputStream out = getContentResolver().openOutputStream(item)) {
                        pipe(in, out);
                    }
                    where = "Yuklanmalar (Download) papkasiga saqlandi: " + name;
                } else {
                    File dir = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
                    File f = new File(dir, name);
                    try (OutputStream out = new FileOutputStream(f)) {
                        pipe(in, out);
                    }
                    where = "Saqlandi: " + f.getAbsolutePath();
                }
            }
            toast(where);
        } catch (Exception e) {
            toast("Yuklab bo'lmadi: " + e.getMessage());
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private static void pipe(InputStream in, OutputStream out) throws Exception {
        byte[] buf = new byte[16384];
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
    }

    private void toast(String text) {
        ui.post(() -> Toast.makeText(this, text, Toast.LENGTH_LONG).show());
    }

    // ------------------------------------------------------------ yuklanish oynasi

    private int dp(float v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics());
    }

    private LinearLayout createSplash() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        box.setBackgroundColor(BG);
        box.setPadding(dp(32), dp(32), dp(32), dp(32));

        ImageView logo = new ImageView(this);
        logo.setImageResource(R.drawable.logo);
        logo.setAdjustViewBounds(true);
        box.addView(logo, new LinearLayout.LayoutParams(dp(240), -2));

        spinner = new ProgressBar(this);
        spinner.setIndeterminateTintList(android.content.res.ColorStateList.valueOf(ACCENT));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(36), dp(36));
        lp.topMargin = dp(36);
        box.addView(spinner, lp);

        splashText = new TextView(this);
        splashText.setText("Yuklanmoqda...");
        splashText.setTextColor(MUTED);
        splashText.setTextSize(14);
        splashText.setTypeface(Typeface.DEFAULT);
        splashText.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams tp = new LinearLayout.LayoutParams(-1, -2);
        tp.topMargin = dp(14);
        box.addView(splashText, tp);
        return box;
    }

    // ------------------------------------------------------------ tizim

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == FILE_REQUEST && fileCallback != null) {
            fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data));
            fileCallback = null;
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            if (web.getVisibility() == View.VISIBLE && web.canGoBack()) {
                web.goBack();
            } else {
                moveTaskToBack(true);  // ilova yopilmaydi - sinxronlash fonda davom etadi
            }
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    protected void onDestroy() {
        if (apkReceiver != null) unregisterReceiver(apkReceiver);
        super.onDestroy();
    }

    @Override
    protected void onPause() {
        super.onPause();
        CookieManager.getInstance().flush();  // tizimga kirish saqlanib qolsin
    }
}
