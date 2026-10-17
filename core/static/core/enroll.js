// Fragments stay out of HTTP access logs. Submit the token only in the protected form body.
const inviteToken = new URLSearchParams(window.location.hash.slice(1)).get('token');
const tokenField = document.getElementById('id_token');
if (inviteToken && tokenField) {
  tokenField.value = inviteToken;
  window.history.replaceState(null, '', window.location.pathname);
}
