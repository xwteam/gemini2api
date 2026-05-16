/**
 * Gemini2API 管理面板 - 主应用入口
 */

import { initializeComponents } from './component-loader.js';
import { initThemeSwitcher } from './theme-switcher.js';
import { initAuth, apiCall, logout } from './auth.js';
import { showToast, formatNumber, getStatusBadge, maskString, copyToClipboard } from './utils.js';
import { initUsageStats, loadUsageStats } from './usage-chart.js';
import { initLogs } from './logs.js';
import { initSettings, loadSettings } from './settings.js';
import { initApiKeys, loadApiKeys } from './api-keys.js';

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
            case 'config':
                await loadConfig();
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

        setText('info-strategy', data.strategy || '-');
        setText('info-concurrent', data.max_concurrent_per_account || '-');
        setText('info-healthy', activeCount > 0 ? '正常' : '异常');
        setText('info-python', '3.12');

        renderAccountStatusGrid(accounts);
        renderModelsList(modelsSet);
        updatePlaygroundModels(modelsSet);
    } catch (error) {
        console.error('加载仪表盘失败:', error);
    }
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
                <span class="label">请求数</span>
                <span class="value">${formatNumber(account.request_count || 0)}</span>
            </div>
            <div class="account-detail">
                <span class="label">错误数</span>
                <span class="value">${formatNumber(account.error_count || 0)}</span>
            </div>
            <div class="account-detail">
                <span class="label">并发</span>
                <span class="value">${account.active_requests || 0}</span>
            </div>
            <div class="account-detail">
                <span class="label">模型数</span>
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
        container.innerHTML = '<span class="text-muted">暂无可用模型</span>';
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
        select.innerHTML = '<option value="">暂无可用模型</option>';
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
                        <i class="fas fa-plus"></i> 添加第一个账号
                    </button>
                </div>`;
            return;
        }

        container.innerHTML = accounts.map(account => `
            <div class="account-card">
                <div class="account-card-header">
                    <div>
                        <h4>${account.label || '未命名账号'}</h4>
                        <span class="text-muted">ID: ${account.id}</span>
                    </div>
                    ${getStatusBadge(account.status)}
                </div>
                <div class="account-detail">
                    <span class="label">PSID</span>
                    <span class="value">${maskString(account.psid || '', 12)}</span>
                </div>
                <div class="account-detail">
                    <span class="label">请求数</span>
                    <span class="value">${formatNumber(account.request_count || 0)}</span>
                </div>
                <div class="account-detail">
                    <span class="label">错误数</span>
                    <span class="value">${formatNumber(account.error_count || 0)}</span>
                </div>
                <div class="account-detail">
                    <span class="label">模型</span>
                    <span class="value">${(account.models || []).length || account.models_count || 0}</span>
                </div>
                <div class="account-actions">
                    <button class="btn btn-sm btn-outline" onclick="window.app.checkAccount('${account.id}')">
                        <i class="fas fa-heartbeat"></i> 检测
                    </button>
                    <button class="btn btn-sm btn-outline" onclick="window.app.openUpdateCookieModal('${account.id}', '${account.label || ''}')">
                        <i class="fas fa-cookie-bite"></i> 更新Cookie
                    </button>
                    <button class="btn btn-sm btn-danger" onclick="window.app.removeAccount('${account.id}')">
                        <i class="fas fa-trash"></i> 删除
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
        showToast('正在检测账号...', 'info');
        const result = await apiCall('GET', `/admin/accounts/${accountId}/check`);
        const msg = result.valid ? '账号有效' : '账号无效';
        showToast(`${msg} | 模型: ${result.models_count || 0}`, result.valid ? 'success' : 'error');
        await loadAccounts();
        await loadDashboard();
    } catch (error) {
        showToast(`检测失败: ${error.message}`, 'error');
    }
}

async function removeAccount(accountId) {
    if (!confirm('确定要删除此账号吗？此操作不可撤销。')) return;

    try {
        showToast('正在删除...', 'info');
        await apiCall('DELETE', `/admin/accounts/${accountId}`);
        showToast('账号已删除', 'success');
        await loadAccounts();
        await loadDashboard();
    } catch (error) {
        showToast(`删除失败: ${error.message}`, 'error');
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
        showToast('正在添加账号...', 'info');
        await apiCall('POST', '/admin/accounts', { psid, psidts, label });
        showToast('账号添加成功', 'success');
        closeAddAccountModal();
        await loadAccounts();
        await loadDashboard();
    } catch (error) {
        showToast(`添加失败: ${error.message}`, 'error');
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
// Config
// ============================================================================

async function loadConfig() {
    try {
        const data = await apiCall('GET', '/admin/status');
        const container = document.getElementById('configDisplay');
        if (!container) return;

        container.innerHTML = `
            <div class="config-item">
                <span class="config-key">轮询策略</span>
                <span class="config-value">${data.strategy || '-'}</span>
            </div>
            <div class="config-item">
                <span class="config-key">单账号并发上限</span>
                <span class="config-value">${data.max_concurrent_per_account || '-'}</span>
            </div>
            <div class="config-item">
                <span class="config-key">账号总数</span>
                <span class="config-value">${(data.accounts || []).length}</span>
            </div>
            <div class="config-item">
                <span class="config-key">活跃账号</span>
                <span class="config-value">${(data.accounts || []).filter(a => a.status === 'active').length}</span>
            </div>
        `;
    } catch (error) {
        console.error('加载配置失败:', error);
    }
}

// ============================================================================
// Playground
// ============================================================================

async function sendPlaygroundRequest() {
    const message = document.getElementById('pg-message')?.value.trim();
    const model = document.getElementById('pg-model')?.value;
    const chatContainer = document.getElementById('pg-chat');

    if (!message) {
        showToast('请输入消息内容', 'warning');
        return;
    }

    const placeholder = chatContainer?.querySelector('.chat-placeholder');
    if (placeholder) placeholder.remove();

    const userMsg = document.createElement('div');
    userMsg.className = 'chat-message user';
    userMsg.innerHTML = `
        <div class="chat-avatar"><i class="fas fa-user"></i></div>
        <div class="chat-bubble">${escapeHtml(message)}</div>
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

    const token = localStorage.getItem('gemini2api_token');
    try {
        const resp = await fetch('/openai/v1/chat/completions', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                model: model || 'gemini-2.5-flash-preview-05-20',
                messages: [{ role: 'user', content: message }],
                stream: true
            })
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
                        aiBubble.textContent = content;
                        chatContainer.scrollTop = chatContainer.scrollHeight;
                    }
                } catch {}
            }
        }

        if (!content) {
            aiBubble.textContent = '无响应内容';
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

function clearPlayground() {
    const chatContainer = document.getElementById('pg-chat');
    if (chatContainer) {
        chatContainer.innerHTML = '<div class="chat-placeholder"><i class="fas fa-comment-dots"></i><p>发送消息开始对话</p></div>';
    }
    const message = document.getElementById('pg-message');
    if (message) message.value = '';
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

    // Logout
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', () => {
            if (confirm('确定要退出登录吗？')) logout();
        });
    }

    // Refresh account status
    const refreshBtn = document.getElementById('refreshAccountStatusBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', loadDashboard);
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
    initNavigation();
    initEventListeners();
    initLogs();
    initUsageStats();
    initSettings();
    initApiKeys();

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
    copyModel
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
