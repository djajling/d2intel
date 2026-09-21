const control = document.querySelector('#probability-control');
const value = document.querySelector('#probability-value');
const fill = document.querySelector('#probability-fill');
const scenarioName = document.querySelector('#scenario-name');
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
  fill.style.background = probability < 50 ? 'var(--hot)' : 'var(--acid)';
  scenarioName.textContent = labelForProbability(probability);
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

updateScenario();

