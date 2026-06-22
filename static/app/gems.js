import { apiCall } from './auth.js';
import { showToast, escapeHtml } from './utils.js';
import { t } from './i18n.js';

// 双引号属性上下文专用转义
function escapeAttr(str) {
    return escapeHtml(String(str ?? '')).replace(/"/g, '&quot;');
}

let currentAccount = '';
let editingGemId = null;

export function initGems() {
    document.getElementById('gem-add-btn')?.addEventListener('click', () => openPanel(null));
    document.getElementById('gem-cancel')?.addEventListener('click', closePanel);
    document.getElementById('gem-confirm')?.addEventListener('click', saveGem);
    document.getElementById('gem-account-select')?.addEventListener('change', (e) => {
        currentAccount = e.target.value;
        loadGems();
    });
}

export async function loadAccountsThenGems() {
    try {
        const data = await apiCall('GET', '/admin/accounts');
        const sel = document.getElementById('gem-account-select');
        const accounts = data.accounts || [];
        sel.innerHTML = accounts.map(a =>
            `<option value="${escapeAttr(a.id)}">${escapeHtml(a.label || a.id)}</option>`).join('');
        currentAccount = accounts[0]?.id || '';
        await loadGems();
    } catch (e) {
        showToast(t('gems.loadFail') + ': ' + e.message, 'error');
    }
}

async function loadGems() {
    if (!currentAccount) return;
    const box = document.getElementById('gem-list-container');
    try {
        const [gemsResp, mapResp] = await Promise.all([
            apiCall('GET', `/admin/gems?account_id=${encodeURIComponent(currentAccount)}`),
            apiCall('GET', '/admin/gem-mapping'),
        ]);
        render(gemsResp.gems || [], mapResp.mappings || {});
    } catch (e) {
        box.innerHTML = `<div class="error">${escapeHtml(e.message)}</div>`;
    }
}

function modelNameForGem(gemId, mappings) {
    for (const [name, info] of Object.entries(mappings)) {
        if (info.gem_id === gemId && info.account_id === currentAccount) return name;
    }
    return '';
}

function render(gems, mappings) {
    const box = document.getElementById('gem-list-container');
    if (!gems.length) { box.innerHTML = `<div class="empty">${escapeHtml(t('gems.empty'))}</div>`; return; }
    box.innerHTML = gems.map(g => {
        const modelName = modelNameForGem(g.id, mappings);
        const unexposeBtn = modelName
            ? `<button class="btn btn-sm btn-warning gem-unexpose-btn" data-model="${escapeAttr(modelName)}">${escapeHtml(t('gems.unexpose'))}</button>`
            : '';
        return `<div class="gem-card" data-id="${escapeAttr(g.id)}">
      <div class="gem-info">
        <b>${escapeHtml(g.name)}</b>
        <small>${escapeHtml(g.description || '')}</small>
      </div>
      <div class="gem-expose">
        <input class="gem-model-name" value="${escapeAttr(modelName)}" placeholder="${escapeAttr(t('gems.modelName'))}">
        <button class="btn btn-sm btn-outline gem-expose-btn">${escapeHtml(t('gems.expose'))}</button>
        ${unexposeBtn}
      </div>
      <div class="gem-actions">
        <button class="btn btn-sm gem-edit"><i class="fas fa-pen"></i></button>
        <button class="btn btn-sm btn-danger gem-del"><i class="fas fa-trash"></i></button>
      </div>
    </div>`;
    }).join('');
    bindRowEvents(gems);
}

function bindRowEvents(gems) {
    const byId = Object.fromEntries(gems.map(g => [g.id, g]));
    document.querySelectorAll('.gem-card').forEach(card => {
        const id = card.dataset.id;
        card.querySelector('.gem-del')?.addEventListener('click', () => removeGem(id));
        card.querySelector('.gem-edit')?.addEventListener('click', () => openPanel(byId[id]));
        card.querySelector('.gem-expose-btn')?.addEventListener('click', () => {
            const name = card.querySelector('.gem-model-name').value.trim();
            exposeGem(id, name);
        });
        card.querySelector('.gem-unexpose-btn')?.addEventListener('click', (e) => {
            const modelName = e.currentTarget.dataset.model;
            unexposeGem(modelName);
        });
    });
}

function openPanel(gem) {
    editingGemId = gem ? gem.id : null;
    document.getElementById('gem-name').value = gem ? gem.name : '';
    document.getElementById('gem-desc').value = gem ? (gem.description || '') : '';
    document.getElementById('gem-prompt').value = gem ? (gem.prompt || '') : '';
    document.getElementById('gem-add-panel').style.display = 'block';
}

function closePanel() { document.getElementById('gem-add-panel').style.display = 'none'; }

async function saveGem() {
    const body = {
        account_id: currentAccount,
        name: document.getElementById('gem-name').value.trim(),
        description: document.getElementById('gem-desc').value.trim(),
        prompt: document.getElementById('gem-prompt').value.trim(),
    };
    if (!body.name || !body.prompt) { showToast(t('gems.namePromptRequired'), 'error'); return; }
    try {
        if (editingGemId) await apiCall('PUT', `/admin/gems/${encodeURIComponent(editingGemId)}`, body);
        else await apiCall('POST', '/admin/gems', body);
        showToast(t('gems.saved'), 'success');
        closePanel();
        await loadGems();
    } catch (e) { showToast(t('gems.saveFail') + ': ' + e.message, 'error'); }
}

async function removeGem(gemId) {
    if (!confirm(t('gems.confirmDelete'))) return;
    try {
        await apiCall('DELETE', `/admin/gems/${encodeURIComponent(gemId)}?account_id=${encodeURIComponent(currentAccount)}`);
        showToast(t('gems.deleted'), 'success');
        await loadGems();
    } catch (e) { showToast(e.message, 'error'); }
}

async function exposeGem(gemId, modelName) {
    if (!modelName) { showToast(t('gems.modelNameRequired'), 'error'); return; }
    try {
        await apiCall('POST', '/admin/gem-mapping', {
            model_name: modelName, gem_id: gemId,
            base_model: 'gemini-pro', account_id: currentAccount,
        });
        showToast(t('gems.exposed'), 'success');
        await loadGems();
    } catch (e) { showToast(e.message, 'error'); }
}

async function unexposeGem(modelName) {
    if (!modelName) return;
    try {
        await apiCall('DELETE', '/admin/gem-mapping/' + encodeURIComponent(modelName));
        showToast(t('gems.unexposed'), 'success');
        await loadGems();
    } catch (e) { showToast(e.message, 'error'); }
}
