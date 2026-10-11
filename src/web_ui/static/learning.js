/* Outcome monitoring and the cloud evaluation handoff, in LoRA settings → Advanced. */
window.TendifLearning = {
  async mount(root) {
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const score = value => value == null ? '—' : Number(value).toFixed(3);
    async function request(path, body) {
      const response = await fetch('/api/feedback/'+path, body===undefined ? {} : {
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const data=await response.json();if(!response.ok)throw new Error(data.error||'Could not load learning history.');return data;
    }
    root.innerHTML=`<section class="tr-card"><div class="learning-heading"><h2>Outcome history</h2><button data-refresh>Refresh</button></div><div data-metrics></div>
      <div class="learning-heading"><div><h3>Candidate review</h3><p class="hint">Prepare an evaluation bundle for the cloud model, then import its results.</p></div><button data-prepare>Prepare review</button></div>
      <p data-message class="hint" role="status"></p><div data-reviews></div></section>`;
    const message=root.querySelector('[data-message]');
    const artifact=(id,name,label)=>`<a href="/api/feedback/reviews/${encodeURIComponent(id)}/artifacts/${name}" download>${label} ↓</a>`;
    let reviews=[];
    async function refresh(){
      const [monitor,history]=await Promise.all([request('monitoring'),request('reviews')]);
      if(!root.isConnected)return;
      root.querySelector('[data-metrics]').innerHTML=`<div class="learning-metrics"><div><b>${monitor.completed_count}</b><span>Verified results</span></div><div><b>${monitor.wins} / ${monitor.losses}</b><span>Won / lost</span></div><div><b>${monitor.prediction_count}</b><span>Saved forecasts</span></div><div><b>${score(monitor.brier_score)}</b><span>Forecast error · lower is better</span></div></div>${monitor.drift.alert?'<p class="hint">Forecast accuracy has shifted. Review the latest outcomes before retraining.</p>':''}`;
      reviews=history.reviews;
      root.querySelector('[data-reviews]').innerHTML=reviews.length ? reviews.map(review=>{
        const result=review.result;
        const label=result ? (result.status==='blocked'?'More evidence needed':result.noninferior?'Ready for human review':'Keep current model') : review.status==='blocked'?'More evidence needed':'Awaiting model results';
        const blockers=result?.blockers||review.blockers||[];
        return `<details class="learning-review"><summary><span>${esc(new Date(review.created_at).toLocaleString())} · ${review.samples} tenders</span><span>${label}</span></summary><div class="learning-review-body">
          ${review.candidate_model_id?`<p>${esc(review.candidate_model_id)}</p>`:''}
          ${blockers.length?`<p class="hint">${blockers.map(esc).join(' ')}</p>`:''}
          ${result && result.samples?`<div class="learning-metrics"><div><b>${score(result.champion_brier)}</b><span>Current forecast error</span></div><div><b>${score(result.candidate_brier)}</b><span>Candidate error</span></div></div><p class="hint">${esc(result.recommendation)} Activation requires a separate decision.</p>`:''}
          <div class="learning-actions">${review.kind==='prepared'?artifact(review.id,'handoff.zip','Download bundle'):''}${result?artifact(review.id,'result.json','Download review'):''}
          ${review.kind==='prepared'&&!result?`<label class="learning-import">Import results<input type="file" data-import="${esc(review.id)}" accept=".json" aria-label="Import results for review ${esc(new Date(review.created_at).toLocaleString())}"></label>`:''}</div>
        </div></details>`;
      }).join('') : '<p class="hint">No candidate reviews yet.</p>';
    }
    root.querySelector('[data-refresh]').onclick=async event=>{
      const button=event.target;button.disabled=true;
      try{await refresh();message.textContent='History updated.';}catch(error){message.textContent=error.message;}finally{button.disabled=false;}
    };
    root.querySelector('[data-prepare]').onclick=async event=>{
      const button=event.target;button.disabled=true;message.textContent='Preparing review…';
      try{const review=await request('reviews',{});await refresh();
        root.querySelector('.learning-review').open=true;
        message.textContent=review.status==='blocked'?'Bundle saved. Add more verified outcomes before evaluation.':'Bundle ready. The cloud connection is pending.';
      }catch(error){message.textContent=error.message;}finally{button.disabled=false;}
    };
    root.addEventListener('change',async event=>{
      const input=event.target;if(!input.dataset.import || !input.files[0])return;
      input.disabled=true;message.textContent='Checking results…';
      try{const file=input.files[0];if(file.size>5*1024*1024)throw new Error('Choose a JSON file smaller than 5 MB.');
        await request('reviews/'+input.dataset.import+'/evaluate',JSON.parse(await file.text()));
        await refresh();root.querySelector('.learning-review').open=true;message.textContent='Review saved.';
      }catch(error){message.textContent=error.message;}finally{input.disabled=false;input.value='';}
    });
    try{await refresh();}catch(error){message.textContent=error.message;}
  }
};
