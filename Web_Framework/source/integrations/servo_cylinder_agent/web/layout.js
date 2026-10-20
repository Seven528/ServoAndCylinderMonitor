// Panel preferences belong to this session; restarting starts with an empty session.
export function projectPanels(width, preferences, focus) {
  const narrow = width < 760;
  return {
    files: focus || !preferences.files ? 'hidden' : narrow ? 'drawer' : 'docked',
    chat: focus || !preferences.chat || (narrow && preferences.files) ? 'hidden' : width < 1250 ? 'drawer' : 'docked',
  };
}

export function setupWorkbench() {
  const $ = (id) => document.getElementById(id);
  const preferences = { files: window.innerWidth >= 760, chat: window.innerWidth >= 1250 };
  let focus = false;
  const triggers = { files: $('open-files'), chat: $('open-chat') };
  function apply() {
    const modes = projectPanels(window.innerWidth, preferences, focus);
    for (const name of ['files', 'chat']) {
      const panel = $(`${name}-panel`);
      panel.dataset.presentation = modes[name];
      panel.inert = modes[name] === 'hidden';
      panel.setAttribute('aria-hidden', String(modes[name] === 'hidden'));
      if (modes[name] === 'drawer') { panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true'); }
      else { panel.removeAttribute('role'); panel.removeAttribute('aria-modal'); }
      triggers[name].setAttribute('aria-expanded', String(modes[name] !== 'hidden'));
    }
    $('drawer-backdrop').hidden = !Object.values(modes).includes('drawer');
    $('focus-view').setAttribute('aria-pressed', String(focus));
  }
  function close(name, restore = true) {
    preferences[name] = false; apply();
    if (restore) triggers[name].focus();
  }
  for (const name of ['files', 'chat']) {
    triggers[name].addEventListener('click', () => {
      focus = false;
      preferences[name] = !preferences[name];
      if (preferences[name] && projectPanels(window.innerWidth, preferences, false)[name] === 'drawer') {
        preferences[name === 'files' ? 'chat' : 'files'] = false;
      }
      apply();
      if (preferences[name]) $(`${name}-panel`).querySelector('button,select').focus();
    });
  }
  document.querySelectorAll('[data-close-panel]').forEach((button) => button.addEventListener('click', () => close(button.dataset.closePanel)));
  $('focus-view').addEventListener('click', () => { focus = !focus; apply(); });
  $('show-results').addEventListener('click', () => { $('result-panel').scrollTo({ top: 0, behavior: 'smooth' }); $('result-panel').focus(); });
  function closeDrawer() {
    const modes = projectPanels(window.innerWidth, preferences, focus);
    for (const name of ['files', 'chat']) if (modes[name] === 'drawer') close(name);
  }
  $('drawer-backdrop').addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      if (focus) { focus = false; apply(); $('focus-view').focus(); }
      else closeDrawer();
    }
    // A drawer acts as a modal surface: keep keyboard navigation inside it.
    if (event.key === 'Tab') {
      const modes = projectPanels(window.innerWidth, preferences, focus);
      const name = ['files', 'chat'].find((item) => modes[item] === 'drawer');
      if (!name) return;
      const controls = [...$(`${name}-panel`).querySelectorAll('button,select,textarea,input')].filter((item) => !item.matches(':disabled') && item.getClientRects().length);
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && (document.activeElement === first || !controls.includes(document.activeElement))) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !controls.includes(document.activeElement))) { event.preventDefault(); first.focus(); }
    }
  });
  window.addEventListener('resize', apply);
  apply();
  return { showResults() { closeDrawer(); $('result-panel').focus(); } };
}
