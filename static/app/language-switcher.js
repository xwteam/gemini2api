import { setLanguage, getCurrentLanguage, t } from './i18n.js';

const LANGUAGES = [
    { code: 'zh-CN', label: '简体中文', short: '简' },
    { code: 'zh-TW', label: '繁體中文', short: '繁' },
    { code: 'en-US', label: 'English', short: 'EN' },
    { code: 'ja-JP', label: '日本語', short: 'JP' },
    { code: 'ko-KR', label: '한국어', short: 'KR' }
];

export function initLanguageSwitcher() {
    const headerControls = document.querySelector('.header-controls');
    if (!headerControls) return;

    const currentLang = getCurrentLanguage();
    const current = LANGUAGES.find(l => l.code === currentLang) || LANGUAGES[0];

    const switcher = document.createElement('div');
    switcher.className = 'language-switcher';
    switcher.innerHTML = `
        <button class="language-btn" id="languageBtn" title="Switch Language">
            <i class="fas fa-globe"></i>
            <span class="current-lang">${current.short}</span>
        </button>
        <div class="language-dropdown" id="languageDropdown">
            ${LANGUAGES.map(lang => `
                <button class="language-option ${lang.code === currentLang ? 'active' : ''}" data-lang="${lang.code}">
                    <span class="lang-label">${lang.label}</span>
                    ${lang.code === currentLang ? '<i class="fas fa-check"></i>' : ''}
                </button>
            `).join('')}
        </div>
    `;

    const logoutBtn = headerControls.querySelector('#logoutBtn');
    if (logoutBtn) {
        headerControls.insertBefore(switcher, logoutBtn);
    } else {
        headerControls.appendChild(switcher);
    }

    bindEvents(switcher);
}

function bindEvents(switcher) {
    const btn = switcher.querySelector('#languageBtn');
    const dropdown = switcher.querySelector('#languageDropdown');

    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        dropdown.classList.toggle('show');
    });

    dropdown.querySelectorAll('.language-option').forEach(option => {
        option.addEventListener('click', (e) => {
            e.stopPropagation();
            const lang = option.getAttribute('data-lang');
            const langInfo = LANGUAGES.find(l => l.code === lang);

            setLanguage(lang);

            btn.querySelector('.current-lang').textContent = langInfo.short;

            dropdown.querySelectorAll('.language-option').forEach(opt => {
                opt.classList.remove('active');
                opt.querySelector('.fa-check')?.remove();
            });
            option.classList.add('active');
            option.insertAdjacentHTML('beforeend', ' <i class="fas fa-check"></i>');

            dropdown.classList.remove('show');
        });
    });

    document.addEventListener('click', () => {
        dropdown.classList.remove('show');
    });
}
