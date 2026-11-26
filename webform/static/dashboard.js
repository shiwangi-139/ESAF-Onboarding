// Copy buttons: <button data-copy="#input-id">
document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-copy]');
  if (!btn) return;
  const value = document.querySelector(btn.dataset.copy).value;
  const done = () => { const t = btn.textContent; btn.textContent = 'Copied!'; setTimeout(() => (btn.textContent = t), 1500); };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(value).then(done);
  } else {
    const ta = document.createElement('textarea');
    ta.value = value; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); ta.remove(); done();
  }
});

// Confirm before destructive actions: <form data-confirm="Are you sure?">
document.addEventListener('submit', (e) => {
  const msg = e.target.dataset.confirm;
  if (msg && !window.confirm(msg)) e.preventDefault();
});

// Lead table search
const search = document.getElementById('search');
if (search) {
  search.addEventListener('input', () => {
    const q = search.value.toLowerCase();
    document.querySelectorAll('#leads tbody tr').forEach((tr) => {
      tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
  });
}

// The lead list refreshes itself every minute while you're not typing.
if (document.body.dataset.autorefresh) {
  setInterval(() => {
    const a = document.activeElement;
    if (!a || !['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON'].includes(a.tagName)) location.reload();
  }, 60000);
}
