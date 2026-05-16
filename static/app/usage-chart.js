/**
 * Usage Stats Chart - Pure SVG chart renderer
 */

import { apiCall } from './auth.js';
import { formatNumber, showToast } from './utils.js';

let currentGranularity = 'hourly';
let currentHours = 24;

export function initUsageStats() {
    initControls();
    loadUsageStats();
}

function initControls() {
    const granBtns = document.querySelectorAll('#us-granularity .btn');
    granBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            granBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentGranularity = btn.dataset.value;
            loadHistory();
        });
    });

    const timeBtns = document.querySelectorAll('#us-timerange .btn');
    timeBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            timeBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentHours = parseInt(btn.dataset.value);
            loadHistory();
        });
    });

    const refreshBtn = document.getElementById('us-refresh-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', loadUsageStats);
    }
}

export async function loadUsageStats() {
    await Promise.all([loadSummary(), loadHistory()]);
}

async function loadSummary() {
    try {
        const data = await apiCall('GET', '/admin/usage-stats/summary');
        const reqEl = document.getElementById('us-total-requests');
        const errEl = document.getElementById('us-error-rate');
        const latEl = document.getElementById('us-avg-latency');
        const rotEl = document.getElementById('us-rotation-rate');

        if (reqEl) reqEl.textContent = formatNumber(data.request_count || 0);

        if (errEl) {
            const total = data.request_count || 0;
            const errors = data.error_count || 0;
            const rate = total > 0 ? ((errors / total) * 100).toFixed(1) : '0';
            errEl.textContent = rate + '%';
        }

        if (latEl) latEl.textContent = (data.avg_latency_ms || 0).toFixed(0) + 'ms';

        if (rotEl) {
            const rs = data.rotation_success || 0;
            const rf = data.rotation_failure || 0;
            const total = rs + rf;
            const rate = total > 0 ? ((rs / total) * 100).toFixed(0) : '0';
            rotEl.textContent = rate + '%';
        }

        renderModelTable(data.model_requests || {});
    } catch (e) {
        console.error('Load usage summary failed:', e);
    }
}

async function loadHistory() {
    const container = document.getElementById('us-chart-container');
    if (!container) return;

    container.innerHTML = '<div class="chart-loading"><i class="fas fa-spinner fa-spin"></i> Loading...</div>';

    try {
        const url = '/admin/usage-stats/history?granularity=' + currentGranularity + '&hours=' + currentHours;
        const data = await apiCall('GET', url);
        if (!data || data.length === 0) {
            container.innerHTML = '<div class="empty-chart"><i class="fas fa-chart-bar"></i><p>No data yet</p></div>';
            return;
        }
        renderChart(container, data);
    } catch (e) {
        container.innerHTML = '<div class="empty-chart"><i class="fas fa-exclamation-circle"></i><p>Load failed</p></div>';
        console.error('Load usage history failed:', e);
    }
}

function renderChart(container, data) {
    const W = 800, H = 280;
    const pad = { top: 30, right: 60, bottom: 40, left: 50 };
    const cw = W - pad.left - pad.right;
    const ch = H - pad.top - pad.bottom;

    const maxReq = Math.max(...data.map(d => d.request_count), 1);
    const maxLat = Math.max(...data.map(d => d.avg_latency_ms), 1);
    const gap = cw / data.length;
    const barW = Math.max(2, Math.min(20, gap * 0.7));
    let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" xmlns="http://www.w3.org/2000/svg">';

    // Grid lines and left Y-axis
    for (let i = 0; i <= 4; i++) {
        const y = pad.top + ch - (ch * i / 4);
        const val = Math.round(maxReq * i / 4);
        svg += '<line x1="' + pad.left + '" y1="' + y + '" x2="' + (W - pad.right) + '" y2="' + y + '" stroke="#e2e8f0" stroke-dasharray="2,2"/>';
        svg += '<text x="' + (pad.left - 8) + '" y="' + (y + 4) + '" text-anchor="end" font-size="10" fill="#64748b">' + val + '</text>';
    }

    // Bars (requests)
    data.forEach((d, i) => {
        const x = pad.left + i * gap + (gap - barW) / 2;
        const h = (d.request_count / maxReq) * ch;
        const y = pad.top + ch - h;
        svg += '<rect x="' + x + '" y="' + y + '" width="' + barW + '" height="' + h + '" fill="#3b82f6" opacity="0.7" rx="1"/>';
    });

    // Latency line
    let points = data.map((d, i) => {
        const x = pad.left + i * gap + gap / 2;
        const y = pad.top + ch - (d.avg_latency_ms / maxLat) * ch;
        return x + ',' + y;
    }).join(' ');
    svg += '<polyline points="' + points + '" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linejoin="round"/>';

    // Right Y-axis labels (latency)
    for (let i = 0; i <= 4; i++) {
        const y = pad.top + ch - (ch * i / 4);
        const val = Math.round(maxLat * i / 4);
        svg += '<text x="' + (W - pad.right + 8) + '" y="' + (y + 4) + '" font-size="10" fill="#f59e0b">' + val + 'ms</text>';
    }

    // X-axis labels
    const step = Math.max(1, Math.floor(data.length / 6));
    data.forEach((d, i) => {
        if (i % step !== 0) return;
        const x = pad.left + i * gap + gap / 2;
        const t = new Date(d.timestamp);
        const hh = t.getHours().toString().padStart(2, '0');
        const mm = t.getMinutes().toString().padStart(2, '0');
        svg += '<text x="' + x + '" y="' + (H - pad.bottom + 16) + '" text-anchor="middle" font-size="10" fill="#64748b">' + hh + ':' + mm + '</text>';
    });

    // Legend
    svg += '<rect x="' + pad.left + '" y="8" width="10" height="10" fill="#3b82f6" opacity="0.7" rx="1"/>';
    svg += '<text x="' + (pad.left + 14) + '" y="17" font-size="11" fill="#64748b">Requests</text>';
    svg += '<line x1="' + (pad.left + 70) + '" y1="13" x2="' + (pad.left + 80) + '" y2="13" stroke="#f59e0b" stroke-width="2"/>';
    svg += '<text x="' + (pad.left + 84) + '" y="17" font-size="11" fill="#64748b">Latency</text>';

    svg += '</svg>';
    container.innerHTML = svg;
}

function renderModelTable(modelRequests) {
    const container = document.getElementById('us-model-table');
    if (!container) return;

    const entries = Object.entries(modelRequests).sort((a, b) => b[1] - a[1]);
    if (entries.length === 0) {
        container.innerHTML = '<div class="empty-chart"><i class="fas fa-cube"></i><p>No model data</p></div>';
        return;
    }

    const maxCount = entries[0][1];
    let html = '<table><thead><tr><th>Model</th><th>Requests</th><th>Share</th></tr></thead><tbody>';
    const total = entries.reduce((s, e) => s + e[1], 0);

    entries.forEach(([model, count]) => {
        const pct = ((count / total) * 100).toFixed(1);
        const barPct = ((count / maxCount) * 100).toFixed(0);
        html += '<tr>';
        html += '<td>' + model + '</td>';
        html += '<td>' + count + '</td>';
        html += '<td><div style="display:flex;align-items:center;gap:0.5rem">';
        html += '<div class="model-bar-container"><div class="model-bar" style="width:' + barPct + '%"></div></div>';
        html += '<span style="font-size:0.8rem;white-space:nowrap">' + pct + '%</span>';
        html += '</div></td>';
        html += '</tr>';
    });

    html += '</tbody></table>';
    container.innerHTML = html;
}
