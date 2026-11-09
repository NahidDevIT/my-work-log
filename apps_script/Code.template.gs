/**
 * My Work Log — sheet script (paste into Extensions → Apps Script of your Google Sheet)
 *
 * Lets the My Work Log app on your PC write each day's summary into column B
 * and the day's working hours (total / start / end / extra) into column C.
 *  - Only requests carrying the secret TOKEN are accepted.
 *  - On an empty sheet it adds the header row: Date | Work | Total Working Hours.
 *  - Finds the row whose column A shows the date (e.g. "Monday, November 9, 2026");
 *    adds a new row at the bottom if that date is not in the sheet yet.
 *  - Never overwrites text typed by hand: a filled cell is replaced only when it still
 *    holds exactly what the app wrote last time (or when the app sends force=true).
 *  - action "email": sends the day's work report from this Google account (MailApp).
 *  - Phone view (version 4): opening the web-app URL with ?k=<view key> shows a read-only,
 *    mobile page of my days, tasks and hours — it works even when my PC is off.
 *    The view key is set by the app (action "set_view_key") and kept in Script Properties.
 */
const TOKEN = '__TOKEN__';
const SHEET_NAME = 'Sheet1';
const VERSION = 4;          // 2 = daily email, 3 = column C "Total Working Hours", 4 = phone view

function sheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  return ss.getSheetByName(SHEET_NAME) || ss.getSheets()[0];
}

function doPost(e) {
  let req;
  try { req = JSON.parse(e.postData.contents); } catch (err) { return reply({ ok: false, error: 'bad json' }); }
  if (req.token !== TOKEN) return reply({ ok: false, error: 'unauthorized' });
  if (req.action === 'email') return sendReport(req);
  if (req.action === 'set_view_key') return setViewKey(req);

  const sh = sheet_();
  const lock = LockService.getScriptLock();
  lock.waitLock(15000);
  try {
    if (!String(sh.getRange(1, 1).getDisplayValue()).trim()) {
      sh.getRange(1, 1, 1, 3).setValues([['Date', 'Work', 'Total Working Hours']]).setFontWeight('bold');
      sh.setFrozenRows(1);
    } else if (String(sh.getRange(1, 1).getDisplayValue()).trim() === 'Date' && !String(sh.getRange(1, 3).getDisplayValue()).trim()) {
      sh.getRange(1, 3).setValue('Total Working Hours').setFontWeight('bold');
    }
    const last = Math.max(sh.getLastRow(), 1);
    const values = sh.getRange(1, 1, last, 3).getDisplayValues();
    let row = -1;
    for (let i = 0; i < values.length; i++) {
      if (String(values[i][0]).trim() === String(req.formatted_date).trim()) { row = i + 1; break; }
    }
    if (req.action === 'ping') {
      return reply({ ok: true, version: VERSION, sheet: sh.getName(), rows: last,
                     view: !!PropertiesService.getScriptProperties().getProperty('VIEW_KEY') });
    }
    if (req.action === 'read') return reply({ ok: true, row: row, value: row > 0 ? values[row - 1][1] : null });

    if (row < 0) {
      sh.appendRow(req.hours ? [req.formatted_date, req.text, req.hours] : [req.formatted_date, req.text]);
      return reply({ ok: true, status: 'row_added', row: sh.getLastRow(), hours_status: req.hours ? 'written' : 'skipped' });
    }
    // Column B (work) and column C (hours) are protected separately: a filled cell is replaced only
    // when it still holds exactly what the app wrote last time (or force=true).
    const res = { ok: true, status: 'written', row: row, hours_status: 'skipped' };
    const current = String(values[row - 1][1] || '');
    if (current && current !== String(req.expected_previous || '') && !req.force) {
      res.ok = false; res.status = 'cell_not_empty'; res.current = current;
    } else if (current !== String(req.text)) {
      sh.getRange(row, 2).setValue(req.text);
    }
    if (req.hours) {
      const curH = String(values[row - 1][2] || '');
      if (curH && curH !== String(req.expected_previous_hours || '') && !req.force) {
        res.hours_status = 'cell_not_empty';
      } else {
        if (curH !== String(req.hours)) sh.getRange(row, 3).setValue(req.hours);
        res.hours_status = 'written';
      }
    }
    return reply(res);
  } finally {
    lock.releaseLock();
  }
}

function sendReport(req) {
  const to = [].concat(req.to || []).map(String).map(function (x) { return x.trim(); })
    .filter(function (x) { return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(x); });
  if (!to.length) return reply({ ok: false, error: 'no valid recipient' });
  if (MailApp.getRemainingDailyQuota() < to.length) return reply({ ok: false, error: 'daily email quota used up' });
  MailApp.sendEmail({
    to: to.join(','),
    subject: String(req.subject || 'My Work Log'),
    body: String(req.text || ''),
    htmlBody: String(req.html || ''),
    name: String(req.from_name || 'My Work Log'),
  });
  return reply({ ok: true, status: 'emailed', to: to, quota_left: MailApp.getRemainingDailyQuota() });
}

function setViewKey(req) {
  const key = String(req.key || '');
  if (key.length < 20) return reply({ ok: false, error: 'key too short' });
  PropertiesService.getScriptProperties().setProperties({
    VIEW_KEY: key, VIEW_NAME: String(req.name || ''), VIEW_ROLE: String(req.role || ''),
    VIEW_HOURS: String(req.workday_hours || 8)
  });
  return reply({ ok: true, status: 'view_key_set' });
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// ───────────────────────────── phone view (read-only) ─────────────────────────────
function doGet(e) {
  const p = PropertiesService.getScriptProperties();
  const key = p.getProperty('VIEW_KEY');
  const given = String((e && e.parameter && e.parameter.k) || '');
  if (!key || given.length !== key.length || given !== key) {
    return HtmlService.createHtmlOutput('<p style="font-family:sans-serif;padding:24px">Not found.</p>').setTitle('My Work Log');
  }
  const sh = sheet_();
  const last = sh.getLastRow();
  const rows = last > 1 ? sh.getRange(2, 1, last - 1, 3).getDisplayValues() : [];
  const tz = Session.getScriptTimeZone();
  const html = renderView(rows, {
    name: p.getProperty('VIEW_NAME') || '', role: p.getProperty('VIEW_ROLE') || '',
    hours: Number(p.getProperty('VIEW_HOURS') || 8),
    today: Utilities.formatDate(new Date(), tz, 'EEEE, MMMM d, yyyy'),
    todayIso: Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd'),
    generated: Utilities.formatDate(new Date(), tz, 'EEE d MMM, h:mm a')
  });
  return HtmlService.createHtmlOutput(html).setTitle('My Work Log')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

/** Pure HTML builder (no Google services) — rows: [[date, work, hours], …] oldest first. */
function renderView(rows, o) {
  const esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  const mins = function (txt) { const m = /(\d+)\s*h\s*(\d+)\s*m/.exec(txt || ''); return m ? (+m[1]) * 60 + (+m[2]) : 0; };
  const hm = function (m) { return Math.floor(m / 60) + 'h ' + ('0' + (m % 60)).slice(-2) + 'm'; };
  const field = function (txt, name) { const m = new RegExp(name + ':\\s*([^\\n]+)', 'i').exec(txt || ''); return m ? m[1].trim() : ''; };
  const short = function (d) { const m = /^(\w+),\s+(\w+)\s+(\d+),\s+(\d{4})$/.exec(String(d).trim());
    return m ? m[1].slice(0, 3) + ', ' + m[3] + ' ' + m[2].slice(0, 3) : String(d); };
  const tasks = function (txt) {
    const out = [];
    String(txt || '').split(/\r?\n/).forEach(function (line) {
      const t = line.trim(); if (!t) return;
      const n = /^(\d+)[.)]\s*(.*)$/.exec(t);
      if (!n && out.length) { out[out.length - 1].text += ' ' + t; return; }
      const body = n ? n[2] : t;
      let m = /^\[([^\]]+)\]\s*-->\s*([\s\S]*)$/.exec(body) || /^(.{1,60}?)\s*-->\s*([\s\S]*)$/.exec(body);
      out.push(m ? { tag: m[1].trim(), text: m[2].trim() } : { tag: '', text: body });
    });
    return out;
  };

  const MONTHS = 'january february march april may june july august september october november december'.split(' ');
  const iso = function (d) {          // "Monday, November 9, 2026" → "2026-11-09" (or '' if it is not a date)
    const m = /(\w+)\s+(\d{1,2}),\s+(\d{4})\s*$/.exec(String(d).trim()); if (!m) return '';
    const mo = MONTHS.indexOf(m[1].toLowerCase()); if (mo < 0) return '';
    return m[3] + '-' + ('0' + (mo + 1)).slice(-2) + '-' + ('0' + m[2]).slice(-2);
  };
  const days = rows.filter(function (r) {
    const d = String(r[0] || '').trim(); if (!d) return false;
    const k = iso(d); return !(k && o.todayIso && k > o.todayIso);        // skip rows prepared for future days
  }).slice(-60).reverse().map(function (r) {
    return { date: String(r[0]).trim(), tasks: tasks(r[1]), hoursTxt: String(r[2] || ''),
             total: mins(field(r[2], 'Total work hours')), extra: mins(field(r[2], 'Extra')),
             start: field(r[2], 'Start'), end: field(r[2], 'End') };
  });
  const week = days.slice(0, 7);
  const wk = { tasks: 0, total: 0, extra: 0, days: 0 };
  week.forEach(function (d) { wk.tasks += d.tasks.length; wk.total += d.total; wk.extra += d.extra; if (d.tasks.length || d.total) wk.days++; });

  let list = '';
  days.forEach(function (d, i) {
    const isToday = d.date === o.today;
    const empty = !d.tasks.length && !d.total;
    if (empty) {
      list += '<div class="day empty"><span class="dt">' + esc(short(d.date)) + '</span><span class="mut">No entry</span></div>';
      return;
    }
    const chips = (d.total ? '<span class="chip ok">' + hm(d.total) + '</span>' : '') +
                  (d.extra ? '<span class="chip warn">+' + hm(d.extra) + '</span>' : '') +
                  '<span class="chip">' + d.tasks.length + ' task' + (d.tasks.length === 1 ? '' : 's') + '</span>';
    const hrs = d.total || d.start ? '<div class="hrs">' +
        '<div><b class="okc">' + (d.total ? hm(d.total) : '—') + '</b><span>Total</span></div>' +
        '<div><b>' + esc(d.start || '—') + '</b><span>Start</span></div>' +
        '<div><b>' + esc(d.end || '—') + '</b><span>End</span></div>' +
        '<div><b class="' + (d.extra ? 'warnc' : 'mut') + '">' + hm(d.extra) + '</b><span>Extra</span></div></div>' : '';
    const items = d.tasks.map(function (t, k) {
      return '<li><span class="n">' + (k + 1) + '.</span><div>' + (t.tag ? '<span class="tag">' + esc(t.tag) + '</span>' : '') +
             '<p>' + esc(t.text) + '</p></div></li>';
    }).join('');
    list += '<details class="day"' + (i === 0 ? ' open' : '') + '><summary><span class="dt">' + esc(short(d.date)) +
            (isToday ? ' <em>Today</em>' : '') + '</span><span class="chips">' + chips + '</span></summary>' +
            hrs + '<ol>' + items + '</ol></details>';
  });
  if (!days.length) list = '<p class="mut" style="padding:24px 0;text-align:center">Nothing in the sheet yet.</p>';

  return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">' +
    '<meta name="color-scheme" content="dark light"><title>My Work Log</title><style>' +
    ':root{--bg:#0f1115;--panel:#161a22;--panel2:#1c212b;--line:#262c38;--text:#e6e8ec;--text2:#b4bbc8;--mut:#8b93a1;--ok:#10b981;--warn:#f59e0b;--sky:#38bdf8}' +
    '@media (prefers-color-scheme:light){:root{--bg:#f6f7f9;--panel:#fff;--panel2:#f3f5f8;--line:#e2e6ec;--text:#14171c;--text2:#3d4552;--mut:#667080;--ok:#059669;--warn:#b45309;--sky:#0369a1}}' +
    '*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}' +
    '.wrap{max-width:720px;margin:0 auto;padding:16px 16px 40px}header h1{margin:0;font-size:20px}header p{margin:2px 0 0;color:var(--mut);font-size:13px}' +
    '.sum{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:14px 0 16px}.sum div{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 12px}' +
    '.sum b{display:block;font-size:20px;font-variant-numeric:tabular-nums}.sum span{font-size:12px;color:var(--mut)}' +
    '.day{background:var(--panel);border:1px solid var(--line);border-radius:14px;margin-bottom:10px}.day.empty{display:flex;justify-content:space-between;padding:10px 14px;opacity:.7}' +
    'summary{list-style:none;cursor:pointer;display:flex;justify-content:space-between;align-items:center;gap:8px;padding:12px 14px;flex-wrap:wrap}summary::-webkit-details-marker{display:none}' +
    '.dt{font-weight:650}.dt em{font-style:normal;font-size:11px;color:var(--ok);margin-left:4px;text-transform:uppercase;letter-spacing:.05em}' +
    '.chips{display:flex;gap:6px;flex-wrap:wrap}.chip{font-size:12px;font-weight:600;padding:2px 8px;border-radius:99px;background:var(--panel2);color:var(--text2)}' +
    '.chip.ok{color:var(--ok)}.chip.warn{color:var(--warn)}.okc{color:var(--ok)}.warnc{color:var(--warn)}.mut{color:var(--mut)}' +
    '.hrs{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;padding:0 14px 10px}.hrs div{background:var(--panel2);border-radius:10px;padding:7px 9px}' +
    '.hrs b{display:block;font-size:14px;font-variant-numeric:tabular-nums}.hrs span{font-size:11px;color:var(--mut)}' +
    'ol{list-style:none;margin:0;padding:0 14px 12px}li{display:flex;gap:8px;padding:8px 0;border-top:1px dashed var(--line)}' +
    'li .n{color:var(--mut);font-weight:600;min-width:18px}li p{margin:2px 0 0;color:var(--text2)}.tag{font-size:12px;font-weight:650;color:var(--sky)}' +
    'footer{color:var(--mut);font-size:12px;text-align:center;margin-top:18px}@media (max-width:380px){.hrs{grid-template-columns:repeat(2,1fr)}}' +
    '</style></head><body><div class="wrap"><header><h1>' + esc(o.name || 'My Work Log') + '</h1><p>' +
    esc([o.role, 'updated ' + o.generated].filter(Boolean).join(' · ')) + '</p></header>' +
    '<div class="sum"><div><b>' + wk.tasks + '</b><span>tasks · last 7 days</span></div><div><b class="okc">' + hm(wk.total) +
    '</b><span>worked · ' + wk.days + ' day' + (wk.days === 1 ? '' : 's') + '</span></div><div><b class="' + (wk.extra ? 'warnc' : 'mut') + '">' +
    hm(wk.extra) + '</b><span>extra (over ' + (o.hours || 8) + 'h)</span></div></div>' + list +
    '<footer>Read-only · from my Google Sheet · My Work Log</footer></div></body></html>';
}
