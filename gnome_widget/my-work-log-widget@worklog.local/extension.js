// My Work Log widget — clock + workday countdown on the desktop and on the lock screen.
//
// Data: http://127.0.0.1:8765/api/widget (when my workday started + its length), refreshed every 2 minutes;
// the clock and countdown tick every second here.
//
// "Show it while the PC sleeps": the PC still locks after GNOME's Screen Blank time, but the screen stays
// on and the lock screen shows the countdown under its clock (see _setupLock).
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import Meta from 'gi://Meta';
import Soup from 'gi://Soup?version=3.0';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const API = 'http://127.0.0.1:8765/api/widget';
const BAR_W = 420;
const pad = n => String(n).padStart(2, '0');
const hms = ms => {
    const s = Math.floor(Math.abs(ms) / 1000);
    return [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60];
};
const t12 = d => `${d.getHours() % 12 || 12}:${pad(d.getMinutes())} ${d.getHours() < 12 ? 'AM' : 'PM'}`;
const dur = ms => {
    const [h, m] = hms(ms);
    return `${h}h ${pad(m)}m`;
};
const ymd = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
    'October', 'November', 'December'];

export default class MyWorkLogWidget extends Extension {
    enable() {
        this._data = null;
        this._session = new Soup.Session({timeout: 30});
        this._buildDesk();
        this._fetch();
        this._fetchId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 120, () => {
            this._fetch();
            return GLib.SOURCE_CONTINUE;
        });
        this._tickId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 1000, () => {
            this._tick();
            return GLib.SOURCE_CONTINUE;
        });
        this._setupLock();
        this._tick();
    }

    disable() {
        for (const id of [this._fetchId, this._tickId])
            if (id)
                GLib.source_remove(id);
        this._fetchId = this._tickId = 0;
        if (this._monitorsId)
            Main.layoutManager.disconnect(this._monitorsId);
        this._monitorsId = 0;
        this._endDrag(false);
        for (const [obj, id] of this._restackIds ?? [])
            obj.disconnect(id);
        this._restackIds = [];
        this._releaseLock();
        this._lockBox?.destroy();
        this._lockBox = null;
        this._desk?.destroy();
        this._desk = null;
        this._session?.abort();
        this._session = null;
        this._data = null;
    }

    // ---------------------------------------------------------------- data
    _fetch() {
        if (!this._session)
            return;
        const msg = Soup.Message.new('GET', API);
        this._session.send_and_read_async(msg, GLib.PRIORITY_DEFAULT, null, (session, res) => {
            try {
                const bytes = session.send_and_read_finish(res);
                if (msg.get_status() === 200 && this._session)
                    this._data = JSON.parse(new TextDecoder().decode(bytes.get_data()));
            } catch (e) {
                // dashboard not running — keep showing the last data (or just the clock)
            }
        });
    }

    _state(now) {
        const w = this._data;
        if (!w || !w.start)
            return null;
        const st = new Date(w.start);
        if (ymd(st) !== ymd(now))
            return null;                         // yesterday's data after midnight
        const total = Number(w.hours || 8) * 3600e3, worked = now - st, left = total - worked;
        return {st, total, worked, left, end: new Date(st.getTime() + total), hours: Number(w.hours || 8),
            startTxt: `${w.source === 'pc_on' ? 'PC on at' : 'Started at'} ${t12(st)}`};
    }

    // ---------------------------------------------------------------- desktop card
    _buildDesk() {
        const V = Clutter.Orientation.VERTICAL, H = Clutter.Orientation.HORIZONTAL;
        this._desk = new St.BoxLayout({style_class: 'mwl-desk', orientation: V, reactive: false});
        this._head = new St.Label({style_class: 'mwl-head', text: 'MY WORK LOG'});
        const row = new St.BoxLayout({style_class: 'mwl-row', orientation: H});
        const left = new St.BoxLayout({orientation: V});
        this._time = new St.Label({style_class: 'mwl-time'});
        this._date = new St.Label({style_class: 'mwl-sub'});
        left.add_child(this._time);
        left.add_child(this._date);
        const right = new St.BoxLayout({orientation: V});
        this._cd = new St.Label({style_class: 'mwl-cd', text: '--:--:--'});
        this._worked = new St.Label({style_class: 'mwl-sub'});
        right.add_child(this._cd);
        right.add_child(this._worked);
        row.add_child(left);
        row.add_child(new St.Widget({style_class: 'mwl-sep', y_expand: true}));
        row.add_child(right);
        this._track = new St.Widget({style_class: 'mwl-track', width: BAR_W});
        this._fill = new St.Widget({style_class: 'mwl-fill', width: 0});
        this._track.add_child(this._fill);
        this._desk.add_child(this._head);
        this._desk.add_child(row);
        this._desk.add_child(this._track);

        // on the desktop: just above the wallpaper and the desktop icons, below every app window
        // (GNOME re-orders this layer whenever windows change, so it is put back in place each time)
        global.window_group.add_child(this._desk);
        this._restackIds = [
            [global.display, global.display.connect('restacked', () => this._restack())],
            [global.window_group, global.window_group.connect('child-added', () => this._restack())],
        ];
        this._pos = this._readPos();
        this._desk.connect('notify::width', () => this._place());
        this._monitorsId = Main.layoutManager.connect('monitors-changed', () => this._place());
        this._setupDrag();
        this._restack();
        this._place();
    }

    _isDesktopIcons(actor) {
        if (!(actor instanceof Meta.WindowActor))
            return false;
        const w = actor.get_meta_window();
        return !!w && (w.get_gtk_application_id() === 'com.rastersoft.ding' ||
            (w.get_title() ?? '').startsWith('Desktop Icons ') || (w.get_title() ?? '').includes('@!'));
    }

    _restack() {
        const wg = global.window_group, d = this._desk;
        if (!d || d.get_parent() !== wg)
            return;
        const kids = wg.get_children();
        let anchor = Main.layoutManager._backgroundGroup;
        for (const a of kids)
            if (this._isDesktopIcons(a))
                anchor = a;                                         // the top-most desktop-icons window
        if (kids.indexOf(d) !== kids.indexOf(anchor) + 1)
            wg.set_child_above_sibling(d, anchor);
    }

    // ---------------------------------------------------------------- drag to move
    _setupDrag() {
        const d = this._desk;
        d.reactive = true;
        d.connect('button-press-event', (a, e) => {
            if (e.get_button() !== 1 || this._drag)
                return Clutter.EVENT_PROPAGATE;
            const [x, y] = e.get_coords();
            this._drag = {dx: x - d.x, dy: y - d.y, grab: global.stage.grab(d)};
            d.add_style_class_name('dragging');
            return Clutter.EVENT_STOP;
        });
        d.connect('motion-event', (a, e) => {
            if (!this._drag)
                return Clutter.EVENT_PROPAGATE;
            const [x, y] = e.get_coords();
            d.set_position(Math.round(x - this._drag.dx), Math.round(y - this._drag.dy));
            return Clutter.EVENT_STOP;
        });
        d.connect('button-release-event', () => {
            if (!this._drag)
                return Clutter.EVENT_PROPAGATE;
            this._endDrag(true);
            return Clutter.EVENT_STOP;
        });
    }

    _endDrag(save) {
        if (!this._drag)
            return;
        this._drag.grab?.dismiss();
        this._drag = null;
        this._desk?.remove_style_class_name('dragging');
        if (save) {
            const m = Main.layoutManager.primaryMonitor;
            this._pos = {x: this._desk.x - m.x, y: this._desk.y - m.y};
            this._place();                                          // keep it inside the screen …
            this._savePos();                                        // … and remember where it ended up
        }
    }

    // where I put it: saved as a point on the primary screen, kept inside the screen
    _place() {
        const lm = Main.layoutManager, m = lm.primaryMonitor;
        if (!m || !this._desk || this._drag)
            return;
        const wa = lm.getWorkAreaForMonitor(lm.primaryIndex);     // screen minus the top bar / dock
        const w = this._desk.width, h = this._desk.height;
        let x = wa.x + wa.width - w - 36, y = wa.y + 28;              // first time: top right
        if (this._pos) {
            x = m.x + this._pos.x;
            y = m.y + this._pos.y;
        }
        x = Math.max(wa.x, Math.min(x, wa.x + wa.width - w));
        y = Math.max(wa.y, Math.min(y, wa.y + wa.height - h));
        this._desk.set_position(Math.round(x), Math.round(y));
    }

    _posPath() {
        return GLib.build_filenamev([GLib.get_user_config_dir(), 'my-work-log-widget.json']);
    }

    _readPos() {
        try {
            const [ok, bytes] = GLib.file_get_contents(this._posPath());
            const p = ok && JSON.parse(new TextDecoder().decode(bytes));
            return p && Number.isFinite(p.x) && Number.isFinite(p.y) ? {x: p.x, y: p.y} : null;
        } catch (e) {
            return null;
        }
    }

    _savePos() {
        const m = Main.layoutManager.primaryMonitor;
        this._pos = {x: Math.round(this._desk.x - m.x), y: Math.round(this._desk.y - m.y)};
        try {
            GLib.file_set_contents(this._posPath(), JSON.stringify(this._pos));
        } catch (e) {}
    }

    // ---------------------------------------------------------------- lock screen
    _lockClock() {
        return Main.screenShield?._dialog?._clock ?? null;     // UnlockDialogClock (time / date / hint)
    }

    _ensureLockBox() {
        const clock = this._lockClock();
        if (!clock) {
            this._lockBox = null;
            return null;
        }
        if (this._lockBox && this._lockBox.get_parent() === clock)
            return this._lockBox;
        const box = new St.BoxLayout({style_class: 'mwl-lock', orientation: Clutter.Orientation.VERTICAL,
            x_align: Clutter.ActorAlign.CENTER});
        box._cd = new St.Label({style_class: 'mwl-lock-cd', x_align: Clutter.ActorAlign.CENTER});
        box._sub = new St.Label({style_class: 'mwl-lock-sub', x_align: Clutter.ActorAlign.CENTER});
        box.add_child(box._cd);
        box.add_child(box._sub);
        if (clock._date)
            clock.insert_child_above(box, clock._date);
        else
            clock.add_child(box);
        box.connect('destroy', () => {
            if (this._lockBox === box)
                this._lockBox = null;
        });
        this._lockBox = box;
        return box;
    }

    // ---------------------------------------------------------------- every second
    _tick() {
        if (!this._desk)
            return;
        this._checkIdle();
        this._restack();                                            // safety net, normally already in place
        const now = new Date();
        const h = now.getHours();
        this._time.text = `${h % 12 || 12}:${pad(now.getMinutes())}:${pad(now.getSeconds())} ${h < 12 ? 'AM' : 'PM'}`;
        this._date.text = `${DAYS[now.getDay()]}, ${MONTHS[now.getMonth()]} ${now.getDate()}`;
        if (now.getSeconds() === 0 && !this._state(now))
            this._fetch();                       // new day / dashboard just started

        const s = this._state(now);
        const lock = this._ensureLockBox();
        this._cd.remove_style_class_name('soon');
        this._cd.remove_style_class_name('over');
        this._fill.remove_style_class_name('over');
        if (!s) {
            this._head.text = 'MY WORK LOG · WORKDAY STARTS WITH MY FIRST ACTIVITY';
            this._cd.text = '--:--:--';
            this._worked.text = this._data ? '' : 'Dashboard not running';
            this._fill.width = 0;
            if (lock) {
                lock._cd.text = '';
                lock._sub.text = '';
            }
            return;
        }
        const [a, b, c] = hms(s.left);
        const clock = `${pad(a)}h ${pad(b)}m ${pad(c)}s`;
        if (s.left > 0) {
            this._head.text = `WORKDAY COUNTDOWN · ${s.startTxt.toUpperCase()} · ENDS ${t12(s.end)}`;
            this._cd.text = clock;
            if (s.left < 30 * 60e3)
                this._cd.add_style_class_name('soon');
            this._worked.text = `Worked ${dur(s.worked)} of ${s.hours}h`;
        } else {
            this._head.text = `EXTRA TIME · ${s.hours}H COMPLETED AT ${t12(s.end)}`;
            this._cd.text = `+${clock}`;
            this._cd.add_style_class_name('over');
            this._fill.add_style_class_name('over');
            this._worked.text = `Worked ${dur(s.worked)} · Extra ${dur(-s.left)}`;
        }
        this._fill.width = Math.round(BAR_W * Math.min(1, Math.max(0, s.worked / s.total)));
        if (lock) {
            lock._cd.text = s.left > 0 ? `Workday · ${clock} left` : `Extra time · +${clock}`;
            lock._sub.text = s.left > 0
                ? `${s.startTxt} · ends ${t12(s.end)} · worked ${dur(s.worked)} of ${s.hours}h`
                : `${s.hours}h done at ${t12(s.end)} · worked ${dur(s.worked)}`;
        }
    }

    // ---------------------------------------------------------------- keep the lock screen visible
    // GNOME fades the lock screen to black and switches the display off. While the PC is LOCKED this widget
    // asks the session to stay awake (an idle inhibitor, like a video player; GNOME drops it by itself if the
    // shell stops) and keeps the lock screen lit, so the clock + countdown stay visible. To get there without
    // a black screen, it locks the PC itself 10 s before GNOME's "Screen Blank" time would. While unlocked
    // nothing is held, so GNOME's own idle lock stays as the backup. No GNOME setting is changed.
    _setupLock() {
        this._sessionSettings = new Gio.Settings({schema_id: 'org.gnome.desktop.session'});
        this._saver = new Gio.Settings({schema_id: 'org.gnome.desktop.screensaver'});
        const shield = Main.screenShield;
        this._lightIds = [shield._shortLightbox, shield._longLightbox].filter(Boolean).map(lb =>
            [lb, lb.connect('notify::active', () => {
                if (!lb.active)
                    return;
                GLib.timeout_add(GLib.PRIORITY_DEFAULT, 150, () => {   // "locked" is set just after the fade
                    if (lb.active && shield.locked)
                        lb.lightOff();
                    return GLib.SOURCE_REMOVE;
                });
            })]);
    }

    _checkIdle() {
        const locked = Main.screenShield.locked;
        if (locked && !this._cookie && !this._inhibiting && Date.now() - (this._inhibitFailed ?? 0) > 60e3)
            this._inhibit();
        else if (!locked && this._cookie)
            this._releaseInhibit();
        if (locked || !this._saver.get_boolean('lock-enabled'))
            return;
        const delay = this._sessionSettings.get_uint('idle-delay');     // Settings → Power → Screen Blank (0 = Never)
        if (!delay)
            return;
        const idle = global.backend.get_core_idle_monitor().get_idletime();
        if (idle < Math.max(30, delay - 10) * 1000) {
            this._lockedThisIdle = false;
            return;
        }
        if (!this._lockedThisIdle) {
            this._lockedThisIdle = true;
            this._inhibit();
            Main.screenShield.lock(true);
        }
    }

    _inhibit() {
        this._inhibiting = true;
        Gio.DBus.session.call('org.gnome.SessionManager', '/org/gnome/SessionManager', 'org.gnome.SessionManager',
            'Inhibit', new GLib.Variant('(susu)', ['my-work-log-widget', 0, 'Showing the workday countdown', 8]),
            new GLib.VariantType('(u)'), Gio.DBusCallFlags.NONE, -1, null, (conn, res) => {
                this._inhibiting = false;
                try {
                    const [cookie] = conn.call_finish(res).deepUnpack();
                    if (this._desk && !this._cookie)
                        this._cookie = cookie;
                    else
                        this._uninhibit(cookie);
                } catch (e) {
                    this._inhibitFailed = Date.now();               // retry in a minute, not every second
                    logError(e, 'My Work Log widget: could not keep the screen on');
                }
            });
    }

    _uninhibit(cookie) {
        Gio.DBus.session.call('org.gnome.SessionManager', '/org/gnome/SessionManager', 'org.gnome.SessionManager',
            'Uninhibit', new GLib.Variant('(u)', [cookie]), null, Gio.DBusCallFlags.NONE, -1, null, null);
    }

    _releaseInhibit() {
        if (this._cookie)
            this._uninhibit(this._cookie);
        this._cookie = 0;
    }

    _releaseLock() {
        this._releaseInhibit();
        for (const [lb, id] of this._lightIds ?? [])
            lb.disconnect(id);
        this._lightIds = [];
    }
}
