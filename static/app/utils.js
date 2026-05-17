/**
 * 工具函数模块
 */

/**
 * 遮蔽敏感字符串
 * @param {string} str - 原始字符串
 * @param {number} showChars - 显示的字符数
 * @returns {string}
 */
function maskString(str, showChars = 10) {
    if (!str) return '';
    if (str.length <= showChars) return str;
    return str.substring(0, showChars) + '...';
}

/**
 * 格式化数字
 * @param {number} num - 数字
 * @returns {string}
 */
function formatNumber(num) {
    if (num === null || num === undefined) return '0';
    return num.toLocaleString('zh-CN');
}

/**
 * 获取状态徽章HTML
 * @param {string} status - 状态
 * @returns {string}
 */
function getStatusBadge(status) {
    const statusMap = {
        'active': { text: '活跃', class: 'success' },
        'inactive': { text: '不活跃', class: 'secondary' },
        'error': { text: '错误', class: 'danger' },
        'disabled': { text: '已禁用', class: 'secondary' }
    };

    const statusInfo = statusMap[status] || { text: status, class: 'secondary' };
    return `<span class="badge badge-${statusInfo.class}">${statusInfo.text}</span>`;
}

/**
 * 格式化日期
 * @param {string} isoString - ISO日期字符串
 * @returns {string}
 */
function formatDate(isoString) {
    if (!isoString) return '-';
    try {
        const date = new Date(isoString);
        return date.toLocaleString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    } catch (error) {
        return isoString;
    }
}

/**
 * 复制文本到剪贴板
 * @param {string} text - 要复制的文本
 * @returns {Promise<void>}
 */
async function copyToClipboard(text) {
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
        } else {
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.left = '-9999px';
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);
        }
        return true;
    } catch (error) {
        console.error('复制失败:', error);
        return false;
    }
}

/**
 * 显示Toast通知
 * @param {string} message - 消息内容
 * @param {string} type - 消息类型: 'success', 'error', 'warning', 'info'
 */
function showToast(message, type = 'info') {
    // 创建toast容器（如果不存在）
    let toastContainer = document.getElementById('toast-container');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'toast-container';
        toastContainer.className = 'toast-container';
        document.body.appendChild(toastContainer);
    }

    // 创建toast元素
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    // 图标映射
    const iconMap = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle'
    };

    const icon = iconMap[type] || iconMap.info;

    toast.innerHTML = `
        <i class="fas ${icon}"></i>
        <span>${message}</span>
    `;

    toastContainer.appendChild(toast);

    // 触发动画
    setTimeout(() => {
        toast.classList.add('show');
    }, 10);

    // 3秒后移除
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => {
            toast.remove();
        }, 300);
    }, 3000);
}

/**
 * 转义HTML特殊字符
 * @param {string} str - 原始字符串
 * @returns {string}
 */
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

/**
 * 格式化文件大小
 * @param {number} bytes - 字节数
 * @returns {string}
 */
function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

/**
 * 防抖函数
 * @param {Function} func - 要防抖的函数
 * @param {number} wait - 等待时间（毫秒）
 * @returns {Function}
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * 节流函数
 * @param {Function} func - 要节流的函数
 * @param {number} limit - 时间限制（毫秒）
 * @returns {Function}
 */
function throttle(func, limit) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

function showConfirm({ title = '确认操作', message = '', confirmText = '确认', cancelText = '取消', type = 'warning' }) {
    return new Promise((resolve) => {
        const iconMap = { warning: 'fa-exclamation-triangle', danger: 'fa-trash-alt', info: 'fa-info-circle' };
        const colorMap = { warning: 'var(--warning-color, #f59e0b)', danger: 'var(--danger-color)', info: 'var(--primary-color)' };
        const icon = iconMap[type] || iconMap.warning;
        const color = colorMap[type] || colorMap.warning;

        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay active';
        overlay.style.bottom = '0';
        overlay.innerHTML = `
            <div style="background:var(--bg-primary);border-radius:var(--radius-xl,16px);width:90%;max-width:400px;box-shadow:0 20px 60px rgba(0,0,0,0.3);animation:modalIn 0.2s ease">
                <div style="padding:2rem;text-align:center">
                    <div style="width:56px;height:56px;border-radius:50%;background:${color}15;display:inline-flex;align-items:center;justify-content:center;margin-bottom:1rem">
                        <i class="fas ${icon}" style="font-size:1.5rem;color:${color}"></i>
                    </div>
                    <h3 style="margin:0 0 0.5rem;font-size:1.125rem;color:var(--text-primary)">${title}</h3>
                    <p style="margin:0;color:var(--text-secondary);font-size:0.875rem;line-height:1.5">${message}</p>
                </div>
                <div style="display:flex;gap:0.75rem;padding:0 2rem 2rem;justify-content:center">
                    <button class="confirm-cancel-btn" style="flex:1;padding:0.625rem 1.25rem;border-radius:var(--radius-lg,10px);border:1px solid var(--border-color);background:var(--bg-tertiary);color:var(--text-primary);cursor:pointer;font-size:0.875rem;font-weight:500;transition:all 0.2s">${cancelText}</button>
                    <button class="confirm-ok-btn" style="flex:1;padding:0.625rem 1.25rem;border-radius:var(--radius-lg,10px);border:none;background:${color};color:#fff;cursor:pointer;font-size:0.875rem;font-weight:600;transition:all 0.2s">${confirmText}</button>
                </div>
            </div>
        `;

        const close = (result) => {
            overlay.style.opacity = '0';
            setTimeout(() => overlay.remove(), 200);
            resolve(result);
        };

        overlay.querySelector('.confirm-cancel-btn').onclick = () => close(false);
        overlay.querySelector('.confirm-ok-btn').onclick = () => close(true);
        overlay.addEventListener('click', (e) => { if (e.target === overlay) close(false); });

        document.body.appendChild(overlay);
        overlay.querySelector('.confirm-ok-btn').focus();
    });
}

// 导出函数
export {
    maskString,
    formatNumber,
    getStatusBadge,
    formatDate,
    copyToClipboard,
    showToast,
    escapeHtml,
    formatFileSize,
    debounce,
    throttle,
    showConfirm
};
