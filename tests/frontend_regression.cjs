const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
let checks = 0;
function context() {
  const elements = new Map();
  function element() {
    const children = new Map();
    return {value:'',style:{},textContent:'',innerHTML:'',classList:{toggle(){}},
      querySelector(selector) { if (!children.has(selector)) children.set(selector,element()); return children.get(selector); }};
  }
  const sandbox = { console, window: { addEventListener() {} }, document: {
    addEventListener() {},
    getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
    createElement() { return {textContent:'',get innerHTML(){return this.textContent.replaceAll('&','&amp;').replaceAll('<','&lt;');}}; }
  }};
  vm.createContext(sandbox);
  return sandbox;
}
function load(ctx, file) { vm.runInContext(fs.readFileSync(path.join(root, 'app/static', file), 'utf8'), ctx); }
async function main() {
  const scores = context(); load(scores, 'trajectory_page.js');
  for (const [input, expected] of [
    ['2024年10月模拟考，总分650，校排100',650], ['总分：650.5',650.5], ['650分',650],
    ['2024年模拟考试，校排名650',null], ['省位次11100',null], ['总分：800',null],
    ['总分7500',null], ['语文120分，数学130分',null], ['总成绩：0',0], ['2024-10-18',null],
  ]) { assert.equal(scores.parseScoreFromText(input), expected, input); checks++; }
  const common = context(); load(common, 'common.js');
  for (const [item, expected] of [
    [{subject_requirement_kind:'unrestricted',subject_eligibility:'eligible'},'不限选科'],
    [{subject_requirement_kind:'restricted',subject_eligibility:'eligible'},'选科符合计划原文'],
    [{subject_requirement_kind:'restricted',subject_eligibility:'unknown',subject_missing:['化学']},'选科待核实 · 需确认化学'],
    [{subject_requirement_kind:'unknown',subject_eligibility:'unknown'},'选科待核实'],
  ]) { assert.equal(common.subjectEligibilityLabel(item),expected); checks++; }
  for (const input of ['（计算机，物理，人工智能）','计算机、物理；人工智能','计算机,物理,人工智能']) {
    assert.equal(JSON.stringify(common.splitCsv(input)), JSON.stringify(['计算机','物理','人工智能'])); checks++;
  }
  const sim = context(); load(sim, 'common.js'); load(sim, 'simulate_page.js');
  const calls = [];
  sim.getState = () => ({rank:11100,score:650,subject_combo:'物理、历史、地理',year:2024,provinces:['成都','上海'],majors:['计算机'],ratio_chong:0,ratio_wen:4,ratio_bao:3});
  sim.api = async (url,method,body) => { calls.push(body); return {all:[],meta:{warnings:[]}}; };
  sim.showToast = () => {};
  sim.document.getElementById('whatifNewRank').value = '12000';
  await sim.runWhatIf();
  assert.equal(calls.length,2); checks++;
  for (const request of calls) {
    assert.equal(request.subject_combo,'物理、历史、地理'); checks++;
    assert.equal(request.ratio_chong,0); checks++;
    assert.equal(request.candidate_scope,'all'); checks++;
    assert.equal(JSON.stringify(request.provinces),JSON.stringify(['成都','上海'])); checks++;
  }
  const main = context(); load(main, 'common.js'); load(main, 'main_page.js');
  main.getState = () => [];
  main.document.getElementById('candidateScope').value = 'all';
  assert.equal(main.collectMainInput().candidate_scope,'all'); checks++;
  main.fillMainInput({rank:120000, candidate_scope:'window'});
  assert.equal(main.collectMainInput().candidate_scope,'window'); checks++;
  const rec = context(); load(rec,'common.js'); load(rec,'recommend_page.js');
  rec.toggleEmptyState = () => {};
  rec.testResult = {all:[],meta:{recommendation_version:'preferences-v6',filter_diagnostics:{major_resolutions:[{input:'财会',scope:['会计','财务管理','审计'],level:'领域别名'}]}}};
  vm.runInContext('getState = (key) => key === STORAGE_KEYS.recommendResult ? testResult : []',rec);
  rec.render();
  assert.match(rec.document.getElementById('recommendDiagnostics').textContent,/财会 → 会计、财务管理、审计/); checks++;
  assert.equal(rec.document.getElementById('recommendEmpty').querySelector('.empty-title').textContent,'当前条件下暂无推荐'); checks++;
  assert.match(rec.document.getElementById('recommendEmpty').querySelector('.empty-description').textContent,/冲稳保比例/); checks++;
  rec.testResult.meta.recommendation_version = 'preferences-v5'; rec.render();
  assert.match(rec.document.getElementById('recommendDiagnostics').textContent,/旧版筛选结果/); checks++;
  const config = context(); load(config,'common.js');
  const nodes = new Map();
  function domNode() { return {textContent:'',children:[],disabled:false,handlers:{},classList:{toggle(){}},
    append(...items) {this.children.push(...items);}, prepend(item) {this.children.unshift(item);},
    replaceChildren(...items) {this.children=items;}, setAttribute(){},
    addEventListener(event,handler) {this.handlers[event]=handler;}, showModal(){}, close(){}}; }
  config.document.getElementById = (id) => {if(!nodes.has(id)) nodes.set(id,domNode());return nodes.get(id);};
  config.document.createElement = domNode;
  const component = {name:'测试组件',state:'missing',ready:false,title:'未填写',detail:'请配置',docs_url:'https://example.org/'};
  let setup = {data_ready:false,components:{neo4j:{...component},ocr:{...component},deepseek:{...component,configured:false,verified:false}}};
  config.api = async () => setup;
  config.initConfigurationChecks();
  await new Promise(setImmediate);
  assert.equal(nodes.get('configurationVerify').disabled,true); checks++;
  assert.match(nodes.get('mainContent').children[0].children[0].textContent,/API Key 未填写/); checks++;
  assert.equal(nodes.get('configurationItems').children.length,3); checks++;
  setup = {data_ready:true,components:{neo4j:{...component,state:'ok',ready:true},ocr:{...component,state:'ok',ready:true},deepseek:{...component,configured:true,verified:true,state:'ok'}}};
  await nodes.get('configurationRefresh').handlers.click();
  assert.equal(nodes.get('configurationVerify').disabled,false); checks++;
  assert.match(nodes.get('mainContent').children[0].children[0].textContent,/API 验证通过/); checks++;
  assert.equal(nodes.get('configurationBadge').textContent,'环境配置可用'); checks++;
  console.log(JSON.stringify({passed:true,checks}));
}
main().catch(error => { console.error(error); process.exitCode=1; });
