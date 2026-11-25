/**
 * Structured Logs - REST polling, table rendering, filtering, pagination
 */

import { apiCall } from './auth.js';
import { t } from './i18n.js';
import { escapeHtml } from './utils.js';

let pollTimer = null;
let currentDirection = 'all';
let currentSearch = '';
let currentOffset = 0;
const PAGE_SIZE = 15;
const POLL_INTERVAL = 1500;
let isPaused = false;
let selectedRecordId = null;

export function initLogs() {
    initLogControls();
    loadLogs();
    startPolling();
}

function initLogControls() {
    const dirBtns = document.querySelectorAll('#log-direction .btn');
    dirBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            dirBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentDirection = btn.dataset.value;
            currentOffset = 0;
            loadLogs();
        });
    });

    const searchInput = document.getElementById('log-search');
    if (searchInput) {
        let debounce = null;
        searchInput.addEventListener('input', () => {
            clearTimeout(debounce);
            debounce = setTimeout(() => {
                currentSearch = searchInput.value.trim();
                currentOffset = 0;
                loadLogs();
            }, 300);
        });
    }

    const toggleBtn = document.getElementById('log-toggle-btn');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', togglePause);
    }

    const clearBtn = document.getElementById('log-clear-btn');
    if (clearBtn) {
        clearBtn.addEventListener('click', clearLogs);
    }

    const prevBtn = document.getElementById('log-prev-btn');
    if (prevBtn) {
        prevBtn.addEventListener('click', () => {
            if (currentOffset >= PAGE_SIZE) {
                currentOffset -= PAGE_SIZE;
                loadLogs();
            }
        });
    }

    const nextBtn = document.getElementById('log-next-btn');
    if (nextBtn) {
        nextBtn.addEventListener('click', () => {
            currentOffset += PAGE_SIZE;
            loadLogs();
        });
    }

    const detailClose = document.getElementById('log-detail-close');
    if (detailClose) {
        detailClose.addEventListener('click', closeDetail);
    }
}

function startPolling() {
    stopPolling();
    pollTimer = setInterval(() => {
        if (!isPaused && document.visibilityState === 'visible') {
            loadLogs();
        }
    }, POLL_INTERVAL);
}

function stopPolling() {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
}

function togglePause() {
    isPaused = !isPaused;
    const btn = document.getElementById('log-toggle-btn');
    if (btn) {
        const icon = btn.querySelector('i');
        if (icon) {
            icon.className = isPaused ? 'fas fa-play' : 'fas fa-pause';
        }
    }
}

async function clearLogs() {
    try {
        await apiCall('POST', '/admin/logs/clear');
        loadLogs();
    } catch (e) {
        console.error('Clear logs failed:', e);
    }
}

async function loadLogs() {
    try {
        let url = '/admin/logs?limit=' + PAGE_SIZE + '&offset=' + currentOffset;
        if (currentDirection !== 'all') {
            url += '&direction=' + currentDirection;
        }
        if (currentSearch) {
            url += '&search=' + encodeURIComponent(currentSearch);
        }

        const data = await apiCall('GET', url);
        renderTable(data.records || []);
        renderPagination(data.total || 0, data.offset || 0);
    } catch (e) {
        console.error('Load logs failed:', e);
    }
}

function renderTable(records) {
    const tbody = document.getElementById('logs-tbody');
    const empty = document.getElementById('logs-empty');
    if (!tbody) return;

    if (records.length === 0) {
        tbody.innerHTML = '';
        if (empty) empty.style.display = 'flex';
        return;
    }

    if (empty) empty.style.display = 'none';

    tbody.innerHTML = records.map(r => {
        const ts = new Date(r.ts);
        const time = ts.toLocaleTimeString();
        const dirLabel = t(r.direction === 'ingress' ? 'logs.ingress' : 'logs.egress');
        const dirClass = r.direction === 'ingress' ? 'badge-ingress' : 'badge-egress';
        const statusClass = getStatusClass(r.status);
        const latency = formatLatency(r.latency_ms, r.ttft_ms);
        const selected = r.id === selectedRecordId ? ' selected' : '';

        // 安全：r.path/r.method/r.model 等字段来自真实 HTTP 请求（攻击者可控），
        // 渲染前一律 escapeHtml 转义，防止存储型 XSS（如 path 内的 <svg onload=...>）。
        return '<tr class="log-row' + selected + '" data-id="' + escapeHtml(String(r.id ?? '')) + '">'
            + '<td>' + escapeHtml(time) + '</td>'
            + '<td><span class="badge ' + dirClass + '">' + escapeHtml(dirLabel) + '</span></td>'
            + '<td>' + escapeHtml(String(r.method ?? '')) + '</td>'
            + '<td>' + escapeHtml(truncatePath(r.path)) + '</td>'
            + '<td><span class="status-code ' + statusClass + '">' + escapeHtml(String(r.status ?? '-')) + '</span></td>'
            + '<td>' + escapeHtml(latency) + '</td>'
            + '<td>' + escapeHtml(String(r.model ?? '-')) + '</td>'
            + '</tr>';
    }).join('');

    tbody.querySelectorAll('.log-row').forEach(row => {
        row.addEventListener('click', () => {
            const id = row.dataset.id;
            selectRecord(id);
        });
    });
}

function formatDurationMs(ms) {
    if (ms == null || !Number.isFinite(ms) || ms < 0) return null;
    if (ms >= 1000) return (ms / 1000).toFixed(1) + 's';
    return Math.round(ms) + 'ms';
}

function formatLatency(latencyMs, ttftMs) {
    const totalStr = latencyMs ? (formatDurationMs(latencyMs) ?? '-') : '-';
    const ttftStr = formatDurationMs(ttftMs);
    if (ttftStr === null) return totalStr;
    return t('logs.latencyWithTtft')
        .replace('{total}', () => totalStr)
        .replace('{ttft}', () => ttftStr);
}

function getStatusClass(status) {
    if (!status) return '';
    if (status < 300) return 'status-2xx';
    if (status < 400) return 'status-3xx';
    if (status < 500) return 'status-4xx';
    return 'status-5xx';
}

function truncatePath(path) {
    if (!path) return '-';
    if (path.length > 40) return path.substring(0, 37) + '...';
    return path;
}

function renderPagination(total, offset) {
    const info = document.getElementById('log-page-info');
    if (info) {
        const start = total > 0 ? offset + 1 : 0;
        const end = Math.min(offset + PAGE_SIZE, total);
        info.textContent = start + '-' + end + ' of ' + total;
    }

    const prevBtn = document.getElementById('log-prev-btn');
    const nextBtn = document.getElementById('log-next-btn');
    if (prevBtn) prevBtn.disabled = offset === 0;
    if (nextBtn) nextBtn.disabled = offset + PAGE_SIZE >= total;
}

async function selectRecord(id) {
    selectedRecordId = id;
    const rows = document.querySelectorAll('.log-row');
    rows.forEach(r => {
        r.classList.toggle('selected', r.dataset.id === id);
    });

    try {
        const record = await apiCall('GET', '/admin/logs/' + id);
        showDetail(record);
    } catch (e) {
        console.error('Load record detail failed:', e);
    }
}

function showDetail(record) {
    const panel = document.getElementById('logs-detail');
    const json = document.getElementById('log-detail-json');
    if (panel && json) {
        json.textContent = JSON.stringify(record, null, 2);
        panel.classList.add('visible');
    }
}

function closeDetail() {
    const panel = document.getElementById('logs-detail');
    if (panel) panel.classList.remove('visible');
    selectedRecordId = null;
    const rows = document.querySelectorAll('.log-row');
    rows.forEach(r => r.classList.remove('selected'));
}

export function destroyLogs() {
    stopPolling();
}
