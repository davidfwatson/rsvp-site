(() => {
  const toast = document.getElementById('workspace-toast');
  let toastTimer;
  window.workspaceToast = message => { toast.textContent = message; toast.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => {toast.hidden = true;}, 3500); };
  document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(button.dataset.copy); window.workspaceToast('Link copied. Ready to share.'); }
    catch { window.workspaceToast('Copy is unavailable. Select the invitation link and copy it manually.'); }
  }));
  const toggle = document.getElementById('nav-toggle');
  toggle?.addEventListener('click', () => { const open = document.getElementById('workspace-nav').classList.toggle('is-open'); toggle.setAttribute('aria-expanded', String(open)); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && toggle) {document.getElementById('workspace-nav').classList.remove('is-open'); toggle.setAttribute('aria-expanded', 'false');} });
  document.querySelectorAll('[data-open-dialog]').forEach(button => button.addEventListener('click', () => document.getElementById(button.dataset.openDialog).showModal()));
  document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
  const eventSearch = document.getElementById('event-search');
  eventSearch?.addEventListener('input', () => {
    let found = 0;
    document.querySelectorAll('[data-event-name]').forEach(card => { card.hidden = !card.dataset.eventName.includes(eventSearch.value.trim().toLowerCase()); if (!card.hidden) found++; });
    document.getElementById('no-events-match').hidden = !!found;
  });
  const form = document.getElementById('new-event-form');
  if (!form) return;
  const names = JSON.parse(document.getElementById('existing-events').textContent);
  const name = document.getElementById('new-name'), slug = document.getElementById('new-slug'), error = document.getElementById('new-event-error');
  let customSlug = false;
  slug.addEventListener('input', () => {customSlug = true;});
  name.addEventListener('input', () => {if (!customSlug) slug.value = name.value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9\s-]/g, '').replace(/[-\s]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 50).replace(/-$/,'');});
  form.addEventListener('submit', e => {
    const problem = names.names.includes(name.value.trim().toLowerCase()) ? 'An event with that name already exists.' : names.slugs.includes(slug.value.trim()) ? 'That invitation link is already in use. Choose another.' : '';
    if (problem) { e.preventDefault(); error.textContent = problem; error.hidden = false; }
    else { error.hidden = true; form.querySelector('[type=submit]').disabled = true; }
  });
})();
