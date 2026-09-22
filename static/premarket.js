/* Public market data only. LLM HTML is sanitized on the server. */
(function () {
  'use strict';
  const root = document.getElementById('premarket-v2');
  if (!root) return;
  const view = root.dataset.view, ticker = root.dataset.ticker;
  const content = document.getElementById('pmv-content'), status = document.getElementById('pmv-status');
  const dateInput = document.getElementById('pmv-date'), sectorInput = document.getElementById('pmv-sector');
  const limitInput = document.getElementById('pmv-limit'), searchInput = document.getElementById('pmv-search');
  const refresh = document.getElementById('pmv-refresh');
  const initial = new URLSearchParams(location.search);
  let runId = initial.get('run_id') || '';
  let revision = 0, debounce, activeJob = null;
  dateInput.value = initial.get('date') || '';
  searchInput.value = initial.get('q') || '';
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const num = value => value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString('en-US');
  const price = value => value == null ? '—' : '$' + Number(value).toFixed(2);
  const pct = value => value == null ? '—' : (Number(value) > 0 ? '+' : '') + Number(value).toFixed(2) + '%';
  const direction = value => value > 0 ? 'pmv-up' : value < 0 ? 'pmv-down' : 'pmv-muted';
  const empty = message => '<div class="pmv-empty">' + esc(message) + '</div>';
  const stamp = value => {
    if (!value) return 'Timestamp unavailable';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat('en-US', {
      timeZone:'America/New_York', month:'short', day:'numeric', year:'numeric', hour:'2-digit', minute:'2-digit'
    }).format(date) + ' ET';
  };
  function stockLink(symbol, day) {
    const params = new URLSearchParams();
    if (day || dateInput.value) params.set('date', day || dateInput.value);
    if (runId) params.set('run_id', runId);
    return '/premarket/stocks/' + encodeURIComponent(symbol) + '?' + params;
  }
  function notices(items) {
    document.getElementById('pmv-notices').innerHTML = (items || []).map(item => '<p class="pmv-notice">' + esc(item) + '</p>').join('');
  }
  async function get(url, options) {
    const response = await fetch(url, options);
    let result;
    try { result = await response.json(); } catch (_) { throw new Error('The server returned an incomplete response. Try refreshing.'); }
    if (!response.ok || result.error) throw new Error(result.error || 'Premarket research is temporarily unavailable.');
    return result;
  }
  function updateLinks() {
    root.querySelectorAll('.pmv-tabs a').forEach(link => {
      const url = new URL(link.href);
      if (dateInput.value) url.searchParams.set('date', dateInput.value);
      link.href = url.pathname + url.search;
    });
    const params = new URLSearchParams(location.search);
    if (!runId) params.delete('run_id');
    if (dateInput.value) params.set('date', dateInput.value);
    if (sectorInput.value) params.set('sector', sectorInput.value); else params.delete('sector');
    if (view === 'search') {
      if (searchInput.value) params.set('q', searchInput.value); else params.delete('q');
    }
    history.replaceState(null, '', location.pathname + (params.size ? '?' + params : ''));
  }
  function moverTable(rows) {
    if (!rows.length) return empty('No movers in this group for the selected session.');
    return '<div class="pmv-scroll"><table><thead><tr><th>Company</th><th class="pmv-number">Price</th><th class="pmv-number">Move</th></tr></thead><tbody>' + rows.map(row =>
      '<tr><td><a href="' + esc(stockLink(row.ticker, row.scan_date)) + '">' + esc(row.ticker) + '</a>' +
      '<span class="pmv-company">' + esc(row.company_name) + '</span>' +
      (row.analysis_preview ? '<p class="pmv-preview"><strong>' + (row.analysis_provider === 'gemini' ? 'Historical Gemini' : 'Grok commentary') + '</strong> · ' + esc(row.analysis_preview) + '…</p><a href="' + esc(stockLink(row.ticker, row.scan_date)) + '">Read analysis</a>' : '') +
      '</td><td class="pmv-number">' + price(row.premarket_close) + '</td><td class="pmv-number ' + direction(row.movement_pct) + '">' + pct(row.movement_pct) + '</td></tr>'
    ).join('') + '</tbody></table></div>';
  }
  function renderDashboard(report) {
    const s = report.summary || {}, top = report.top || {gainers:[], fallers:[]};
    dateInput.value = report.trading_date || dateInput.value;
    const selected = sectorInput.value || initial.get('sector') || '';
    sectorInput.innerHTML = '<option value="">All sectors</option>' + (report.sector_names || Object.keys(report.sectors || {})).map(sector => '<option value="' + esc(sector) + '">' + esc(sector) + '</option>').join('');
    sectorInput.value = selected;
    const metrics = [[s.total_stocks_attempted, 'Companies'], [s.total_stocks_scanned, 'Usable prices'],
      [s.total_up_movements, 'Gainers'], [s.total_down_movements, 'Losers'], [s.total_unchanged, 'Unchanged'], [s.total_stocks_failed, 'Unavailable']];
    const breadth = Object.entries(report.sectors || {}).map(([sector, row]) => {
      const total = row.total_scanned || 0, up = total ? 100 * (row.total_gainers || 0) / total : 0;
      const down = total ? 100 * (row.total_losers || 0) / total : 0;
      const url = '/premarket/sectors?' + new URLSearchParams({date:dateInput.value, sector});
      return '<div class="pmv-breadth"><a href="' + esc(url) + '">' + esc(sector) + '</a><div class="pmv-bar" role="img" aria-label="' + esc((row.total_gainers || 0) + ' gainers, ' + (row.total_losers || 0) + ' losers') + '"><span class="up" style="width:' + up + '%"></span><span class="down" style="width:' + down + '%"></span></div><span class="pmv-number">' + num(row.total_gainers) + ' / ' + num(row.total_losers) + '</span></div>';
    }).join('');
    const earnings = report.earnings || [];
    const earningsHTML = earnings.length ? '<div class="pmv-scroll"><table><thead><tr><th>Company</th><th>Release date</th><th>Session</th></tr></thead><tbody>' + earnings.map(row =>
      '<tr><td><a href="' + esc(stockLink(row.ticker)) + '">' + esc(row.ticker) + '</a><span class="pmv-company">' + esc(row.company_name) + '</span></td><td>' + esc(row.date) + '</td><td>' + esc(row.session) + '</td></tr>'
    ).join('') + '</tbody></table></div>' : empty('No earnings announcements are available for this session.');
    const dates = view === 'history' ? '<section><h2>Stored sessions</h2><div class="pmv-dates">' + (report.available_dates || []).map(day => '<a href="/premarket/history?date=' + encodeURIComponent(day) + '">' + esc(day) + '</a>').join('') + '</div></section>' : '';
    content.innerHTML = dates + '<div class="pmv-metrics">' + metrics.map(([value, label]) => '<dl><dt>' + label + '</dt><dd>' + num(value) + '</dd></dl>').join('') + '</div>' +
      '<div class="pmv-columns"><section><h2>Top gainers</h2>' + moverTable(top.gainers || []) + '</section><section><h2>Top losers</h2>' + moverTable(top.fallers || []) + '</section></div>' +
      '<section><h2>Sector breadth <span class="pmv-muted">Gainers / losers</span></h2>' + breadth + '</section>' +
      '<section><h2>Earnings announcements</h2><p class="pmv-sub">Selected morning and the previous trading session’s after-hours releases</p>' + earningsHTML + '</section>';
    const warnings = [...(report.notices || [])];
    if (report.stale) warnings.unshift('Historical session: ' + dateInput.value + '. These are not today’s prices.');
    notices(warnings);
    status.textContent = (report.mode === 'delayed' ? (report.delay_minutes || 16) + '-minute delayed feed. As of ' : 'Snapshot cutoff: ') + stamp(report.scan_timestamp);
    updateLinks();
  }
  function renderSearch(result) {
    const rows = result.rows || [];
    content.innerHTML = rows.length ? '<div class="pmv-scroll"><table><thead><tr><th>Ticker</th><th>Company</th><th>Sector</th></tr></thead><tbody>' + rows.map(row => '<tr><td><a href="' + esc(stockLink(row.ticker)) + '">' + esc(row.ticker) + '</a></td><td>' + esc(row.company_name) + '</td><td>' + esc(row.sector) + '</td></tr>').join('') + '</tbody></table></div>' : empty('No companies match this search. Try a ticker or part of the company name.');
    status.textContent = rows.length + ' matching companies shown. Open a stock for ' + dateInput.value + '.';
    notices([]); updateLinks();
  }
  function renderStock(result) {
    const row = result.stock;
    dateInput.value = result.trading_date || dateInput.value;
    const analyses = result.analyses || [], hasGrok = analyses.some(item => item.provider === 'grok');
    const analysisHTML = analyses.map(item => '<details ' + (item.provider === 'grok' ? 'open' : '') + '><summary>' + (item.provider === 'gemini' ? 'Historical Gemini analysis' : 'Grok analysis') + '</summary>' +
      '<p class="pmv-stock-meta">' + esc(item.model_name || item.provider) + (item.generated_at ? ' · Generated ' + esc(stamp(item.generated_at)) : ' · Preserved from Finespresso') +
      (item.retrospective ? ' · Retrospective analysis of this session' : '') + '</p><div class="pmv-analysis">' + (item.html || esc(item.text)) + '</div>' +
      '<ul class="pmv-sources">' + (item.sources || []).map(source => '<li><a href="' + esc(source.url) + '" target="_blank" rel="noopener noreferrer">' + esc(source.title || source.url) + '</a>' +
        (source.published_at ? ' · ' + esc(stamp(source.published_at)) : '') + '</li>').join('') + '</ul></details>').join('');
    let action = '';
    if (!hasGrok) {
      if (root.dataset.signedIn !== 'true') action = '<p><a href="/signin">Sign in</a> to generate Grok commentary. Saved research is public.</p>';
      else if (result.can_analyze) action = '<button type="button" class="pmv-button" id="pmv-analyze">Generate Grok analysis</button><p class="pmv-sub">Uses your xAI key or platform allowance. A saved result is reused.</p>';
      else action = '<p class="pmv-sub">Analysis needs a usable 09:00 snapshot and previous close. Today’s generation opens after 09:16:20 ET.</p>';
    }
    content.innerHTML = '<section><h2>' + esc(row.company_name || row.ticker) + '</h2><div class="pmv-stock-price">' + price(row.premarket_close) + '</div>' +
      '<p class="' + direction(row.movement_pct) + '">' + pct(row.movement_pct) + ' <span class="pmv-muted">from the previous regular close</span></p>' +
      '<div class="pmv-stock-meta">' + esc([row.sector, row.industry, row.exchange].filter(Boolean).join(' · ')) + '<br>Previous close ' + price(row.prev_close) + ' · Volume ' + num(row.accumulated_volume) +
      '<br>Last observed bar: ' + esc(stamp(row.quote_timestamp)) + '</div><div class="pmv-chart" id="pmv-chart"></div></section>' +
      '<section><h2>Premarket movement analysis</h2>' + (analysisHTML || empty('No saved commentary for this stock and date.')) + action + '<div id="pmv-job" role="status" aria-live="polite"></div></section>';
    notices(result.notices); status.textContent = 'Trading session ' + dateInput.value + ' · Cutoff 09:00 ET · Feed delay ' + (result.delay_minutes || 16) + ' minutes';
    drawChart(result.history || []);
    const button = document.getElementById('pmv-analyze');
    if (button) button.addEventListener('click', generate);
    updateLinks();
  }
  function drawChart(rows) {
    const target = document.getElementById('pmv-chart');
    if (!rows.length) { target.innerHTML = empty('Minute bars are unavailable for this session.'); return; }
    if (!window.Plotly) { target.innerHTML = empty('The chart library could not load. Refresh to retry.'); return; }
    const groups = [{key:'after_hours',name:'Previous after-hours',color:'#788d82'}, {key:'premarket',name:'Premarket',color:'#1F5D43'}];
    const traces = groups.map(group => {
      const subset = rows.filter(row => (row.session || 'premarket') === group.key);
      return {type:'scatter', mode:'lines', name:group.name, x:subset.map(row => stamp(row.timestamp)),
        y:subset.map(row => row.price), line:{color:group.color,width:2}, connectgaps:false, hovertemplate:'%{x}<br>$%{y:.2f}<extra></extra>'};
    });
    Plotly.newPlot(target, traces, {height:290, margin:{t:20,r:20,b:55,l:60}, paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)',
      font:{family:getComputedStyle(root).fontFamily,color:getComputedStyle(root).color}, legend:{orientation:'h'},
      xaxis:{type:'category',nticks:5,categoryorder:'array',categoryarray:rows.map(row => stamp(row.timestamp)),title:'US Eastern Time'},
      yaxis:{tickprefix:'$'}, hovermode:'x unified'}, {responsive:true,displayModeBar:false});
  }
  async function generate() {
    const button = document.getElementById('pmv-analyze'), message = document.getElementById('pmv-job');
    const day = dateInput.value;
    button.disabled = true;
    try {
      const result = await get('/premarket/stocks/' + encodeURIComponent(ticker) + '/analysis', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({date:day})});
      if (result.status === 'completed') { await load(); return; }
      activeJob = result.job_id;
      message.textContent = 'Analysis queued. You can return to this stock later.';
      for (let count = 0; count < 120 && activeJob === result.job_id && dateInput.value === day; count++) {
        await new Promise(resolve => setTimeout(resolve, 2500));
        const job = await get('/premarket/jobs/' + encodeURIComponent(result.job_id));
        if (job.status === 'failed') throw new Error(job.error || 'Analysis failed. Try again later.');
        if (job.status === 'completed') { activeJob = null; await load(); return; }
        message.textContent = job.status === 'running' ? 'Grok is researching sources for this session…' : 'Analysis queued. You can return to this stock later.';
      }
      if (activeJob === result.job_id) message.textContent = 'Research is still pending. Return to this stock later to read the saved result.';
    } catch (error) { message.textContent = error.message; }
    finally { if (button.isConnected) button.disabled = false; }
  }
  async function load() {
    const ownRevision = ++revision;
    refresh.disabled = true; content.setAttribute('aria-busy', 'true'); status.textContent = 'Loading premarket research…';
    try {
      let result;
      if (view === 'search') {
        if (!dateInput.value) dateInput.value = root.dataset.today;
        result = await get('/premarket/companies?' + new URLSearchParams({q:searchInput.value}));
        if (ownRevision === revision) renderSearch(result);
      } else if (view === 'stock') {
        result = await get('/premarket/stocks/' + encodeURIComponent(ticker) + '/data?' + new URLSearchParams({date:dateInput.value,run_id:runId}));
        if (ownRevision === revision) renderStock(result);
      } else {
        const params = new URLSearchParams({date:dateInput.value, sector:sectorInput.value || initial.get('sector') || '', limit:limitInput.value, run_id:runId, historical:view === 'history' ? 'true' : 'false'});
        result = await get('/premarket/data?' + params);
        if (ownRevision === revision) renderDashboard(result);
      }
    } catch (error) {
      if (ownRevision === revision) { status.textContent = error.message; content.innerHTML = empty('Use Refresh data to retry, or select another trading date.'); }
    } finally {
      if (ownRevision === revision) { refresh.disabled = false; content.setAttribute('aria-busy', 'false'); }
    }
  }
  document.getElementById('pmv-search-label').hidden = view !== 'search';
  document.getElementById('pmv-sector-label').hidden = view === 'search' || view === 'stock';
  document.getElementById('pmv-limit-label').hidden = view === 'search' || view === 'stock';
  dateInput.addEventListener('change', () => { activeJob = null; runId = ''; load(); });
  sectorInput.addEventListener('change', () => { initial.delete('sector'); load(); });
  limitInput.addEventListener('change', load);
  refresh.addEventListener('click', load);
  searchInput.addEventListener('input', () => { clearTimeout(debounce); debounce = setTimeout(load, 250); });
  load();
}());
