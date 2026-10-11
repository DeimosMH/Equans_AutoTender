/* Training workspace. Source collection and dataset preparation are independent jobs. */
window.AutoTenderTraining = (() => {
  const tasks = [
    {key:'market_extraction', label:'Public notices', title:'Public notice dataset', source:'simap publications', description:'Turn historical tenders and awards into structured procurement data, with a traceable source for every example.', need:'Public notices teach metadata extraction. They do not establish whether Equans won or lost a bid.'},
    {key:'input_processing', label:'Tender matching', title:'Tender matching dataset', source:'sponsor examples', description:'Use reviewed position descriptions and catalogue matches to prepare the tender processing adapter.', need:'The 22 sponsor examples belong to one project. Add reviewed examples from independent projects for validation and testing. PDF extraction still needs separately reviewed labels.'},
    {key:'win_ratio', label:'Bid outcomes', title:'Bid outcome dataset', source:'verified own bids', description:'Prepare outcome classification from your bids and their confirmed won or lost results.', need:'Use facts known at submission and evidence of the later outcome. Both won and lost bids must appear in training. Public awards cannot substitute for your bid history.'},
    {key:'productivity_factors', label:'Productivity', title:'Productivity dataset', source:'measured factors', description:'Prepare productivity targets from completed work, with a measurement reference for every example.', need:'Upload measured positive factors and their evidence. Suggested or demo factors do not count as training evidence.'},
  ];
  const busy = j => ['queued','collecting','preparing'].includes(j.status);
  const escape = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const status = s => ({ready_for_training:'Dataset ready',blocked:'More evidence needed',failed:'Failed',queued:'Queued',collecting:'Collecting sources',preparing:'Preparing dataset',collected:'Sources collected'}[s] || s);
  const date = v => v ? new Date(v).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '—';
  const artifact = (j,n) => `/api/settings/jobs/${encodeURIComponent(j.id)}/artifacts/${encodeURIComponent(n)}`;
  let host, state, timer, generation = 0, active='market_extraction', tab='datasets', selected={}, model='glm-5.3-flash', include=true, resultSignature='';
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
  function render() {
    if(!host?.isConnected) return;
    host.innerHTML=`<div class="tr-summary" id="tr-stats"></div>
      <div class="tr-tabs" aria-label="Training views">${[['datasets','Datasets'],['sources','Source library'],['history','Run history']].map(([id,label])=>`<button data-tab="${id}" class="${tab===id?'selected':''}" aria-pressed="${tab===id}">${label}</button>`).join('')}</div>
      <div id="tr-message" role="status" aria-live="polite" hidden></div><div id="tr-page"></div>`;
    host.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{capture();tab=b.dataset.tab;render();});
    renderStats();
    if(tab==='sources') renderSources(); else if(tab==='history') renderHistory(); else renderDataset();
  }
  function renderStats() {
    $('tr-stats').innerHTML=`<span><b>${state.sources.length}</b> public publications</span><span><b>${state.sponsor_records}</b> sponsor examples</span><span class="tr-badge pending">Training not connected</span>`;
  }
  function renderDataset() {
    const task=tasks.find(t=>t.key===active);
    const uploads=state.uploads.filter(u=>u.task===active);
    const reusable=active==='market_extraction'?state.sources.length:active==='input_processing'?state.sponsor_records:0;
    $('tr-page').innerHTML=`<div class="tr-task-tabs" aria-label="Dataset tasks">${tasks.map(t=>`<button data-task="${t.key}" class="${t.key===active?'selected':''}" aria-pressed="${t.key===active}">${t.label}</button>`).join('')}</div>
      <div class="tr-grid"><section class="tr-card"><div class="tr-eyebrow">DATASET RECIPE</div><h3>${task.title}</h3><details class="tr-requirements"><summary>Data requirements</summary><p>${task.need}</p></details>
        <div class="tr-section-label">Sources</div>
        ${reusable||['market_extraction','input_processing'].includes(active)?`<label class="tr-source-choice"><input type="checkbox" id="tr-existing" ${include?'checked':''}><span><b>Use ${task.source}</b><small>${reusable} available examples${active==='input_processing'?' · one project':''}</small></span><span class="tr-count">${reusable}</span></label>`:''}
        <div class="tr-upload"><div><b>Task-specific JSONL</b><small>${uploads.reduce((n,u)=>n+u.records,0)} uploaded records in ${uploads.length} files</small></div><button id="tr-upload-btn">Upload data</button><input id="tr-file" type="file" accept=".jsonl" hidden></div>
        <div id="tr-upload-status" role="status" class="tr-help"></div>
        <a class="tr-text-link" href="/api/settings/dataset-format" target="_blank" rel="noopener">View data schemas & examples ↗</a>
        <div class="tr-section-label">Model</div><label class="tr-field">Provider model ID<input id="tr-model" type="text" value="${escape(model)}" placeholder="glm-5.3-flash" maxlength="200" spellcheck="false"></label>
        <div class="tr-action"><button id="tr-prepare" class="primary">Prepare dataset <span aria-hidden="true">→</span></button></div>
      </section><section class="tr-card tr-result" id="tr-result" aria-live="polite"></section></div>
      <details class="tr-provider"><summary>Training connection</summary><p>Connect the cloud service to train an adapter. Endpoint ${state.provider.endpoint_configured?'configured':'not configured'} · Credentials ${state.provider.credential_configured?'configured':'not configured'}.</p><p class="tr-help">Server settings: <code>AUTOTENDER_TRAINING_ENDPOINT</code> and <code>AUTOTENDER_TRAINING_API_KEY</code>. Training integration awaits the service’s upload, job and adapter API.</p></details>`;
    host.querySelectorAll('[data-task]').forEach(b=>b.onclick=()=>{capture(); active=b.dataset.task;renderDataset();});
    $('tr-upload-btn').onclick=()=>$('tr-file').click();
    $('tr-file').onchange=upload;
    $('tr-prepare').onclick=prepare;
    resultSignature='';renderResult();
  }
  function renderResult() {
    if(!$('tr-result')) return;
    const j=currentJob(), signature=JSON.stringify(j||{});
    $('tr-prepare').disabled=taskJobs().some(busy);
    if(signature===resultSignature) return;
    resultSignature=signature;
    if(!j) { $('tr-result').innerHTML='<div class="tr-empty"><h3>No dataset prepared yet</h3><p>Choose your sources and prepare a dataset to review it here.</p></div>'; return; }
    const m=j.manifest, counts=m?.counts||{}, total=Object.values(counts).reduce((n,v)=>n+v,0);
    $('tr-result').innerHTML=`<div class="tr-result-head"><span class="tr-eyebrow">DATASET REVIEW</span>${badge(j)}</div><h3>${busy(j)?'Preparing your evidence':m?`${total} accepted examples`:'Preparation could not finish'}</h3><p class="tr-help">${escape(j.base_model)} · ${date(j.created_at)}</p>
      ${busy(j)?'<div class="tr-progress" role="progressbar" aria-label="Dataset preparation in progress"></div><p>Preparing examples…</p>':''}
      ${j.error?`<div class="tr-note tr-error">${escape(j.error)}</div>`:''}
      ${m?`<div class="tr-splits">${['train','validation','test'].map(s=>`<div><strong>${counts[s]||0}</strong><span>${s==='train'?'Training':s==='test'?'Test':'Validation'}</span></div>`).join('')}</div><div class="tr-split-bar" aria-hidden="true">${['train','validation','test'].map(s=>`<i class="${s}" style="flex:${counts[s]||0}"></i>`).join('')}</div><p class="tr-help">${Object.keys(m.projects||{}).length} distinct projects · ${m.rejected_count} rejected records</p>
      ${m.blockers.length?`<div class="tr-note"><b>What’s needed next</b><ul>${m.blockers.map(b=>`<li>${escape(b)}</li>`).join('')}</ul></div>`:''}
      <div class="tr-result-actions">${j.artifacts.includes('dataset_bundle.zip')?`<a class="tr-button" href="${artifact(j,'dataset_bundle.zip')}">Download bundle ↓</a>`:''}<button id="tr-preview-btn">Preview examples</button></div><div id="tr-preview"></div>
      <details class="tr-artifacts"><summary>Files, rejected records & provenance</summary><div>${j.artifacts.map(n=>`<a href="${artifact(j,n)}" download>${escape(n)}</a>`).join('')}</div></details>`:''}
      ${j.collection_errors?.length?`<details class="tr-note"><summary>${j.collection_errors.length} collection warnings</summary><pre>${escape(JSON.stringify(j.collection_errors,null,2))}</pre></details>`:''}`;
    if($('tr-preview-btn')) $('tr-preview-btn').onclick=()=>loadPreview(j,'train');
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
    const input=$('tr-file'), file=input.files[0], uploadTask=active, label=$('tr-upload-status'), button=$('tr-upload-btn');
    if(!file) return;
    label.textContent='Validating upload…'; button.disabled=true;
    try {
      const response=await fetch(`/api/settings/upload-data?task=${uploadTask}&name=${encodeURIComponent(file.name)}`,{method:'POST',body:file});
      const data=await response.json(); if(!response.ok) throw new Error(data.error);
      await refresh();
      if(active===uploadTask&&tab==='datasets') {capture();renderDataset();$('tr-upload-status').textContent=`${data.records} validated records uploaded. Prepare a new dataset to include them.`;}
    } catch(e) {label.textContent=e.message;label.classList.add('err');}
    finally {button.disabled=false;input.value='';}
  }
  async function prepare() {
    capture(); const task=active;
    $('tr-prepare').disabled=true;message('');
    try { const data=await api('/api/training/prepare',{task,base_model:model,include_existing:include});selected[task]=data.job.id;await refresh(); }
    catch(e) {message(e.message,true);if($('tr-prepare'))$('tr-prepare').disabled=false;}
  }
  function renderSources() {
    const collected=state.jobs.find(j=>j.kind==='collection');
    $('tr-page').innerHTML=`<div class="tr-grid tr-source-grid"><section class="tr-card"><div class="tr-eyebrow">COLLECT FROM SIMAP</div><h3>Add real public tender history</h3><p>Import a project directly, or search recent ventilation awards in German and French.</p><label class="tr-field">Project URLs · one per line<textarea id="tr-urls" rows="4" placeholder="https://www.simap.ch/de/project-detail/…"></textarea></label><button class="tr-text-button" id="tr-sample">Use supplied tender example</button><label class="tr-source-choice"><input id="tr-search" type="checkbox"><span><b>Search historical HVAC awards</b><small>Up to 20 awards · bounded multilingual search</small></span></label><button id="tr-collect" class="primary">Collect sources →</button><p class="tr-help">Each publication keeps its URL, retrieval time and raw source hash. Existing publications are deduplicated.</p><div id="tr-collection-status"></div></section>
      <section class="tr-card"><div class="tr-result-head"><div><div class="tr-eyebrow">SOURCE LIBRARY</div><h3>${state.sources.length} archived publications</h3></div></div><p></p><label class="tr-field">Filter publications<input id="tr-source-filter" type="search" placeholder="Search title, buyer or canton"></label><div class="tr-source-list" id="tr-source-list"></div><p class="tr-help">Source: simap.ch. Refer to the original publication for current authoritative information.</p></section></div>
      <section class="tr-card"><h3>Uploaded evidence</h3>${state.uploads.length?`<div class="tr-table-wrap"><table class="tr-table"><thead><tr><th>File</th><th>Task</th><th>Records</th><th>Projects</th></tr></thead><tbody>${state.uploads.map(u=>`<tr><td>${escape(u.file)}${u.error?`<span class="err">${escape(u.error)}</span>`:''}</td><td>${escape(tasks.find(t=>t.key===u.task)?.label)}</td><td>${u.records}</td><td>${u.projects||'—'}</td></tr>`).join('')}</tbody></table></div>`:'<p>No JSONL uploaded yet. Choose a task in Datasets to upload reviewed evidence.</p>'}</section>`;
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
    $('tr-page').innerHTML=`<section class="tr-card"><div class="tr-eyebrow">AUDIT TRAIL</div><h3>Collection & preparation runs</h3><p>Review previous collections and datasets.</p><div class="tr-table-wrap"><table class="tr-table"><thead><tr><th>Run</th><th>Model</th><th>Status</th><th>Created</th><th>Review</th></tr></thead><tbody>${state.jobs.map(j=>`<tr><td><b>${j.kind==='collection'?'Source collection':escape(tasks.find(t=>t.key===j.task)?.label||j.task)}</b><small>${escape(j.id.slice(0,9))}</small></td><td>${escape(j.base_model||'—')}</td><td>${badge(j)}</td><td>${date(j.created_at)}</td><td><button data-run="${j.id}">View</button></td></tr>`).join('')||'<tr><td colspan="5">No runs yet. Prepare a dataset to start.</td></tr>'}</tbody></table></div></section>`;
    host.querySelectorAll('[data-run]').forEach(b=>b.onclick=()=>{const j=state.jobs.find(j=>j.id===b.dataset.run);if(j.kind==='collection')tab='sources';else{active=j.task;selected[active]=j.id;tab='datasets';}render();});
  }
  async function refresh() {
    const token=generation;
    const data=await api('/api/training');
    if(token!==generation||!host?.isConnected)return;
    const sourceChanged=JSON.stringify(state?.sources)!==JSON.stringify(data.sources);
    state=data;renderStats();
    if(tab==='datasets')renderResult();
    if(tab==='sources') {renderCollection(state.jobs.find(j=>j.kind==='collection'));if(sourceChanged){capture();renderSources();}}
    if(tab==='history')renderHistory();
    clearTimeout(timer);
    if(state.jobs.some(busy)) timer=setTimeout(()=>refresh().catch(e=>message(e.message,true)),1600);
  }
  async function mount(element) {
    dispose();host=element;const token=generation;
    host.className='training';host.innerHTML='<div class="tr-card" role="status">Loading training workspace…</div>';
    try {state=await api('/api/training');if(token!==generation||!host.isConnected)return;render();if(state.jobs.some(busy))timer=setTimeout(()=>refresh().catch(e=>message(e.message,true)),1600);}
    catch(e){if(token===generation&&host.isConnected){host.innerHTML='<div class="tr-card"><p role="alert"></p><button>Retry</button></div>';host.querySelector('p').textContent=e.message;host.querySelector('button').onclick=()=>mount(element);}}
  }
  function dispose(){generation++;clearTimeout(timer);}
  return {mount,dispose};
})();
