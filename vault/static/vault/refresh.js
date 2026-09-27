// Queue a rate-limited refresh using CSRF-protected POST; never fetch Gmail in the browser.
const form = document.getElementById('vault-refresh');
if (form) {
  fetch(form.action, {
    method: 'POST', credentials: 'same-origin',
    headers: {Accept: 'application/json'}, body: new FormData(form)
  }).catch(() => {}); // The visible refresh button remains available when offline.
}
