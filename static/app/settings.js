import { apiCall } from './auth.js';
import { showToast } from './utils.js';
import { t } from './i18n.js';

let originalSettings = {};
let modelMappings = {};

function getGroupTitle(groupKey) {
  const map = {
    performance: 'settings.group.performance',
    rate_limiting: 'settings.group.rateLimit',
    health_check: 'settings.group.healthCheck',
    account_management: 'settings.group.accounts',
    usage_stats: 'settings.group.stats'
  };
  return t(map[groupKey] || groupKey);
}

const GROUP_ICONS = {
  performance: 'fa-bolt',
  rate_limiting: 'fa-shield-alt',
  health_check: 'fa-heartbeat',
  account_management: 'fa-users-cog',
  usage_stats: 'fa-chart-line'
};

function getFieldLabel(key) {
  const map = {
    refresh_interval: 'settings.field.refreshInterval',
    max_retries: 'settings.field.maxRetries',
    jitter_enabled: 'settings.field.jitterEnabled',
    rate_limit_enabled: 'settings.field.rateLimitEnabled',
    rate_limit_window: 'settings.field.rateLimitWindow',
    rate_limit_max: 'settings.field.rateLimitMax',
    health_check_enabled: 'settings.field.healthCheckEnabled',
    health_check_interval: 'settings.field.healthCheckInterval',
    rotation_strategy: 'settings.field.rotationStrategy',
    max_concurrent_per_account: 'settings.field.maxConcurrent',
    usage_stats_enabled: 'settings.field.usageStatsEnabled',
    usage_stats_interval: '快照间隔(秒)',
    usage_stats_retention_days: '数据保留天数'
  };
  return map[key] ? (map[key].startsWith('settings.') ? t(map[key]) : map[key]) : key;
}

const ROTATION_OPTIONS = [
  { value: 'round-robin', label: '轮询' },
  { value: 'least-used', label: '最少使用' }
];

function createFieldInput(key, value) {
  const type = typeof value;

  if (type === 'boolean') {
    return `
      <label class="toggle-switch">
        <input type="checkbox" data-key="${key}" ${value ? 'checked' : ''}>
      </label>
    `;
  }

  if (key.endsWith('.rotation_strategy')) {
    const radios = ROTATION_OPTIONS.map(opt =>
      `<label class="radio-option">
        <input type="radio" name="rotation_strategy" data-key="${key}" value="${opt.value}" ${value === opt.value ? 'checked' : ''}>
        <span>${opt.label}</span>
      </label>`
    ).join('');
    return `<div class="radio-group">${radios}</div>`;
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
    const groupTitle = getGroupTitle(groupKey);
    const groupIcon = GROUP_ICONS[groupKey] || 'fa-cog';

    html += '<div class="settings-group">';
    html += '<h3><i class="fas ' + groupIcon + '"></i> ' + groupTitle + '</h3>';
    html += '<div class="settings-fields">';

    for (const [key, value] of Object.entries(groupSettings)) {
      const label = getFieldLabel(key);
      const fullKey = groupKey + '.' + key;
      const input = createFieldInput(fullKey, value);
      html += '<div class="setting-field"><label>' + label + '</label>' + input + '</div>';
    }

    html += '</div></div>';
  }

  container.innerHTML = html;
}

function renderModelMapping() {
  const container = document.getElementById('model-mapping-container');
  if (!container) return;

  const entries = Object.entries(modelMappings);

  let html = '<div class="settings-group">';
  html += '<h3><i class="fas fa-exchange-alt"></i> <span data-i18n="settings.modelMapping">' + t('settings.modelMapping') + '</span></h3>';
  html += '<p class="mapping-desc" data-i18n="settings.modelMappingDesc">' + t('settings.modelMappingDesc') + '</p>';
  html += '<div class="mapping-header"><span data-i18n="settings.requestModel">' + t('settings.requestModel') + '</span><span data-i18n="settings.actualModel">' + t('settings.actualModel') + '</span><span></span></div>';

  for (const [alias, target] of entries) {
    html += '<div class="mapping-row" data-alias="' + alias + '">';
    html += '<input type="text" class="form-control mapping-alias" value="' + alias + '" readonly>';
    html += '<input type="text" class="form-control mapping-target" value="' + target + '">';
    html += '<button class="btn-icon btn-delete-mapping" data-alias="' + alias + '"><i class="fas fa-trash"></i></button>';
    html += '</div>';
  }

  html += '<div class="mapping-row mapping-new">';
  html += '<input type="text" class="form-control" id="new-mapping-alias" data-i18n-placeholder="settings.aliasPlaceholder" placeholder="' + t('settings.aliasPlaceholder') + '">';
  html += '<input type="text" class="form-control" id="new-mapping-target" data-i18n-placeholder="settings.targetPlaceholder" placeholder="' + t('settings.targetPlaceholder') + '">';
  html += '<button class="btn-icon btn-add-mapping" id="btn-add-mapping"><i class="fas fa-plus"></i></button>';
  html += '</div>';
  html += '</div>';
  html += '<div class="mapping-actions">';
  html += '<button class="btn btn-primary" id="btn-save-mapping"><span data-i18n="settings.saveMapping">' + t('settings.saveMapping') + '</span></button>';
  html += '</div>';
  html += '</div>';

  container.innerHTML = html;
  bindMappingEvents();
}

function bindMappingEvents() {
  document.getElementById('btn-add-mapping')?.addEventListener('click', addMapping);
  document.getElementById('btn-save-mapping')?.addEventListener('click', saveAllMappings);
  document.querySelectorAll('.btn-delete-mapping').forEach(btn => {
    btn.addEventListener('click', () => deleteMapping(btn.dataset.alias));
  });
  document.getElementById('new-mapping-target')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') addMapping();
  });
}

async function addMapping() {
  const aliasInput = document.getElementById('new-mapping-alias');
  const targetInput = document.getElementById('new-mapping-target');
  const alias = aliasInput.value.trim();
  const target = targetInput.value.trim();

  if (!alias || !target) {
    showToast('请填写别名和目标模型', 'warning');
    return;
  }
  if (alias === target) {
    showToast('别名不能与目标相同', 'warning');
    return;
  }

  try {
    await apiCall('POST', '/admin/model-mapping', { alias, target });
    showToast('映射已添加', 'success');
    await loadModelMapping();
  } catch (error) {
    showToast('添加失败: ' + error.message, 'error');
  }
}

async function deleteMapping(alias) {
  try {
    await apiCall('DELETE', '/admin/model-mapping/' + encodeURIComponent(alias));
    showToast('映射已删除', 'success');
    await loadModelMapping();
  } catch (error) {
    showToast('删除失败: ' + error.message, 'error');
  }
}

async function saveAllMappings() {
  const rows = document.querySelectorAll('.mapping-row:not(.mapping-new)');
  let updated = 0;

  for (const row of rows) {
    const alias = row.dataset.alias;
    const target = row.querySelector('.mapping-target').value.trim();
    if (target && target !== modelMappings[alias]) {
      try {
        await apiCall('POST', '/admin/model-mapping', { alias, target });
        updated++;
      } catch (error) {
        showToast('更新 ' + alias + ' 失败: ' + error.message, 'error');
      }
    }
  }

  if (updated > 0) {
    showToast('已更新 ' + updated + ' 条映射', 'success');
  } else {
    showToast('无变更', 'info');
  }
  await loadModelMapping();
}

async function loadModelMapping() {
  try {
    const data = await apiCall('GET', '/admin/model-mapping');
    modelMappings = data.mappings || {};
    renderModelMapping();
  } catch (error) {
    showToast('加载模型映射失败: ' + error.message, 'error');
  }
}

function collectFormValues() {
  const values = {};

  document.querySelectorAll('#settings-container [data-key]').forEach(input => {
    const key = input.dataset.key;

    if (input.type === 'radio') {
      if (input.checked) {
        values[key] = input.value;
      }
      return;
    }

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
      flat[groupKey + '.' + key] = value;
    }
  }
  return flat;
}

export async function loadSettings() {
  try {
    const data = await apiCall('GET', '/admin/settings');
    originalSettings = flattenSettings(data);
    renderSettings(data);
    await loadModelMapping();
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

  const apiSettings = {};
  for (const [key, value] of Object.entries(changedSettings)) {
    const fieldName = key.split('.').pop();
    apiSettings[fieldName] = value;
  }

  try {
    await apiCall('POST', '/admin/settings', { settings: apiSettings });
    showToast(t('settings.saved'), 'success');
    await loadSettings();
  } catch (error) {
    showToast(t('settings.saveFailed') + ': ' + error.message, 'error');
  }
}

async function resetSettings() {
  await loadSettings();
  showToast(t('settings.resetDone'), 'info');
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
