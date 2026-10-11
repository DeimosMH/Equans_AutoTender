/* Training workspace. Source collection and dataset preparation are independent jobs. */
window.AutoTenderTraining = (() => {
  const tasks = [
    {key:'market_extraction', label:'Public notices', title:'Understand public tenders', source:'saved simap notices', description:'Use saved tender notices and awards from simap.', empty:'No notices saved yet', next:'Import a simap project or find past ventilation awards to get started.', add:'Add notices'},
    {key:'input_processing', label:'Tender matching', title:'Match tender positions', source:'reviewed sample positions', description:'Learn from position descriptions matched to the right catalogue products.', empty:'No reviewed examples yet', next:'Import reviewed positions from your tenders to get started.', add:'Import reviewed examples'},
    {key:'win_ratio', label:'Bid outcomes', title:'Improve bid estimates', description:'Uses verified results linked to offers saved before submission.', empty:'No eligible bid results yet', next:'Save an offer before submitting it, then record its verified result under Tender finalised.', add:'Add tender results'},
    {key:'productivity_factors', label:'Productivity', title:'Improve productivity estimates', description:'Learn from measured work on completed tenders.', empty:'No measurements yet', next:'Add actual productivity to a finalised tender. Verified measurements appear here automatically.', add:'Add measurements'},
  ];
  const busy = j => ['queued','collecting','preparing'].includes(j.status);
  const escape = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const status = s => ({ready_for_training:'Data ready',blocked:'More examples needed',failed:'Failed',queued:'Queued',collecting:'Collecting sources',preparing:'Preparing dataset',collected:'Sources collected'}[s] || s);
  const date = v => v ? new Date(v).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '—';
  const artifact = (j,n) => `/api/settings/jobs/${encodeURIComponent(j.id)}/artifacts/${encodeURIComponent(n)}`;
  let host, state, settings, timer, generation = 0, active='market_extraction', mode='simple', tab='configuration', selected={}, model, include=true, resultSignature='', openTender, settingsChanged, navigationChanged;
  const preparing = new Set();
  const $ = id => host?.querySelector('#'+id);
  async function api(path, body) {
    const res = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Request failed. Please try again.');
    return data;
  }
  function message(text, error=false) {
    const box=$('tr-message'); if(!box) return;
    box.textContent=text; box.className='tr-message'+(error?' tr-error':''); box.hidden=!text;
  }
  function badge(j) { return `<span class="tr-badge ${j.status==='ready_for_training'||j.status==='collected'?'good':j.status==='failed'?'bad':'pending'}">${escape(status(j.status))}</span>`; }
  function taskJobs() { return state.jobs.filter(j=>j.kind!=='collection'&&j.task===active); }
  function currentJob() { const jobs=taskJobs(); return jobs.find(j=>j.id===selected[active]) || jobs[0]; }
  function capture() { if($('tr-model')) model=$('tr-model').value; if($('tr-existing')) include=$('tr-existing').checked; }
  function getRoute() {
    const lora=TendifLoras.getRoute();
    const page=mode==='advanced'?(tab==='datasets'?'data-preparation':tab):(lora.view==='base'?'base-models':lora.view);
    const task=mode==='advanced'?(tab==='datasets'?active:tab==='configuration'?lora.task:null):(lora.view==='update'?lora.task:null);
    const runtime=mode==='advanced'&&tab==='configuration'?lora.runtime:null;
    return `lora-settings/${mode==='advanced'?'advanced':'loras'}/${page}${task?'/'+task.replaceAll('_','-'):''}${runtime?'/'+runtime:''}`;
  }
  function restoreRoute(path) {
    capture();
    const [,section,page,taskSlug='',runtime]=path.split('/'), task=taskSlug.replaceAll('-','_');
    mode=section==='advanced'?'advanced':'simple';
    if(mode==='advanced') {
      tab=page==='data-preparation'?'datasets':['configuration','sources','history','evaluation'].includes(page)?page:'configuration';
      if(tab==='datasets')active=tasks.some(t=>t.key===task)?task:'market_extraction';
      if(tab==='configuration')TendifLoras.setRoute(TendifLoras.getRoute().view,task,runtime);
    } else TendifLoras.setRoute(page==='base-models'?'base':page,task);
    render();
  }
  function navigate() {render();navigationChanged();}
  function render() {
    if(!host?.isConnected||!state) return;
    host.dataset.mode=mode;
    host.innerHTML=`<div class="tr-mode-tabs" aria-label="LoRA workspace">${[['simple','LoRAs'],['advanced','Advanced']].map(([id,label])=>`<button data-mode="${id}" class="${mode===id?'selected':''}" aria-pressed="${mode===id}">${label}</button>`).join('')}</div>
      ${mode==='advanced'?`<div class="tr-tabs" aria-label="Administration views">${[['configuration','Configuration'],['datasets','Data preparation'],['sources','Sources'],['history','History'],['evaluation','Evaluation']].map(([id,label])=>`<button data-tab="${id}" class="${tab===id?'selected':''}" aria-pressed="${tab===id}">${label}</button>`).join('')}</div>`:''}
      <div id="tr-message" role="status" aria-live="polite" hidden></div><div id="tr-page"></div>`;
    host.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{capture();mode=b.dataset.mode;navigate();host.querySelector(`[data-mode="${mode}"]`).focus();});
    host.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{capture();tab=b.dataset.tab;navigate();host.querySelector(`[data-tab="${tab}"]`).focus();});
    if(mode==='simple'||tab==='configuration')TendifLoras.mount($('tr-page'),settings,state.evidence,mode==='advanced',navigationChanged);
    else if(tab==='datasets')renderDataset();else if(tab==='sources')renderSources();
    else if(tab==='evaluation')TendifLearning.mount($('tr-page'));else renderHistory();
  }
  function evidence() {
    const data=state.evidence[active];
    return include ? data : {examples:data.uploaded_examples, projects:data.uploaded_projects};
  }
  function renderDataset() {
    const task=tasks.find(t=>t.key===active), uploads=state.uploads.filter(u=>u.task===active);
    const reusable=active==='market_extraction'?state.sources.length:active==='input_processing'?state.sponsor_records:0;
    $('tr-page').innerHTML=`<p class="tr-question" id="tr-task-label">What should Tendif improve?</p>
      <div class="tr-task-tabs" role="group" aria-labelledby="tr-task-label">${tasks.map(t=>`<button data-task="${t.key}" class="${t.key===active?'selected':''}" aria-pressed="${t.key===active}">${t.label}</button>`).join('')}</div>
      <section class="tr-card tr-prepare-card"><h3>${task.title}</h3><p>${task.description}</p>
        <div id="tr-evidence" class="tr-evidence"></div>
        <div class="tr-action"><button id="tr-prepare" class="primary">Prepare training data</button><button id="tr-add">${task.add}</button></div>
        <div id="tr-tender-picker" hidden></div>
        <div id="tr-result" aria-live="polite" hidden></div>
        <section class="tr-options" id="tr-options"><h4>Preparation settings</h4>
          <div class="tr-model-row"><label class="tr-field">Model ID<input id="tr-model" type="text" value="${escape(model)}" maxlength="200" spellcheck="false"></label><button id="tr-save-model">Save as default</button></div>
          ${task.source?`<label class="tr-source-choice"><input type="checkbox" id="tr-existing" ${include?'checked':''}><span>Include ${task.source} (${reusable})</span></label>`:''}
          <div class="tr-upload"><div><b>Import a prepared dataset</b><small>JSONL · <span id="tr-upload-count"></span> saved examples</small></div><button id="tr-upload-btn">Choose file</button></div>
          <input id="tr-file" type="file" accept=".jsonl" hidden><div id="tr-upload-status" role="status" class="tr-help"></div>
          <a class="tr-text-link" href="/api/settings/dataset-format" target="_blank" rel="noopener">File format &amp; examples ↗</a>
          ${uploads.filter(u=>u.error).map(u=>`<p class="err">${escape(u.file)}: ${escape(u.error)}</p>`).join('')}
        </section>
      </section><p class="tr-connection">Training service not connected</p>
      <details class="tr-provider"><summary>Connection settings</summary><p>Endpoint ${state.provider.endpoint_configured?'configured':'not configured'} · Credentials ${state.provider.credential_configured?'configured':'not configured'}. The cloud training API integration is pending.</p><p class="tr-help">Server configuration: <code>AUTOTENDER_TRAINING_ENDPOINT</code> and <code>AUTOTENDER_TRAINING_API_KEY</code>.</p></details>`;
    host.querySelectorAll('[data-task]').forEach(b=>b.onclick=()=>{capture();active=b.dataset.task;renderDataset();navigationChanged();host.querySelector(`[data-task="${active}"]`).focus();});
    $('tr-evidence').before($('tr-options'));$('tr-upload-btn').onclick=()=>$('tr-file').click();$('tr-file').onchange=upload;$('tr-save-model').onclick=saveModel;
    $('tr-prepare').onclick=prepare;
    $('tr-add').onclick=addEvidence;
    if($('tr-existing'))$('tr-existing').onchange=()=>{capture();renderEvidence();};
    resultSignature='';renderResult();
  }
  function renderEvidence() {
    if(!$('tr-evidence'))return;
    const task=tasks.find(t=>t.key===active), data=evidence(), working=preparing.has(active)||taskJobs().some(busy);
    if($('tr-upload-count'))$('tr-upload-count').textContent=state.uploads.filter(u=>u.task===active).reduce((n,u)=>n+u.records,0);
    $('tr-evidence').innerHTML=data.examples ? `<b>${data.examples} example${data.examples===1?'':'s'} from ${data.projects} tender${data.projects===1?'':'s'}</b><p>${data.projects<3?`Add examples from ${3-data.projects} more tender${data.projects===2?'':'s'} before training.`:'Saved evidence is included automatically. Tendif will check it and set aside examples for evaluation.'}</p>` : `<b>${task.empty}</b><p>${task.next}</p>`;
    $('tr-prepare').hidden=!data.examples&&!working;
    $('tr-prepare').disabled=working;
    $('tr-prepare').textContent=working?'Preparing…':'Prepare training data';
    $('tr-add').hidden=active==='input_processing';
    $('tr-add').textContent=task.add;
    $('tr-add').classList.toggle('primary',!data.examples&&!working);
  }
  function addEvidence() {
    capture();
    if(active==='market_extraction'){mode='advanced';tab='sources';navigate();$('tr-urls').focus();return;}
    if(active==='input_processing'){mode='advanced';tab='datasets';navigate();$('tr-upload-btn').focus();return;}
    const tenders=[...state.tenders].sort((a,b)=>Number(b.finalised)-Number(a.finalised));
    const panel=$('tr-tender-picker');panel.hidden=false;
    if(!tenders.length){panel.innerHTML='<p>Upload and calculate a tender first. When it is complete, choose <b>Tender finalised</b> to add its result and measurements.</p>';return;}
    panel.innerHTML=`<label class="tr-field">Choose a tender<select id="tr-tender">${tenders.map(t=>`<option value="${escape(t.id)}">${escape(t.name)}${t.finalised?' · Finalised':''}</option>`).join('')}</select></label><button id="tr-open-tender">Open tender</button><p class="tr-help">Completed tender forms save this evidence directly.</p>`;
    $('tr-open-tender').onclick=()=>openTender($('tr-tender').value,active).catch(e=>message(e.message,true));
    $('tr-tender').focus();
  }
  function renderResult() {
    if(!$('tr-result'))return;
    const j=currentJob(),expanded=!!selected[active]||j&&busy(j);
    const signature=JSON.stringify([j||{},expanded]);
    renderEvidence();
    if(signature===resultSignature)return;
    resultSignature=signature;
    const box=$('tr-result');
    box.hidden=!j || (!expanded&&!j.manifest?.accepted_count);
    if(box.hidden)return;
    if(!expanded){box.innerHTML=`<button id="tr-last-run" class="tr-text-button">Last preparation · ${date(j.created_at)} · ${escape(status(j.status))} ›</button>`;
      $('tr-last-run').onclick=()=>{selected[active]=j.id;renderResult();};return;}
    const m=j.manifest,counts=m?.counts||{},total=m?.accepted_count||0;
    const next=[];
    if(m?.project_count<3)next.push(`Add examples from ${3-m.project_count} more tender${m.project_count===2?'':'s'}.`);
    if(m?.blockers.some(b=>b.includes('Both own won')))next.push('Include confirmed wins and losses.');
    else if(m?.blockers.some(b=>b.includes('both outcome classes')))next.push('Add more won and lost tenders so both can be used for training.');
    box.innerHTML=`<div class="tr-result-head"><span>Preparation · ${date(j.created_at)}</span>${badge(j)}</div>
      ${busy(j)?'<div class="tr-progress" role="progressbar" aria-label="Dataset preparation in progress"></div>':''}
      ${j.error?`<p class="err">${escape(j.error)}</p>`:''}
      ${m?`<p><b>${total} example${total===1?'':'s'} accepted</b>${m.rejected_count?` · ${m.rejected_count} excluded`:''}</p>
        ${next.length?`<p class="tr-next">${next.map(escape).join(' ')}</p>`:''}
        <div class="tr-result-actions">${j.status==='ready_for_training'&&j.artifacts.includes('dataset_bundle.zip')?`<a class="tr-button" href="${artifact(j,'dataset_bundle.zip')}" download>Download training data ↓</a>`:''}${total?'<button id="tr-preview-btn">Review examples</button>':''}</div><div id="tr-preview"></div>
        <details class="tr-artifacts"><summary>Preparation details &amp; files</summary><p class="tr-help">${escape(j.base_model)} · ${m.project_count} tenders</p>
          <div class="tr-splits">${['train','validation','test'].map(s=>`<div><strong>${counts[s]||0}</strong><span>${s==='train'?'Training':s==='test'?'Test':'Validation'}</span></div>`).join('')}</div>
          ${m.blockers.length?`<ul>${m.blockers.map(b=>`<li>${escape(b)}</li>`).join('')}</ul>`:''}
          <div>${j.artifacts.map(n=>`<a href="${artifact(j,n)}" download>${escape(n)}</a>`).join('')}</div>
        </details>`:''}
      ${j.collection_errors?.length?`<details class="tr-note"><summary>${j.collection_errors.length} collection warnings</summary><pre>${escape(JSON.stringify(j.collection_errors,null,2))}</pre></details>`:''}`;
    if($('tr-preview-btn'))$('tr-preview-btn').onclick=()=>loadPreview(j,'train');
  }
  async function loadPreview(j,split) {
    try {
      const data=await api(`/api/training/${j.id}/preview?split=${split}`);
      if(!$('tr-preview') || currentJob()?.id!==j.id) return;
      $('tr-preview').innerHTML=`<div class="tr-preview-head"><b>Sample review</b><label>Split <select id="tr-preview-split">${['train','validation','test'].map(s=>`<option ${s===split?'selected':''}>${s}</option>`).join('')}</select></label></div><p class="tr-help">Showing up to 3 examples. Complete files are in the bundle.</p>${data.examples.map((r,i)=>`<details class="tr-example"><summary>Example ${i+1} · ${escape(data.evidence[i]?.project_id||'Archived example')}</summary><b>Model input</b><pre>${escape(r.messages.find(m=>m.role==='user')?.content)}</pre><b>Expected answer</b><pre>${escape(r.messages.find(m=>m.role==='assistant')?.content)}</pre>${data.evidence[i]?`<b>Source evidence</b><pre>${escape(JSON.stringify(data.evidence[i].evidence,null,2))}</pre>`:''}</details>`).join('')||'<p>No examples in this split yet.</p>'}`;
      $('tr-preview-split').onchange=e=>loadPreview(j,e.target.value);
    } catch(e) { message(e.message,true); }
  }
  async function upload() {
    const input=$('tr-file'),file=input.files[0],uploadTask=active,token=generation,label=$('tr-upload-status'),button=$('tr-upload-btn');
    if(!file)return;
    label.textContent='Checking file…';label.classList.remove('err');button.disabled=true;
    try {
      const response=await fetch(`/api/settings/upload-data?task=${uploadTask}&name=${encodeURIComponent(file.name)}`,{method:'POST',body:file});
      const data=await response.json();if(!response.ok)throw new Error(data.error);
      await refresh();
      if(token===generation&&active===uploadTask&&tab==='datasets')label.textContent=`${data.records} example${data.records===1?'':'s'} added. Prepare training data to include them.`;
    }catch(e){label.textContent=e.message;label.classList.add('err');}
    finally{button.disabled=false;input.value='';}
  }
  async function prepare() {
    capture();const task=active,token=generation;preparing.add(task);renderEvidence();message('');
    try{const data=await api('/api/training/prepare',{task,base_model:model,include_existing:include});selected[task]=data.job.id;if(token===generation)await refresh();}
    catch(e){if(token===generation)message(e.message,true);}
    finally{preparing.delete(task);if(token===generation)renderEvidence();}
  }
  async function saveModel() {
    capture();const token=generation,baseModel=model,button=$('tr-save-model');button.disabled=true;
    try{const settings=await api('/api/settings');const saved=await api('/api/settings',{...settings,base_model:baseModel});settingsChanged(saved.settings);
      if(token===generation){await refresh();message('Default model saved.');}}
    catch(e){if(token===generation)message(e.message,true);}finally{button.disabled=false;}
  }
  function renderSources() {
    const collected=state.jobs.find(j=>j.kind==='collection');
    $('tr-page').innerHTML=`<div class="tr-grid tr-source-grid"><section class="tr-card"><div class="tr-eyebrow">COLLECT FROM SIMAP</div><h3>Add public notices</h3><p>Import a project directly, or search recent ventilation awards in German and French.</p><label class="tr-field">simap project links · one per line<textarea id="tr-urls" rows="4" placeholder="https://www.simap.ch/de/project-detail/…"></textarea></label><button class="tr-text-button" id="tr-sample">Use supplied tender example</button><label class="tr-source-choice"><input id="tr-search" type="checkbox"><span><b>Find past ventilation awards</b><small>Import up to 20 past awards</small></span></label><button id="tr-collect" class="primary">Import notices</button><p class="tr-help">Saved notices are available for training automatically. Duplicates are skipped.</p><div id="tr-collection-status"></div></section>
      <section class="tr-card"><div class="tr-result-head"><div><div class="tr-eyebrow">SOURCE LIBRARY</div><h3>${state.sources.length} archived publications</h3></div></div><p></p><label class="tr-field">Filter publications<input id="tr-source-filter" type="search" placeholder="Search title, buyer or canton"></label><div class="tr-source-list" id="tr-source-list"></div><p class="tr-help">Source: simap.ch. Refer to the original publication for current authoritative information.</p></section></div>
      <details class="tr-card"><summary>Imported data files</summary>${state.uploads.length?`<div class="tr-table-wrap"><table class="tr-table"><thead><tr><th>File</th><th>Task</th><th>Records</th><th>Projects</th></tr></thead><tbody>${state.uploads.map(u=>`<tr><td>${escape(u.file)}${u.error?`<span class="err">${escape(u.error)}</span>`:''}</td><td>${escape(tasks.find(t=>t.key===u.task)?.label)}</td><td>${u.records}</td><td>${u.projects||'—'}</td></tr>`).join('')}</tbody></table></div>`:'<p>No additional files imported.</p>'}</details>`;
    $('tr-sample').onclick=()=>{$('tr-urls').value='https://www.simap.ch/de/project-detail/d849c22b-3fc4-48d8-94c9-c45457544ab1';};
    $('tr-source-filter').oninput=renderSourceList;
    $('tr-collect').onclick=async()=>{
      $('tr-collect').disabled=true;message('');
      try {await api('/api/training/collect',{urls:$('tr-urls').value.trim().split(/\s+/).filter(Boolean),search_hvac:$('tr-search').checked});await refresh();}
      catch(e){message(e.message,true);$('tr-collect').disabled=false;}
    };
    renderSourceList();renderCollection(collected);
  }
  function renderCollection(j) {
    if(!$('tr-collection-status'))return;
    $('tr-collect').disabled=state.jobs.some(j=>j.kind==='collection'&&busy(j));
    $('tr-collection-status').innerHTML=j?`${badge(j)}<p class="tr-help">${busy(j)?'Collecting and archiving public records. This can take a few minutes.':`${j.public_record_count||0} publications collected · ${date(j.created_at)}`}</p>${j.error?`<p class="err">${escape(j.error)}</p>`:''}${j.collection_errors?.length?`<details><summary>${j.collection_errors.length} source errors</summary><pre>${escape(JSON.stringify(j.collection_errors,null,2))}</pre></details>`:''}`:'';
  }
  function renderSourceList() {
    if(!$('tr-source-list'))return;
    const query=$('tr-source-filter').value.toLowerCase();
    const rows=state.sources.filter(s=>`${s.title} ${s.buyer} ${s.canton}`.toLowerCase().includes(query));
    $('tr-source-list').innerHTML=rows.map(s=>`<article><div><span class="tr-badge ${s.record_type==='market_award'?'good':''}">${s.record_type==='market_award'?'Award':'Tender'}</span><time>${escape(s.publication_date)}</time></div><b>${escape(s.title)}</b><p>${escape(s.buyer||'Buyer unspecified')}${s.canton?' · '+escape(s.canton):''}</p>${/^https:\/\/(www\.)?simap\.ch\//.test(s.url)?`<a href="${escape(s.url)}" target="_blank" rel="noopener">View on simap ↗</a>`:''}<details><summary>Source provenance</summary><p>Retrieved ${escape(s.retrieved_at||'See source artifact')}</p><code>${escape(s.sha256||'See source artifact')}</code></details></article>`).join('')||'<p>No publications match. Collect a source to get started.</p>';
  }
  function renderHistory() {
    $('tr-page').innerHTML=`<section class="tr-card"><div class="tr-eyebrow">AUDIT TRAIL</div><h3>Collection & preparation runs</h3><p>Review previous collections and datasets.</p><div class="tr-table-wrap"><table class="tr-table"><thead><tr><th>Run</th><th>Examples</th><th>Status</th><th>Created</th><th>Review</th></tr></thead><tbody>${state.jobs.map(j=>`<tr><td><b>${j.kind==='collection'?'Source collection':escape(tasks.find(t=>t.key===j.task)?.label||j.task)}</b></td><td>${j.manifest?.accepted_count??j.public_record_count??'—'}</td><td>${badge(j)}</td><td>${date(j.created_at)}</td><td><button data-run="${j.id}">View</button></td></tr>`).join('')||'<tr><td colspan="5">No preparations yet. Open Data preparation to get started.</td></tr>'}</tbody></table></div></section>`;
    host.querySelectorAll('[data-run]').forEach(b=>b.onclick=()=>{const j=state.jobs.find(j=>j.id===b.dataset.run);if(j.kind==='collection')tab='sources';else{active=j.task;selected[active]=j.id;tab='datasets';}navigate();});
  }
  async function refresh() {
    const token=generation;
    const data=await api('/api/training');
    if(token!==generation||!host?.isConnected)return;
    const sourceChanged=JSON.stringify(state?.sources)!==JSON.stringify(data.sources);
    state=data;
    if(mode==='advanced'&&tab==='datasets')renderResult();
    if(mode==='advanced'&&tab==='sources') {renderCollection(state.jobs.find(j=>j.kind==='collection'));if(sourceChanged){capture();renderSources();}}
    if(mode==='advanced'&&tab==='history')renderHistory();
    clearTimeout(timer);
    if(state.jobs.some(busy)) timer=setTimeout(()=>refresh().catch(e=>message(e.message,true)),1600);
  }
  async function mount(element, navigate=openTender, changed=settingsChanged, onNavigate=navigationChanged) {
    dispose();host=element;state=null;openTender=navigate;settingsChanged=changed;navigationChanged=onNavigate;const token=generation;
    host.className='training';host.innerHTML='<div class="tr-card" role="status">Loading training workspace…</div>';
    try {const data=await Promise.all([api('/api/training'),api('/api/settings')]);if(token!==generation||!host.isConnected)return;[state,settings]=data;model??=state.default_model;render();navigationChanged(true);if(state.jobs.some(busy))timer=setTimeout(()=>refresh().catch(e=>message(e.message,true)),1600);}
    catch(e){if(token===generation&&host.isConnected){host.innerHTML='<div class="tr-card"><p role="alert"></p><button>Retry</button></div>';host.querySelector('p').textContent=e.message;host.querySelector('button').onclick=()=>mount(element);}}
  }
  function dispose(){capture();generation++;clearTimeout(timer);}
  return {mount,dispose,getRoute,restoreRoute};
})();
