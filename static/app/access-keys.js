import { apiCall } from './auth.js';
import { showToast, escapeHtml, formatDate, formatNumber, copyToClipboard, showConfirm } from './utils.js';
import { t } from './i18n.js';

// 双引号属性上下文专用转义（escapeHtml 不转义 "，属性里必须再补一手）
function escapeAttr(str) {
    return escapeHtml(String(str ?? '')).replace(/"/g, '&quot;');
}

let keysData = [];
let optionsData = { accounts: [], models: [] };
let editingId = null;

const STATE_BADGE = {
    valid: 'badge-success',
    pending: 'badge-info',
    disabled: 'badge-secondary',
    expired: 'badge-warning',
    quota_exceeded: 'badge-danger',
};

const STATE_I18N = {
    valid: 'accessKeys.stateValid',
    pending: 'accessKeys.statePending',
    disabled: 'accessKeys.stateDisabled',
    expired: 'accessKeys.stateExpired',
    quota_exceeded: 'accessKeys.stateQuota',
};

function statusBadge(key) {
    const state = String(key.state || 'valid');
    const cls = STATE_BADGE[state] || 'badge-secondary';
    const label = STATE_I18N[state] ? t(STATE_I18N[state]) : state;
    return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
}

function validityText(key) {
    if (key.expires_at) return formatDate(key.expires_at);
    if (key.duration_days) {
        return t('accessKeys.pendingDays').replace('{n}', String(key.duration_days));
    }
    return t('accessKeys.never');
}

function usageText(key) {
    const used = formatNumber(Number(key.request_count || 0));
    if (key.request_limit === null || key.request_limit === undefined) {
        return `${used} / ${t('accessKeys.unlimited')}`;
    }
    return `${used} / ${formatNumber(Number(key.request_limit))}`;
}

function boundText(key) {
    const accounts = Array.isArray(key.bound_account_ids) ? key.bound_account_ids.length : 0;
    const models = Array.isArray(key.allowed_models) ? key.allowed_models.length : 0;
    const parts = [];
    parts.push(accounts ? t('accessKeys.boundAccountsN').replace('{n}', String(accounts)) : t('accessKeys.allAccounts'));
    parts.push(models ? t('accessKeys.boundModelsN').replace('{n}', String(models)) : t('accessKeys.allModels'));
    return parts.join(' · ');
}

function render() {
    const box = document.getElementById('akk-list-container');
    if (!box) return;
    if (!keysData.length) {
        box.innerHTML = `<div class="akk-empty"><i class="fas fa-id-card"></i><p>${escapeHtml(t('accessKeys.empty'))}</p></div>`;
        return;
    }
    let html = '<table><thead><tr>';
    html += `<th>${escapeHtml(t('accessKeys.name'))}</th>`
        + `<th>${escapeHtml(t('accessKeys.key'))}</th>`
        + `<th>${escapeHtml(t('accessKeys.status'))}</th>`
        + `<th>${escapeHtml(t('accessKeys.validity'))}</th>`
        + `<th>${escapeHtml(t('accessKeys.usage'))}</th>`
        + `<th>${escapeHtml(t('accessKeys.scope'))}</th>`
        + `<th>${escapeHtml(t('accessKeys.actions'))}</th>`;
    html += '</tr></thead><tbody>';
    keysData.forEach(k => {
        const idEsc = escapeAttr(k.id);
        html += '<tr>';
        html += `<td class="akk-name-cell">${escapeHtml(String(k.display_name || k.name || ''))}</td>`;
        html += `<td><code class="akk-key">${escapeHtml(String(k.key || ''))}</code>`
            + `<button class="btn btn-sm btn-outline akk-copy-btn" data-id="${idEsc}" title="${escapeAttr(t('accessKeys.copy'))}">`
            + '<i class="fas fa-copy"></i></button></td>';
        html += `<td>${statusBadge(k)}</td>`;
        html += `<td>${escapeHtml(validityText(k))}</td>`;
        html += `<td>${escapeHtml(usageText(k))}</td>`;
        html += `<td>${escapeHtml(boundText(k))}</td>`;
        html += '<td class="akk-actions">'
            + `<button class="btn btn-sm btn-outline akk-edit-btn" data-id="${idEsc}" title="${escapeAttr(t('accessKeys.edit'))}"><i class="fas fa-pen"></i></button>`
            + `<button class="btn btn-sm btn-outline akk-toggle-btn" data-id="${idEsc}">`
            + escapeHtml(k.enabled ? t('accessKeys.disable') : t('accessKeys.enable')) + '</button>'
            + `<button class="btn btn-sm btn-outline akk-reset-btn" data-id="${idEsc}">${escapeHtml(t('accessKeys.resetUsage'))}</button>`
            + `<button class="btn btn-sm btn-danger akk-del-btn" data-id="${idEsc}" title="${escapeAttr(t('accessKeys.delete'))}"><i class="fas fa-trash"></i></button>`
            + '</td></tr>';
    });
    html += '</tbody></table>';
    box.innerHTML = html;

    // data-* + addEventListener：绝不把用户填的名称拼进 inline onclick 的 JS 字符串
    box.querySelectorAll('.akk-copy-btn').forEach(b => b.addEventListener('click', () => onCopy(b.dataset.id)));
    box.querySelectorAll('.akk-edit-btn').forEach(b => b.addEventListener('click', () => openPanel(findKey(b.dataset.id))));
    box.querySelectorAll('.akk-toggle-btn').forEach(b => b.addEventListener('click', () => onToggle(b.dataset.id)));
    box.querySelectorAll('.akk-reset-btn').forEach(b => b.addEventListener('click', () => onResetUsage(b.dataset.id)));
    box.querySelectorAll('.akk-del-btn').forEach(b => b.addEventListener('click', () => onDelete(b.dataset.id)));
}

function findKey(id) {
    return keysData.find(k => String(k.id) === String(id)) || null;
}

function renderChecklist(containerId, items, checked) {
    const box = document.getElementById(containerId);
    if (!box) return;
    if (!items.length) {
        box.innerHTML = `<span class="akk-checklist-empty">${escapeHtml(t('accessKeys.noOptions'))}</span>`;
        return;
    }
    const on = new Set((checked || []).map(String));
    box.innerHTML = items.map(item => {
        const value = escapeAttr(item.value);
        const mark = on.has(String(item.value)) ? ' checked' : '';
        return `<label><input type="checkbox" value="${value}"${mark}> ${escapeHtml(String(item.label))}</label>`;
    }).join('');
}

function checklistValues(containerId) {
    const box = document.getElementById(containerId);
    if (!box) return [];
    return Array.from(box.querySelectorAll('input[type=checkbox]'))
        .filter(cb => cb.checked)
        .map(cb => cb.value);
}

function toLocalInputValue(iso) {
    // <input type="datetime-local"> 的 value 是「本地墙上时间」。后端存的是 UTC 瞬间，
    // 直接截 ISO 的前 16 个字符会把 UTC 的钟面当成本地钟面，而 readExpiresAt 又按本地
    // 解析回 UTC —— 一次「什么都没改」的保存就能把有效期整整挪掉一个时区偏移，
    // 而且每保存一次挪一次（UTC+8 越挪越早，UTC-5 越挪越晚）。
    const dt = new Date(iso);
    if (Number.isNaN(dt.getTime())) return '';
    const pad = n => String(n).padStart(2, '0');
    return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}`
        + `T${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
}

function numberInputValue(value) {
    // duration_days 后端是 float（0.5 天也合法），但 7 不该显示成 "7.0"
    const n = Number(value);
    return Number.isFinite(n) ? String(n) : '';
}

function openPanel(key) {
    editingId = key ? key.id : null;
    const set = (id, value) => { const el = document.getElementById(id); if (el) el.value = value; };
    set('akk-name', key ? (key.name || '') : '');
    set('akk-count', '1');
    set('akk-request-limit', key && key.request_limit != null ? numberInputValue(key.request_limit) : '');
    // 「有效天数」与「绝对过期时间」是互斥的两个框，而有效天数的密钥**一旦首次使用**，
    // 后端就会把算出来的 expires_at 也填上。两个框都回填的话，submitPanel 的互斥校验
    // 会把每一次保存都拦掉——改名、改额度、改绑定全都做不了，只剩停用/重置/删除。
    // 所以口径是：有 duration_days 就只显示它（绝对时间本来就是它派生出来的），
    // 保存时后端会按 activated_at 重新算回同一个 expires_at。
    const hasDuration = !!(key && key.duration_days != null);
    set('akk-duration-days', hasDuration ? numberInputValue(key.duration_days) : '');
    set('akk-expires-at', !hasDuration && key && key.expires_at ? toLocalInputValue(key.expires_at) : '');
    const countGroup = document.getElementById('akk-count');
    if (countGroup) countGroup.disabled = !!key;
    renderChecklist('akk-accounts-list',
        optionsData.accounts.map(a => ({ value: a.id, label: a.label || a.id })),
        key ? key.bound_account_ids : []);
    renderChecklist('akk-models-list',
        optionsData.models.map(m => ({ value: m, label: m })),
        key ? key.allowed_models : []);
    const panel = document.getElementById('akk-add-panel');
    if (panel) panel.style.display = 'block';
}

function closePanel() {
    editingId = null;
    const panel = document.getElementById('akk-add-panel');
    if (panel) panel.style.display = 'none';
}

function readNumber(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    const raw = String(el.value || '').trim();
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
}

function readExpiresAt() {
    const el = document.getElementById('akk-expires-at');
    const raw = el ? String(el.value || '').trim() : '';
    if (!raw) return null;
    // <input type="datetime-local"> 给的是本地时间、无时区；转成带时区的 ISO 再发给后端
    const dt = new Date(raw);
    return Number.isNaN(dt.getTime()) ? null : dt.toISOString();
}

async function submitPanel() {
    const name = (document.getElementById('akk-name')?.value || '').trim();
    const requestLimit = readNumber('akk-request-limit');
    const durationDays = readNumber('akk-duration-days');
    const expiresAt = readExpiresAt();
    if (durationDays && expiresAt) {
        showToast(t('accessKeys.validityConflict'), 'error');
        return;
    }
    const boundAccounts = checklistValues('akk-accounts-list');
    const allowedModels = checklistValues('akk-models-list');

    try {
        if (editingId !== null) {
            const clear = [];
            const body = { name, enabled: findKey(editingId)?.enabled !== false };
            if (requestLimit != null) body.request_limit = requestLimit; else clear.push('request_limit');
            if (durationDays != null) body.duration_days = durationDays; else clear.push('duration_days');
            if (expiresAt) body.expires_at = expiresAt; else clear.push('expires_at');
            if (boundAccounts.length) body.bound_account_ids = boundAccounts; else clear.push('bound_account_ids');
            if (allowedModels.length) body.allowed_models = allowedModels; else clear.push('allowed_models');
            body.clear = clear;
            await apiCall('PATCH', `/admin/access-keys/${encodeURIComponent(editingId)}`, body);
            showToast(t('accessKeys.saved'), 'success');
        } else {
            const count = readNumber('akk-count') || 1;
            await apiCall('POST', '/admin/access-keys', {
                name,
                count,
                request_limit: requestLimit,
                duration_days: durationDays,
                expires_at: expiresAt,
                bound_account_ids: boundAccounts.length ? boundAccounts : null,
                allowed_models: allowedModels.length ? allowedModels : null,
            });
            showToast(t('accessKeys.created'), 'success');
        }
        closePanel();
        await loadAccessKeys();
    } catch (e) {
        showToast(t('accessKeys.saveFail') + ': ' + e.message, 'error');
    }
}

async function onCopy(id) {
    // 明文从内存里的 keysData 取，不从 DOM 读回来（DOM 里是转义后的文本）
    const key = findKey(id);
    if (!key) return;
    const ok = await copyToClipboard(String(key.key || ''));
    showToast(ok ? t('accessKeys.copied') : t('accessKeys.copyFail'), ok ? 'success' : 'error');
}

async function onToggle(id) {
    const key = findKey(id);
    if (!key) return;
    try {
        await apiCall('PATCH', `/admin/access-keys/${encodeURIComponent(id)}`, { enabled: !key.enabled });
        await loadAccessKeys();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function onResetUsage(id) {
    try {
        await apiCall('POST', `/admin/access-keys/${encodeURIComponent(id)}/reset-usage`);
        showToast(t('accessKeys.usageReset'), 'success');
        await loadAccessKeys();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function onDelete(id) {
    const key = findKey(id);
    const confirmed = await showConfirm({
        title: t('accessKeys.confirmDeleteTitle'),
        message: t('accessKeys.confirmDelete').replace('{name}', key ? (key.display_name || key.name || '') : ''),
        confirmText: t('accessKeys.delete'),
        cancelText: t('accessKeys.cancel'),
        type: 'danger',
    });
    if (!confirmed) return;
    try {
        await apiCall('DELETE', `/admin/access-keys/${encodeURIComponent(id)}`);
        showToast(t('accessKeys.deleted'), 'success');
        await loadAccessKeys();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

export function initAccessKeys() {
    document.getElementById('akk-add-btn')?.addEventListener('click', () => openPanel(null));
    document.getElementById('akk-cancel')?.addEventListener('click', closePanel);
    document.getElementById('akk-confirm')?.addEventListener('click', submitPanel);
}

export async function loadAccessKeys() {
    const box = document.getElementById('akk-list-container');
    try {
        const [list, options] = await Promise.all([
            apiCall('GET', '/admin/access-keys'),
            apiCall('GET', '/admin/access-keys/options'),
        ]);
        keysData = list.keys || [];
        optionsData = {
            accounts: options.accounts || [],
            models: options.models || [],
        };
        render();
    } catch (e) {
        if (box) box.innerHTML = `<div class="akk-empty">${escapeHtml(e.message)}</div>`;
        showToast(t('accessKeys.loadFail') + ': ' + e.message, 'error');
    }
}
