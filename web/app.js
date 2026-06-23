// PhoneDesk dashboard — vanilla JS, no build step.
const token = localStorage.getItem('pd_token');
const role = localStorage.getItem('pd_role');
if (!token) location.href = '/login.html';

document.getElementById('who').textContent =
  (localStorage.getItem('pd_name') || '') + (role === 'admin' ? ' · Admin' : ' · VA');
if (role === 'admin') document.getElementById('addBtn').classList.remove('hide');

function logout() {
  localStorage.clear();
  location.href = '/login.html';
}

async function authFetch(url, opts = {}) {
  opts.headers = Object.assign({ Authorization: 'Bearer ' + token }, opts.headers || {});
  const r = await fetch(url, opts);
  if (r.status === 401) { logout(); throw new Error('session expired'); }
  return r;
}

function fmtAgo(ts) {
  if (!ts) return '—';
  const s = Math.floor(Date.now() / 1000 - ts);
  if (s < 10) return 'now';
  if (s < 60) return s + 's ago';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  return Math.floor(s / 86400) + 'd ago';
}

function battHTML(d) {
  if (d.battery == null) return '<span class="muted">—</span>';
  // ⚡ = actively charging, 🔌 = plugged in but charging paused by the limit, 🪫 = on battery.
  let icon = '';
  if (d.charging === true) icon = ' ⚡';
  else if (d.charge_limit_enabled && d.battery >= d.charge_stop) icon = ' 🔌';
  const limit = d.charge_limit_enabled
    ? `<span class="muted" style="font-size:12px"> · cap ${d.charge_stop}/${d.charge_resume}</span>`
    : '';
  return `<span class="batt">${d.battery}%${icon}</span>${limit}`;
}

function rowHTML(d) {
  const online = d.online;
  const status = `<span class="dot ${online ? 'online' : 'offline'}"></span>
                  <span class="pill ${online ? 'online' : 'offline'}">${online ? 'Online' : 'Offline'}</span>`;
  const phone = [d.brand, d.model].filter(Boolean).join(' ') || '—';
  const admin = role === 'admin';
  const actions = [
    online
      ? `<button class="btn primary" onclick="connect('${d.id}')">Connect</button>`
      : `<button class="btn" disabled title="Device offline">Connect</button>`,
    admin ? `<button class="btn icon" title="Battery charge limit" onclick="showBatt('${d.id}')">🔋</button>` : '',
    admin ? `<button class="btn icon" title="Bulk profile creation" onclick="showProf('${d.id}')">👥</button>` : '',
    admin ? `<button class="btn icon" title="Logs" onclick="showLogs('${d.id}')">📋</button>` : '',
    admin ? `<button class="btn icon" title="Rename" onclick="renameDevice('${d.id}')">✎</button>` : '',
    admin ? `<button class="btn icon danger" title="Delete" onclick="deleteDevice('${d.id}')">🗑</button>` : '',
  ].join(' ');
  return `<tr>
    <td>${status}</td>
    <td><strong>${esc(d.name)}</strong></td>
    <td class="muted">${esc(phone)}</td>
    <td>${battHTML(d)}</td>
    <td class="muted">${online ? 'now' : fmtAgo(d.last_seen)}</td>
    <td style="text-align:right;white-space:nowrap">${actions}</td>
  </tr>`;
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

let _devices = [];

async function loadDevices() {
  try {
    const r = await authFetch('/api/devices');
    const list = await r.json();
    _devices = list;
    const rows = document.getElementById('rows');
    if (!list.length) {
      rows.innerHTML = `<tr><td colspan="6" class="empty">
        No devices yet.${role === 'admin' ? ' Click <b>+ Add device</b> to onboard one.' : ' Ask your admin to assign you a phone.'}
        </td></tr>`;
      return;
    }
    rows.innerHTML = list.map(rowHTML).join('');
  } catch (e) { /* handled by authFetch */ }
}

async function renameDevice(id) {
  const d = _devices.find(x => x.id === id);
  const name = prompt('New name for this phone:', d ? d.name : '');
  if (!name || !name.trim()) return;
  try {
    const r = await authFetch('/api/devices/' + id, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim() })
    });
    if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || ('error ' + r.status)); }
    loadDevices();
  } catch (e) { alert('Could not rename the phone: ' + e.message); }
}

async function deleteDevice(id) {
  const d = _devices.find(x => x.id === id);
  const name = d ? d.name : 'this phone';
  if (!confirm(`Delete "${name}"?\n\nThe owner's app forgets this phone too (frees a slot). Re-adding needs a new pairing code.`)) return;
  try {
    const r = await authFetch('/api/devices/' + id, { method: 'DELETE' });
    if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || ('error ' + r.status)); }
    loadDevices();
  } catch (e) { alert('Could not delete the phone: ' + e.message); }
}

async function addDevice() {
  try {
    const r = await authFetch('/api/pairing-codes', { method: 'POST' });
    const d = await r.json();
    document.getElementById('codeBox').textContent = d.code;
    document.getElementById('codeExp').textContent = 'Code expires in 30 minutes';
    document.getElementById('modal').classList.remove('hide');
  } catch (e) { alert('Could not create a pairing code.'); }
}
function closeModal() { document.getElementById('modal').classList.add('hide'); }

async function connect(deviceId) {
  try {
    const r = await authFetch('/api/sessions', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_id: deviceId })
    });
    if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || 'Could not start session'); }
    const s = await r.json();
    // Tell the stream page WHICH phone to open (by serial), so with multiple phones plugged into one
    // computer it jumps to the one you clicked — not just the first device in the ws-scrcpy list.
    const dev = _devices.find(x => x.id === deviceId);
    try { if (dev && dev.serial) sessionStorage.setItem('pd_target_serial', dev.serial);
          else sessionStorage.removeItem('pd_target_serial'); } catch (e) {}
    // The pd_stream cookie was set on this response; open the vendored ws-scrcpy client (tunneled).
    location.href = `/stream/`;
  } catch (e) { alert(e.message); }
}

// ---- battery charge limit (admin) ----
let _battDeviceId = null;

function showBatt(id) {
  _battDeviceId = id;
  const d = _devices.find(x => x.id === id);
  document.getElementById('battTitle').textContent = 'Battery charge limit — ' + (d ? d.name : id);
  document.getElementById('battEnabled').checked = d ? d.charge_limit_enabled !== false : true;
  document.getElementById('battStop').value = d && d.charge_stop != null ? d.charge_stop : 80;
  document.getElementById('battResume').value = d && d.charge_resume != null ? d.charge_resume : 25;
  // Agent-reported live state: shows whether limiting is actually active on the phone (firmware /
  // poll) or unavailable (e.g. phone not rooted) — so you can confirm it works on real hardware.
  const st = document.getElementById('battStatus');
  const cs = d && d.charge_status;
  if (!cs) { st.textContent = d && d.online ? 'Status: waiting for the phone to report…' : 'Status: phone offline'; st.style.color = 'var(--muted)'; }
  else {
    st.textContent = 'Status: ' + cs;
    st.style.color = /unavailable/i.test(cs) ? 'var(--amber)' : 'var(--green)';
  }
  document.getElementById('battErr').classList.add('hide');
  document.getElementById('battModal').classList.remove('hide');
}
function closeBatt() {
  _battDeviceId = null;
  document.getElementById('battModal').classList.add('hide');
}
async function saveBatt() {
  if (!_battDeviceId) return;
  const enabled = document.getElementById('battEnabled').checked;
  const stop = parseInt(document.getElementById('battStop').value, 10);
  const resume = parseInt(document.getElementById('battResume').value, 10);
  const err = document.getElementById('battErr');
  if (!(resume > 0 && resume < stop && stop <= 100)) {
    err.textContent = 'Need 0 < resume < stop ≤ 100.'; err.classList.remove('hide'); return;
  }
  const btn = document.getElementById('battSaveBtn');
  btn.disabled = true; btn.textContent = 'Saving…';
  try {
    const r = await authFetch('/api/devices/' + _battDeviceId + '/charge-policy', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled, stop, resume })
    });
    if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || ('error ' + r.status)); }
    closeBatt(); loadDevices();
  } catch (e) {
    err.textContent = 'Could not save: ' + e.message; err.classList.remove('hide');
  } finally { btn.disabled = false; btn.textContent = 'Save'; }
}

// ---- bulk profile creation (admin) ----
let _profDeviceId = null;

function showProf(id) {
  _profDeviceId = id;
  const d = _devices.find(x => x.id === id);
  document.getElementById('profTitle').textContent = 'Bulk profile creation — ' + (d ? d.name : id);
  document.getElementById('profErr').classList.add('hide');
  document.getElementById('profModal').classList.remove('hide');
}
function closeProf() {
  _profDeviceId = null;
  document.getElementById('profModal').classList.add('hide');
}
async function createProfiles() {
  if (!_profDeviceId) return;
  const count = parseInt(document.getElementById('profCount').value, 10);
  const pkg = document.getElementById('profPackage').value.trim();
  const prefix = document.getElementById('profPrefix').value.trim() || 'Profile';
  const err = document.getElementById('profErr');
  if (!(count >= 1 && count <= 50)) {
    err.textContent = 'Number of profiles must be between 1 and 50.'; err.classList.remove('hide'); return;
  }
  const btn = document.getElementById('profCreateBtn');
  btn.disabled = true; btn.textContent = 'Creating…';
  try {
    const r = await authFetch('/api/devices/' + _profDeviceId + '/create-profiles', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ count, package: pkg, name_prefix: prefix })
    });
    if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || ('error ' + r.status)); }
    btn.textContent = 'Requested ✓';
    setTimeout(() => { closeProf(); loadDevices(); }, 1200);
  } catch (e) {
    err.textContent = 'Could not create profiles: ' + e.message; err.classList.remove('hide');
    btn.disabled = false; btn.textContent = 'Create';
  }
}

// ---- live logs (admin) ----
let _logsDeviceId = null;

function showLogs(id) {
  _logsDeviceId = id;
  const d = _devices.find(x => x.id === id);
  document.getElementById('logsTitle').textContent = 'Logs — ' + (d ? d.name : id);
  document.getElementById('logsBox').textContent = 'Loading…';
  document.getElementById('logsModal').classList.remove('hide');
  refreshLogs();
}
function closeLogs() {
  _logsDeviceId = null;
  document.getElementById('logsModal').classList.add('hide');
}
async function refreshLogs() {
  const modal = document.getElementById('logsModal');
  if (!_logsDeviceId || modal.classList.contains('hide')) return;   // only poll while open
  try {
    const r = await authFetch('/api/devices/' + _logsDeviceId + '/logs');
    if (!r.ok) throw new Error('error ' + r.status);
    const data = await r.json();
    const box = document.getElementById('logsBox');
    const lines = data.logs || [];
    const stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;   // keep pinned to bottom
    box.textContent = lines.length ? lines.join('\n')
      : 'No logs yet. The phone may be offline, or the owner needs to update their PhoneDesk app to v0.2.8+.';
    if (stick) box.scrollTop = box.scrollHeight;
  } catch (e) { /* transient; next tick retries */ }
}
function copyLogs() {
  const txt = document.getElementById('logsBox').textContent || '';
  navigator.clipboard.writeText(txt).then(
    () => { const b = document.getElementById('copyLogsBtn'); b.textContent = 'Copied!'; setTimeout(() => b.textContent = 'Copy', 1200); },
    () => alert('Could not copy.'));
}

loadDevices();
setInterval(loadDevices, 5000); // live-ish refresh
setInterval(refreshLogs, 2000); // live logs while the modal is open (early-returns otherwise)
