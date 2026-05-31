/**
 * Gemini2API 管理面板 - 主应用入口
 */

import { initializeComponents } from './component-loader.js';
import { initThemeSwitcher } from './theme-switcher.js';
import { initAuth, apiCall, logout } from './auth.js';
import { showToast, formatNumber, getStatusBadge, maskString, copyToClipboard, showConfirm } from './utils.js';
import { initUsageStats, loadUsageStats } from './usage-chart.js';
import { initLogs } from './logs.js';
import { initSettings, loadSettings } from './settings.js';
import { initApiKeys, loadApiKeys } from './api-keys.js';
import { initI18n, t } from './i18n.js';
import { initLanguageSwitcher } from './language-switcher.js';

let isAppInitialized = false;

const elements = {
    navItems: null,
    sections: null
};

function initElements() {
    elements.navItems = document.querySelectorAll('.nav-item');
    elements.sections = document.querySelectorAll('.section');
}

function initNavigation() {
    if (!elements.navItems || !elements.sections) return;

    elements.navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const sectionId = item.dataset.section;
            activateSection(sectionId);
        });
    });

    window.addEventListener('hashchange', () => {
        const sectionId = window.location.hash.slice(1) || 'dashboard';
        activateSection(sectionId, false);
    });

    const initialSectionId = window.location.hash.slice(1) || 'dashboard';
    activateSection(initialSectionId, false);
}

function activateSection(sectionId, updateHash = true) {
    elements.navItems.forEach(nav => {
        nav.classList.remove('active');
        if (nav.dataset.section === sectionId) {
            nav.classList.add('active');
        }
    });

    elements.sections.forEach(section => {
        section.classList.remove('active');
        if (section.id === sectionId) {
            section.classList.add('active');
        }
    });

    if (updateHash) {
        window.location.hash = sectionId;
    }

    loadSectionData(sectionId);
    window.scrollTo(0, 0);
}

async function loadSectionData(sectionId) {
    try {
        switch (sectionId) {
            case 'dashboard':
                await loadDashboard();
                break;
            case 'accounts':
                await loadAccounts();
                break;
            case 'usage-stats':
                await loadUsageStats();
                break;
            case 'logs':
                break;
            case 'settings':
                await loadSettings();
                break;
            case 'api-keys':
                await loadApiKeys();
                break;
        }
    } catch (error) {
        console.error(`加载${sectionId}数据失败:`, error);
    }
}

// ============================================================================
// Dashboard
// ============================================================================

async function loadDashboard() {
    try {
        const data = await apiCall('GET', '/admin/status');
        const accounts = data.accounts || [];

        const activeCount = accounts.filter(a => a.status === 'active').length;
        const totalRequests = accounts.reduce((sum, a) => sum + (a.request_count || 0), 0);
        const modelsSet = new Set();
        accounts.forEach(a => {
            if (a.models && Array.isArray(a.models)) {
                a.models.forEach(m => modelsSet.add(m));
            }
        });

        setText('stat-total', formatNumber(accounts.length));
        setText('stat-active', formatNumber(activeCount));
        setText('stat-requests', formatNumber(totalRequests));
        setText('stat-models', formatNumber(modelsSet.size || accounts.reduce((s, a) => s + (a.models_count || 0), 0)));

        const strategyMap = { 'round-robin': t('settings.strategy.roundRobin'), 'least-used': t('settings.strategy.leastUsed'), 'failover': t('settings.strategy.failover') };
        setText('info-strategy', strategyMap[data.strategy] || data.strategy);
        setText('info-concurrent', data.max_concurrent_per_account || '-');
        setText('info-total-accounts', accounts.length);
        setText('info-active-accounts', activeCount);

        renderAccountStatusGrid(accounts);
        renderModelsList(modelsSet);
        updatePlaygroundModels(modelsSet);
        await loadSystemInfo();
        await loadQrCards();

        // Bind and auto-check update button (must be after DOM is loaded)
        const updateBtn = document.getElementById('checkUpdateBtn');
        if (updateBtn && !updateBtn._bound) {
            updateBtn._bound = true;
            updateBtn.addEventListener('click', handleCheckUpdate);
            checkForUpdate();
        }
    } catch (error) {
        console.error('加载仪表盘失败:', error);
    }
}

let uptimeInterval = null;

function startUptimeTimer(initialSeconds) {
    if (uptimeInterval) clearInterval(uptimeInterval);
    let seconds = initialSeconds;
    function update() {
        const d = Math.floor(seconds / 86400);
        const h = Math.floor((seconds % 86400) / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = seconds % 60;
        setText('uptime-display', d + t('time.days') + ' ' + h + t('time.hours') + ' ' + m + t('time.minutes') + ' ' + s + t('time.seconds'));
        seconds++;
    }
    update();
    uptimeInterval = setInterval(update, 1000);
}

async function loadSystemInfo() {
    try {
        const data = await apiCall('GET', '/admin/system-info');
        setText('sys-version', 'v' + data.version);
        setText('sys-ver-detail', 'v' + data.version);
        setText('sys-python', data.python_version);
        setText('sys-time', data.server_time);
        setText('sys-os', data.os);
        setText('sys-memory', data.memory_usage + ' MB / ' + data.memory_total + ' MB');
        setText('sys-cpu', data.cpu_percent + '%');
        setText('sys-mode', data.run_mode);
        setText('sys-pid', data.pid);
        if (data.uptime_seconds !== undefined) {
            startUptimeTimer(data.uptime_seconds);
        }
    } catch (error) {
        console.error('加载系统信息失败:', error);
    }
}

const QR_REMOTE_BASE = 'https://raw.githubusercontent.com/xwteam/gemini2api/main/api';

async function loadQrCards() {
    const container = document.getElementById('qrCardsContainer');
    if (!container) return;
    try {
        const resp = await fetch(`${QR_REMOTE_BASE}/qr-config.json`);
        if (!resp.ok) return;
        const config = await resp.json();
        container.innerHTML = (config.cards || []).map(card => `
            <div class="qr-card">
                <p class="qr-title">${card.title}</p>
                <img src="${QR_REMOTE_BASE}/${card.image}" alt="${card.title}" class="qr-img" onclick="window.app.openLightbox(this.src)">
                <p class="qr-desc">${card.description}</p>
            </div>
        `).join('');
    } catch (e) {
        console.error('加载二维码配置失败:', e);
    }
}

function openLightbox(src) {
    const overlay = document.getElementById('lightboxOverlay');
    const img = document.getElementById('lightboxImage');
    if (overlay && img) {
        img.src = src;
        overlay.classList.add('active');
    }
}

function closeLightbox() {
    const overlay = document.getElementById('lightboxOverlay');
    if (overlay) overlay.classList.remove('active');
}

function initLightbox() {
    const overlay = document.getElementById('lightboxOverlay');
    const closeBtn = document.getElementById('lightboxClose');
    if (overlay) overlay.addEventListener('click', (e) => { if (e.target === overlay) closeLightbox(); });
    if (closeBtn) closeBtn.addEventListener('click', closeLightbox);
}

function renderAccountStatusGrid(accounts) {
    const container = document.getElementById('accountStatusGrid');
    if (!container) return;

    if (accounts.length === 0) {
        container.innerHTML = '<div class="empty-state"><i class="fas fa-server"></></div>';
        return;
    }

    container.innerHTML = accounts.map(account => `
        <div class="provider-card">
            <div class="provider-card-header">
                <h4>${account.label || account.id}</h4>
                ${getStatusBadge(account.status)}
            </div>
            <div class="account-detail">
                <span class="label">${t('accounts.requests')}</span>
                <span class="value">${formatNumber(account.request_count || 0)}</span>
            </div>
            <div class="account-detail">
                <span class="label">${t('accounts.errors')}</span>
                <span class="value">${formatNumber(account.error_count || 0)}</span>
            </div>
            <div class="account-detail">
                <span class="label">${t('accounts.concurrency')}</span>
                <span class="value">${account.active_requests || 0}</span>
            </div>
            <div class="account-detail">
                <span class="label">${t('accounts.models')}</span>
                <span class="value">${account.models_count || 0}</span>
            </div>
        </div>
    `).join('');
}

function renderModelsList(modelsSet) {
    const container = document.getElementById('modelsList');
    if (!container) return;

    const models = Array.from(modelsSet).sort();
    if (models.length === 0) {
        container.innerHTML = `<span class="text-muted">${t('accounts.noModels')}</span>`;
        return;
    }

    container.innerHTML = models.map(model => `
        <span class="model-tag" onclick="window.app.copyModel('${model}')">
            <i class="fas fa-cube"></i> ${model}
        </span>
    `).join('');
}

function updatePlaygroundModels(modelsSet) {
    const select = document.getElementById('pg-model');
    if (!select) return;

    const models = Array.from(modelsSet).sort();
    if (models.length === 0) {
        select.innerHTML = `<option value="">${t('accounts.noModels')}</option>`;
        return;
    }

    select.innerHTML = models.map(model =>
        `<option value="${model}">${model}</option>`
    ).join('');
}

// ============================================================================
// Accounts
// ============================================================================

async function loadAccounts() {
    try {
        const data = await apiCall('GET', '/admin/accounts');
        const accounts = data.accounts || [];

        const container = document.getElementById('accountsList');
        if (!container) return;

        if (accounts.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-users"></i>
                    <p>暂无账号</p>
                    <button class="btn btn-primary" onclick="window.app.openAddAccountModal()">
                        <i class="fas fa-plus"></i> ${t('accounts.noAccounts')}
                    </button>
                </div>`;
            return;
        }

        container.innerHTML = accounts.map(account => `
            <div class="account-card">
                <div class="account-card-header">
                    <div>
                        <h4>${account.label || t('accounts.unnamed')}</h4>
                        <span class="text-muted">ID: ${account.id}</span>
                    </div>
                    ${getStatusBadge(account.status)}
                </div>
                <div class="account-detail">
                    <span class="label">PSID</span>
                    <span class="value">${maskString(account.psid || '', 12)}</span>
                </div>
                <div class="account-detail">
                    <span class="label">${t('accounts.requests')}</span>
                    <span class="value">${formatNumber(account.request_count || 0)}</span>
                </div>
                <div class="account-detail">
                    <span class="label">${t('accounts.errors')}</span>
                    <span class="value">${formatNumber(account.error_count || 0)}</span>
                </div>
                <div class="account-detail">
                    <span class="label">${t('accounts.models')}</span>
                    <span class="value">${(account.models || []).length || account.models_count || 0}</span>
                </div>
                <div class="account-actions">
                    <button class="btn btn-sm btn-outline" onclick="window.app.checkAccount('${account.id}')">
                        <i class="fas fa-heartbeat"></i> ${t('accounts.check')}
                    </button>
                    <button class="btn btn-sm btn-outline" onclick="window.app.openUpdateCookieModal('${account.id}', '${account.label || ''}')">
                        <i class="fas fa-cookie-bite"></i> ${t('accounts.updateCookie')}
                    </button>
                    <button class="btn btn-sm btn-danger" onclick="window.app.removeAccount('${account.id}')">
                        <i class="fas fa-trash"></i> ${t('accounts.delete')}
                    </button>
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('加载账号列表失败:', error);
    }
}

async function checkAccount(accountId) {
    try {
        showToast(t('accounts.checking'), 'info');
        const result = await apiCall('GET', `/admin/accounts/${accountId}/check`);
        const msg = result.valid ? '账号有效' : '账号无效';
        showToast(`${msg} | 模型: ${result.models_count || 0}`, result.valid ? 'success' : 'error');
        await loadAccounts();
        await loadDashboard();
    } catch (error) {
        showToast(`${t('accounts.checkFailed')}: ${error.message}`, 'error');
    }
}

async function removeAccount(accountId) {
    const confirmed = await showConfirm({
        title: t('confirm.delete.title'),
        message: t('confirm.delete.message'),
        confirmText: t('confirm.delete.btn'),
        cancelText: t('confirm.cancel'),
        type: 'danger'
    });
    if (!confirmed) return;

    try {
        showToast(t('accounts.deleting'), 'info');
        await apiCall('DELETE', `/admin/accounts/${accountId}`);
        showToast(t('accounts.deleted'), 'success');
        await loadAccounts();
        await loadDashboard();
    } catch (error) {
        showToast(`${t('accounts.deleteFailed')}: ${error.message}`, 'error');
    }
}

function openAddAccountModal() {
    const modal = document.getElementById('addAccountModal');
    if (modal) modal.classList.add('active');
}

function closeAddAccountModal() {
    const modal = document.getElementById('addAccountModal');
    if (modal) {
        modal.classList.remove('active');
        const inputs = modal.querySelectorAll('input');
        inputs.forEach(input => { input.value = ''; });
    }
}

async function submitAddAccount() {
    const psid = document.getElementById('add-psid')?.value.trim();
    const psidts = document.getElementById('add-psidts')?.value.trim() || '';
    const label = document.getElementById('add-label')?.value.trim() || '';

    if (!psid) {
        showToast('请填写 __Secure-1PSID', 'warning');
        return;
    }

    try {
        showToast(t('accounts.adding'), 'info');
        await apiCall('POST', '/admin/accounts', { psid, psidts, label });
        showToast(t('accounts.added'), 'success');
        closeAddAccountModal();
        await loadAccounts();
        await loadDashboard();
    } catch (error) {
        showToast(`${t('accounts.addFailed')}: ${error.message}`, 'error');
    }
}

// ============================================================================
// Update Cookie Modal
// ============================================================================

let updateCookieAccountId = null;

function openUpdateCookieModal(accountId, label) {
    updateCookieAccountId = accountId;
    const modal = document.getElementById('updateCookieModal');
    const title = document.getElementById('updateCookieTitle');
    if (title) title.textContent = `更新 Cookie - ${label || accountId}`;
    if (modal) modal.classList.add('active');
}

function closeUpdateCookieModal() {
    const modal = document.getElementById('updateCookieModal');
    if (modal) {
        modal.classList.remove('active');
        const inputs = modal.querySelectorAll('input');
        inputs.forEach(input => { input.value = ''; });
    }
    updateCookieAccountId = null;
}

async function submitUpdateCookie() {
    const psid = document.getElementById('update-psid')?.value.trim();
    const psidts = document.getElementById('update-psidts')?.value.trim() || '';

    if (!psid) {
        showToast('请填写 __Secure-1PSID', 'warning');
        return;
    }

    if (!updateCookieAccountId) {
        showToast('未选择账号', 'error');
        return;
    }

    try {
        showToast('正在更新 Cookie...', 'info');
        await apiCall('PUT', `/admin/accounts/${updateCookieAccountId}/cookies`, { psid, psidts });
        showToast('Cookie 更新成功', 'success');
        closeUpdateCookieModal();
        await loadAccounts();
        await loadDashboard();
    } catch (error) {
        showToast(`更新失败: ${error.message}`, 'error');
    }
}

// ============================================================================
// Playground
// ============================================================================

let _pgConversationId = '';
let _pgMessages = [];
let _pgImages = [];  // 待发送的图片 [{dataUrl, name}]

async function sendPlaygroundRequest() {
    const message = document.getElementById('pg-message')?.value.trim();
    const model = document.getElementById('pg-model')?.value;
    const chatContainer = document.getElementById('pg-chat');

    if (!message && _pgImages.length === 0) {
        showToast('请输入消息内容', 'warning');
        return;
    }

    const placeholder = chatContainer?.querySelector('.chat-placeholder');
    if (placeholder) placeholder.remove();

    // 组装多模态 content：有图片时用数组格式，纯文本保持字符串
    let userContent;
    if (_pgImages.length > 0) {
        userContent = [];
        if (message) userContent.push({ type: 'text', text: message });
        for (const img of _pgImages) {
            userContent.push({ type: 'image_url', image_url: { url: img.dataUrl } });
        }
    } else {
        userContent = message;
    }
    _pgMessages.push({ role: 'user', content: userContent });

    const imgHtml = _pgImages.map(img => `<img src="${img.dataUrl}" class="chat-img" alt="${escapeHtml(img.name)}">`).join('');
    const userMsg = document.createElement('div');
    userMsg.className = 'chat-message user';
    userMsg.innerHTML = `
        <div class="chat-avatar"><i class="fas fa-user"></i></div>
        <div class="chat-bubble">${escapeHtml(message)}${imgHtml}</div>
    `;
    chatContainer.appendChild(userMsg);

    const aiMsg = document.createElement('div');
    aiMsg.className = 'chat-message assistant';
    aiMsg.innerHTML = `
        <div class="chat-avatar"><i class="fas fa-microchip"></i></div>
        <div class="chat-bubble"><span class="typing-cursor"></span></div>
    `;
    chatContainer.appendChild(aiMsg);
    const aiBubble = aiMsg.querySelector('.chat-bubble');
    chatContainer.scrollTop = chatContainer.scrollHeight;

    document.getElementById('pg-message').value = '';
    _pgImages = [];
    _renderPgImagePreview();

    const token = localStorage.getItem('gemini2api_token');
    const reqBody = {
        model: model || 'gemini-3-flash',
        messages: [..._pgMessages],
        stream: true
    };
    if (_pgConversationId) {
        reqBody.conversation_id = _pgConversationId;
    }

    try {
        const resp = await fetch('/openai/v1/chat/completions', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify(reqBody)
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => null);
            const msg = err?.error?.message || `请求失败 (状态: ${resp.status})`;
            aiBubble.innerHTML = `<span class="text-danger">${msg}</span>`;
            return;
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let content = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const data = line.slice(6).trim();
                if (data === '[DONE]') break;
                try {
                    const chunk = JSON.parse(data);
                    const delta = chunk.choices?.[0]?.delta?.content || '';
                    if (delta) {
                        content += delta;
                        aiBubble.textContent = content;  // 流式过程显示文本
                        chatContainer.scrollTop = chatContainer.scrollHeight;
                    }
                } catch {}
            }
        }

        if (!content) {
            aiBubble.textContent = '无响应内容';
        } else {
            // 流式结束：把图片（markdown/URL/dataURI）渲染成 <img>，其余文本转义显示
            aiBubble.innerHTML = _pgRenderContent(content);
            chatContainer.scrollTop = chatContainer.scrollHeight;
            _pgMessages.push({ role: 'assistant', content: content });
        }
    } catch (error) {
        aiBubble.innerHTML = `<span class="text-danger">错误: ${error.message}</span>`;
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 把 AI 回复渲染成 HTML：markdown 图片 ![](url)、裸图片 URL/data URI → <img>，其余文本转义
function _pgRenderContent(text) {
    if (!text) return '';
    const imgs = [];
    let s = text;
    // 1) markdown 图片 ![alt](url)
    s = s.replace(/!\[[^\]]*\]\((data:image\/[^)]+|https?:\/\/[^)\s]+)\)/g, (m, url) => {
        const i = imgs.push(url) - 1;
        return ` IMG${i} `;
    });
    // 2) 裸的 data:image 或 /images/ 图片 URL
    s = s.replace(/(data:image\/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=]+)/g, (m, url) => {
        const i = imgs.push(url) - 1;
        return ` IMG${i} `;
    });
    s = s.replace(/(https?:\/\/[^\s)]+\/images\/[^\s)]+\.(?:png|jpg|jpeg|webp|gif))/gi, (m, url) => {
        const i = imgs.push(url) - 1;
        return ` IMG${i} `;
    });
    // 转义剩余文本，再把占位符还原成 <img>
    let html = escapeHtml(s);
    imgs.forEach((url, i) => {
        html = html.replace(` IMG${i} `,
            `<img src="${url}" class="chat-img" alt="generated image">`);
    });
    return html;
}

function clearPlayground() {
    const chatContainer = document.getElementById('pg-chat');
    if (chatContainer) {
        chatContainer.innerHTML = '<div class="chat-placeholder"><i class="fas fa-comment-dots"></i><p>发送消息开始对话</p></div>';
    }
    const message = document.getElementById('pg-message');
    if (message) message.value = '';
    _pgConversationId = '';
    _pgMessages = [];
    _pgImages = [];
    _renderPgImagePreview();
}

function _renderPgImagePreview() {
    const box = document.getElementById('pg-image-preview');
    if (!box) return;
    box.innerHTML = _pgImages.map((img, i) =>
        `<span class="pg-img-thumb"><img src="${img.dataUrl}" alt="${escapeHtml(img.name)}"><button type="button" class="pg-img-del" data-idx="${i}">&times;</button></span>`
    ).join('');
    box.querySelectorAll('.pg-img-del').forEach(btn => {
        btn.addEventListener('click', () => {
            _pgImages.splice(parseInt(btn.dataset.idx), 1);
            _renderPgImagePreview();
        });
    });
}

function _handlePgImageSelect(files) {
    for (const file of files) {
        if (!file.type.startsWith('image/')) continue;
        const reader = new FileReader();
        reader.onload = (e) => {
            _pgImages.push({ dataUrl: e.target.result, name: file.name });
            _renderPgImagePreview();
        };
        reader.readAsDataURL(file);
    }
}

// ============================================================================
// Utilities
// ====================================================================================

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

async function copyModel(model) {
    const ok = await copyToClipboard(model);
    showToast(ok ? `已复制: ${model}` : '复制失败', ok ? 'success' : 'error');
}

// ============================================================================
// Update Check
// ============================================================================

let updateInfo = null;

async function checkForUpdate() {
    try {
        const data = await apiCall('GET', '/admin/check-update');
        updateInfo = data;
        updateCheckButton(data);
    } catch (error) {
        console.error('检查更新失败:', error);
    }
}

function updateCheckButton(data) {
    const btn = document.getElementById('checkUpdateBtn');
    if (!btn) return;

    const text = btn.querySelector('span');

    if (data.has_update) {
        btn.classList.remove('btn-outline');
        btn.classList.add('btn-success');
        if (text) text.textContent = t('dashboard.updateAvailable') + ' v' + data.latest;
    } else {
        if (text) text.textContent = t('dashboard.upToDate');
    }
}

function extractLocalizedNotes(body) {
    if (!body) return '';
    const lang = localStorage.getItem('gemini2api_lang') || 'zh-CN';
    const marker = `<!-- ${lang} -->`;
    const idx = body.indexOf(marker);
    if (idx === -1) {
        const enIdx = body.indexOf('<!-- en-US -->');
        if (enIdx !== -1) {
            const start = enIdx + '<!-- en-US -->'.length;
            const nextMarker = body.indexOf('<!--', start);
            return (nextMarker === -1 ? body.slice(start) : body.slice(start, nextMarker)).trim();
        }
        return body.replace(/<!--.*?-->/g, '').trim().split('\n').slice(0, 10).join('\n');
    }
    const start = idx + marker.length;
    const nextMarker = body.indexOf('<!--', start);
    return (nextMarker === -1 ? body.slice(start) : body.slice(start, nextMarker)).trim();
}

async function handleCheckUpdate() {
    const btn = document.getElementById('checkUpdateBtn');
    if (!btn) return;

    if (updateInfo && updateInfo.has_update) {
        const updateCmd = 'docker compose pull && docker compose up -d';
        const releaseNotes = extractLocalizedNotes(updateInfo.release_notes || '');

        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay active';
        overlay.style.bottom = '0';
        overlay.innerHTML = `
            <div style="background:var(--bg-primary);border-radius:var(--radius-xl,16px);width:90%;max-width:460px;box-shadow:0 20px 60px rgba(0,0,0,0.3);animation:modalIn 0.2s ease">
                <div style="padding:1.5rem 2rem;text-align:center">
                    <div style="width:56px;height:56px;border-radius:50%;background:var(--primary-color)15;display:inline-flex;align-items:center;justify-content:center;margin-bottom:1rem">
                        <i class="fas fa-cloud-download-alt" style="font-size:1.5rem;color:var(--primary-color)"></i>
                    </div>
                    <h3 style="margin:0 0 0.5rem;font-size:1.125rem;color:var(--text-primary)">${t('confirm.update.title')} v${updateInfo.latest}</h3>
                    ${releaseNotes ? `<div style="max-height:120px;overflow-y:auto;text-align:left;padding:0.75rem;margin:0.75rem 0;background:var(--bg-tertiary);border-radius:var(--radius-lg,10px);border:1px solid var(--border-color);font-size:0.8rem;color:var(--text-secondary);line-height:1.5;white-space:pre-wrap">${releaseNotes}</div>` : ''}
                    <p style="margin:0.75rem 0 0.5rem;color:var(--text-secondary);font-size:0.85rem">${t('confirm.update.message')}</p>
                    <div style="display:flex;align-items:center;background:var(--bg-tertiary);border-radius:var(--radius-lg,10px);padding:0.6rem 1rem;margin:0.5rem 0;border:1px solid var(--border-color)">
                        <code style="flex:1;font-size:0.8rem;color:var(--text-primary);font-family:monospace;word-break:break-all">${updateCmd}</code>
                        <button class="update-copy-btn" style="flex-shrink:0;margin-left:0.5rem;background:none;border:none;color:var(--text-secondary);cursor:pointer;padding:0.25rem;border-radius:4px;transition:all 0.2s" title="${t('toast.copied')}">
                            <i class="fas fa-copy" style="font-size:0.9rem"></i>
                        </button>
                    </div>
                </div>
                <div style="display:flex;gap:0.75rem;padding:0 2rem 1.5rem;justify-content:center">
                    <button class="update-close-btn" style="flex:1;padding:0.625rem 1.25rem;border-radius:var(--radius-lg,10px);border:1px solid var(--border-color);background:var(--bg-tertiary);color:var(--text-primary);cursor:pointer;font-size:0.875rem;font-weight:500;transition:all 0.2s">${t('confirm.cancel')}</button>
                </div>
            </div>
        `;

        const close = () => {
            overlay.style.opacity = '0';
            setTimeout(() => overlay.remove(), 200);
        };

        overlay.querySelector('.update-copy-btn').onclick = async () => {
            try {
                await navigator.clipboard.writeText(updateCmd);
            } catch (e) {
                const ta = document.createElement('textarea');
                ta.value = updateCmd;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            }
            const icon = overlay.querySelector('.update-copy-btn i');
            icon.className = 'fas fa-check';
            setTimeout(() => { icon.className = 'fas fa-copy'; }, 1500);
            showToast(t('toast.copied'), 'success');
        };

        overlay.querySelector('.update-close-btn').onclick = close;
        overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

        document.body.appendChild(overlay);
    } else {
        // Check for update
        btn.disabled = true;
        await checkForUpdate();
        btn.disabled = false;
    }
}

// ============================================================================
// Event Listeners
// ============================================================================

function initEventListeners() {
    // Add account button
    const addAccountBtn = document.getElementById('addAccountBtn');
    if (addAccountBtn) {
        addAccountBtn.addEventListener('click', openAddAccountModal);
    }

    // Confirm add account
    const confirmBtn = document.getElementById('confirmAddAccount');
    if (confirmBtn) {
        confirmBtn.addEventListener('click', submitAddAccount);
    }

    // Add account modal close buttons
    const addModal = document.getElementById('addAccountModal');
    if (addModal) {
        addModal.querySelectorAll('.modal-close, .modal-cancel').forEach(btn => {
            btn.addEventListener('click', closeAddAccountModal);
        });
        addModal.addEventListener('click', (e) => {
            if (e.target === addModal) closeAddAccountModal();
        });
    }

    // Update cookie modal
    const updateModal = document.getElementById('updateCookieModal');
    if (updateModal) {
        updateModal.querySelectorAll('.modal-close, .modal-cancel').forEach(btn => {
            btn.addEventListener('click', closeUpdateCookieModal);
        });
        updateModal.addEventListener('click', (e) => {
            if (e.target === updateModal) closeUpdateCookieModal();
        });
        const confirmUpdateBtn = document.getElementById('confirmUpdateCookie');
        if (confirmUpdateBtn) {
            confirmUpdateBtn.addEventListener('click', submitUpdateCookie);
        }
    }

    // Playground send
    const pgSend = document.getElementById('pg-send');
    if (pgSend) {
        pgSend.addEventListener('click', sendPlaygroundRequest);
    }

    // Playground textarea: Enter to send, Shift+Enter for newline
    const pgMessage = document.getElementById('pg-message');
    if (pgMessage) {
        pgMessage.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendPlaygroundRequest();
            }
        });
    }

    // Playground clear
    const pgClear = document.getElementById('pg-clear-btn');
    if (pgClear) {
        pgClear.addEventListener('click', clearPlayground);
    }

    // Playground image upload
    const pgImageBtn = document.getElementById('pg-image-btn');
    const pgImageInput = document.getElementById('pg-image-input');
    if (pgImageBtn && pgImageInput) {
        pgImageBtn.addEventListener('click', () => pgImageInput.click());
        pgImageInput.addEventListener('change', (e) => {
            _handlePgImageSelect(e.target.files);
            e.target.value = '';
        });
    }

    // Restart
    const restartBtn = document.getElementById('restartBtn');
    if (restartBtn) {
        restartBtn.addEventListener('click', async () => {
            const confirmed = await showConfirm({
                title: t('confirm.restart.title'),
                message: t('confirm.restart.message'),
                confirmText: t('confirm.restart.btn'),
                cancelText: t('confirm.cancel'),
                type: 'warning'
            });
            if (!confirmed) return;
            restartBtn.classList.add('restarting');
            showToast(t('toast.restarting'), 'success');
            try {
                await apiCall('POST', '/admin/restart');
            } catch (e) {}
            setTimeout(() => {
                const check = setInterval(async () => {
                    try {
                        const resp = await fetch('/health');
                        if (resp.ok) {
                            clearInterval(check);
                            window.location.reload();
                        }
                    } catch (e) {}
                }, 1500);
                setTimeout(() => {
                    clearInterval(check);
                    window.location.reload();
                }, 15000);
            }, 2000);
        });
    }

    // Logout
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', async () => {
            const confirmed = await showConfirm({
                title: t('confirm.logout.title'),
                message: t('confirm.logout.message'),
                confirmText: t('confirm.logout.btn'),
                cancelText: t('confirm.cancel'),
                type: 'info'
            });
            if (confirmed) logout();
        });
    }

    // Refresh account status
    const refreshBtn = document.getElementById('refreshAccountStatusBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', loadDashboard);
    }

    // Check update button
    const checkUpdateBtn = document.getElementById('checkUpdateBtn');
    if (checkUpdateBtn) {
        checkUpdateBtn.addEventListener('click', handleCheckUpdate);
    }

    // Mobile menu toggle
    const mobileToggle = document.getElementById('mobileMenuToggle');
    if (mobileToggle) {
        mobileToggle.addEventListener('click', () => {
            const sidebar = document.querySelector('.sidebar');
            if (sidebar) sidebar.classList.toggle('active');
        });
    }
}

// ============================================================================
// Initialization
// ============================================================================

async function initApp() {
    if (isAppInitialized) return;
    isAppInitialized = true;

    initElements();
    initThemeSwitcher();
    initI18n();
    initLanguageSwitcher();
    initNavigation();
    initEventListeners();
    initLogs();
    initUsageStats();
    initSettings();
    initApiKeys();
    initLightbox();

    console.log('Gemini2API 管理控制台已加载');
}

// Expose functions for onclick handlers
window.app = {
    checkAccount,
    removeAccount,
    openAddAccountModal,
    closeAddAccountModal,
    openUpdateCookieModal,
    closeUpdateCookieModal,
    sendPlaygroundRequest,
    clearPlayground,
    copyModel,
    openLightbox,
    reloadCurrentSection() {
        const activeSection = document.querySelector('.section.active');
        if (activeSection) {
            loadSectionData(activeSection.id);
        }
    }
};

// Wait for components to load, then initialize
window.addEventListener('componentsLoaded', async () => {
    const authSuccess = await initAuth();
    if (authSuccess) {
        await initApp();
    }
});

// Fallback: if components are already in DOM (static HTML)
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(async () => {
        if (!isAppInitialized) {
            const sidebar = document.querySelector('.sidebar');
            if (sidebar) {
                const authSuccess = await initAuth();
                if (authSuccess) await initApp();
            }
        }
    }, 500);
});
