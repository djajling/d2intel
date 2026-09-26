/* D2INTEL local workbench. All displayed counts and snapshots come from the API. */

const PAGE_SIZE = 12;
const API_BASE = '/api';
const $ = (selector, root = document) => root.querySelector(selector);
const state = {
  overview: null,
  matches: [],
  matchTotal: 0,
  matchOffset: 0,
  matchSearch: '',
  matchRequest: 0,
  snapshots: [],
  snapshotsById: new Map(),
  visibleSnapshots: [],
  activeMatch: null,
  pendingPrediction: false,
  predictionFilter: 'all',
  predictionSearch: '',
  predictionsError: '',
};

const FEATURE_LABELS = {
  d_team_wr_lifetime: ['Разница win rate · вся история', 'п. п.'],
  d_team_wr_last_long: ['Разница win rate · последние 20 карт', 'п. п.'],
  d_team_wr_last_short: ['Разница win rate · последние 10 карт', 'п. п.'],
  d_team_n_eff: ['Разница эффективного объёма истории', 'карт'],
  d_team_days_since_last: ['Разница дней с последней карты', 'дн.'],
  d_player_wr: ['Разница prior-form игроков · win rate', 'п. п.'],
  d_player_kda: ['Разница prior-form игроков · KDA', 'KDA'],
  d_player_gpm: ['Разница prior-form игроков · GPM', 'GPM'],
  d_player_xpm: ['Разница prior-form игроков · XPM', 'XPM'],
};

const dateFormat = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit', month: 'short', year: 'numeric',
});
const timeFormat = new Intl.DateTimeFormat('ru-RU', {
  hour: '2-digit', minute: '2-digit', timeZone: 'UTC', timeZoneName: 'short',
});
const dateTimeFormat = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  timeZone: 'UTC', timeZoneName: 'short',
});

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function formatDate(value) {
  if (!value) return 'Дата неизвестна';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Дата неизвестна' : dateFormat.format(date);
}

function formatTime(value) {
  if (!value) return 'время неизвестно';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'время неизвестно' : timeFormat.format(date);
}

function formatDateTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : dateTimeFormat.format(date);
}

function formatProbability(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  return `${Math.round(Number(value) * 100)}%`;
}

function formatMetric(key, value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return 'Нет данных';
  const number = Number(value);
  if (key.startsWith('d_team_wr_') || key === 'd_player_wr') {
    const points = number * 100;
    const prefix = points > 0 ? '+' : points < 0 ? '−' : '';
    return `${prefix}${Math.abs(points).toFixed(1)} п. п.`;
  }
  const places = Math.abs(number) < 10 ? 2 : 1;
  const prefix = number > 0 ? '+' : number < 0 ? '−' : '';
  const units = FEATURE_LABELS[key]?.[1];
  return `${prefix}${Math.abs(number).toFixed(places)}${units ? ` ${units}` : ''}`;
}

function initials(value) {
  const words = String(value || '').trim().split(/\s+/).filter(Boolean);
  if (!words.length) return '??';
  return words.length === 1
    ? words[0].slice(0, 2).toUpperCase()
    : `${words[0][0]}${words[words.length - 1][0]}`.toUpperCase();
}

function describeError(error) {
  return error instanceof Error && error.message
    ? error.message
    : 'Не удалось связаться с локальным API.';
}

async function requestJSON(path, options = {}) {
  let response;
  try {
    const url = path === '/health' ? path : `${API_BASE}${path}`;
    response = await fetch(url, {
      cache: 'no-store',
      ...options,
      headers: { Accept: 'application/json', ...options.headers },
    });
  } catch {
    throw new Error('Локальный API недоступен. Проверьте, что D2INTEL запущен.');
  }

  let body;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    const detail = typeof body?.detail === 'string' ? body.detail : null;
    throw new Error(detail || `Запрос завершился с ошибкой ${response.status}.`);
  }
  return body;
}

function setHealth(isHealthy, label) {
  const indicator = $('#health-indicator');
  indicator?.classList.toggle('health-indicator--up', isHealthy === true);
  indicator?.classList.toggle('health-indicator--down', isHealthy === false);
  const text = $('#health-label');
  if (text) text.textContent = label;
}

function updateOverview(data) {
  state.overview = data;
  $('#stat-match-count').textContent = Number(data.eligible_matches || 0).toLocaleString('ru-RU');
  $('#stat-snapshot-count').textContent = Number(data.saved_snapshots || 0).toLocaleString('ru-RU');
  $('#stat-evaluated-count').textContent = Number(data.evaluated_snapshots || 0).toLocaleString('ru-RU');
  $('#stat-observed-note').textContent = `Проспективных наблюдений: ${Number(data.observed_snapshots || 0).toLocaleString('ru-RU')}`;
  $('#nav-match-count').textContent = Number(data.eligible_matches || 0).toLocaleString('ru-RU');

  const modelAvailable = data.model_available === true;
  const modelRegistered = Boolean(data.latest_model_version_id);
  const status = $('#stat-model-status');
  const dot = $('#model-status-dot');
  status.textContent = modelAvailable ? 'Доступна' : modelRegistered ? 'Артефакт не найден' : 'Не обучена';
  status.classList.toggle('metric-status-value--ready', modelAvailable);
  status.classList.toggle('metric-status-value--missing', !modelAvailable);
  $('#stat-model-version').textContent = modelRegistered
    ? `${data.latest_feature_schema_version || 'LR'} · ${String(data.latest_model_version_id).slice(0, 8)}`
    : 'Сначала зарегистрируйте baseline Logistic Regression';
  dot.classList.toggle('sidebar-status-dot--ready', modelAvailable);
  dot.classList.toggle('sidebar-status-dot--missing', !modelAvailable);
  $('#model-status-label').textContent = modelAvailable
    ? 'LR · готова к расчёту'
    : modelRegistered ? 'Артефакт модели недоступен' : 'Модель не зарегистрирована';
  $('#model-sidebar-status').textContent = modelAvailable
    ? 'Baseline доступен локально. Новый расчёт сохранит отдельный снимок.'
    : modelRegistered
      ? 'Версия модели зарегистрирована, но её файл не найден в каталоге артефактов.'
      : 'В этой базе пока нет зарегистрированной версии модели.';

  $('#stat-match-note').textContent = data.latest_match_at
    ? `Последняя карта в базе: ${formatDate(data.latest_match_at)}`
    : 'В базе пока нет завершённых карт';
}

function renderMatchPlaceholder(message, kind = '') {
  const body = $('#match-body');
  body.replaceChildren();
  const row = el('tr', `placeholder-row${kind ? ` placeholder-row--${kind}` : ''}`);
  const cell = el('td', '', message);
  cell.colSpan = 6;
  row.append(cell);
  body.append(row);
}

function latestSnapshotsByGame() {
  const result = new Map();
  for (const snapshot of state.snapshots) {
    if (!snapshot.target_game_id) continue;
    const current = result.get(snapshot.target_game_id);
    if (!current || Number(snapshot.snapshot_seq) > Number(current.snapshot_seq)) {
      result.set(snapshot.target_game_id, snapshot);
    }
  }
  return result;
}

function appendTeam(name, side) {
  const team = el('span', `team-token team-token--${side}`);
  team.append(el('span', 'team-monogram', initials(name)));
  team.append(el('span', 'team-name', name || 'Команда не определена'));
  return team;
}

function isSnapshotEvaluated(snapshot) {
  return snapshot.evaluation_y !== null && snapshot.evaluation_y !== undefined;
}

function isSnapshotAbstention(snapshot) {
  return Boolean(snapshot.abstention_reason)
    || ((snapshot.p_a === null || snapshot.p_a === undefined)
      && (snapshot.p_b === null || snapshot.p_b === undefined));
}

function getSnapshotMode(snapshot) {
  return snapshot.evaluation_mode || 'retrospective_reconstructed';
}

function appendSnapshotPreview(cell, snapshot) {
  if (!snapshot) {
    cell.append(el('span', 'snapshot-empty', 'Пока нет снимка'));
    return;
  }
  const abstention = isSnapshotAbstention(snapshot);
  const button = el('button', `snapshot-preview${abstention ? ' snapshot-preview--abstained' : ''}`);
  button.type = 'button';
  button.dataset.snapshotId = snapshot.snapshot_id;
  button.setAttribute(
    'aria-label',
    abstention
      ? `Открыть снимок #${snapshot.snapshot_seq}: модель воздержалась`
      : `Открыть снимок ${formatProbability(snapshot.p_a)} — ${snapshot.team_a}`,
  );
  button.append(el('span', 'snapshot-preview-id', `#${String(snapshot.snapshot_seq).padStart(3, '0')}`));
  if (abstention) {
    button.append(el('span', 'abstention-tag', 'Воздержание'));
  } else {
    button.append(el('strong', '', formatProbability(snapshot.p_a)));
    button.append(el('span', 'snapshot-preview-team', snapshot.team_a || 'Team A'));
  }
  cell.append(button);
}

function updateMatchPagination() {
  const pages = Math.max(1, Math.ceil(state.matchTotal / PAGE_SIZE));
  const page = Math.floor(state.matchOffset / PAGE_SIZE) + 1;
  $('#match-page-label').textContent = `${page} / ${pages}`;
  $('#match-previous').disabled = state.matchOffset <= 0;
  $('#match-next').disabled = state.matchOffset + PAGE_SIZE >= state.matchTotal;
}

function renderMatches() {
  const body = $('#match-body');
  body.replaceChildren();
  const latestByGame = latestSnapshotsByGame();
  const modelAvailable = state.overview?.model_available === true;
  const matchSnapshots = new Map(state.matches.map((match) => [
    match.game_id,
    match.latest_snapshot_id ? {
      snapshot_id: match.latest_snapshot_id,
      snapshot_seq: match.latest_snapshot_seq,
      p_a: match.latest_p_a,
      p_b: match.latest_p_b,
      team_a: match.team_a,
      abstention_reason: match.latest_abstention_reason,
    } : latestByGame.get(match.game_id),
  ]));

  if (!state.matches.length) {
    const message = state.matchSearch
      ? 'По этому запросу подходящих завершённых карт не найдено.'
      : 'Подходящих завершённых первых карт пока нет. Проверьте, что история загружена и нормализована.';
    renderMatchPlaceholder(message, 'empty');
    $('#match-count-label').textContent = state.matchSearch ? '0 результатов поиска' : '0 матчей доступно';
    updateMatchPagination();
    return;
  }

  for (const match of state.matches) {
    const row = el('tr', 'match-row');
    const teamsCell = el('td');
    const matchup = el('div', 'matchup');
    matchup.append(appendTeam(match.team_a, 'a'));
    matchup.append(el('span', 'versus-mark', 'vs'));
    matchup.append(appendTeam(match.team_b, 'b'));
    teamsCell.append(matchup);
    const gameLabel = match.best_of ? `BO${match.best_of} · ` : '';
    teamsCell.append(el('span', 'match-subline', `${gameLabel}первая карта`));

    const tournamentCell = el('td');
    tournamentCell.append(el('span', 'table-primary', match.tournament_name || 'Турнир не указан'));
    tournamentCell.append(el('span', 'table-secondary', match.patch_label ? `Патч ${match.patch_label}` : 'Патч неизвестен'));

    const dateCell = el('td');
    dateCell.append(el('span', 'table-primary', formatDate(match.event_time)));
    dateCell.append(el('span', 'table-secondary', formatTime(match.event_time)));

    const outcomeCell = el('td');
    outcomeCell.append(el('span', 'evaluation-result', `Победила ${match.winner_team}`));

    const snapshotCell = el('td');
    appendSnapshotPreview(snapshotCell, matchSnapshots.get(match.game_id));

    const actionCell = el('td', 'match-actions-cell');
    const action = el(
      'button',
      'button button--small button--outline',
      modelAvailable ? 'Новый расчёт' : 'Нет модели',
    );
    action.type = 'button';
    action.dataset.predictGame = match.game_id;
    action.dataset.teamA = match.team_a || 'Team A';
    action.dataset.teamB = match.team_b || 'Team B';
    action.disabled = !modelAvailable || state.pendingPrediction;
    action.title = modelAvailable
      ? 'Создать новый неизменяемый ретроспективный снимок'
      : 'Сначала зарегистрируйте доступный артефакт Logistic Regression';
    actionCell.append(action);

    row.append(teamsCell, tournamentCell, dateCell, outcomeCell, snapshotCell, actionCell);
    body.append(row);
  }

  const start = state.matchTotal ? state.matchOffset + 1 : 0;
  const end = Math.min(state.matchOffset + state.matches.length, state.matchTotal);
  $('#match-count-label').textContent = `Показано ${start}–${end} из ${state.matchTotal.toLocaleString('ru-RU')} матчей`;
  updateMatchPagination();
}

function createModeTag(snapshot) {
  const observed = getSnapshotMode(snapshot) === 'prospective_observed';
  return el(
    'span',
    `mode-tag ${observed ? 'mode-tag--observed' : 'mode-tag--retrospective'}`,
    observed ? 'НАБЛЮДАЛСЯ' : 'РЕТРОСПЕКТИВА',
  );
}

function renderEvaluation(snapshot) {
  const cell = el('td');
  if (!isSnapshotEvaluated(snapshot)) {
    cell.append(el('span', 'evaluation-empty', isSnapshotAbstention(snapshot) ? 'Без оценки исхода' : 'Ожидает оценки'));
    return cell;
  }
  const result = el(
    'span',
    'evaluation-result',
    snapshot.actual_winner ? `Победила ${snapshot.actual_winner}` : 'Исход сохранён',
  );
  cell.append(result);
  const metrics = [];
  if (snapshot.log_loss !== null && snapshot.log_loss !== undefined) metrics.push(`LL ${Number(snapshot.log_loss).toFixed(3)}`);
  if (snapshot.brier !== null && snapshot.brier !== undefined) metrics.push(`Brier ${Number(snapshot.brier).toFixed(3)}`);
  if (metrics.length) cell.append(el('span', 'table-secondary', metrics.join(' · ')));
  return cell;
}

function renderProbability(snapshot) {
  const cell = el('td');
  if (isSnapshotAbstention(snapshot)) {
    cell.append(el('span', 'abstention-tag', 'Модель воздержалась'));
    if (snapshot.abstention_reason) {
      cell.append(el('span', 'table-secondary', snapshot.abstention_reason));
    }
    return cell;
  }
  const probability = el('div', 'probability-cell');
  probability.append(el('span', 'team-probability team-probability--a', `${formatProbability(snapshot.p_a)} ${snapshot.team_a || 'A'}`));
  probability.append(el('span', 'team-probability team-probability--b', `${formatProbability(snapshot.p_b)} ${snapshot.team_b || 'B'}`));
  cell.append(probability);
  return cell;
}

function averageMetric(snapshots, key) {
  const values = snapshots
    .map((snapshot) => snapshot[key])
    .filter((value) => value !== null && value !== undefined)
    .map(Number)
    .filter(Number.isFinite);
  if (!values.length) return null;
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function renderJournalMetrics(visible) {
  state.visibleSnapshots = visible;
  $('#journal-visible-count').textContent = visible.length.toLocaleString('ru-RU');
  $('#journal-visible-note').textContent = `из ${state.snapshots.length} загруженных · фильтр и поиск применены`;
  const evaluated = visible.filter(isSnapshotEvaluated);
  $('#journal-evaluated-count').textContent = evaluated.length.toLocaleString('ru-RU');

  for (const [mode, prefix] of [
    ['retrospective_reconstructed', 'journal-retrospective'],
    ['prospective_observed', 'journal-observed'],
  ]) {
    const cohort = evaluated.filter((snapshot) => getSnapshotMode(snapshot) === mode);
    const logLossSnapshots = cohort.filter((snapshot) => snapshot.log_loss !== null
      && snapshot.log_loss !== undefined && Number.isFinite(Number(snapshot.log_loss)));
    const brierSnapshots = cohort.filter((snapshot) => snapshot.brier !== null
      && snapshot.brier !== undefined && Number.isFinite(Number(snapshot.brier)));
    const logLoss = averageMetric(logLossSnapshots, 'log_loss');
    const brier = averageMetric(brierSnapshots, 'brier');
    $(`#${prefix}-stats`).textContent = cohort.length ? `n = ${cohort.length} исходов` : '—';
    const metrics = [];
    if (logLoss !== null) metrics.push(`LL ${logLoss.toFixed(3)} · n=${logLossSnapshots.length}`);
    if (brier !== null) metrics.push(`Brier ${brier.toFixed(3)} · n=${brierSnapshots.length}`);
    $(`#${prefix}-note`).textContent = metrics.length
      ? metrics.join(' · ')
      : 'Оценок с метриками пока нет';
  }

  const exportButton = $('#export-predictions');
  exportButton.disabled = visible.length === 0;
  exportButton.title = visible.length
    ? `Скачать ${visible.length} снимков с текущими фильтрами`
    : 'Нет снимков для экспорта';
}

function renderPredictions() {
  const body = $('#prediction-body');
  body.replaceChildren();
  if (state.predictionsError) {
    renderJournalMetrics([]);
    const row = el('tr', 'placeholder-row placeholder-row--error');
    const cell = el('td', '', state.predictionsError);
    cell.colSpan = 6;
    row.append(cell);
    body.append(row);
    $('#prediction-count-label').textContent = 'Журнал снимков загрузить не удалось';
    return;
  }
  const filter = state.predictionFilter;
  const search = state.predictionSearch.trim().toLocaleLowerCase('ru-RU');
  const visible = state.snapshots.filter((snapshot) => {
    const evaluated = isSnapshotEvaluated(snapshot);
    const abstention = isSnapshotAbstention(snapshot);
    const matchesFilter = filter === 'all'
      || (filter === 'evaluated' && evaluated)
      || (filter === 'pending' && !evaluated)
      || (filter === 'abstentions' && abstention)
      || getSnapshotMode(snapshot) === filter;
    const searchable = [
      snapshot.snapshot_id,
      snapshot.snapshot_seq,
      snapshot.prediction_id,
      snapshot.target_game_id,
      snapshot.team_a,
      snapshot.team_b,
      snapshot.tournament_name,
      snapshot.patch_label,
      snapshot.actual_winner,
      getSnapshotMode(snapshot),
      snapshot.abstention_reason,
    ].filter(Boolean).join(' ').toLocaleLowerCase('ru-RU');
    return matchesFilter && (!search || searchable.includes(search));
  });
  renderJournalMetrics(visible);

  if (!visible.length) {
    let message = 'Снимков ещё нет. Выберите завершённый матч выше и сохраните первый расчёт.';
    if (state.snapshots.length && search) message = 'По этому запросу снимки не найдены.';
    else if (state.snapshots.length && filter !== 'all') message = 'Снимков с выбранным фильтром пока нет.';
    const row = el('tr', 'placeholder-row placeholder-row--empty');
    const cell = el('td', '', message);
    cell.colSpan = 6;
    row.append(cell);
    body.append(row);
    const label = state.snapshots.length
      ? `${state.snapshots.length} снимков загружено · 0 соответствуют фильтру`
      : 'Снимков в журнале пока нет';
    $('#prediction-count-label').textContent = label;
    return;
  }

  for (const snapshot of visible) {
    const row = el('tr', 'prediction-row');
    const idCell = el('td');
    const idButton = el(
      'button',
      'snapshot-id-button',
      `SNAP-${String(snapshot.snapshot_id || '').slice(0, 8).toUpperCase()}`,
    );
    idButton.type = 'button';
    idButton.dataset.snapshotId = snapshot.snapshot_id;
    idButton.setAttribute('aria-label', 'Открыть подробности снимка');
    idCell.append(idButton);
    idCell.append(el('span', 'table-secondary', `${formatDateTime(snapshot.computed_at)} · #${snapshot.snapshot_seq}`));

    const matchCell = el('td');
    const matchButton = el(
      'button',
      'match-link-button',
      `${snapshot.team_a || 'Team A'} vs ${snapshot.team_b || 'Team B'}`,
    );
    matchButton.type = 'button';
    matchButton.dataset.snapshotId = snapshot.snapshot_id;
    matchCell.append(matchButton);
    const meta = [snapshot.tournament_name, snapshot.patch_label ? `Патч ${snapshot.patch_label}` : null]
      .filter(Boolean).join(' · ') || 'Первая карта';
    matchCell.append(el('span', 'table-secondary', meta));

    const modeCell = el('td');
    modeCell.append(createModeTag(snapshot));

    const detailsCell = el('td', 'details-cell');
    const detailsButton = el('button', 'button button--small button--quiet', 'Открыть');
    detailsButton.type = 'button';
    detailsButton.dataset.snapshotId = snapshot.snapshot_id;
    detailsCell.append(detailsButton);

    row.append(idCell, matchCell, renderProbability(snapshot), renderEvaluation(snapshot), modeCell, detailsCell);
    row.dataset.evaluationMode = getSnapshotMode(snapshot);
    row.dataset.evaluated = String(isSnapshotEvaluated(snapshot));
    row.dataset.abstention = String(isSnapshotAbstention(snapshot));
    body.append(row);
  }
  const label = filter === 'all' && !search ? `Последние ${visible.length}` : `${visible.length} по фильтру и поиску`;
  $('#prediction-count-label').textContent = `${label} из ${state.snapshots.length} загруженных снимков`;
}

function showToast(message, kind = 'info') {
  const stack = $('#toast-stack');
  const toast = el('div', `toast toast--${kind}`);
  toast.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  toast.append(el('span', 'toast-mark', kind === 'success' ? '✓' : kind === 'error' ? '!' : 'i'));
  toast.append(el('span', 'toast-message', message));
  stack.append(toast);
  window.setTimeout(() => {
    toast.classList.add('toast--leaving');
    window.setTimeout(() => toast.remove(), 240);
  }, 5000);
}

function updateTimestamp() {
  $('#updated-label').textContent = `Обновлено ${new Intl.DateTimeFormat('ru-RU', {
    hour: '2-digit', minute: '2-digit',
  }).format(new Date())}`;
}

async function checkHealth() {
  try {
    const health = await requestJSON('/health');
    setHealth(
      health.database === 'up',
      health.database === 'up' ? 'API · база на связи' : 'База данных недоступна',
    );
  } catch {
    setHealth(false, 'Локальный API недоступен');
  }
}

async function loadMatches() {
  const requestId = ++state.matchRequest;
  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(state.matchOffset) });
  if (state.matchSearch) params.set('search', state.matchSearch);
  renderMatchPlaceholder('Загружаем исторические матчи…', 'loading');
  try {
    const result = await requestJSON(`/matches?${params}`);
    if (requestId !== state.matchRequest) return;
    state.matches = Array.isArray(result.items) ? result.items : [];
    state.matchTotal = Number(result.total || 0);
    const lastPageOffset = Math.max(0, Math.ceil(state.matchTotal / PAGE_SIZE - 1) * PAGE_SIZE);
    if (state.matchOffset > lastPageOffset) {
      state.matchOffset = lastPageOffset;
      return loadMatches();
    }
    renderMatches();
  } catch (error) {
    if (requestId !== state.matchRequest) return;
    state.matches = [];
    state.matchTotal = 0;
    renderMatchPlaceholder(describeError(error), 'error');
    $('#match-count-label').textContent = 'Историю загрузить не удалось';
    updateMatchPagination();
  }
}

async function loadPredictions() {
  try {
    const result = await requestJSON('/predictions?limit=100&offset=0');
    const detailedSnapshots = new Map(
      [...state.snapshotsById.entries()].filter(([, snapshot]) => snapshot.feature_values !== undefined),
    );
    state.snapshots = Array.isArray(result.items) ? result.items : [];
    state.predictionsError = '';
    state.snapshotsById = new Map(state.snapshots.map((snapshot) => [
      snapshot.snapshot_id,
      detailedSnapshots.has(snapshot.snapshot_id)
        ? { ...snapshot, ...detailedSnapshots.get(snapshot.snapshot_id) }
        : snapshot,
    ]));
    renderPredictions();
  } catch (error) {
    state.snapshots = [];
    state.snapshotsById.clear();
    state.visibleSnapshots = [];
    state.predictionsError = describeError(error);
    renderPredictions();
  }
}

async function refreshWorkspace({ toast = false } = {}) {
  const refreshButton = $('#refresh-button');
  refreshButton.classList.add('is-refreshing');
  refreshButton.disabled = true;
  const overviewPromise = requestJSON('/overview')
    .then((data) => {
      updateOverview(data);
      setHealth(true, 'API · база на связи');
    })
    .catch((error) => {
      state.overview = null;
      $('#stat-match-count').textContent = '—';
      $('#stat-snapshot-count').textContent = '—';
      $('#stat-evaluated-count').textContent = '—';
      $('#stat-model-status').textContent = 'Нет соединения';
      $('#model-status-label').textContent = 'API недоступен';
      $('#model-sidebar-status').textContent = describeError(error);
      setHealth(false, 'Локальный API недоступен');
    });
  await Promise.all([overviewPromise, loadMatches(), loadPredictions(), checkHealth()]);
  updateTimestamp();
  renderMatches();
  renderPredictions();
  refreshButton.classList.remove('is-refreshing');
  refreshButton.disabled = false;
  if (toast) showToast('Рабочая область обновлена.', 'success');
}

function updateSnapshotInJournal(snapshotId, details) {
  const snapshot = state.snapshots.find((item) => item.snapshot_id === snapshotId);
  if (!snapshot) return;
  Object.assign(snapshot, details);
  state.snapshotsById.set(snapshotId, { ...snapshot, ...details, _detailsRequested: true });
  renderPredictions();
}

async function openSnapshot(snapshotId) {
  const loaded = state.snapshotsById.get(snapshotId);
  if (!loaded) return;
  const snapshot = loaded;
  const dialog = $('#snapshot-dialog');

  if (snapshot._detailsRequested && snapshot.feature_values === undefined) return;
  if (snapshot.feature_values === undefined) {
    state.snapshotsById.set(snapshotId, { ...snapshot, _detailsRequested: true });
    $('#dialog-seq').textContent = `SNAPSHOT #${String(snapshot.snapshot_seq).padStart(3, '0')} · ${String(snapshot.snapshot_id).slice(0, 8).toUpperCase()}`;
    $('#dialog-title').textContent = `${snapshot.team_a || 'Team A'} vs ${snapshot.team_b || 'Team B'}`;
    $('#dialog-match-meta').textContent = 'Загружаем сохранённые признаки и происхождение…';
    $('#dialog-feature-list').replaceChildren(el('p', 'empty-features', 'Загружаем признаки…'));
    if (!dialog.open) dialog.showModal();
    try {
      const details = await requestJSON(`/predictions/${encodeURIComponent(snapshotId)}`);
      state.snapshotsById.set(snapshotId, { ...snapshot, ...details, _detailsRequested: true });
      updateSnapshotInJournal(snapshotId, details);
      await openSnapshot(snapshotId);
    } catch (error) {
      state.snapshotsById.set(snapshotId, { ...snapshot, _detailsRequested: false });
      showToast(describeError(error), 'error');
      if (dialog.open) dialog.close();
    }
    return;
  }

  const snapshotDetails = state.snapshotsById.get(snapshotId) || snapshot;
  const modeObserved = getSnapshotMode(snapshotDetails) === 'prospective_observed';
  const abstention = isSnapshotAbstention(snapshotDetails);
  const title = `${snapshotDetails.team_a || 'Team A'} vs ${snapshotDetails.team_b || 'Team B'}`;
  $('#dialog-kicker').textContent = 'СНИМОК ПРОГНОЗА · НЕИЗМЕНЯЕМЫЙ';
  $('#dialog-seq').textContent = `SNAPSHOT #${String(snapshotDetails.snapshot_seq).padStart(3, '0')} · ${String(snapshotDetails.snapshot_id).slice(0, 8).toUpperCase()}`;
  $('#dialog-title').textContent = title;
  $('#dialog-match-meta').textContent = [
    snapshotDetails.tournament_name,
    snapshotDetails.best_of ? `BO${snapshotDetails.best_of} · первая карта` : 'первая карта',
    snapshotDetails.patch_label ? `Патч ${snapshotDetails.patch_label}` : null,
  ].filter(Boolean).join(' · ');
  const mode = $('#dialog-mode');
  mode.className = `mode-tag ${modeObserved ? 'mode-tag--observed' : 'mode-tag--retrospective'}`;
  mode.textContent = modeObserved ? 'PROSPECTIVE OBSERVED' : 'RETROSPECTIVE RECONSTRUCTED';
  mode.title = modeObserved
    ? 'Данные действительно зафиксированы системой до cutoff.'
    : 'Историческая реконструкция, не прогноз до матча.';
  $('#dialog-team-a').textContent = snapshotDetails.team_a || 'Team A';
  $('#dialog-team-b').textContent = snapshotDetails.team_b || 'Team B';
  const probabilityAvailable = !abstention
    && Number.isFinite(Number(snapshotDetails.p_a))
    && Number.isFinite(Number(snapshotDetails.p_b));
  $('.dialog-probability').setAttribute('aria-label', probabilityAvailable
    ? 'Вероятности сохранённого снимка'
    : 'Вероятность недоступна или модель воздержалась');
  $('#dialog-probability-a').textContent = probabilityAvailable ? formatProbability(snapshotDetails.p_a) : '—';
  $('#dialog-probability-b').textContent = probabilityAvailable ? formatProbability(snapshotDetails.p_b) : '—';
  const probabilityBar = $('#dialog-probability-bar');
  const probabilityValue = Number(snapshotDetails.p_a);
  $('#dialog-probability-fill').style.width = probabilityAvailable
    ? `${Math.max(0, Math.min(100, probabilityValue * 100))}%`
    : '0%';
  probabilityBar.classList.toggle('probability-bar--unavailable', !probabilityAvailable);
  probabilityBar.setAttribute(
    'aria-label',
    probabilityAvailable ? 'Вероятность исхода' : 'Вероятность не рассчитана или недоступна',
  );
  $('.dialog-probability').classList.toggle('dialog-probability--abstained', !probabilityAvailable);
  const evaluation = abstention
    ? `Модель воздержалась: ${snapshotDetails.abstention_reason || 'причина не указана'}.`
    : !isSnapshotEvaluated(snapshotDetails)
      ? 'Исход ещё не привязан к этому снимку.'
      : `Фактический результат: ${snapshotDetails.actual_winner || 'сохранён'}${snapshotDetails.log_loss != null ? ` · log loss ${Number(snapshotDetails.log_loss).toFixed(4)}` : ''}${snapshotDetails.brier != null ? ` · Brier ${Number(snapshotDetails.brier).toFixed(4)}` : ''}.`;
  $('#dialog-result-note').textContent = `${evaluation} ${probabilityAvailable ? 'Вероятности не обещают исход.' : 'Вероятность не рассчитывалась или недоступна.'}`;

  const provenance = $('#dialog-provenance');
  provenance.replaceChildren();
  const entries = [
    ['Время расчёта', formatDateTime(snapshotDetails.computed_at)],
    ['Информационный cutoff', formatDateTime(snapshotDetails.cutoff_at)],
    ['Версия модели', snapshotDetails.model_version_id || 'не указана'],
    ['Алгоритм', snapshotDetails.model_algorithm || 'не указан'],
    ['Схема признаков', snapshotDetails.feature_schema_version || 'не указана'],
    ['Снимок признаков', snapshotDetails.feature_snapshot_id || 'не сохранён'],
    ['Целевая карта', snapshotDetails.target_game_id || 'не указана'],
    ['Фаза цели', snapshotDetails.phase_contract || 'pre_draft'],
    ['Режим оценки', getSnapshotMode(snapshotDetails)],
  ];
  entries.forEach(([label, value]) => provenance.append(el('dt', '', label), el('dd', '', value)));

  const featureValues = snapshotDetails.feature_values && typeof snapshotDetails.feature_values === 'object'
    ? snapshotDetails.feature_values
    : {};
  const coverage = snapshotDetails.feature_coverage && typeof snapshotDetails.feature_coverage === 'object'
    ? snapshotDetails.feature_coverage
    : {};
  const featureList = $('#dialog-feature-list');
  featureList.replaceChildren();
  const featureEntries = Object.entries(featureValues).filter(([key]) => FEATURE_LABELS[key]);
  let knownCount = 0;
  for (const [key, value] of featureEntries) {
    const mask = coverage[key];
    const known = value !== null && value !== undefined && mask?.known !== false;
    if (known) knownCount += 1;
    const row = el('div', `feature-row${known ? '' : ' feature-row--unknown'}`);
    row.append(el('span', 'feature-label', FEATURE_LABELS[key][0]));
    row.append(el('strong', 'feature-value', formatMetric(key, known ? value : null)));
    if (!known) row.append(el('span', 'feature-unknown-mark', 'НЕИЗВЕСТНО'));
    featureList.append(row);
  }
  if (!featureEntries.length) {
    featureList.append(el('p', 'empty-features', 'В этом снимке нет сериализованных признаков для отображения.'));
  }
  $('#dialog-coverage-summary').textContent = featureEntries.length
    ? `${knownCount} / ${featureEntries.length} известных признаков`
    : 'Нет доступных данных';
  if (!dialog.open) dialog.showModal();
}

function setPredictionPending(pending) {
  state.pendingPrediction = pending;
  document.querySelectorAll('[data-predict-game]').forEach((button) => {
    const modelAvailable = state.overview?.model_available === true;
    const active = pending && button.dataset.predictGame === state.activeMatch?.game_id;
    button.disabled = pending || !modelAvailable;
    button.textContent = active ? 'Считаем…' : modelAvailable ? 'Новый расчёт' : 'Нет модели';
  });
  $('#confirm-submit').disabled = pending;
}

async function createPrediction() {
  const match = state.activeMatch;
  if (!match || state.pendingPrediction) return;
  const confirmDialog = $('#confirm-dialog');
  if (confirmDialog.open) confirmDialog.close('confirm');
  setPredictionPending(true);
  try {
    const result = await requestJSON(`/predict/game/${encodeURIComponent(match.game_id)}`, { method: 'POST' });
    const savedMessage = result.abstention_reason
      ? `Снимок сохранён · модель воздержалась: ${result.abstention_reason}`
      : `Новый снимок сохранён · ${formatProbability(result.p_a)} ${match.team_a}`;
    showToast(savedMessage, 'success');
    await refreshWorkspace();
    if (result.snapshot_id) await openSnapshot(result.snapshot_id);
  } catch (error) {
    showToast(describeError(error), 'error');
  } finally {
    setPredictionPending(false);
  }
}

function csvField(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  const text = value === null || value === undefined ? '' : String(value);
  const protectedText = /^[\t\r ]*[=+\-@]/.test(text) ? `'${text}` : text;
  return `"${protectedText.replaceAll('"', '""')}"`;
}

function exportVisiblePredictions() {
  const snapshots = state.visibleSnapshots;
  if (!snapshots.length) return;
  const columns = [
    ['snapshot_id', 'snapshot_id'],
    ['snapshot_seq', 'snapshot_seq'],
    ['computed_at', 'computed_at'],
    ['cutoff_at', 'cutoff_at'],
    ['team_a', 'team_a'],
    ['team_b', 'team_b'],
    ['p_a', 'p_a'],
    ['p_b', 'p_b'],
    ['abstention_reason', 'abstention_reason'],
    ['actual_winner', 'actual_winner'],
    ['evaluation_y', 'evaluation_y'],
    ['log_loss', 'log_loss'],
    ['brier', 'brier'],
    ['evaluation_mode', 'evaluation_mode'],
    ['model_version_id', 'model_version_id'],
    ['model_algorithm', 'model_algorithm'],
    ['feature_schema_version', 'feature_schema_version'],
    ['target_game_id', 'target_game_id'],
    ['tournament_name', 'tournament_name'],
    ['patch_label', 'patch_label'],
    ['phase_contract', 'phase_contract'],
  ];
  const rows = [
    columns.map(([header]) => header),
    ...snapshots.map((snapshot) => columns.map(([, key]) => snapshot[key])),
  ];
  const csv = `\uFEFF${rows.map((row) => row.map(csvField).join(',')).join('\r\n')}`;
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = el('a');
  link.href = url;
  link.download = `d2intel-predictions-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
  showToast(`Экспортировано снимков: ${snapshots.length}.`, 'success');
}

function bindEvents() {
  $('#refresh-button').addEventListener('click', () => refreshWorkspace({ toast: true }));
  $('#match-previous').addEventListener('click', () => {
    state.matchOffset = Math.max(0, state.matchOffset - PAGE_SIZE);
    loadMatches();
  });
  $('#match-next').addEventListener('click', () => {
    if (state.matchOffset + PAGE_SIZE >= state.matchTotal) return;
    state.matchOffset += PAGE_SIZE;
    loadMatches();
  });

  let searchTimer;
  $('#match-search').addEventListener('input', (event) => {
    window.clearTimeout(searchTimer);
    state.matchSearch = event.target.value.trim();
    state.matchOffset = 0;
    searchTimer = window.setTimeout(() => loadMatches(), 240);
  });
  $('#match-search-form').addEventListener('submit', (event) => event.preventDefault());
  document.addEventListener('keydown', (event) => {
    const input = event.target instanceof HTMLElement
      && ['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName);
    if (event.key === '/' && !input) {
      event.preventDefault();
      $('#match-search').focus();
    }
  });

  $('#prediction-filter').addEventListener('change', (event) => {
    state.predictionFilter = event.target.value;
    renderPredictions();
  });
  $('#prediction-search').addEventListener('input', (event) => {
    state.predictionSearch = event.target.value;
    renderPredictions();
  });
  $('#export-predictions').addEventListener('click', exportVisiblePredictions);

  document.addEventListener('click', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const snapshotButton = target?.closest('[data-snapshot-id]');
    if (snapshotButton) {
      openSnapshot(snapshotButton.dataset.snapshotId);
      return;
    }
    const predictButton = target?.closest('[data-predict-game]');
    if (predictButton && !predictButton.disabled) {
      state.activeMatch = {
        game_id: predictButton.dataset.predictGame,
        team_a: predictButton.dataset.teamA,
        team_b: predictButton.dataset.teamB,
      };
      $('#confirm-copy').textContent = `Для матча ${state.activeMatch.team_a} vs ${state.activeMatch.team_b} будет создана новая неизменяемая запись. Предыдущие снимки останутся без изменений.`;
      $('#confirm-dialog').showModal();
    }
  });

  $('#dialog-close').addEventListener('click', () => $('#snapshot-dialog').close());
  $('#snapshot-dialog').addEventListener('click', (event) => {
    if (event.target === event.currentTarget) event.currentTarget.close();
  });
  $('#confirm-submit').addEventListener('click', (event) => {
    event.preventDefault();
    createPrediction();
  });
  $('#confirm-cancel').addEventListener('click', (event) => {
    event.preventDefault();
    $('#confirm-dialog').close('cancel');
  });
}

bindEvents();
refreshWorkspace();
