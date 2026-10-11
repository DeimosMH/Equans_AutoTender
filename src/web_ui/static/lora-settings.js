/* UI preview preferences stay local until the model service supplies activation/update APIs. */
window.TendifLoras = (() => {
  const storageKey='tendif_lora_preferences_v1';
  const tasks=[
    {key:'input_processing',label:'Input processing',description:'Read tender documents and match positions.',fallback:'Base model only'},
    {key:'productivity_factors',label:'Productivity factors',description:'Estimate labour using experience and measured work.',fallback:'Expert values (manual)'},
    {key:'win_ratio',label:'Success probability',description:'Estimate the chance of winning a tender.',fallback:'Current calculation'},
  ];
  const parameters={rank:16,alpha:32,dropout:0.05,epochs:3,learning_rate:0.0002};
  const files={}; // File objects stay in this session; saved requests retain their metadata only.
  const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const versionKey=v=>JSON.stringify([v.base,v.version,v.adapter_id||'']);
  const modelName=id=>id==='glm-5.3-flash'?'GLM 5.3 Flash':id;
  let host,settings,evidence,prefs,view='select',task='input_processing',advanced=false,navigationChanged,pendingRuntime;
  const $=id=>host.querySelector('#'+id);
  const versions=key=>settings.tasks[key]?.versions||[];
  const chosen=key=>versions(key).find(v=>versionKey(v)===prefs.tasks[key].selected);
  function load() {
    let saved={};
    try{saved=JSON.parse(localStorage.getItem(storageKey))||{};}catch{}
    const value={tasks:{},advanced:{...settings.advanced,data_dir:'/data/training',...saved.advanced,
      execution_mode:saved.advanced?.execution_mode==='local'?'local':'cloud',
      cloud_endpoint:typeof saved.advanced?.cloud_endpoint==='string'?saved.advanced.cloud_endpoint:''},requests:saved.requests||{}};
    for(const t of tasks){
      const prior=saved.tasks?.[t.key]||{},source=settings.tasks[t.key]||{};
      const initial=versions(t.key).find(v=>v.version===source.selected&&v.base===settings.base_model);
      const base=typeof prior.base_model==='string'&&prior.base_model?prior.base_model:settings.base_model;
      const selected=versions(t.key).find(v=>versionKey(v)===(prior.selected??(initial?versionKey(initial):null))&&v.base===base);
      value.tasks[t.key]={base_model:base,selected:selected?versionKey(selected):null,
        links:typeof prior.links==='string'?prior.links:source.links||'',include_internal:prior.include_internal!==false,
        parameters:{...parameters,...prior.parameters}};
    }
    return value;
  }
  function message(text,error=false) {
    const box=$('lm-message');box.textContent=text;box.hidden=!text;box.className='lm-message'+(error?' tr-error':'');
  }
  function save(text='Choices saved in this browser.') {
    if(prefs.advanced.execution_mode==='cloud'&&prefs.advanced.cloud_endpoint.trim()){
      try{
        const url=new URL(prefs.advanced.cloud_endpoint.trim());
        if(!['http:','https:'].includes(url.protocol)||url.username||url.password)throw new Error();
      }catch{
        const error='Use an http:// or https:// cloud endpoint without embedded credentials.';
        message(error,true);
        if($('lm-cloud-endpoint')){$('lm-cloud-endpoint').setCustomValidity(error);$('lm-cloud-endpoint').reportValidity();}
        return false;
      }
    }
    try{localStorage.setItem(storageKey,JSON.stringify(prefs));message(text);return true;}
    catch{message('Could not save. Allow browser storage and try again.',true);return false;}
  }
  function getRoute() {return {view,task,runtime:pendingRuntime??prefs?.advanced.execution_mode};}
  function setRoute(nextView,nextTask,runtime) {
    view=['select','update','base'].includes(nextView)?nextView:'select';
    task=tasks.some(t=>t.key===nextTask)?nextTask:'input_processing';
    pendingRuntime=['local','cloud'].includes(runtime)?runtime:undefined;
  }
  function mount(element,options,inventory,isAdvanced=false,onNavigate=()=>{}) {
    host=element;settings=options;evidence=inventory;advanced=isAdvanced;navigationChanged=onNavigate;prefs??=load();
    if(pendingRuntime){prefs.advanced.execution_mode=pendingRuntime;pendingRuntime=undefined;}
    render();
  }
  function taskTabs() {
    return `<div class="tr-task-tabs" role="group" aria-label="LoRA task">${tasks.map(t=>`<button type="button" data-lm-task="${t.key}" class="${task===t.key?'selected':''}" aria-pressed="${task===t.key}">${t.label}</button>`).join('')}</div>`;
  }
  function render() {
    host.innerHTML=`${advanced?'':`<div class="tr-tabs lm-menu" aria-label="LoRA settings">${[['select','Select LoRAs'],['update','Update LoRAs'],['base','Base models']].map(([id,label])=>`<button data-lm-view="${id}" class="${view===id?'selected':''}" aria-pressed="${view===id}">${label}</button>`).join('')}</div>`}
      <p class="lm-preview">UI preview · choices saved in this browser</p>
      <div id="lm-message" role="status" aria-live="polite" hidden></div><div id="lm-panel"></div>`;
    host.querySelectorAll('[data-lm-view]').forEach(b=>b.onclick=()=>{view=b.dataset.lmView;render();navigationChanged();host.querySelector(`[data-lm-view="${view}"]`).focus();});
    if(advanced)renderAdvanced();else if(view==='update')renderUpdate();else renderSelection();
    host.querySelectorAll('[data-lm-task]').forEach(b=>b.onclick=()=>{task=b.dataset.lmTask;render();navigationChanged();host.querySelector(`[data-lm-task="${task}"]`).focus();});
  }
  function renderSelection() {
    const baseView=view==='base';
    $('lm-panel').innerHTML=`<form id="lm-selection" class="tr-card lm-card"><h3>${baseView?'Base model for each task':'LoRA for each task'}</h3>
      <p>${baseView?'Choose a base model for each task. Changing it clears an incompatible LoRA.':'Each LoRA uses the base model it was created for.'}</p>
      ${tasks.map(t=>{
        const choice=prefs.tasks[t.key],options=versions(t.key);
        const models=[...new Set([settings.base_model,...settings.base_models,...options.map(v=>v.base),choice.base_model])];
        return `<div class="lm-row"><div><label for="lm-${t.key}">${t.label}</label><p>${t.description}</p></div><div class="lm-choice">
          <select id="lm-${t.key}" data-lm-select="${t.key}">${baseView?models.map(m=>`<option value="${escape(m)}" ${choice.base_model===m?'selected':''}>${escape(modelName(m))}</option>`).join(''):
            `<option value="">${t.fallback}</option>${options.map(v=>`<option value="${escape(versionKey(v))}" ${choice.selected===versionKey(v)?'selected':''}>${escape(v.version)} · ${escape(modelName(v.base))}</option>`).join('')}`}</select>
          <p class="lm-base" id="lm-base-${t.key}">${baseView?`LoRA: ${escape(chosen(t.key)?.version||t.fallback)}`:`Base model: ${escape(modelName(choice.base_model))}`}</p>
          ${!baseView&&!options.length?'<p class="tr-help">No LoRA versions available yet.</p>':''}
        </div></div>`;
      }).join('')}
      <div class="lm-footer"><button class="primary">Save choices</button>${!baseView?'<a href="#settings">Edit expert productivity values ↗</a>':''}</div></form>`;
    host.querySelectorAll('[data-lm-select]').forEach(select=>select.onchange=()=>{
      const key=select.dataset.lmSelect,choice=prefs.tasks[key],t=tasks.find(t=>t.key===key);
      if(baseView){choice.base_model=select.value;if(chosen(key)?.base!==select.value)choice.selected=null;}
      else{choice.selected=select.value||null;const v=chosen(key);if(v)choice.base_model=v.base;}
      $('lm-base-'+key).textContent=baseView?'LoRA: '+(chosen(key)?.version||t.fallback):'Base model: '+modelName(choice.base_model);
      message('Unsaved changes');
    });
    $('lm-selection').onsubmit=e=>{e.preventDefault();save();};
    const expertLink=host.querySelector('a[href="#settings"]');
    if(expertLink)expertLink.onclick=e=>{e.preventDefault();document.getElementById('settingsBtn').click();};
  }
  function renderUpdate() {
    const t=tasks.find(t=>t.key===task),choice=prefs.tasks[task],version=chosen(task);
    $('lm-panel').innerHTML=`${taskTabs()}<form id="lm-update" class="tr-card lm-card"><h3>${version?'Update':'Create'} ${t.label.toLowerCase()} LoRA</h3>
      <p>${version?escape(version.version):'New LoRA'} · ${escape(modelName(choice.base_model))}</p>
      <label class="tr-source-choice"><input type="checkbox" id="lm-internal" ${choice.include_internal?'checked':''}><span><b>Use internal training data</b><small>${evidence[task]?.examples||0} saved examples</small></span></label>
      <div class="lm-upload"><button type="button" id="lm-upload">Upload data</button><span id="lm-file-count"></span></div>
      <input type="file" id="lm-files" multiple hidden><div id="lm-file-list" aria-live="polite"></div>
      <p class="tr-help" id="lm-file-reminder" hidden>Files from the previous request need to be selected again after reloading.</p>
      <label class="tr-field lm-links">Additional data links <span>(optional · one per line)</span><textarea id="lm-links" rows="3" maxlength="4000" placeholder="https://…">${escape(choice.links)}</textarea></label>
      <div class="lm-footer"><button class="primary">${version?'Update LoRA':'Create LoRA'}</button><span>${prefs.advanced.execution_mode==='local'?'Local · service not connected':prefs.advanced.cloud_endpoint.trim()?'Cloud · service not connected':'Cloud · endpoint pending'}</span></div>
      <p id="lm-request" class="tr-help" ${prefs.requests[task]?'':'hidden'}>${prefs.requests[task]?'Update request saved · '+escape(new Date(prefs.requests[task].saved_at).toLocaleString()):''}</p>
    </form>`;
    $('lm-internal').onchange=e=>{choice.include_internal=e.target.checked;};
    $('lm-upload').onclick=()=>$('lm-files').click();
    $('lm-files').onchange=e=>{
      files[task]??=[];
      for(const file of e.target.files){
        if(!files[task].some(f=>f.name===file.name&&f.size===file.size&&f.lastModified===file.lastModified))files[task].push(file);
      }
      e.target.value='';renderFiles();
    };
    renderFiles();
    $('lm-links').oninput=e=>{choice.links=e.target.value;e.target.setCustomValidity('');};
    $('lm-update').onsubmit=e=>{
      e.preventDefault();const links=choice.links.split('\n').map(s=>s.trim()).filter(Boolean);
      if(links.some(link=>{try{return !['https:','http:'].includes(new URL(link).protocol);}catch{return true;}})){
        $('lm-links').setCustomValidity('Use complete http:// or https:// links, one per line.');$('lm-links').reportValidity();return;
      }
      if(!choice.include_internal&&!links.length&&!files[task]?.length){message('Choose internal training data, upload files or add a link.',true);return;}
      const previous=prefs.requests[task],config=prefs.advanced;
      prefs.requests[task]={task,base_model:choice.base_model,adapter:version?{version:version.version,base:version.base,adapter_id:version.adapter_id}:null,
        include_internal:choice.include_internal,links,
        execution:config.execution_mode==='cloud'?{mode:'cloud',endpoint:config.cloud_endpoint.trim()||null}:
          {mode:'local',paths:{models_dir:config.models_dir,loras_dir:config.loras_dir,data_dir:config.data_dir,cache_dir:config.cache_dir}},
        files:(files[task]||[]).map(f=>({name:f.name,size:f.size,type:f.type,last_modified:f.lastModified})),
        parameters:{...choice.parameters},saved_at:new Date().toISOString()};
      if(save('Update request saved. Waiting for the training service.')){
        $('lm-request').hidden=false;$('lm-request').textContent='Update request saved · '+new Date(prefs.requests[task].saved_at).toLocaleString();
        renderFiles();
      }else if(previous)prefs.requests[task]=previous;else delete prefs.requests[task];
    };
  }
  function renderFiles() {
    const selected=files[task]||[];
    $('lm-file-count').textContent=selected.length?`${selected.length} file${selected.length===1?'':'s'} selected`:'No files selected';
    $('lm-file-list').innerHTML=selected.map((f,i)=>`<div class="lm-file"><span>${escape(f.name)}</span><small>${f.size<1024?f.size+' B':f.size<1048576?(f.size/1024).toFixed(1)+' KB':(f.size/1048576).toFixed(1)+' MB'}</small><button type="button" data-lm-remove="${i}" aria-label="Remove ${escape(f.name)}">×</button></div>`).join('');
    $('lm-file-reminder').hidden=!!selected.length||!prefs.requests[task]?.files?.length;
    host.querySelectorAll('[data-lm-remove]').forEach(button=>button.onclick=()=>{files[task].splice(Number(button.dataset.lmRemove),1);renderFiles();$('lm-upload').focus();});
  }
  function renderAdvanced() {
    const config=prefs.advanced,cloud=config.execution_mode==='cloud';
    $('lm-panel').innerHTML=`<form id="lm-advanced" class="tr-card lm-card"><h3>Model service &amp; LoRA parameters</h3>
      <p>Choose where base models and LoRAs run.</p>
      <div class="tr-task-tabs" role="group" aria-label="Model location">${['local','cloud'].map(mode=>`<button type="button" data-lm-runtime="${mode}" class="${config.execution_mode===mode?'selected':''}" aria-pressed="${config.execution_mode===mode}">${mode==='local'?'Local':'Cloud'}</button>`).join('')}</div>
      ${cloud?`<label class="tr-field">Cloud endpoint<input id="lm-cloud-endpoint" type="url" value="${escape(config.cloud_endpoint)}" placeholder="https://your-service.example" maxlength="1000" spellcheck="false"></label><p class="tr-help">Your cloud service endpoint can be added later.</p>`:
        `<div class="lm-fields">${[['models_dir','Base models directory'],['loras_dir','LoRA directory'],['data_dir','Internal training data directory'],['cache_dir','Cache directory']].map(([key,label])=>`<label class="tr-field">${label}<input data-lm-path="${key}" value="${escape(config[key])}" required maxlength="300" spellcheck="false"></label>`).join('')}</div>`}
      <div class="lm-parameters"><h4>Training parameters</h4>${taskTabs()}<div class="lm-fields lm-numbers">${[['rank','Rank',1,256,1],['alpha','Alpha',1,1024,1],['dropout','Dropout',0,.9,.01],['epochs','Epochs',.1,100,.1],['learning_rate','Learning rate',.000001,.1,.000001]].map(([key,label,min,max,step])=>`<label class="tr-field">${label}<input type="number" data-lm-parameter="${key}" value="${escape(prefs.tasks[task].parameters[key])}" min="${min}" max="${max}" step="${step}" required></label>`).join('')}</div></div>
      <div class="lm-footer"><button class="primary">Save configuration</button></div>
    </form>`;
    host.querySelectorAll('[data-lm-runtime]').forEach(button=>button.onclick=()=>{config.execution_mode=button.dataset.lmRuntime;render();navigationChanged();host.querySelector(`[data-lm-runtime="${config.execution_mode}"]`).focus();});
    if($('lm-cloud-endpoint'))$('lm-cloud-endpoint').oninput=e=>{config.cloud_endpoint=e.target.value;e.target.setCustomValidity('');};
    host.querySelectorAll('[data-lm-path]').forEach(input=>input.oninput=()=>{prefs.advanced[input.dataset.lmPath]=input.value;});
    host.querySelectorAll('[data-lm-parameter]').forEach(input=>input.oninput=()=>{if(input.validity.valid)prefs.tasks[task].parameters[input.dataset.lmParameter]=Number(input.value);});
    $('lm-advanced').onsubmit=e=>{e.preventDefault();save('Configuration saved in this browser.');};
  }
  return {mount,getRoute,setRoute};
})();
