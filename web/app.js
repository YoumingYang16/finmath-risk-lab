'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = { price: null, simulation: null, results: null, competencies: null, researchV2: null };
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const fmt = (value, digits = 4) => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('en-US', {maximumFractionDigits: digits, minimumFractionDigits: digits}) : '—';
const compact = value => typeof value === 'number' ? Number.isInteger(value) ? value.toLocaleString('en-US') : fmt(value, Math.abs(value) < .001 ? 7 : 4) : value === true ? '是' : value === false ? '否' : value == null ? '—' : String(value);
const list = value => Array.isArray(value) ? value : value && typeof value === 'object' ? Object.entries(value).map(([key, item]) => typeof item === 'object' && item !== null ? {id: key, ...item} : {id:key, value:item}) : [];
const display = value => Array.isArray(value) ? value.map(display).join(' · ') : value && typeof value === 'object' ? Object.entries(value).map(([k,v])=>`${k}: ${display(v)}`).join('；') : compact(value);
const labels = { n:'样本数', n_paths:'路径数', mean_pnl:'平均损益', std_pnl:'损益标准差', rmse:'损益 RMSE', mean_loss:'平均损失', var95:'损失 VaR 95%', es95:'损失 ES 95%', mean_cost:'期末化平均成本', mean_trades:'平均交易次数', source:'来源', status:'状态', selection:'模型选择', selected_model:'选定模型', model:'模型', split:'数据划分', currency:'汇率', qlike:'QLIKE', mse:'MSE', ci_low:'区间下限', ci_high:'区间上限', difference:'均值差', standard_error:'标准误', step:'步数', time:'时间 / 年', spot:'标的价格', delta:'Delta', shares:'持仓', cash:'现金余额', cost:'费用', trade:'交易数量', trade_shares:'交易数量', option_payoff:'期权支付', payoff:'到期支付', event:'事件', position:'持仓', terminal_pnl:'期末损益', hedge_value:'对冲价值', trade_cost:'交易费用', cash_before:'交易前现金', cash_after:'交易后现金', action:'操作', turnover:'交易名义金额', interest:'现金利息' };
const label = key => labels[key] || key.replaceAll('_', ' ');
function toast(message) { const node = $('#toast'); node.textContent=message; node.hidden=false; clearTimeout(toast.timer); toast.timer=setTimeout(()=>node.hidden=true,3200); }
async function api(path, data) { const options=data===undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)}; const response=await fetch(path, options); const body=await response.json(); if(!response.ok) throw new Error(body.error || `请求失败 (${response.status})`); return body; }
function readForm(form) { const result={}; for (const [key,value] of new FormData(form)) { if(value==='')continue; result[key]=['kind','model','policy'].includes(key)?value:Number(value); } return result; }
function setMessage(id, text, type='') { const node=$(id); node.textContent=text; node.className=`form-message ${type}`; }
function setBusy(form,busy) { $('button[type="submit"]',form).disabled=busy; form.setAttribute('aria-busy',String(busy)); }
function table(rows, columns, className='') { if(!rows.length)return '<p class="muted">没有可用记录。</p>'; return `<div class="table-wrap" tabindex="0" aria-label="数据表格，可左右滚动"><table class="${esc(className)}"><thead><tr>${columns.map(column=>`<th scope="col">${esc(column.title || label(column.key))}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${columns.map(column=>`<td>${esc(column.format?column.format(row[column.key],row):display(row[column.key]))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`; }
function lineChart(series, {title='数值曲线',xLabel='标的价格',yLabel='期权价格',dark=false,height=255,nonnegative=false}={}) {
  if(!series.length || !series[0].points.length)return '<p class="muted">没有可用数据。</p>';
  const all=series.flatMap(s=>s.points), xs=all.map(p=>p[0]), ys=all.map(p=>p[1]);
  let xmin=Math.min(...xs), xmax=Math.max(...xs), ymin=Math.min(...ys), ymax=Math.max(...ys);
  if(xmin===xmax)xmax=xmin+1;if(ymin===ymax)ymax=ymin+1;
  const pad=(ymax-ymin)*.08;ymin-=pad;ymax+=pad;if(nonnegative)ymin=Math.max(0,ymin);
  const w=620,h=height,l=54,r=15,t=25,b=39,pw=w-l-r,ph=h-t-b;
  const x=v=>l+(v-xmin)/(xmax-xmin)*pw,y=v=>h-b-(v-ymin)/(ymax-ymin)*ph;
  const ticks=Array.from({length:5},(_,i)=>i/4),colors=dark?['#7bc3b5','#c99766']:['#137d74','#c96d36','#719490','#8e9b72','#7c85a0','#ae8e70','#8bafa4','#a6b2bc'];
  const tickX=v=>xLabel==='年份'?String(Math.round(v)):fmt(v,xmax-xmin<1?3:1);
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(title)}"><title>${esc(title)}</title><desc>${esc(`${series.length} 条曲线；${xLabel} ${fmt(xmin,2)} 至 ${fmt(xmax,2)}；${yLabel}范围 ${fmt(ymin,2)} 至 ${fmt(ymax,2)}。`)}</desc>${ticks.map(i=>{const v=ymin+i*(ymax-ymin);return `<line class="grid" x1="${l}" x2="${w-r}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${l-9}" y="${y(v)+3}" text-anchor="end">${fmt(v,1)}</text>`}).join('')}${ticks.map(i=>{const v=xmin+i*(xmax-xmin);return `<text class="axis" x="${x(v)}" y="${h-b+19}" text-anchor="middle">${tickX(v)}</text>`}).join('')}${series.map((s,i)=>`<path fill="none" stroke="${colors[i%colors.length]}" stroke-width="${series.length>2?1.25:2.4}" opacity="${series.length>2?.8:1}" d="${s.points.map((p,j)=>`${j?'L':'M'}${x(p[0]).toFixed(2)},${y(p[1]).toFixed(2)}`).join(' ')}"><title>${esc(s.name)}</title></path>`).join('')}<text class="axis" x="${l}" y="12">${esc(yLabel)}</text><text class="axis" x="${w-r}" y="${h-3}" text-anchor="end">${esc(xLabel)}</text></svg>`;
}
function histogramChart(histogram) {
 const {counts,edges}=histogram,w=620,h=235,l=46,r=15,t=25,b=40,pw=w-l-r,ph=h-t-b,max=Math.max(...counts,1),bw=pw/counts.length;
 return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="期末损益直方图"><title>所选策略期末损益分布，已计交易成本</title>${[0,.5,1].map(f=>`<line class="grid" x1="${l}" x2="${w-r}" y1="${h-b-f*ph}" y2="${h-b-f*ph}"/><text class="axis" x="${l-8}" y="${h-b-f*ph+3}" text-anchor="end">${Math.round(max*f)}</text>`).join('')}${counts.map((count,i)=>`<rect x="${l+i*bw+1}" y="${h-b-count/max*ph}" width="${Math.max(bw-2,1)}" height="${count/max*ph}" fill="${(edges[i]+edges[i+1])/2<0?'#c98b63':'#438e7c'}"><title>${fmt(edges[i],3)} 至 ${fmt(edges[i+1],3)}：${count} 条路径</title></rect>`).join('')}${[0,.25,.5,.75,1].map(f=>`<text class="axis" x="${l+f*pw}" y="${h-b+20}" text-anchor="middle">${fmt(edges[0]+f*(edges.at(-1)-edges[0]),2)}</text>`).join('')}<text class="axis" x="${l}" y="12">路径数</text><text class="axis" x="${w-r}" y="${h-2}" text-anchor="end">期末损益 / 货币单位</text></svg>`;
}
function renderPrice(result) {
  const p=result.parameters, mc=result.mc;
  $('#price-results').className='';
  $('#price-results').innerHTML=`<div class="price-strip"><div><span class="metric-label">BLACK–SCHOLES</span><strong class="metric-number primary">${fmt(result.bs)}</strong><span class="metric-foot">解析基准 / ${p.kind==='call'?'看涨':'看跌'}</span></div><div><span class="metric-label">CRR 二叉树</span><strong class="metric-number">${fmt(result.crr)}</strong><span class="metric-foot">${result.settings.crr_steps} 步 · 差值 ${fmt(result.crr-result.bs)}</span></div><div><span class="metric-label">蒙特卡洛</span><strong class="metric-number">${fmt(mc.price)}</strong><span class="metric-foot">95% CI [${fmt(mc.ci_low,3)}, ${fmt(mc.ci_high,3)}]</span></div></div><p class="inline-fact">路径数 <strong>${compact(mc.n_paths)}</strong> · 独立抽样单元 <strong>${compact(mc.independent_units)}</strong> · Seed <strong>${result.settings.seed}</strong>${result.implied_volatility!==undefined?` · 隐含波动率 <strong>${fmt(result.implied_volatility*100,2)}%</strong>`:''}</p>`;
  const series=[{name:'Black–Scholes 价格',points:result.curve.map(p=>[p.spot,p.price])}];
  $('#price-chart').innerHTML=lineChart(series,{title:'标的价格变化时的欧式期权价格',nonnegative:true});
  $('#hero-chart').innerHTML=lineChart(series,{title:'实时定价模型截面',dark:true,height:230,nonnegative:true});
  $('#hero-caption').textContent=`K = ${compact(p.strike)} · T = ${compact(p.maturity)} 年 · σ = ${fmt(p.vol*100,1)}% · ${p.kind==='call'?'看涨期权':'看跌期权'}`;
  $('#greeks').innerHTML=`<div class="greek-grid">${['delta','gamma','vega','theta','rho'].map(key=>`<div><span>${key[0].toUpperCase()+key.slice(1)}</span><strong>${fmt(result.greeks[key])}</strong></div>`).join('')}</div><p class="unit-note">Vega / Rho 按波动率 / 利率变化 1.0 计；若查看变化 1 个百分点的影响，除以 100。Theta 按一年计；Delta 与 Gamma 按标的价格变化 1 单位计。</p>`;
}
async function calculatePrice(event) {
  event?.preventDefault();const form=$('#price-form');if(!form.reportValidity())return;
  setBusy(form,true);setMessage('#price-message','正在运行解析、二叉树与蒙特卡洛计算…');
  try { const result=await api('/api/price',readForm(form));state.price=result;renderPrice(result);setMessage('#price-message','计算完成。显示结果对应上次提交的参数。','success'); }
  catch(error){setMessage('#price-message',`计算未完成：${error.message}`,'error');if(!state.price)$('#hero-chart').textContent='计算内核暂不可用；未生成图形。';}
  finally{setBusy(form,false);}
}
function renderSimulation(result) {
  const rows=['mean_pnl','rmse','mean_cost','mean_trades','var95','es95'].map(key=>({metric:label(key),chosen:result.summary[key],reference:result.reference[key]}));
  const ci=result.paired_pnl_difference;
  $('#hedge-results').className='';
  $('#hedge-results').innerHTML=`<p class="inline-fact">共同初始权利金 <strong>${fmt(result.premium)}</strong> · <strong>${compact(result.parameters.n_paths)}</strong> 条路径 · Seed <strong>${result.parameters.seed}</strong></p>${table(rows,[{key:'metric',title:'评价指标'},{key:'chosen',title:'所选策略',format:v=>fmt(v)},{key:'reference',title:'每步调仓',format:v=>fmt(v)}],'compare-table')}<div class="interval"><strong>配对平均损益差：${fmt(ci.difference)}</strong><br>所选策略 − 每步调仓 · 95% CI [${fmt(ci.ci_low)}, ${fmt(ci.ci_high)}]${ci.ci_low<=0&&ci.ci_high>=0?'<br>区间包含 0；本次模拟未清楚区分均值差异。':''}</div>`;
  $('#path-chart').innerHTML=lineChart(result.paths.map((path,i)=>({name:`路径 ${i+1}`,points:path.map((v,j)=>[j/result.parameters.steps*result.parameters.horizon,v])})),{title:'同一实验生成的前八条价格路径',xLabel:'时间 / 年',yLabel:'标的价格',height:235});
  $('#histogram').innerHTML=histogramChart(result.histogram);
  $('#ledger-section').hidden=false;
  const keys=[...new Set(result.ledger.flatMap(row=>Object.keys(row)))];
  $('#ledger').innerHTML=table(result.ledger,keys.map(key=>({key,title:label(key),format:v=>typeof v==='number'?fmt(v,5):display(v)})));
}
async function calculateHedge(event){
 event.preventDefault();const form=$('#hedge-form');if(!form.reportValidity())return;const params=readForm(form);
 if(params.n_paths*(params.steps+1)>400000){setMessage('#hedge-message','路径数 ×（步数 + 1）不能超过 400,000。请减小路径数或步数。','error');return;}
 if(params.policy==='fixed'&&params.every>params.steps){setMessage('#hedge-message','调仓间隔不能大于每条路径的步数。','error');return;}
 setBusy(form,true);setMessage('#hedge-message','正在生成路径、逐步核算并进行配对比较…');
 try{state.simulation=await api('/api/simulate',params);renderSimulation(state.simulation);setMessage('#hedge-message','实验完成。以下为该配置的实际计算结果。','success');}
 catch(error){setMessage('#hedge-message',`实验未完成：${error.message}`,'error');}
 finally{setBusy(form,false);}
}
function updateConditionalFields(){
 $('#regime-fields').hidden=$('#path-model').value!=='regime';$('#jump-fields').hidden=$('#path-model').value!=='jump';
 $('#every-field').hidden=$('#hedge-policy').value!=='fixed';$('#threshold-field').hidden=$('#hedge-policy').value!=='threshold';
 for(const group of ['#regime-fields','#jump-fields','#every-field','#threshold-field'])$$('input',$(group)).forEach(input=>input.disabled=$(group).hidden);
}
function navigate(){
 $('#toast').hidden=true;
 const allowed=['overview','pricing','hedging','historical','competencies','research-v2'];const requested=location.hash.slice(1),page=allowed.includes(requested)?requested:'overview';
 $$('.page').forEach(node=>{node.hidden=node.id!==page;node.classList.toggle('active',node.id===page)});
 $$('nav a').forEach(a=>{if(a.dataset.page===page)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')});
 $('#breadcrumb').textContent=`RESEARCH / ${{overview:'OVERVIEW',pricing:'PRICING',hedging:'HEDGING',historical:'EVIDENCE',competencies:'CAPABILITIES','research-v2':'DEPTH & PUBLICATION'}[page]}`;
 document.title=`${{overview:'研究概览',pricing:'定价与敏感度',hedging:'对冲实验',historical:'历史数据证据',competencies:'能力并集','research-v2':'研究深化与投稿'}[page]} · FinMath Risk Lab`;
 if(requested)$('#main').focus({preventScroll:true});window.scrollTo({top:0,behavior:'instant'});
}
function renderEvidence(){
 const map={simulation:['可控模拟研究','相同路径、统一核算与模型误设'],historical:['历史参考数据研究','按时间划分、验证选择与锁定测试'],validation:['实现与研究验证','软件测试、数值校验与执行记录']};
 $('#evidence-status').innerHTML=Object.entries(map).map(([key,[title,desc]],i)=>{const item=state.results?.[key],available=item?.status==='available';return `<div class="evidence-row"><span class="index">${String(i+1).padStart(2,'0')}</span><div><h3>${title}</h3><p>${desc}</p></div><span class="badge ${available?'':item?.status==='invalid'?'error':'pending'}">${available?'结果文件已生成':item?.status==='invalid'?'文件无效':'尚未生成'}</span></div>`}).join('');
}
function renderRecord(value,depth=0){
 if(value===null||value===undefined)return '<span class="muted">未提供</span>';
 if(Array.isArray(value)){
   if(!value.length)return '<span class="muted">无记录</span>';
   if(value.every(row=>row&&typeof row==='object'&&!Array.isArray(row))){const keys=[...new Set(value.flatMap(row=>Object.keys(row)))];if(keys.length<=12)return table(value,keys.map(key=>({key})));}
   return `<ul>${value.map(item=>`<li>${esc(display(item))}</li>`).join('')}</ul>`;
 }
 if(typeof value==='object')return `<dl>${Object.entries(value).map(([key,item])=>`<div class="key-value"><dt>${esc(label(key))}</dt><dd>${esc(display(item))}</dd></div>`).join('')}</dl>`;
 return `<p>${esc(display(value))}</p>`;
}
function renderHistorical(){
 const artifact=state.results?.historical,node=$('#historical-content');
 if(artifact?.status!=='available'){node.className='empty-state';node.textContent=artifact?.message||'历史实验尚未生成。运行历史数据与研究脚本后刷新。';$('#historical-json').textContent=JSON.stringify(artifact||{},null,2);return;}
 const data=artifact.data;node.className='';$('#historical-json').textContent=JSON.stringify(data,null,2);
 if(data.currencies){
   node.innerHTML=`<div class="research-callout"><strong>真实参考数据，假想对冲实验</strong><p>ECB · ${compact(data.data_quality?.processed_rows)} 个原始日期观察 · 截至 ${esc(data.analysis_endpoint)}。两种汇率分别评价，不合并成独立重复实验。</p></div><div class="history-toolbar"><label>查看汇率<select id="history-currency">${Object.keys(data.currencies).map(key=>`<option value="${esc(key)}">${esc(key)} / 每 1 欧元</option>`).join('')}</select></label><span>${link(data.source?.source_url,'ECB 数据来源 ↗')}</span></div><div id="currency-evidence"></div><details><summary>数据来源、处理与实验口径</summary><section class="evidence-detail"><h3>数据质量</h3>${renderRecord(data.data_quality)}</section><section class="evidence-detail"><h3>指标定义</h3>${renderRecord(data.metric_definitions)}</section><section class="evidence-detail"><h3>全部解释限制</h3>${renderRecord(data.limitations||data.caveats)}</section></details>`;
   $('#history-currency').addEventListener('change',()=>renderCurrency(data,$('#history-currency').value));renderCurrency(data,Object.keys(data.currencies)[0]);return;
 }
 node.innerHTML=Object.entries(data).map(([key,value])=>`<section class="evidence-detail"><h3>${esc(label(key))}</h3>${renderRecord(value)}</section>`).join('');
}
const methodNames={train_constant:'训练期固定估计',rolling63:'63 期滚动估计',ewma:'EWMA 指数加权',ridge:'Ridge 正则回归',frozen_rolling63_daily:'初始估计固定 / 每步',rolling63_daily:'滚动估计 / 每步',ewma_daily:'EWMA / 每步',ridge_daily:'Ridge / 每步',selected_daily:'验证选定模型 / 每步',selected_every5:'验证选定模型 / 每 5 步',selected_threshold:'验证选定模型 / 阈值调仓'};
function renderCurrency(data,currency){
 const item=data.currencies[currency],test=item.forecast_evaluation.test;
 const forecast=Object.entries(test.metrics).map(([key,value])=>({method:methodNames[key]||key,qlike:value.qlike,mse:value.mse}));
 const hedge=item.hedging_metrics.filter(row=>row.split==='test'&&row.cost_bps===5);
 const selected=item.selection.selected_forecast_family;
 const interval=item.forecast_evaluation.test_loss_difference_intervals.find(row=>row.candidate===selected&&row.metric==='qlike'&&row.block_length===21);
 const daily=hedge.find(row=>row.strategy==='selected_daily'),threshold=hedge.find(row=>row.strategy==='selected_threshold');
 const costChange=daily&&threshold?threshold.mean_cost-daily.mean_cost:null,rmseChange=daily&&threshold?threshold.rmse-daily.rmse:null;
 const annual=['rolling63','ewma','ridge'].map(key=>({name:methodNames[key],points:item.forecast_evaluation.test_yearly.filter(row=>row.method===key).map(row=>[row.year,row.qlike])}));
 $('#currency-evidence').innerHTML=`<div class="price-strip"><div><span class="metric-label">锁定测试预测数</span><strong class="metric-number primary">${compact(test.n)}</strong><span class="metric-foot">${esc(test.target_start)} — ${esc(test.target_end)}</span></div><div><span class="metric-label">非重叠对冲片段</span><strong class="metric-number">${compact(item.episode_counts.test.n)}</strong><span class="metric-foot">每段 ${compact(data.protocol.episode_steps)} 个收益观察</span></div><div><span class="metric-label">验证阶段选定模型</span><strong class="metric-number">${esc(selected.toUpperCase())}</strong><span class="metric-foot">阈值 ${compact(item.threshold_selection.chosen_threshold)} · 不基于测试集选择</span></div></div>
 <div class="section-title"><h2>预测能力 / 锁定测试</h2><span>数值越小越好</span></div>${table(forecast,[{key:'method',title:'估计方法'},{key:'qlike',title:'QLIKE',format:v=>fmt(v,6)},{key:'mse',title:'MSE',format:v=>Number(v).toExponential(5)}])}
 <p class="unit-note">QLIKE 为 log(h) + y/h 的平均值，允许为负。MSE 使用未年化的方差单位。平方收益是含噪的二阶矩代理，预测指标不等于实际对冲表现。</p>
 ${interval?`<div class="interval">选定模型相对 63 期滚动估计的 QLIKE 差：<strong>${fmt(interval.mean,6)}</strong><br>95% 移动分块区间 [${fmt(interval.ci_low,6)}, ${fmt(interval.ci_high,6)}] · 区块长 ${interval.block_length}${interval.ci_low<=0&&interval.ci_high>=0?'<br>区间包含 0。当前证据不能清楚区分平均预测损失。':''}<br>负差值有利于候选模型；区间为点态、条件于模型选择，未作多重比较修正。</div>`:''}
 <div class="section-title"><h2>按年度检查稳定性</h2><span>QLIKE / 测试期</span></div><div class="historical-chart">${lineChart(annual,{title:`${currency} 年度预测QLIKE`,xLabel:'年份',yLabel:'QLIKE',height:245})}</div><p class="plot-caption">青绿：63 期滚动估计 · 橙色：EWMA · 灰绿：Ridge</p>
 <div class="section-title"><h2>对冲能力 / 单边 5 基点</h2><span>初始价格统一为 100</span></div>${table(hedge,[{key:'strategy',title:'对冲策略',format:v=>methodNames[v]||v},{key:'rmse',title:'净损益 RMSE',format:v=>fmt(v)},{key:'gross_replication_rmse',title:'费用前复制 RMSE',format:v=>fmt(v)},{key:'mean_cost',title:'平均费用',format:v=>fmt(v)},{key:'mean_trades',title:'交易次数',format:v=>fmt(v,2)},{key:'es95',title:'损失 ES95',format:v=>fmt(v)}])}
 ${daily&&threshold?`<div class="interval"><strong>保留取舍，不只展示胜出指标</strong><br>阈值策略相对每步调仓：平均费用${costChange<0?'下降':'上升'} ${fmt(Math.abs(costChange))}，净损益 RMSE ${rmseChange<0?'下降':'上升'} ${fmt(Math.abs(rmseChange))}。这些是样本描述，不自动构成显著性结论。</div>`:''}
 <p class="unit-note">每种策略使用同一片段起点的信息和共同权利金。测试期预算达标与否按实际结果记录；验证期可行性不是未来费用保证。每种汇率仅 ${compact(item.episode_counts.test.n)} 个测试片段，95% 尾部只涉及少数片段。</p>`;
}
function link(url,text='官方来源 ↗'){try{const parsed=new URL(url);return ['https:','http:'].includes(parsed.protocol)?`<a href="${esc(parsed.href)}" target="_blank" rel="noopener noreferrer">${esc(text)}</a>`:esc(text);}catch{return esc(text);}}
function renderCompetencies(){
 const artifact=state.competencies,node=$('#competency-content');$('#competency-json').textContent=JSON.stringify(artifact||{},null,2);
 if(artifact?.status!=='available'){node.className='empty-state';node.textContent=artifact?.message||'能力并集与来源映射尚未生成。';return;}
 const data=artifact.data;node.className='';const competencies=list(data.competencies||data.capabilities||data.union),programs=list(data.programs||data.schools);
 const statusNames={implemented_pending_validation:'已实现，待验证',implemented_validated:'已有执行证据',validated:'已有执行证据',executed:'已有执行证据',partial:'部分覆盖',external_evidence_required:'需要外部证据'};
 let html='';if(competencies.length){html+='<div class="section-title"><h2>能力与成果对应</h2><span>相同项目 · 可核查证据</span></div>';html+=table(competencies,[{key:'name',title:'能力',format:(v,row)=>v||row.title||row.id},{key:'description',title:'能力内涵',format:(v,row)=>v||row.meaning||row.requirement||'见完整映射'},{key:'evidence',title:'项目证据',format:(v,row)=>display(v?.length?v:row.project_evidence||row.artifacts||row.deliverables||'本项目不单独提供')},{key:'status',title:'覆盖边界',format:(v,row)=>statusNames[v]||display(v||row.boundary||row.coverage||'辅助证据')}]);}
 if(programs.length){html+='<div class="section-title"><h2>十个项目的官方来源</h2><span>公开侧重的并集 ∪</span></div><div class="program-list">'+programs.map(p=>`<article class="program-item"><h3>${esc(p.name||p.program||p.id)}</h3><p>${esc(display(p.emphases||p.focus||p.capabilities||p.requirements||p.summary||''))}</p>${p.note?`<p>${esc(p.note)}</p>`:''}${link(p.url||p.source_url||p.sources?.[0]?.url||'', '核对官方项目说明 ↗')}</article>`).join('')+'</div>';}
 if(data.boundaries||data.limitations)html+='<div class="section-title"><h2>仍需其他材料证明</h2></div>'+renderRecord(data.boundaries||data.limitations);
 node.innerHTML=html||Object.entries(data).map(([key,value])=>`<section class="evidence-detail"><h3>${esc(label(key))}</h3>${renderRecord(value)}</section>`).join('');
}
const v2Labels = {forecast_first:'预测优先选择',joint_mse:'联合选择 / 净 MSE',joint_es90:'联合选择 / ES90',retrospective:'回溯评价',holdout:'留出期',currency:'汇率',cost_bps:'费率 / bps',selector:'选择流程',scenario:'场景',validation_paths:'验证路径数',difference:'配对差',mean_difference:'平均配对差',ci_low:'95% 区间下限',ci_high:'95% 区间上限',p_value:'近似 p 值',p_holm:'Holm 校正 p 值',mse:'净 MSE',es90:'损失 ES90',mean_cost:'平均期末化成本',budget_exceeded:'预算超限',n:'样本数',replicates:'独立重复数',objective:'目标值',max_constraint_violation:'最大约束违差'};
Object.assign(v2Labels,{record:'记录',value:'实际值',heston:'Heston 匹配',matched_heston:'Heston 匹配',matched_gbm:'GBM 匹配',heston_shift:'Heston 参数变化',jump_shift:'跳跃机制变化',test_mse:'测试净 MSE',validation_n:'验证路径数',fee_bps:'费率 / bps',baseline:'比较基准',metric:'指标',primary:'预定主比较',method:'方法',replicate:'重复编号',mean_test_mse:'平均测试净 MSE',mean_test_variance:'平均损益方差',mean_test_bias_squared:'平均偏差平方',mean_test_es90:'平均测试 ES90',mean_test_cost:'平均期末化成本',test_budget_violation_fraction:'测试预算超限比例',validation_fallback_fraction:'验证不可行比例',mean_reference_signed_gap:'有限类参考差',selection_entropy_nats:'选择熵 / nat',most_selected_fraction:'最常选候选的比例',all_fits_successful:'全部求解成功',fits:'已执行拟合',max_abs_duality_gap:'最大绝对对偶间隙',max_objective_reconciliation_gap:'最大独立目标核对差',convex_cvar:'CVaR 凸优化',validation_selected_band:'验证选定无交易带',position_violation_fraction:'持仓约束违反比例',test_budget_exceeded:'测试平均成本超预算'});
Object.assign(v2Labels,{period:'评价时期',additional_2026:'2026 年额外留出期',retrospective:'2015–2025 回溯期',holm_six_currency_p:'六币 Holm 校正 p',fold_budget_exceedance_fraction:'年份平均成本超限比例',ridge_term:'Ridge 期限匹配',ridge_flat:'Ridge 单期外推',ewma97:'EWMA 0.97',rolling63:'63 期滚动',band05:'无交易带 0.05',band10:'无交易带 0.10',daily:'每步调仓',every5:'每 5 步调仓',policy:'策略'});
function v2Name(value){return v2Labels[value]||label(value);}
function v2Data(name){return state.researchV2?.[name]?.status==='available'?state.researchV2[name].data:null;}
function v2Missing(name){const artifact=state.researchV2?.[name];return `<div class="v2-missing"><strong>${artifact?.status==='invalid'?'文件无效，未展示数值':artifact?.status==='too_large'?'摘要超过读取上限':'尚未生成可用结果'}</strong><p>${esc(artifact?.message||'尚未读取此研究文件。')}。读取结果不会自动执行实验。</p></div>`;}
function v2Rows(value){
 if(Array.isArray(value))return value.filter(row=>row&&typeof row==='object'&&!Array.isArray(row));
 if(value&&typeof value==='object')return Object.entries(value).map(([key,item])=>item&&typeof item==='object'&&!Array.isArray(item)?{record:key,...item}:{record:key,value:item});
 return [];
}
function v2Table(value,maxRows=30){
 const rows=v2Rows(value);if(!rows.length)return `<p class="muted">${esc(display(value))}</p>`;
 const keys=[...new Set(rows.flatMap(row=>Object.keys(row)))].filter(key=>rows.some(row=>row[key]!=null&&typeof row[key]!=='object')).slice(0,12);
 if(!keys.length)return `<p class="muted">此记录包含嵌套审计数据，请展开原始记录核对。</p>`;
 return table(rows.slice(0,maxRows),keys.map(key=>({key,title:v2Name(key),format:v=>typeof v==='number'?compact(v):v2Labels[v]||display(v)})))+(rows.length>maxRows?`<p class="unit-note">显示前 ${maxRows} / ${rows.length} 条，全部记录包含在导出 JSON 中。</p>`:'');
}
function v2Block(title,value){return `<article class="v2-result-block"><h3>${esc(title)}</h3>${v2Table(value)}</article>`;}
function firstRecord(data,keys){for(const key of keys)if(data?.[key]!=null)return data[key];return null;}
function v2Interval(row,title='配对差与 95% 区间'){
 if(!row||![row.difference,row.ci_low,row.ci_high].every(Number.isFinite))return v2Table(row);
 let lo=Math.min(0,row.ci_low),hi=Math.max(0,row.ci_high),span=hi-lo||1;lo-=span*.15;hi+=span*.15;
 const x=v=>40+(v-lo)/(hi-lo)*600,zero=x(0),included=row.ci_low<=0&&row.ci_high>=0;
 return `<div class="v2-metric-grid"><div><span>候选 − 基准 / ${esc(v2Name(row.metric||'mse'))}</span><strong>${fmt(row.difference,6)}</strong></div><div><span>95% 区间</span><strong class="v2-ci-value">[${fmt(row.ci_low,6)}, ${fmt(row.ci_high,6)}]</strong></div><div><span>独立评价单元数</span><strong>${compact(row.n)}</strong></div></div><svg class="chart v2-interval-chart" viewBox="0 0 680 92" role="img" aria-label="${esc(title)}"><title>${esc(title)}：${row.difference}，95% CI [${row.ci_low}, ${row.ci_high}]</title><line x1="40" x2="640" y1="42" y2="42" stroke="#d1d7ce"/><line x1="${zero}" x2="${zero}" y1="12" y2="66" stroke="#8b999d" stroke-dasharray="4 4"/><text x="${zero}" y="82" text-anchor="middle" class="axis">0 / 无差异</text><line x1="${x(row.ci_low)}" x2="${x(row.ci_high)}" y1="42" y2="42" stroke="#137d74" stroke-width="4"/><line x1="${x(row.ci_low)}" x2="${x(row.ci_low)}" y1="31" y2="53" stroke="#137d74" stroke-width="2"/><line x1="${x(row.ci_high)}" x2="${x(row.ci_high)}" y1="31" y2="53" stroke="#137d74" stroke-width="2"/><circle cx="${x(row.difference)}" cy="42" r="6" fill="#c96d36"/><text x="40" y="16" class="axis">${fmt(lo,5)}</text><text x="640" y="16" text-anchor="end" class="axis">${fmt(hi,5)}</text></svg><p class="unit-note">${included?'区间包含 0，本次比较尚未清楚区分差异。':row.ci_high<0?'本次指定比较的区间位于 0 以下。':'本次指定比较的区间位于 0 以上。'}${row.interpretation?' '+esc(row.interpretation):''}</p>`;
}
function renderV2Protocol(){
 const p=v2Data('protocol'),node=$('#v2-protocol');node.className='';if(!p){node.innerHTML=v2Missing('protocol');return;}
 const h=p.historical||{},s=p.simulation||{},c=p.convex_extension||{};
 node.innerHTML=`<div class="v2-protocol-heading"><div><span class="metric-label">本轮来源冻结</span><strong>${esc(p.frozen_date_hong_kong||'日期未提供')}</strong></div><div><span class="metric-label">历史参考汇率范围</span><strong>${esc((h.currencies||[]).join(' · ')||'未提供')}</strong></div></div><ol class="pipeline v2-pipeline"><li><span>01 / ALIGN</span><strong>匹配剩余期限</strong><p>${compact(h.horizons?.length)} 个期限目标；训练边界按标签结束时间处理。</p></li><li><span>02 / SELECT</span><strong>比较选择流程</strong><p>${esc((s.selectors||[]).map(v2Name).join(' / '))}</p></li><li><span>03 / SHIFT</span><strong>独立流程重复</strong><p>${compact(s.replicates)} 次重复；${compact(s.scenarios?.length)} 个指定模拟场景。</p></li><li><span>04 / AUDIT</span><strong>核对优化账本</strong><p>CVaR ${typeof c.alpha==='number'?compact(c.alpha*100):'—'}%；独立重算目标与约束。</p></li></ol><div class="note"><strong>数据使用记录</strong><p>V1 已经查看 USD / JPY 的 2021–2025 结果，本轮重复使用的历史期保持回溯、探索性解释。来源冻结不等于外部预注册。</p></div><details><summary>查看本轮具体主比较与留出期规则</summary><div class="evidence-detail"><h3>历史主比较</h3><p>${esc(h.primary_comparison||'尚未规定')}</p><h3>模拟主比较</h3><p>${esc(s.primary||'尚未规定')}</p><h3>留出期规则</h3><p>${esc(h.holdout_rule||'尚未规定')}</p><h3>原始数据使用说明</h3><p>${esc(p.prior_data_use||'未提供')}</p></div></details>`;
}
function renderV2Primary(){
 const node=$('#v2-primary');node.className='';let html='';
 for(const [key,title] of [['selection','模拟中的主比较'],['historical','各汇率的历史主比较']]){
  const data=v2Data(key);if(!data){html+=`<article class="v2-result-block"><h3>${title}</h3>${v2Missing(key)}</article>`;continue;}
  let primary=firstRecord(data,['primary_comparison','primary_comparisons','primary_result','primary_results','primary','comparisons']);
  if(key==='historical'&&Array.isArray(primary)){const rows=primary.filter(r=>r.primary_block!==false);html+=`<article class="v2-result-block"><h3>${title}</h3><p class="inline-fact">Ridge 期限匹配 − 单期外推 · 无交易带 0.05 · 5 bps · MBB 块长 3</p>${table(rows,['period','currency','difference','ci_low','ci_high','holm_six_currency_p','n'].map(field=>({key:field,title:v2Name(field),format:v=>typeof v==='string'?v2Name(v):compact(v)})))}<p class="unit-note">区间是各币种的点态区间；近似 p 值按每个时期的六币比较作 Holm 校正。币种共享冲击，不能按独立重复合并。</p></article>`;continue;}
  html+=primary?`<article class="v2-result-block"><h3>${title}</h3>${primary.difference!==undefined?`<p class="inline-fact">${esc(v2Name(primary.scenario||''))} · ${compact(primary.validation_n)} 条验证路径 · ${compact(primary.fee_bps)} bps · ${esc(v2Name(primary.selector||''))} − ${esc(v2Name(primary.baseline||''))}</p>${v2Interval(primary)}`:v2Table(primary)}</article>`:`<article class="v2-result-block"><h3>${title}</h3><p class="muted">研究文件已生成，尚未找到可直接展示的主比较字段；请在原始记录中核对。</p></article>`;
 }
 const selection=v2Data('selection');
 if(selection?.aggregates?.length)html+=`<article class="v2-result-block"><h3>查看完整选择流程的风险与成本</h3><div class="v2-control-row"><label>模拟场景<select id="v2-scenario">${[...new Set(selection.aggregates.map(r=>r.scenario))].map(v=>`<option value="${esc(v)}">${esc(v2Name(v))}</option>`).join('')}</select></label><label>验证路径数<select id="v2-validation-n">${[...new Set(selection.aggregates.map(r=>r.validation_n))].sort((a,b)=>a-b).map(v=>`<option value="${v}">${v}</option>`).join('')}</select></label><label>费率 / bps<select id="v2-fee">${[...new Set(selection.aggregates.map(r=>r.fee_bps))].sort((a,b)=>a-b).map(v=>`<option value="${v}">${v}</option>`).join('')}</select></label></div><div id="v2-selection-detail"></div></article>`;
 node.innerHTML=html+`<p class="unit-note">负值的含义取决于记录中规定的“候选 − 基准”方向。区间包含 0 时，不把它解释为明确改善。没有数值的区域不代表结果为 0。</p>`;
 if($('#v2-scenario')){for(const id of ['#v2-scenario','#v2-validation-n','#v2-fee'])$(id).addEventListener('change',renderV2SelectionDetail);const initial=selection.primary_comparison||selection.aggregates[0];$('#v2-scenario').value=initial.scenario;$('#v2-validation-n').value=String(initial.validation_n);$('#v2-fee').value=String(initial.fee_bps);renderV2SelectionDetail();}
}
function renderV2SelectionDetail(){
 const rows=v2Data('selection').aggregates.filter(r=>r.scenario===$('#v2-scenario').value&&r.validation_n===Number($('#v2-validation-n').value)&&r.fee_bps===Number($('#v2-fee').value));
 const columns=['selector','mean_test_mse','mean_test_es90','mean_test_cost','test_budget_violation_fraction','mean_reference_signed_gap'];
 $('#v2-selection-detail').innerHTML=table(rows,columns.map(key=>({key,title:v2Name(key),format:v=>typeof v==='string'?v2Name(v):fmt(v,6)})))+`<p class="unit-note">每行对独立完整流程重复取平均；有限类参考差使用单独大样本作回溯基准，不是可部署的先知策略。</p><details><summary>查看方差、偏差与选择稳定性</summary>${table(rows,['selector','mean_test_variance','mean_test_bias_squared','selection_entropy_nats','most_selected_fraction','validation_fallback_fraction'].map(key=>({key,title:v2Name(key),format:v=>typeof v==='string'?v2Name(v):fmt(v,6)})))}</details>`;
}
function renderV2Historical(){
 const data=v2Data('historical'),node=$('#v2-historical');node.className='';if(!data){node.innerHTML=v2Missing('historical');return;}
 if(Array.isArray(data.aggregate)&&data.aggregate.length){
  const rows=data.aggregate;node.innerHTML=`<div class="research-callout"><strong>实际生成的历史实验</strong><p>${compact(data.counts?.currency_year_folds)} 个币种年度外层评价；${compact(data.counts?.currencies)} 种 ECB 参考汇率。币种共享欧元与宏观冲击，不视为独立重复。</p></div><div class="v2-control-row"><label>参考汇率<select id="v2-currency">${[...new Set(rows.map(r=>r.currency))].map(v=>`<option value="${esc(v)}">${esc(v)} / 每 1 欧元</option>`).join('')}</select></label><label>评价时期<select id="v2-period">${[...new Set(rows.map(r=>r.period))].map(v=>`<option value="${esc(v)}">${esc(v2Name(v))}</option>`).join('')}</select></label><label>费率 / bps<select id="v2-history-fee">${[...new Set(rows.flatMap(r=>r.candidate_metrics.map(m=>m.cost_bps)))].sort((a,b)=>a-b).map(v=>`<option value="${v}">${v}</option>`).join('')}</select></label></div><div id="v2-currency-detail"></div><details><summary>数据与统计解释限制</summary>${renderRecord(data.limitations||[])}</details>`;
  if([...$('#v2-period').options].some(o=>o.value==='retrospective'))$('#v2-period').value='retrospective';$('#v2-history-fee').value='5';
  for(const id of ['#v2-currency','#v2-period','#v2-history-fee'])$(id).addEventListener('change',renderV2HistoryDetail);renderV2HistoryDetail();return;
 }
 const currencies=data.currencies||data.by_currency;
 let html=`<div class="research-callout"><strong>实际生成的历史实验</strong><p>六种参考汇率共享欧元基准，分别评价，不假定币种之间独立。2021–2025 的部分数据已在 V1 查看，本轮回溯结果保持探索性解释。</p></div>`;
 if(currencies&&!Array.isArray(currencies)&&typeof currencies==='object'){
  html+=`<div class="history-toolbar"><label>查看汇率<select id="v2-currency">${Object.keys(currencies).map(key=>`<option value="${esc(key)}">${esc(key)}</option>`).join('')}</select></label></div><div id="v2-currency-detail"></div>`;
  node.innerHTML=html;const render=()=>{const item=currencies[$('#v2-currency').value];$('#v2-currency-detail').innerHTML=Object.entries(item).filter(([,v])=>Array.isArray(v)||v&&typeof v==='object').map(([key,value])=>v2Block(v2Name(key),value)).join('')||renderRecord(item);};$('#v2-currency').addEventListener('change',render);render();
 }else{
  const records=firstRecord(data,['primary_comparisons','comparisons','summary_rows','rows','metrics']);
  html+=records?v2Table(records):`<p class="muted">摘要已读取，完整字段与运行记录见下方 JSON。</p>`;
  if(data.limitations)html+=`<details><summary>本次历史实验限制</summary>${renderRecord(data.limitations)}</details>`;node.innerHTML=html;
 }
}
function renderV2HistoryDetail(){
 const data=v2Data('historical'),currency=$('#v2-currency').value,period=$('#v2-period').value,fee=Number($('#v2-history-fee').value);
 const group=data.aggregate.find(r=>r.currency===currency&&r.period===period);if(!group){$('#v2-currency-detail').textContent='该组合没有可用结果。';return;}
 const chosen=group.selector_metrics.filter(r=>r.cost_bps===fee),candidates=group.candidate_metrics.filter(r=>r.cost_bps===fee),folds=(data.folds||[]).filter(f=>f.currency===currency&&f.period===period);
 const columns=['selector','mse','es90','mean_cost','fold_budget_exceedance_fraction'];
 let html=`<div class="v2-metric-grid"><div><span>非重叠的对冲片段</span><strong>${compact(group.unique_episodes)}</strong></div><div><span>年度外层评价</span><strong>${compact(folds.length)}</strong></div><div><span>ES90 尾部等效观察数</span><strong>${fmt(group.unique_episodes*.1,1)}</strong></div></div><h3 class="v2-detail-heading">已冻结选择流程 / 实际外层表现</h3>${table(chosen,columns.map(key=>({key,title:v2Name(key),format:v=>typeof v==='string'?v2Name(v):fmt(v,6)})))}`;
 if(period==='additional_2026')html+=`<div class="note"><strong>短留出期</strong><p>仅 ${compact(group.unique_episodes)} 个不重叠片段；尾部指标主要由极少观察决定。本期来源在冻结后才评分，但不是外部预注册或广泛确认。</p></div>`;
 if(folds.length>1){
  const models=[...new Set(candidates.map(r=>r.model))];const curves=models.map(model=>({name:v2Name(model),points:folds.map(f=>{const row=f.outer_metrics.find(r=>r.model===model&&r.policy==='band05'&&r.cost_bps===fee);return row?[Number(f.outer_start.slice(0,4)),row.mse]:null;}).filter(Boolean)})).filter(s=>s.points.length);
  html+=`<div class="plot-panel"><div class="section-title"><h2>年度净 MSE / 固定无交易带 0.05</h2><span>${fee} bps · ${esc(currency)}</span></div>${lineChart(curves,{title:`${currency} ${period} 年度净MSE`,xLabel:'年份',yLabel:'净 MSE',nonnegative:true})}<p class="unit-note">曲线顺序：${models.map(v2Name).map(esc).join(' / ')}。年度波动反映指定方法与市场路径，不是收益率。</p></div>`;
 }
 html+=`<details><summary>比较全部模型与候选策略</summary>${table(candidates,['model','policy','mse','es90','mean_cost','bias_squared'].map(key=>({key,title:v2Name(key),format:v=>typeof v==='string'?v2Name(v):fmt(v,6)})))}</details>`;
 $('#v2-currency-detail').innerHTML=html;
}
function renderV2Convex(){
 const data=v2Data('convex'),node=$('#v2-convex');node.className='';if(!data){node.innerHTML=v2Missing('convex');return;}
 let html=`<div class="v2-audit-note"><strong>样本内约束与样本外行为分开核查</strong><p>优化类为可解释线性修正加比例交易成本。训练状态上的持仓约束，不等于所有未来状态均满足持仓限制。</p></div>`;
 if(data.audit)html+=`<div class="v2-metric-grid">${Object.entries(data.audit).map(([key,v])=>`<div><span>${esc(v2Name(key))}</span><strong>${typeof v==='number'&&v!==0&&Math.abs(v)<.0001?esc(v.toExponential(2)):esc(compact(v))}</strong></div>`).join('')}</div>`;
 if(data.contrasts?.length){html+=`<div class="v2-control-row"><label>对照场景<select id="v2-convex-scenario">${[...new Set(data.contrasts.map(r=>r.scenario))].map(v=>`<option value="${esc(v)}">${esc(v2Name(v))}</option>`).join('')}</select></label><label>风险或成本指标<select id="v2-convex-metric">${[...new Set(data.contrasts.map(r=>r.metric))].map(v=>`<option value="${esc(v)}">${esc(v2Name(v))}</option>`).join('')}</select></label></div><div id="v2-convex-contrast"></div>`;}
 else for(const [key,value] of Object.entries(data))if(/residual|primary|comparison|summary|aggregate|diagnostic/.test(key)&&value&&typeof value==='object')html+=v2Block(v2Name(key),value);
 if(data.test_rows)html+=`<details><summary>核对每次重复的持仓、费用与损失</summary>${v2Table(data.test_rows.map(r=>({scenario:r.scenario,replicate:r.replicate,method:r.method,mse:r.mse,es90:r.es90,mean_cost:r.mean_cost,test_budget_exceeded:r.test_budget_exceeded,position_violation_fraction:r.position_violation_fraction})),80)}</details>`;
 if(data.limitations)html+=`<details><summary>优化实验适用范围</summary>${renderRecord(data.limitations)}</details>`;
 node.innerHTML=html;
 if($('#v2-convex-scenario')){for(const id of ['#v2-convex-scenario','#v2-convex-metric'])$(id).addEventListener('change',renderV2ConvexContrast);renderV2ConvexContrast();}
}
function renderV2ConvexContrast(){const row=v2Data('convex').contrasts.find(r=>r.scenario===$('#v2-convex-scenario').value&&r.metric===$('#v2-convex-metric').value);$('#v2-convex-contrast').innerHTML=`<p class="inline-fact">CVaR 凸优化 − 验证选定无交易带 · 探索性点态区间</p>${v2Interval(row,'凸优化探索性比较区间')}<p class="unit-note">仅八次独立完整流程重复；同时查看成本和分布变化后的结果，不能据一个区间主张普遍优势。</p>`;}
function renderV2Routes(){
 const data=v2Data('publication_routes'),node=$('#v2-routes');node.className='';if(!data){node.innerHTML=v2Missing('publication_routes');return;}
 $('#v2-route-date').textContent=`核验日期 ${data.checked_on||'未提供'} / 香港`;
 const filter=$('#v2-route-filter').value,isOpen=v=>v.status_on_checked_date==='open'||v.status_on_checked_date==='open_but_near_deadline'||v.status_on_checked_date?.startsWith('late_breaking_and_poster_open');
 const routes=(data.venues||[]).filter(v=>filter==='all'||(filter==='open')===isOpen(v));
 node.innerHTML=`<div class="v2-route-list">${routes.map(v=>`<article class="v2-route"><div class="v2-route-heading"><h3>${esc(v.name)}</h3><span class="badge ${isOpen(v)?'':'pending'}">${isOpen(v)?'当前开放':'后续 / 条件待满足'}</span></div><p class="v2-deadline">${esc(v.deadline||(v.id==='SIURO'?'常规投稿 / 指导条件待核验':'常规投稿 / 暂不满足项目条件'))}</p><p>${esc(v.route)}</p><p class="v2-publication-type">${esc(v.publication_status)}</p><details><summary>要求与适配判断</summary><p>${esc(v.format)}</p><p>${esc(v.fit)}</p><p>${esc(v.conditions)}</p></details><div class="v2-source-links">${(v.sources||[]).map((url,index)=>link(url,index?'补充官方规则 ↗':'核对官方征稿 ↗')).join(' ')}</div></article>`).join('')}</div><details><summary>AI 使用披露与作者责任</summary>${(data.ai_policies||[]).map(p=>`<section class="evidence-detail"><h3>${esc(p.publisher)}</h3><p>${esc(p.verified_policy)}</p>${p.verification_note?`<p>${esc(p.verification_note)}</p>`:''}${(p.sources||[]).map(url=>link(url,'核对官方政策 ↗')).join(' · ')}</section>`).join('')}</details>`;
 const routeZh={SIAM_FM27:['会议摘要与展示','Poster / contributed talk；属于会议交流展示，不能写成正式会议论文发表。'],IEEE_SSCI_CIFER27:['研究进展海报 / 摘要','Late-breaking 最多 2 页；poster 最多 250 词。两种路径均不进入会议论文集。'],ACM_ICAIF_MAIN:['主会正式研究论文','主会录用稿进入 ACM proceedings；2026 截止已过，2027 征稿尚未核验。'],RAIOPS4FIN26:['模型风险与审计专题 workshop','至少 5 页的录用稿可能考虑 CEUR 收录，需作者同意；不等于 ICAIF 主会论文。'],JOSS:['研究软件期刊','需要超过六个月活跃公开开发历史及真实研究用途。当前新项目尚不满足。'],SIURO:['本科研究期刊','英文稿通常约 20 页。须真实指导函核验本科期间研究与学生贡献；当前尚未确认具备该条件。']};
 $$('.v2-route',node).forEach((article,i)=>{const v=routes[i],zh=routeZh[v.id];if(!zh)return;$('.badge',article).textContent=isOpen(v)?'核验日开放':'后续 / 条件待满足';const paragraphs=$$('p',article);paragraphs[1].textContent=zh[0];$('.v2-publication-type',article).textContent=zh[1];const details=$('details',article);const original=document.createElement('p');original.textContent=v.publication_status;details.append(original);});
}
function renderV2(){
 const sections=[['historical','期限匹配与六币评价'],['selection','模型变化与选择误差'],['convex','直接风险优化审计']];
 $('#v2-status').innerHTML=sections.map(([key,title],i)=>{const a=state.researchV2?.[key],ready=a?.status==='available';return `<article><span class="metric-label">EXPERIMENT ${String(i+1).padStart(2,'0')}</span><h3>${title}</h3><span class="badge ${ready?'':'pending'}">${ready?'实际摘要已读取':a?.status==='invalid'?'文件无效':a?.status==='too_large'?'超出读取上限':'尚未生成'}</span></article>`}).join('');
 renderV2Protocol();renderV2Primary();renderV2Historical();renderV2Convex();renderV2Routes();
 const raw=JSON.stringify(state.researchV2,null,2);$('#v2-json').textContent=raw.length>200000?raw.slice(0,200000)+'\n…预览长度已限制，导出 JSON 可取得全部读取内容。':raw;
}
async function loadV2(){
 const button=$('#refresh-v2');button.disabled=true;$('#v2-message').className='form-message';$('#v2-message').textContent='正在读取冻结协议与实际研究摘要…';
 try{state.researchV2=await api('/api/research-v2');renderV2();$('#v2-message').textContent='文件读取完成；缺失、无效与超过上限的结果会明确标示。';}
 catch(error){$('#v2-message').textContent=`研究证据读取失败：${error.message}`;$('#v2-message').className='form-message error';}
 finally{button.disabled=false;}
}
async function loadEvidence(){
 const button=$('#refresh-results');button.disabled=true;
 try{state.results=await api('/api/results');renderEvidence();renderHistorical();}
 catch(error){$('#evidence-status').textContent=`结果读取失败：${error.message}`;$('#historical-content').textContent='历史结果读取失败，请检查本地服务后刷新。';}
 try{state.competencies=await api('/api/competencies');renderCompetencies();}
 catch(error){$('#competency-content').textContent=`能力映射读取失败：${error.message}`;}
 finally{button.disabled=false;}
}
function downloadJSON(value,name){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json;charset=utf-8'}));const anchor=document.createElement('a');anchor.href=url;anchor.download=name;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('已导出本次实验的完整 JSON。');}
$('#price-form').addEventListener('submit',calculatePrice);
$('#hedge-form').addEventListener('submit',calculateHedge);
$('#hedge-form').addEventListener('reset',()=>{setTimeout(updateConditionalFields,0);setMessage('#hedge-message','配置已重置。运行实验后更新结果。');});
$('#price-form').addEventListener('reset',()=>setMessage('#price-message','输入已重置。运行计算后更新结果。'));
$('#hedge-form').addEventListener('input',()=>{if(state.simulation)setMessage('#hedge-message','配置已更改；当前图表仍为上次运行的结果。');});
$('#price-form').addEventListener('input',()=>{if(state.price)setMessage('#price-message','参数已更改；当前结果仍对应上次提交。');});
$('#path-model').addEventListener('change',updateConditionalFields);$('#hedge-policy').addEventListener('change',updateConditionalFields);
$('#refresh-results').addEventListener('click',async()=>{await loadEvidence();toast('已重新读取本地研究结果。');});
$('#download-simulation').addEventListener('click',()=>{if(state.simulation)downloadJSON(state.simulation,`risklab-seed-${state.simulation.parameters.seed}.json`);});
$('#refresh-v2').addEventListener('click',loadV2);
$('#v2-route-filter').addEventListener('change',renderV2Routes);
$('#download-v2').addEventListener('click',()=>{if(state.researchV2)downloadJSON(state.researchV2,'finmath-risklab-v2-evidence.json');});
window.addEventListener('hashchange',navigate);navigate();updateConditionalFields();
async function boot(){try{await api('/api/health');$('#connection').textContent='本地数值内核已连接';$('#connection-dot').classList.add('ready');}catch{$('#connection').textContent='本地服务连接失败';$('#connection-dot').classList.add('failed');}await Promise.all([calculatePrice(),loadEvidence(),loadV2()]);}
boot();
