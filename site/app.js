const control = document.querySelector('#probability-control');
const value = document.querySelector('#probability-value');
const fill = document.querySelector('#probability-fill');
const pulse = document.querySelector('.probability-pulse');
const scenarioName = document.querySelector('#scenario-name');
const scenarioLive = document.querySelector('#scenario-live');
const notice = document.querySelector('.demo-notice');
const closeNotice = document.querySelector('.notice-close');
const filterButton = document.querySelector('.filter-button');
const ledgerRows = [...document.querySelectorAll('.ledger-row')];

function labelForProbability(probability) {
  if (probability < 47) return 'Преимущество Falcons';
  if (probability < 54) return 'Почти равные шансы';
  if (probability < 66) return 'Умеренное преимущество';
  return 'Выраженное преимущество';
}

function updateScenario() {
  const probability = Number(control.value);
  value.value = probability;
  value.textContent = probability;
  fill.style.width = `${probability}%`;
  if (pulse) pulse.style.left = `${probability}%`;
  fill.style.background = probability < 50 ? 'var(--hot)' : 'var(--acid)';
  const label = labelForProbability(probability);
  scenarioName.textContent = label;
  if (scenarioLive) scenarioLive.textContent = `Демонстрационный сценарий: ${label}, вероятность ${probability}%.`;
}

control.addEventListener('input', updateScenario);
closeNotice.addEventListener('click', () => notice.classList.add('demo-notice--hidden'));

filterButton.addEventListener('click', () => {
  const active = filterButton.getAttribute('aria-pressed') === 'true';
  filterButton.setAttribute('aria-pressed', String(!active));
  ledgerRows.forEach((row) => {
    const isPending = row.querySelector('.status-pill--open');
    row.hidden = !active && Boolean(isPending);
  });
});

/* Progressive enhancement: reveal sections on scroll only when JS is available. */
document.documentElement.classList.add('js-reveal');
const reveals = [...document.querySelectorAll('[data-reveal]')];
if ('IntersectionObserver' in window) {
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    },
    { rootMargin: '0px 0px -8% 0px', threshold: 0.08 }
  );
  reveals.forEach((el) => observer.observe(el));
} else {
  reveals.forEach((el) => el.classList.add('is-visible'));
}

/* Graceful fallback for external assets that fail to load: show a monogram
   instead of a broken image. This is purely visual and does not inject data. */
document.querySelectorAll('img').forEach((img) => {
  img.addEventListener('error', () => {
    const wrap = img.closest('.team-logo, .hero-portrait');
    if (!wrap) return;
    const mono = img.dataset.mono || (img.getAttribute('alt') || '?').trim().charAt(0);
    wrap.setAttribute('data-mono', mono);
    wrap.classList.add('asset-failed');
    img.remove();
  });
});

updateScenario();
