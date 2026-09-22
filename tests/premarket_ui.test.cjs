// Execute the shipped controller against a small DOM contract; no browser opens.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/premarket.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

function mount(view, respond, search = '?date=2026-08-07') {
  const nodes = {};
  for (const id of ['premarket-v2', 'pmv-content', 'pmv-status', 'pmv-date', 'pmv-sector',
    'pmv-limit', 'pmv-search', 'pmv-refresh', 'pmv-notices', 'pmv-search-label',
    'pmv-sector-label', 'pmv-limit-label', 'pmv-chart', 'pmv-analyze', 'pmv-job']) {
    nodes[id] = {value:'', innerHTML:'', textContent:'', dataset:{}, handlers:{}, isConnected:true,
      setAttribute() {}, querySelectorAll() { return []; },
      addEventListener(name, handler) { this.handlers[name] = handler; }};
  }
  nodes['premarket-v2'].dataset = {view, ticker:'AAA', signedIn:'true', today:'2026-08-07'};
  nodes['pmv-limit'].value = '10';
  const requests = [], navigation = [];
  vm.runInNewContext(source, {
    document:{getElementById:id => nodes[id]}, location:{search, pathname:'/premarket'},
    history:{replaceState:(_a, _b, url) => navigation.push(url)},
    window:{}, URL, URLSearchParams, Intl, Date, console,
    setTimeout:handler => setImmediate(handler), clearTimeout:clearImmediate,
    fetch:async (url, options) => {
      requests.push({url, options});
      return {ok:true, json:async () => respond(url, options)};
    },
  });
  return {nodes, requests, navigation};
}

function report(day = '2026-08-07', name = 'Alpha Incorporated') {
  const row = {ticker:'AAA', company_name:name, premarket_close:110, movement_pct:10,
    scan_date:day, analysis_preview:'Saved catalyst'};
  return {trading_date:day, summary:{total_stocks_attempted:4806, total_stocks_scanned:2832},
    top:{gainers:[row], fallers:[]}, sectors:{Technology:{total_scanned:1, total_gainers:1}},
    earnings:[{ticker:'AAA', company_name:name, date:'2026-08-06', session:'After hours'}],
    available_dates:[day], scan_timestamp:day+'T09:00:00-04:00'};
}

test('overview links preserve research date and escape untrusted names/previews', async () => {
  const ui = mount('overview', () => report('2026-08-07', '<img src=x onerror=bad()>'));
  await tick();
  const html = ui.nodes['pmv-content'].innerHTML;
  assert.match(html, /premarket\/stocks\/AAA\?date=2026-08-07/);
  assert.match(html, /premarket\/sectors\?date=2026-08-07&amp;sector=Technology/);
  assert.match(html, /Saved catalyst/);
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
  assert.match(html, /After hours/);
});

test('changing dates clears an archived run and discards an older in-flight result', async () => {
  let release;
  const ui = mount('history', url => url.includes('run_id=old')
    ? new Promise(resolve => { release = resolve; }) : report('2026-08-06'), '?date=2026-08-07&run_id=old');
  await tick();
  ui.nodes['pmv-date'].value = '2026-08-06';
  await ui.nodes['pmv-date'].handlers.change();
  await tick();
  release(report('2026-08-07'));
  await tick();
  assert.equal(ui.nodes['pmv-date'].value, '2026-08-06');
  assert.match(ui.nodes['pmv-content'].innerHTML, /date=2026-08-06/);
  assert.doesNotMatch(ui.navigation.at(-1), /run_id/);
});

test('stock generation posts the selected date then polls and loads saved research', async () => {
  let completed = false;
  const ui = mount('stock', (url, options) => {
    if (options?.method === 'POST') {
      assert.equal(JSON.parse(options.body).date, '2026-08-07');
      return {status:'queued', job_id:'job-1'};
    }
    if (url.startsWith('/premarket/jobs/')) { completed = true; return {status:'completed'}; }
    return {stock:{ticker:'AAA', company_name:'Alpha', premarket_close:110, prev_close:100},
      trading_date:'2026-08-07', can_analyze:true, history:[],
      analyses:completed ? [{provider:'grok', text:'Saved result', html:'<p>Saved result</p>'}] : []};
  });
  await tick();
  await ui.nodes['pmv-analyze'].handlers.click();
  assert.equal(completed, true);
  assert.match(ui.nodes['pmv-content'].innerHTML, /Saved result/);
  assert.match(ui.nodes['pmv-chart'].innerHTML, /Minute bars are unavailable/);
});
