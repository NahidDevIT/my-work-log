/**
 * My Work Log — sheet webhook (paste into Extensions → Apps Script of your Google Sheet)
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
 */
const TOKEN = '__TOKEN__';
const SHEET_NAME = 'Sheet1';
const VERSION = 3;          // 2 = daily email, 3 = column C "Total Working Hours"

function doPost(e) {
  let req;
  try { req = JSON.parse(e.postData.contents); } catch (err) { return reply({ ok: false, error: 'bad json' }); }
  if (req.token !== TOKEN) return reply({ ok: false, error: 'unauthorized' });
  if (req.action === 'email') return sendReport(req);

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName(SHEET_NAME) || ss.getSheets()[0];
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
    if (req.action === 'ping') return reply({ ok: true, version: VERSION, sheet: sh.getName(), rows: last });
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

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
