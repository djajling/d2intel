/* D2INTEL prototype — render from the mock JSON contract.
   The contract is the single source of truth for demo data. It can later be
   swapped for a real API response with the same shape. No fabricated "battle"
   data is ever treated as a real forecast. */

const $ = (sel) => document.querySelector(sel);

function loadContract() {
  // Preferred: external mock contract file (used when served over http).
  // Fallback: the same JSON embedded in index.html (used when opened as a file).
  return fetch('./match.snapshot.json', { cache: 'no-store' })
    .then((res) => (res.ok ? res.json() : Promise.reject()))
    .catch(() => {
      const fb = document.getElementById('match-contract-fallback');
      if (fb) return JSON.parse(fb.textContent);
      throw new Error('contract unavailable');
    });
}

function fmtUTC(iso) {
  const d = new Date(iso);
  const hh = String(d.getUTCHours()).padStart(2, '0');
  const mm = String(d.getUTCMinutes()).padStart(2, '0');
  return `${hh}:${mm} UTC`;
}

function scenarioLabel(bands, probability) {
  for (const band of bands) {
    if (probability < band.upto) return band.label;
  }
  return bands[bands.length - 1].label;
}

function renderEvidence(list) {
  const root = $('#evidence-list');
  if (!root) return;
  root.innerHTML = '';
  list.forEach((item) => {
    const positive = item.direction !== 'negative';
    const width = Math.max(10, Math.min(46, Math.abs(item.delta) * 4));
    const bar = document.createElement('span');
    bar.className =
      'evidence-bar ' + (positive ? 'evidence-bar--positive' : 'evidence-bar--negative');
    if (width < 28) bar.classList.add('evidence-bar--short');
    bar.style.width = `${width}px`;

    const value = document.createElement('strong');
    value.textContent = `${item.delta > 0 ? '+' : '−'}${Math.abs(item.delta).toFixed(1)}%`;

    const label = document.createElement('span');
    label.textContent = item.label;

    const cell = document.createElement('div');
    cell.appendChild(value);
    cell.appendChild(label);

    const row = document.createElement('div');
    row.className = 'evidence';
    row.appendChild(bar);
    row.appendChild(cell);
    root.appendChild(row);
  });
}

function renderHeroes(pool) {
  const portraits = $('#hero-portraits');
  const chips = $('#hero-chips');
  if (portraits) {
    portraits.innerHTML = '';
    pool.forEach((hero, i) => {
      const n = i + 1;
      const fig = document.createElement('div');
      fig.className = `hero-portrait hero-portrait--${n === 1 ? 'one' : n === 2 ? 'two' : 'three'}`;
      fig.innerHTML =
        `<img src="${hero.image}" alt="" loading="lazy" decoding="async" />` +
        '<span class="hero-tag">DEMO</span>' +
        `<span class="hero-name">${hero.name}</span>`;
      portraits.appendChild(fig);
    });
  }
  if (chips) {
    chips.innerHTML = '';
    pool.forEach((hero) => {
      const li = document.createElement('li');
      li.textContent = hero.name;
      chips.appendChild(li);
    });
  }
}

function renderRoster(fixture) {
  const root = $('#roster-rows');
  if (!root) return;
  root.innerHTML = '';
  [fixture.team_a, fixture.team_b].forEach((team) => {
    const row = document.createElement('div');
    row.className = 'roster-row';
    const statusClass = team.roster_status === 'confirmed' ? 'good' : 'neutral';
    row.innerHTML =
      `<span class="roster-team">${team.name.toUpperCase()}</span>` +
      '<div class="player-dots"><i></i><i></i><i></i><i></i><i></i></div>' +
      `<span class="roster-status roster-status--${statusClass}">${team.roster_status.toUpperCase()}</span>`;
    root.appendChild(row);
  });
}

function renderLedger(rows) {
  const body = $('#ledger-body');
  if (!body) return;
  body.innerHTML = '';
  rows.forEach((r) => {
    const anchor = document.createElement('a');
    anchor.className = 'ledger-row';
    anchor.href = '#match';
    anchor.setAttribute('role', 'row');
    anchor.setAttribute('tabindex', '0');
    const resultClass = r.status_kind === 'miss' ? 'outcome outcome--miss' : 'outcome';
    const pillClass = r.status_kind === 'open' ? 'status-pill status-pill--open' : 'status-pill';
    anchor.innerHTML =
      `<span class="mono" role="cell">${r.snapshot_id}</span>` +
      `<span role="cell"><strong>${r.team_a}</strong> <i>vs</i> ${r.team_b}<small>${r.event}</small></span>` +
      `<span class="prob-chip" role="cell">${r.prob_chip}</span>` +
      `<span role="cell" class="${r.status_kind === 'open' ? 'pending' : resultClass}">${r.result}</span>` +
      `<span role="cell"><b class="${pillClass}">${r.status}</b></span>`;
    body.appendChild(anchor);
  });
  return body;
}

function renderProvenance(c) {
  const dl = $('#provenance');
  if (!dl) return;
  const entries = [
    ['SNAPSHOT', c.snapshot_id],
    ['COMPUTED', fmtUTC(c.computed_at)],
    ['CUTOFF', fmtUTC(c.cutoff_at)],
    ['MODEL', c.model_version_id],
    ['FEATURE', c.feature_snapshot_id],
    ['MODE', c.evaluation_mode],
    ['SOURCES', c.sources.map((s) => `${s.id} (${s.access})`).join(' · ')],
  ];
  dl.innerHTML = entries
    .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`)
    .join('');
}

function renderChart(form) {
  const area = $('#area-a');
  const lineA = $('#line-a');
  const lineB = $('#line-b');
  const endA = $('#chart-end-a');
  const endB = $('#chart-end-b');
  if (area) area.setAttribute('d', form.team_a_path);
  if (lineA) lineA.setAttribute('d', form.team_a_line);
  if (lineB) lineB.setAttribute('d', form.team_b_line);
  if (endA) {
    endA.setAttribute('cx', form.team_a_end.x);
    endA.setAttribute('cy', form.team_a_end.y);
  }
  if (endB) {
    endB.setAttribute('cx', form.team_b_end.x);
    endB.setAttribute('cy', form.team_b_end.y);
  }
}

function setupSlider(contract) {
  const control = $('#probability-control');
  const value = $('#probability-value');
  const fill = $('#probability-fill');
  const pulse = $('.probability-pulse');
  const scenarioName = $('#scenario-name');
  const scenarioLive = $('#scenario-live');
  const { slider, scenario_bands: bands, team_a_win_probability: base } = contract.prediction;

  if (control) {
    control.min = slider.min;
    control.max = slider.max;
    control.value = slider.default;
  }

  function update() {
    const probability = Number(control.value);
    value.value = probability;
    value.textContent = probability;
    fill.style.width = `${probability}%`;
    if (pulse) pulse.style.left = `${probability}%`;
    fill.style.background = probability < 50 ? 'var(--hot)' : 'var(--acid)';
    const label = scenarioLabel(bands, probability);
    scenarioName.textContent = label;
    if (scenarioLive) scenarioLive.textContent =
      `Демонстрационный сценарий: ${label}, вероятность ${probability}%.`;
  }

  if (control) control.addEventListener('input', update);
  update();
  return update;
}

function setupInteractions(ledgerBody) {
  const notice = $('.demo-notice');
  const closeNotice = $('.notice-close');
  const filterButton = $('.filter-button');

  if (closeNotice && notice) {
    closeNotice.addEventListener('click', () => notice.classList.add('demo-notice--hidden'));
  }
  if (filterButton && ledgerBody) {
    filterButton.addEventListener('click', () => {
      const active = filterButton.getAttribute('aria-pressed') === 'true';
      filterButton.setAttribute('aria-pressed', String(!active));
      ledgerBody.querySelectorAll('.ledger-row').forEach((row) => {
        const isPending = row.querySelector('.status-pill--open');
        row.hidden = !active && Boolean(isPending);
      });
    });
  }
}

function setupReveal() {
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
}

function setupImageFallback() {
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
}

function render(contract) {
  const { fixture, prediction, evidence, hero_pool, form_trajectory, ledger } = contract;

  $('#match-meta').innerHTML =
    `<span>${fixture.tournament}</span><span>•</span>` +
    `<span>${fixture.series_format} / GAME ${fixture.game_number}</span><span>•</span>` +
    `<span>PATCH ${fixture.patch}</span>`;

  $('#team-a-label').textContent = fixture.team_a.name;
  $('#match-heading').textContent = fixture.team_a.name;
  $('#team-b-name').textContent = fixture.team_b.name;

  $('#signal-capture').textContent = `CAPTURED ${fmtUTC(contract.computed_at)}`;
  $('#signal-confidence').textContent = prediction.confidence.toFixed(2);
  $('#signal-confidence-note').textContent = prediction.confidence_note;

  renderEvidence(evidence);
  renderHeroes(hero_pool);
  renderRoster(fixture);
  renderLedger(ledger);
  renderProvenance(contract);
  renderChart(form_trajectory);

  const ledgerBody = $('#ledger-body');
  setupSlider(contract);
  setupInteractions(ledgerBody);
  setupImageFallback();
}

setupReveal();
loadContract()
  .then(render)
  .catch((err) => console.error('[d2intel] contract render failed:', err));
