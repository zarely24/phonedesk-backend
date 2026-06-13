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
    admin ? `<button class="btn icon" title="Logs" onclick="showLogs('${d.id}')">📋</button>` : '',
    admin ? `<button class="btn icon" title="Rename" onclick="renameDevice('${d.id}')">✎</button>` : '',
    admin ? `<button class="btn icon danger" title="Delete" onclick="deleteDevice('${d.id}')">🗑</button>` : '',
  ].join(' ');
  return `<tr>
    <td>${status}</td>
    <td><strong>${esc(d.name)}</strong></td>
    <td class="muted">${esc(phone)}</td>
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
      rows.innerHTML = `<tr><td colspan="5" class="empty">
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
