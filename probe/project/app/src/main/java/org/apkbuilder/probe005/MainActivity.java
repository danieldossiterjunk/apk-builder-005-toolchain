package org.apkbuilder.probe005;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.TypedValue;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * One screen: run the tests (all, or one at a time), watch progress, then save the JSON report with Android's
 * document picker or copy it. The report is also kept in this app's private storage until the next run.
 */
public final class MainActivity extends Activity {
    private static final int RC_SAVE = 1;
    private static final long STACK = 128L * 1024 * 1024;   // the Kotlin compiler recurses deeply

    private static volatile boolean running;
    private static final StringBuilder LOG = new StringBuilder();
    private static volatile String lastReport;

    private final Handler main = new Handler(Looper.getMainLooper());
    private TextView logView, summary;
    private final List<Button> runButtons = new ArrayList<>();
    private Button save, copy;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        int pad = dp(12);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("APK Builder 005 feasibility probe " + Probe.VERSION);
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 20);
        root.addView(title);
        TextView intro = new TextView(this);
        intro.setText("Disposable test app. It tests the Compose compiler plugin (P1), D8 (P2) and AAPT2 (P3) on this phone, "
                + "using only files inside this app. It changes nothing else. Run all three, then save the report.");
        intro.setPadding(0, dp(4), 0, dp(8));
        root.addView(intro);

        LinearLayout row1 = row(root), row2 = row(root);
        runButtons.add(button(row1, "Run all", new View.OnClickListener() { @Override public void onClick(View v) { start(true, true, true); } }));
        runButtons.add(button(row1, "P1 Compose", new View.OnClickListener() { @Override public void onClick(View v) { start(true, false, false); } }));
        runButtons.add(button(row2, "P2 D8", new View.OnClickListener() { @Override public void onClick(View v) { start(false, true, false); } }));
        runButtons.add(button(row2, "P3 AAPT2", new View.OnClickListener() { @Override public void onClick(View v) { start(false, false, true); } }));
        LinearLayout row3 = row(root);
        save = button(row3, "Save report", new View.OnClickListener() { @Override public void onClick(View v) { saveReport(); } });
        copy = button(row3, "Copy report", new View.OnClickListener() { @Override public void onClick(View v) { copyReport(); } });

        summary = new TextView(this);
        summary.setPadding(0, dp(8), 0, dp(8));
        summary.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        root.addView(summary);

        ScrollView sv = new ScrollView(this);
        logView = new TextView(this);
        logView.setTypeface(Typeface.MONOSPACE);
        logView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        logView.setTextIsSelectable(true);
        sv.addView(logView);
        root.addView(sv, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));
        setContentView(root);

        if (lastReport == null) {
            File f = reportFile();
            if (f.isFile()) {
                try { lastReport = new String(Files2.read(f), StandardCharsets.UTF_8); } catch (Exception ignored) { lastReport = null; }
            }
        }
        refresh();
    }

    private LinearLayout row(LinearLayout parent) {
        LinearLayout r = new LinearLayout(this);
        r.setOrientation(LinearLayout.HORIZONTAL);
        parent.addView(r);
        return r;
    }

    private Button button(LinearLayout parent, String text, View.OnClickListener l) {
        Button b = new Button(this);
        b.setText(text);
        b.setAllCaps(false);
        b.setOnClickListener(l);
        parent.addView(b, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        return b;
    }

    private int dp(int v) { return (int) (v * getResources().getDisplayMetrics().density + 0.5f); }

    private File reportFile() { return new File(new File(getNoBackupFilesDir(), "probe"), "last-report.json"); }

    private void line(final String s) {
        String t = new SimpleDateFormat("HH:mm:ss", Locale.ROOT).format(new Date());
        synchronized (LOG) { LOG.append(t).append("  ").append(s).append('\n'); }
        main.post(new Runnable() { @Override public void run() { refresh(); } });
    }

    private void refresh() {
        synchronized (LOG) { logView.setText(LOG.toString()); }
        for (Button b : runButtons) b.setEnabled(!running);
        save.setEnabled(!running && lastReport != null);
        copy.setEnabled(!running && lastReport != null);
        summary.setText(running ? "Running ... (P1 and P2 can take several minutes; keep the screen on)" : summarise(lastReport));
    }

    @SuppressWarnings("unchecked")
    private static String summarise(String report) {
        if (report == null) return "No report yet.";
        try {
            Map<String, Object> r = (Map<String, Object>) Json.parse(report);
            StringBuilder sb = new StringBuilder("Last report:\n");
            Map<String, Object> tests = (Map<String, Object>) r.get("tests");
            for (Map.Entry<String, Object> e : tests.entrySet()) {
                Map<String, Object> t = (Map<String, Object>) e.getValue();
                int ok = 0, failed = 0;
                List<Object> checks = (List<Object>) t.get("checks");
                if (checks != null) for (Object c : checks) {
                    if ("CHECK OK".equals(((Map<String, Object>) c).get("result"))) ok++; else failed++;
                }
                sb.append(e.getKey()).append(": ").append(t.get("status")).append(", ").append(ok).append(" checks OK, ")
                        .append(failed).append(" failed\n");
            }
            sb.append("Total time ").append(((Number) r.get("total_ms")).longValue() / 1000).append(" s. Save the report and send it.");
            return sb.toString();
        } catch (Exception e) {
            return "Report present (summary unavailable: " + e.getMessage() + ")";
        }
    }

    private void start(final boolean p1, final boolean p2, final boolean p3) {
        if (running) return;
        running = true;
        synchronized (LOG) { LOG.setLength(0); }
        refresh();
        final Context app = getApplicationContext();
        new Thread(null, new Runnable() {
            @Override public void run() {
                String json;
                try {
                    Probe probe = new Probe(app, new Probe.Log() { @Override public void line(String s) { MainActivity.this.line(s); } });
                    Map<String, Object> rep = probe.runAll(p1, p2, p3);
                    json = Json.write(rep);
                } catch (Throwable t) {
                    json = Json.write(Json.map("report", "APK Builder 005 Stage 1 feasibility probe", "fatal_error", String.valueOf(t)));
                }
                try {
                    File f = reportFile();
                    Files2.write(f, json.getBytes(StandardCharsets.UTF_8));
                } catch (Exception ignored) {
                    // the report stays in memory
                }
                lastReport = json;
                running = false;
                line("Finished. Save or copy the report.");
            }
        }, "probe-tests", STACK).start();
    }

    private void saveReport() {
        if (lastReport == null) return;
        Intent i = new Intent(Intent.ACTION_CREATE_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType("application/json");
        i.putExtra(Intent.EXTRA_TITLE, "apk-builder-005-probe-report-" + new SimpleDateFormat("yyyyMMdd-HHmm", Locale.ROOT).format(new Date()) + ".json");
        try { startActivityForResult(i, RC_SAVE); }
        catch (Exception e) { Toast.makeText(this, "No document picker: " + e.getMessage(), Toast.LENGTH_LONG).show(); }
    }

    @Override
    protected void onActivityResult(int rc, int result, Intent data) {
        super.onActivityResult(rc, result, data);
        if (rc != RC_SAVE || result != RESULT_OK || data == null || data.getData() == null || lastReport == null) return;
        Uri uri = data.getData();
        try (OutputStream out = getContentResolver().openOutputStream(uri, "wt")) {
            if (out == null) throw new java.io.IOException("cannot open the chosen file");
            out.write(lastReport.getBytes(StandardCharsets.UTF_8));
            Toast.makeText(this, "Report saved", Toast.LENGTH_SHORT).show();
        } catch (Exception e) {
            Toast.makeText(this, "Not saved: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private void copyReport() {
        if (lastReport == null) return;
        ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        if (cm == null) return;
        cm.setPrimaryClip(ClipData.newPlainText("APK Builder 005 probe report", lastReport));
        Toast.makeText(this, "Report copied (" + (lastReport.length() / 1024) + " KB)", Toast.LENGTH_SHORT).show();
    }

    @Override
    protected void onResume() {
        super.onResume();
        refresh();
    }
}
