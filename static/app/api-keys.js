import { apiCall } from './auth.js';
import { showToast, escapeHtml } from './utils.js';
import { t } from './i18n.js';

// 双引号属性上下文专用转义：escapeHtml(textContent 实现) 不转义 ASCII 双引号，
// 直接拼入 value="..." 仍可被 `"` 逸出注入事件属性，故对属性值额外转义双引号。
function escapeAttr(str) {
    return escapeHtml(String(str ?? '')).replace(/"/g, '&quot;');
}

let keysData = [];
let catalogData = {};
let selectedIds = new Set();

const PROVIDER_COLORS = {
    openai: '#10a37f',
    anthropic: '#cc785c',
    gemini: '#4285f4',
    openrouter: '#6366f1',
    custom: '#6b7280'
};

export function initApiKeys() {
    document.getElementById('ak-add-btn')?.addEventListener('click', toggleAddPanel);
    document.getElementById('ak-cancel-add')?.addEventListener('click', hideAddPanel);
    document.getElementById('ak-confirm-add')?.addEventListener('click', handleAddKey);
    document.getElementById('ak-provider')?.addEventListener('change', handleProviderChange);
    document.getElementById('ak-fetch-models-btn')?.addEventListener('click', handleFetchModels);
    document.getElementById('ak-batch-delete')?.addEventListener('click', handleBatchDelete);
    document.getElementById('ak-export-btn')?.addEventListener('click', handleExport);
    document.getElementById('ak-import-btn')?.addEventListener('click', handleImportClick);
    document.getElementById('ak-fallback-switch')?.addEventListener('change', handleFallbackToggle);

    document.getElementById('ak-custom-model')?.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            const val = this.value.trim();
            if (val) {
                addModelChip(val);
                this.value = '';
            }
        }
    });
}

export async function loadApiKeys() {
    try {
        const data = await apiCall('GET', '/admin/api-keys');
        keysData = data.keys || [];
        renderKeysList();
    } catch (error) {
        showToast('加载 API Keys 失败: ' + error.message, 'error');
    }
    await loadFallbackState();
}

async function loadFallbackState() {
    try {
        const data = await apiCall('GET', '/admin/api-keys/fallback');
        const sw = document.getElementById('ak-fallback-switch');
        if (sw) sw.checked = !!data.enabled;
    } catch (error) {
        console.error('加载兜底开关状态失败:', error);  // 不影响 key 列表，静默
    }
}

async function handleFallbackToggle(e) {
    const enabled = e.currentTarget.checked;
    try {
        await apiCall('PATCH', '/admin/api-keys/fallback', { enabled });
        showToast(enabled ? t('apiKeys.fallback.on') : t('apiKeys.fallback.off'), 'success');
    } catch (error) {
        e.currentTarget.checked = !enabled;  // 回滚 UI
        showToast(t('apiKeys.fallback.failed') + ': ' + error.message, 'error');
    }
}

function toggleAddPanel() {
    const panel = document.getElementById('ak-add-panel');
    if (panel.style.display === 'none') {
        panel.style.display = '';
        loadCatalog();
    } else {
        panel.style.display = 'none';
    }
}

function hideAddPanel() {
    document.getElementById('ak-add-panel').style.display = 'none';
    resetAddForm();
}

async function loadCatalog() {
    if (Object.keys(catalogData).length > 0) return;
    try {
        const data = await apiCall('GET', '/admin/api-keys/catalog');
        catalogData = data.catalog || {};
        handleProviderChange();
    } catch (error) {
        showToast('加载模型目录失败: ' + error.message, 'error');
    }
}

function handleProviderChange() {
    const provider = document.getElementById('ak-provider').value;
    const baseUrlInput = document.getElementById('ak-baseurl');
    const modelsList = document.getElementById('ak-models-list');
    const customInput = document.getElementById('ak-custom-model');
    const fetchBtn = document.getElementById('ak-fetch-models-btn');

    // All providers use the same flow: base_url + api_key -> fetch models
    baseUrlInput.disabled = false;
    customInput.style.display = '';
    fetchBtn.style.display = '';

    const info = catalogData[provider];
    if (info && info.default_base_url) {
        baseUrlInput.value = info.default_base_url;
    } else {
        baseUrlInput.value = '';
    }

    modelsList.innerHTML = `<span style="color:var(--text-secondary);font-size:0.8rem">${t('apiKeys.modelsHint')}</span>`;
}

function renderModelCheckboxes(models) {
    const container = document.getElementById('ak-models-list');
    if (models.length === 0) {
        container.innerHTML = '<span style="color:var(--text-secondary);font-size:0.8rem">暂无可用模型</span>';
        return;
    }
    // 安全：模型 id 可能来自攻击者可控的自定义 provider /models 接口，转义后再拼入
    // value 属性（escapeAttr 含双引号）与文本内容（escapeHtml），防止存储型 XSS。
    container.innerHTML = models.map(m =>
        '<label style="display:inline-flex;align-items:center;gap:0.3rem;padding:0.2rem 0.5rem;cursor:pointer;font-size:0.85rem">' +
        '<input type="checkbox" value="' + escapeAttr(m) + '"> ' + escapeHtml(String(m ?? '')) + '</label>'
    ).join('');
}

function addModelChip(model) {
    const container = document.getElementById('ak-models-list');
    // 通过遍历比对 dataset 而非把 model 拼进 CSS 选择器，避免选择器注入/语法错误
    const existing = Array.from(container.querySelectorAll('.ak-model-chip'))
        .some(el => el.dataset.model === model);
    if (existing) return;

    const placeholder = container.querySelector('span');
    if (placeholder) placeholder.remove();

    const chip = document.createElement('span');
    chip.className = 'ak-model-chip';
    chip.dataset.model = model;
    // 安全：model 可能来自攻击者可控字符串，模型名作为文本节点写入（textContent），
    // 删除图标单独 append，避免把未转义的 model 拼进 innerHTML 触发 XSS。
    chip.textContent = model + ' ';
    const icon = document.createElement('i');
    icon.className = 'fas fa-times';
    icon.style.cursor = 'pointer';
    icon.style.fontSize = '0.7rem';
    icon.addEventListener('click', () => chip.remove());
    chip.appendChild(icon);
    container.appendChild(chip);
}

async function handleFetchModels() {
    const apiKey = document.getElementById('ak-apikey').value.trim();
    const baseUrl = document.getElementById('ak-baseurl').value.trim();
    const provider = document.getElementById('ak-provider').value;

    if (!apiKey) { showToast('请先输入 API Key', 'warning'); return; }
    if (!baseUrl) { showToast('请先输入 Base URL', 'warning'); return; }

    try {
        const data = await apiCall('POST', '/admin/api-keys/models', { provider, api_key: apiKey, base_url: baseUrl });
        const models = (data.models || []).map(m => m.id || m.display_name || m);
        if (models.length > 0) {
            renderModelCheckboxes(models);
            showToast('获取到 ' + models.length + ' 个模型', 'success');
        } else {
            showToast('未获取到模型', 'warning');
        }
    } catch (error) {
        showToast('获取模型失败: ' + error.message, 'error');
    }
}

async function handleAddKey() {
    const provider = document.getElementById('ak-provider').value;
    const apiKey = document.getElementById('ak-apikey').value.trim();
    const baseUrl = document.getElementById('ak-baseurl').value.trim();
    const label = document.getElementById('ak-label').value.trim();
    const reasoningEffort = document.getElementById('ak-effort').value.trim();

    if (!apiKey) { showToast('请填写 API Key', 'warning'); return; }

    let models = [];
    const chips = document.querySelectorAll('#ak-models-list .ak-model-chip');
    const checkboxes = document.querySelectorAll('#ak-models-list input[type="checkbox"]:checked');
    chips.forEach(c => models.push(c.dataset.model));
    checkboxes.forEach(c => models.push(c.value));
    if (models.length === 0) {
        const customVal = document.getElementById('ak-custom-model').value.trim();
        if (customVal) models = [customVal];
    }

    if (models.length === 0) { showToast('请至少选择一个模型', 'warning'); return; }

    try {
        await apiCall('POST', '/admin/api-keys', { provider, models, api_key: apiKey, base_url: baseUrl, label, reasoning_effort: reasoningEffort || null });
        showToast('添加成功', 'success');
        hideAddPanel();
        await loadApiKeys();
    } catch (error) {
        showToast('添加失败: ' + error.message, 'error');
    }
}

function resetAddForm() {
    document.getElementById('ak-provider').value = 'openai';
    document.getElementById('ak-apikey').value = '';
    document.getElementById('ak-baseurl').value = '';
    document.getElementById('ak-baseurl').disabled = false;
    document.getElementById('ak-label').value = '';
    document.getElementById('ak-custom-model').value = '';
    document.getElementById('ak-models-list').innerHTML = '';
    document.getElementById('ak-effort').value = '';
}

function renderKeysList() {
    const container = document.getElementById('ak-list-container');
    selectedIds.clear();
    updateBatchBar();

    if (keysData.length === 0) {
        container.innerHTML = `<div class="ak-empty"><i class="fas fa-key"></i><p>${t('apiKeys.noKeys')}</p>` +
            `<button class="btn btn-primary btn-sm" onclick="document.getElementById('ak-add-btn').click()"><i class="fas fa-plus"></i> ${t('apiKeys.addFirst')}</button></div>`;
        return;
    }

    let html = '<table><thead><tr>';
    html += '<th><input type="checkbox" id="ak-select-all"></th>';
    html += '<th>Provider</th><th>模型</th><th>API Key</th><th>标签</th><th>状态</th><th>思考</th><th>操作</th>';
    html += '</tr></thead><tbody>';

    keysData.forEach(key => {
        const color = PROVIDER_COLORS[key.provider] || PROVIDER_COLORS.custom;
        const statusClass = key.status === 'active' ? 'ak-status-active' : 'ak-status-disabled';
        const statusText = key.status === 'active' ? '启用' : '禁用';
        const toggleText = key.status === 'active' ? '禁用' : '启用';

        // 安全：provider/model/api_key/label 均为用户可控且持久化（label 来自添加表单，
        // model 可能来自攻击者可控的 provider /models / 导入文件），渲染前一律转义；
        // id/status 进入 data-* 属性也用 escapeAttr 转义，防止属性逸出。
        const idEsc = escapeAttr(key.id);
        html += '<tr>';
        html += '<td><input type="checkbox" class="ak-cb" data-id="' + idEsc + '"></td>';
        html += '<td><span class="ak-provider-badge" style="background:' + color + '20;color:' + color + '">' + escapeHtml(String(key.provider ?? '')) + '</span></td>';
        html += '<td>' + escapeHtml(String(key.model ?? '-')) + '</td>';
        html += '<td><span class="ak-key-masked">' + escapeHtml(String(key.api_key ?? '-')) + '</span></td>';
        html += '<td>' + escapeHtml(String(key.label ?? '-')) + '</td>';
        html += '<td><span class="' + statusClass + '">' + escapeHtml(statusText) + '</span></td>';
        html += '<td><input type="text" class="ak-effort-input" data-id="' + idEsc +
                '" list="ak-effort-presets" value="' + escapeAttr(String(key.reasoning_effort ?? '')) +
                '" placeholder="默认" style="width:90px"></td>';
        html += '<td class="ak-actions">';
        html += '<button class="btn btn-xs btn-outline ak-toggle-btn" data-id="' + idEsc + '" data-status="' + escapeAttr(key.status) + '">' + escapeHtml(toggleText) + '</button>';
        html += '<button class="btn btn-xs btn-danger ak-del-btn" data-id="' + idEsc + '"><i class="fas fa-trash"></i></button>';
        html += '</td></tr>';
    });

    html += '</tbody></table>';
    container.innerHTML = html;

    document.getElementById('ak-select-all')?.addEventListener('change', handleSelectAll);
    container.querySelectorAll('.ak-cb').forEach(cb => cb.addEventListener('change', handleCheckboxChange));
    container.querySelectorAll('.ak-toggle-btn').forEach(btn => btn.addEventListener('click', handleStatusToggle));
    container.querySelectorAll('.ak-del-btn').forEach(btn => btn.addEventListener('click', handleDelete));
    container.querySelectorAll('.ak-effort-input').forEach(inp => inp.addEventListener('change', handleEffortChange));
}

function handleSelectAll(e) {
    const checked = e.target.checked;
    document.querySelectorAll('.ak-cb').forEach(cb => {
        cb.checked = checked;
        if (checked) selectedIds.add(cb.dataset.id);
        else selectedIds.delete(cb.dataset.id);
    });
    updateBatchBar();
}

function handleCheckboxChange(e) {
    if (e.target.checked) selectedIds.add(e.target.dataset.id);
    else selectedIds.delete(e.target.dataset.id);
    updateBatchBar();
}

function updateBatchBar() {
    const bar = document.getElementById('ak-batch-bar');
    const countEl = document.getElementById('ak-selected-count');
    if (selectedIds.size > 0) {
        bar.style.display = '';
        countEl.textContent = selectedIds.size + ' 项已选';
    } else {
        bar.style.display = 'none';
    }
}

async function handleStatusToggle(e) {
    const btn = e.currentTarget;
    const id = btn.dataset.id;
    const newStatus = btn.dataset.status === 'active' ? 'disabled' : 'active';
    try {
        await apiCall('PATCH', '/admin/api-keys/' + id + '/status', { status: newStatus });
        showToast('状态已更新', 'success');
        await loadApiKeys();
    } catch (error) {
        showToast('更新失败: ' + error.message, 'error');
    }
}

async function handleEffortChange(e) {
    const inp = e.currentTarget;
    const id = inp.dataset.id;
    const value = inp.value.trim();
    try {
        await apiCall('PATCH', '/admin/api-keys/' + id + '/reasoning-effort', { reasoning_effort: value || null });
        showToast('思考设置已更新', 'success');
        await loadApiKeys();
    } catch (error) {
        showToast('更新失败: ' + error.message, 'error');
    }
}

async function handleDelete(e) {
    const id = e.currentTarget.dataset.id;
    if (!confirm('确定要删除这个 API Key 吗？')) return;
    try {
        await apiCall('DELETE', '/admin/api-keys/' + id);
        showToast('删除成功', 'success');
        await loadApiKeys();
    } catch (error) {
        showToast('删除失败: ' + error.message, 'error');
    }
}

async function handleBatchDelete() {
    if (selectedIds.size === 0) return;
    if (!confirm('确定要删除选中的 ' + selectedIds.size + ' 个 Key 吗？')) return;
    try {
        await apiCall('POST', '/admin/api-keys/batch-delete', { ids: Array.from(selectedIds) });
        showToast('批量删除成功', 'success');
        await loadApiKeys();
    } catch (error) {
        showToast('批量删除失败: ' + error.message, 'error');
    }
}

async function handleExport() {
    try {
        // 契约：批次2 后 export 默认脱敏，导出可再导入的明文需 reveal=true（VULN-002）
        const data = await apiCall('GET', '/admin/api-keys/export?reveal=true');
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'api-keys-' + new Date().toISOString().split('T')[0] + '.json';
        a.click();
        URL.revokeObjectURL(url);
        showToast('导出成功', 'success');
    } catch (error) {
        showToast('导出失败: ' + error.message, 'error');
    }
}

function handleImportClick() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = handleImport;
    input.click();
}

async function handleImport(e) {
    const file = e.target.files[0];
    if (!file) return;
    try {
        const text = await file.text();
        const data = JSON.parse(text);
        const keys = data.keys || data;
        await apiCall('POST', '/admin/api-keys/import', { keys: Array.isArray(keys) ? keys : [] });
        showToast('导入成功', 'success');
        await loadApiKeys();
    } catch (error) {
        showToast('导入失败: ' + error.message, 'error');
    }
}
