(() => {
  const form = document.getElementById('event-editor');
  if (!form) return;
  const token = document.querySelector('meta[name=csrf-token]').content;
  const status = document.getElementById('save-status'), statusText = document.getElementById('save-status-text');
  const error = document.getElementById('editor-error'), retry = document.getElementById('retry-save');
  const reload = document.getElementById('reload-editor'), frame = document.getElementById('live-preview');
  const caption = document.getElementById('preview-caption');
  const layout = document.getElementById('editor-layout');
  const replay = document.getElementById('preview-replay'), replayLabel = document.getElementById('preview-replay-label');
  const widePreview = window.matchMedia('(min-width: 951px)');
  let previewReady = false, animationBusy = false;
  let version = Number(form.elements.version.value), revision = 0, savedRevision = 0, previewRevision = 0;
  let timer, previewTimer, worker = null, blocked = false, previewController;
  let uploading = 0;
  function commandPreview(command) {
    frame.contentWindow?.postMessage({type:'invitation-preview', command}, window.location.origin);
  }
  function previewControls() {
    replay.disabled = !previewReady || animationBusy;
    replayLabel.textContent = animationBusy ? 'Replaying…' : 'Replay opening';
  }
  function replayPreview() {
    if (!previewReady || animationBusy) return;
    commandPreview('replay');
  }
  window.addEventListener('message', event => {
    if (event.source !== frame.contentWindow || event.origin !== window.location.origin || event.data?.type !== 'invitation-preview-state') return;
    previewReady = true; animationBusy = Boolean(event.data.animating); previewControls();
  });
  frame.addEventListener('load', () => commandPreview('status'));
  // A cached iframe can finish before this deferred script attaches its load listener.
  commandPreview('status');
  replay.addEventListener('click', replayPreview);
  function state(value, message) { status.dataset.state = value; statusText.textContent = message; }
  function fields() {
    const result = {version};
    for (const [key, value] of new FormData(form)) {
      if (!['csrf_token', 'update_event', 'version'].includes(key) && typeof value === 'string') result[key] = value;
    }
    for (const key of ['archived', 'show_attendees']) result[key] = form.elements[key].checked;
    return result;
  }
  // Deduplicate input/change events by the draft, never by save completion.
  // A change-only control must still update while another edit is unsaved.
  let draftSnapshot = JSON.stringify({...fields(), version:0});
  async function save() {
    clearTimeout(timer);
    if (blocked || uploading) return false;
    if (worker) return worker;
    if (revision === savedRevision) return true;
    worker = (async () => {
      while (savedRevision < revision) {
        if (!navigator.onLine) { state('error', 'Offline · changes unsaved'); error.textContent = 'Your changes are still in this window. Reconnect to save them.'; error.hidden = false; retry.hidden = false; return false; }
        if (!form.checkValidity()) {state('error', 'Check your event details'); error.textContent = 'Complete the required fields before your changes can be saved.'; error.hidden = false; return false;}
        const snapshotRevision = revision, payload = fields();
        state('saving', 'Saving changes…'); retry.hidden = true;
        try {
          const response = await fetch(form.dataset.saveUrl, {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':token}, body:JSON.stringify(payload)});
          if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Your session expired. Keep this window open and sign in again in another tab, then reload.');
          const data = await response.json();
          if (!response.ok) {
            if (response.status === 409) {blocked = true; reload.hidden = false;}
            throw new Error(data.error || 'Changes could not be saved.');
          }
          version = data.version; form.elements.version.value = version; savedRevision = snapshotRevision;
          error.hidden = true; retry.hidden = true;
          const current = fields();
          document.getElementById('editor-title').textContent = current.name;
          const eventState = document.getElementById('event-state');
          eventState.textContent = current.archived ? 'Archived' : 'Active invitation'; eventState.classList.toggle('badge-success', !current.archived);
        } catch (err) {
          state('error', blocked ? 'Conflict · reload needed' : 'Changes unsaved');
          error.textContent = err.message || 'Could not reach the server. Your changes are still in this window.';
          error.hidden = false; retry.hidden = blocked;
          return false;
        }
      }
      state('saved', 'All changes saved'); return true;
    })();
    try { return await worker; } finally { worker = null; }
  }
  async function preview() {
    if ((!widePreview.matches && layout.dataset.activeTab !== 'design') || !form.checkValidity()) {
      previewController?.abort();
      if (!form.checkValidity()) caption.textContent = 'Complete the required details to update the preview.';
      return;
    }
    if (revision === previewRevision) return;
    previewController?.abort(); previewController = new AbortController();
    const controller = previewController;
    const snapshotRevision = revision;
    try {
      const response = await fetch(form.dataset.previewUrl, {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':token}, body:JSON.stringify(fields()), signal:controller.signal});
      if (!response.ok || response.redirected) {caption.textContent = 'Preview shows the last valid invitation. Check your event details.'; return;}
      const html = await response.text();
      if (controller !== previewController || controller.signal.aborted) return;
      previewReady = false; animationBusy = false; previewControls();
      previewRevision = snapshotRevision;
      frame.srcdoc = html; caption.textContent = 'Your envelope, updated as you edit.';
    } catch (err) {if (err.name !== 'AbortError') caption.textContent = 'Preview will update when the connection returns.';}
  }
  function changed(event) {
    if (event?.target.type === 'file') return;
    const snapshot = JSON.stringify({...fields(), version:0});
    if (snapshot === draftSnapshot) return;
    draftSnapshot = snapshot;
    revision++; state('dirty', 'Unsaved changes');
    clearTimeout(timer); timer = setTimeout(save, 850);
    clearTimeout(previewTimer); previewTimer = setTimeout(preview, 450);
    document.querySelectorAll('[data-color-label]').forEach(label => {label.textContent = form.elements[label.dataset.colorLabel].value;});
  }
  form.addEventListener('input', changed);
  form.addEventListener('change', changed);
  form.addEventListener('submit', async event => {event.preventDefault(); await save();});
  retry.addEventListener('click', save);
  window.addEventListener('beforeunload', event => {if (revision !== savedRevision || uploading) {event.preventDefault(); event.returnValue = '';}});
  window.addEventListener('offline', () => {if (revision !== savedRevision) state('error', 'Offline · changes unsaved');});
  window.addEventListener('online', () => {save(); preview();});
  widePreview.addEventListener('change', preview);
  const tabs = [...document.querySelectorAll('button[data-editor-tab]')];
  function activate(button) {
    const tab = button.dataset.editorTab;
    layout.dataset.activeTab = tab;
    tabs.forEach(other => {const active = other === button; other.classList.toggle('is-active', active); other.setAttribute('aria-selected', active); other.tabIndex = active ? 0 : -1;});
    document.querySelectorAll('.tab-panel').forEach(panel => {panel.hidden = panel.id !== `tab-${tab}`;});
    const editorTab = ['details', 'design'].includes(tab);
    form.hidden = !editorTab; document.getElementById('editor-layout').classList.toggle('list-view', !editorTab);
    if (editorTab) preview();
  }
  tabs.forEach((button,index) => {button.addEventListener('click', () => activate(button)); button.addEventListener('keydown', event => {let next; if(event.key==='ArrowRight') next=(index+1)%tabs.length; if(event.key==='ArrowLeft') next=(index+tabs.length-1)%tabs.length; if(event.key==='Home') next=0; if(event.key==='End') next=tabs.length-1; if(next!==undefined){event.preventDefault();tabs[next].focus();activate(tabs[next]);}});});
  const guestSearch = document.getElementById('guest-search');
  guestSearch?.addEventListener('input', () => {let found=0;document.querySelectorAll('[data-guest]').forEach(row=>{row.hidden=!row.dataset.guest.includes(guestSearch.value.toLowerCase().trim());if(!row.hidden)found++;});document.getElementById('no-guests-match').hidden=!!found;});
  function imagePreview(field, url) {
    form.elements[field].value = url;
    const thumbnail = document.querySelector(`[data-image-preview=${field}]`); thumbnail.hidden = !url;
    if (url) thumbnail.src = url; else thumbnail.removeAttribute('src');
    document.querySelector(`[data-remove-image=${field}]`).hidden = !url;
    if (field === 'background_image') form.elements.background_style.value = url ? 'image' : 'linen';
    changed();
  }
  document.querySelectorAll('[data-upload-field]').forEach(input => input.addEventListener('change', async () => {
    const file = input.files[0]; if (!file) return;
    if (file.size > 8*1024*1024) {window.workspaceToast('Choose an image smaller than 8 MB.');input.value='';return;}
    uploading++; input.disabled = true; state('saving', 'Uploading photograph…');
    try {
      const payload = new FormData();payload.append('image',file);
      const response = await fetch(form.dataset.uploadUrl,{method:'POST',headers:{'X-CSRF-Token':token},body:payload});
      const result = await response.json(); if(!response.ok) throw new Error(result.error || 'Upload failed.');
      imagePreview(input.dataset.uploadField,result.url); window.workspaceToast('Image uploaded.');
    } catch(err) {error.textContent=err.message || 'Upload failed. Please try again.';error.hidden=false;state('error','Upload failed');}
    finally {uploading--;input.disabled=false;input.value='';if(revision>savedRevision)save();else if(!uploading)state('saved','All changes saved');}
  }));
  document.querySelectorAll('[data-remove-image]').forEach(button=>button.addEventListener('click',()=>imagePreview(button.dataset.removeImage,'')));
  let sending = false;
  document.getElementById('send-invitation').addEventListener('submit',async event=>{
    if(sending)return;
    event.preventDefault();
    if(uploading){window.workspaceToast('Wait for your photograph to finish uploading.');return;}
    if(await save()){sending=true;event.target.requestSubmit();}
    else window.workspaceToast('Save your changes before sending the invitation.');
  });
})();
