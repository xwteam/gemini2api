import { apiCall } from './auth.js';
import { showToast } from './utils.js';

let originalSettings = {};

const GROUP_TITLES = {
  performance: '性能',
  rate_limiting: '速率限制',
  health_check: '健康检查',
  account_management: '账号管理',
  usage_stats: '用量统计',
  models: '模型配置',
  logging: '日志'
};

const GROUP_ICONS = {
  performance: 'fa-bolt',
  rate_limiting: 'fa-shield-alt',
  health_check: 'fa-heartbeat',
  account_management: 'fa-users-cog',
  usage_stats: 'fa-chart-line',
  models: 'fa-cube',
  logging: 'fa-file-alt'
};

const FIELD_LABELS = {
  refresh_interval: 'Cookie刷新间隔(分钟)',
  max_retries: '最大重试次数',
  jitter_enabled: '启用时间抖动',
  rate_limit_enabled: '启用速率限制',
  rate_limit_window: '限制窗口(秒)',
  rate_limit_max: '窗口最大请求数',
  health_check_enabled: '启用健康检查',
  health_check_interval: '检查间隔(分钟)',
  rotation_strategy: '轮换策略',
  max_concurrent_per_account: '单账号最大并发',
  usage_stats_enabled: '启用用量统计',
  usage_stats_interval: '快照间隔(秒)',
  usage_stats_retention_days: '数据保留天数',
  model_whitelist: '模型白名单(逗号分隔)',
  log_level: '日志级别'
};

const ROTATION_STRATEGY_OPTIONS = [
  { value: 'round-robin', label: '轮询' },
  { value: 'least-used', label: '最少使用' }
];

const LOG_LEVEL_OPTIONS = [
  { value: 'DEBUG', label: 'DEBUG' },
  { value: 'INFO', label: 'INFO' },
  { value: 'WARNING', label: 'WARNING' },
  { value: 'ERROR', label: 'ERROR' }
];

function createFieldInput(key, value) {
  const type = typeof value;

  if (type === 'boolean') {
    return `
      <label class="toggle-switch">
        <input type="checkbox" data-key="${key}" ${value ? 'checked' : ''}>
        <span class="toggle-slider"></span>
      </label>
    `;
  }

  if (key === 'rotation_strategy') {
    const options = ROTATION_STRATEGY_OPTIONS.map(opt =>
      `<option value="${opt.value}" ${value === opt.value ? 'selected' : ''}>${opt.label}</option>`
    ).join('');
    return `<select class="form-control" data-key="${key}">${options}</select>`;
  }

  if (key === 'log_level') {
    const options = LOG_LEVEL_OPTIONS.map(opt =>
      `<option value="${opt.value}" ${value === opt.value ? 'selected' : ''}>${opt.label}</option>`
    ).join('');
    return `<select class="form-control" data-key="${key}">${options}</select>`;
  }

  if (type === 'number') {
    return `<input type="number" class="form-control" data-key="${key}" value="${value}">`;
  }

  return `<input type="text" class="form-control" data-key="${key}" value="${value}">`;
}

function renderSettings(settings) {
  const container = document.getElementById('settings-container');
  if (!container) return;

  let html = '';

  for (const [groupKey, groupSettings] of Object.entries(settings)) {
    const groupTitle = GROUP_TITLES[groupKey] || groupKey;
    const groupIcon = GROUP_ICONS[groupKey] || 'fa-cog';

    html += '<div class="settings-group">';
    html += '<h3><i class="fas ' + groupIcon + '"></i> ' + groupTitle + '</h3>';
    html += '<div class="settings-fields">';

    for (const [key, value] of Object.entries(groupSettings)) {
      const label = FIELD_LABELS[key] || key;
      const fullKey = groupKey + '.' + key;
      const input = createFieldInput(fullKey, value);
      html += '<div class="setting-field"><label>' + label + '</label>' + input + '</div>';
    }

    html += '</div></div>';
  }

  container.innerHTML = html;
}

function collectFormValues() {
  const values = {};

  document.querySelectorAll('[data-key]').forEach(input => {
    const key = input.dataset.key;
    let value;

    if (input.type === 'checkbox') {
      value = input.checked;
    } else if (input.type === 'number') {
      value = parseInt(input.value, 10);
    } else {
      value = input.value;
    }

    values[key] = value;
  });

  return values;
}

function getChangedSettings(current, original) {
  const changed = {};

  for (const [key, value] of Object.entries(current)) {
    if (original[key] !== value) {
      changed[key] = value;
    }
  }

  return changed;
}

function flattenSettings(settings) {
  const flat = {};
  for (const [groupKey, groupSettings] of Object.entries(settings)) {
    for (const [key, value] of Object.entries(groupSettings)) {
      flat[`${groupKey}.${key}`] = value;
    }
  }
  return flat;
}

export async function loadSettings() {
  try {
    const data = await apiCall('GET', '/admin/settings');
    originalSettings = flattenSettings(data);
    renderSettings(data);
  } catch (error) {
    showToast('加载设置失败: ' + error.message, 'error');
  }
}

async function saveSettings() {
  const currentValues = collectFormValues();
  const changedSettings = getChangedSettings(currentValues, originalSettings);

  if (Object.keys(changedSettings).length === 0) {
    showToast('没有修改', 'info');
    return;
  }

  try {
    await apiCall('POST', '/admin/settings', { settings: changedSettings });

    showToast('设置已保存', 'success');
    await loadSettings();
  } catch (error) {
    showToast('保存设置失败: ' + error.message, 'error');
  }
}

async function resetSettings() {
  await loadSettings();
  showToast('设置已重置', 'info');
}

export function initSettings() {
  const saveBtn = document.getElementById('settings-save-btn');
  const resetBtn = document.getElementById('settings-reset-btn');

  if (saveBtn) {
    saveBtn.addEventListener('click', saveSettings);
  }

  if (resetBtn) {
    resetBtn.addEventListener('click', resetSettings);
  }
}
