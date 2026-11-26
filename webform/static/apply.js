(() => {
  const cfg = JSON.parse(document.getElementById('apply-config').textContent);
  const uploaded = new Set(cfg.uploaded);
  let current = cfg.start;

  const MESSAGES = {
    invalid_mobile: 'कृपया 10 अंकों का सही मोबाइल नंबर डालें / Please enter a valid 10-digit mobile number',
    consent_required: 'आगे बढ़ने के लिए सहमति पर टिक करें / Please tick the consent box to continue',
    mobile_first: 'पहले मोबाइल नंबर डालें / Please enter your mobile number first',
    session_expired: 'पेज दोबारा खोलें / Please reload the page',
    too_large: 'फोटो बहुत बड़ी है / Photo is too large',
    not_an_image: 'यह फोटो नहीं है, कृपया फोटो चुनें / This is not a photo, please choose a photo',
    infected: 'यह फ़ाइल सुरक्षित नहीं है / This file was blocked as unsafe',
    scan_unavailable: 'अभी अपलोड नहीं हो सका, थोड़ी देर बाद कोशिश करें / Could not upload right now, try again shortly',
  };
  const errorText = (e) => MESSAGES[e] || 'नेटवर्क समस्या, फिर से कोशिश करें / Network problem, please try again';

  async function post(url, body) {
    try {
      const r = await fetch(url, { method: 'POST', body, credentials: 'same-origin', headers: { 'X-CSRF-Token': cfg.csrf } });
      if (r.status === 413) return { ok: false, error: 'too_large' };
      const j = await r.json().catch(() => ({}));
      return { ok: r.ok && j.ok, error: j.error };
    } catch (e) {
      return { ok: false };
    }
  }

  // Shrink big phone photos before upload (weak rural networks). The shop photo is sent as-is so the
  // server can read its GPS geo-stamp; the server re-checks and re-encodes every file anyway.
  async function shrink(file) {
    if (!file.type.startsWith('image/') || file.size < 600 * 1024) return file;
    try {
      const bitmap = await createImageBitmap(file);
      const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(bitmap.width * scale);
      canvas.height = Math.round(bitmap.height * scale);
      canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((res) => canvas.toBlob(res, 'image/jpeg', 0.85));
      return blob && blob.size < file.size ? new File([blob], 'photo.jpg', { type: 'image/jpeg' }) : file;
    } catch (e) {
      return file;
    }
  }

  function showStep(n) {
    current = n;
    document.querySelectorAll('.step').forEach((s) => s.classList.toggle('active', +s.dataset.step === n));
    document.querySelectorAll('.progress .circle').forEach((c) => {
      c.classList.toggle('active', +c.dataset.step === n);
      c.classList.toggle('done', +c.dataset.step < n);
    });
    document.getElementById('back-btn').style.visibility = n === 1 ? 'hidden' : 'visible';
    document.getElementById('next-btn').style.display = n === cfg.total ? 'none' : 'block';
    document.getElementById('submit-btn').style.display = n === cfg.total ? 'block' : 'none';
    window.scrollTo(0, 0);
  }

  async function nextStep() {
    const stepDiv = document.querySelector(`.step[data-step="${current}"]`);
    for (const el of stepDiv.querySelectorAll('input:not([type=file]):not([type=hidden]), select')) {
      if (el.closest('.hidden')) continue;
      if (!el.checkValidity()) { el.reportValidity(); return; }
    }
    const addr = document.getElementById('f-lives_at_aadhaar_address');
    const local = document.getElementById('f-local_address');
    if (addr && stepDiv.contains(addr) && addr.value === 'no' && !local.value.trim()) {
      local.setCustomValidity('कृपया पता भरें / Please enter your address');
      local.reportValidity(); local.setCustomValidity(''); return;
    }
    const missingDocs = cfg.docKeys.filter((k) => !uploaded.has(k));
    if (stepDiv.querySelector('[data-doc]') && missingDocs.length) {
      alert(`कृपया सभी ${cfg.docKeys.length} दस्तावेज़ अपलोड करें (${missingDocs.length} बाकी) / Please upload all documents (${missingDocs.length} left)`);
      return;
    }

    const body = new FormData();
    body.append('step', current);
    stepDiv.querySelectorAll('input:not([type=file]):not([type=checkbox]), select').forEach((el) => body.append(el.name, el.value));
    const consent = stepDiv.querySelector('#consent');
    if (consent && consent.checked) body.append('consent', 'yes');
    const btn = document.getElementById('next-btn');
    btn.disabled = true; btn.textContent = 'सेव हो रहा है… / Saving…';
    const res = await post(cfg.saveUrl, body);
    btn.disabled = false; btn.textContent = 'अगला / Next';
    if (!res.ok) { alert(errorText(res.error)); return; }
    showStep(current + 1);
  }

  document.querySelectorAll('input[data-doc]').forEach((input) => input.addEventListener('change', async () => {
    if (!input.files.length) return;
    const key = input.dataset.doc;
    const status = document.getElementById('st-' + key);
    status.className = 'doc-status'; status.textContent = 'अपलोड हो रहा है… / Uploading…';
    const file = key === 'shop_photo' ? input.files[0] : await shrink(input.files[0]);
    const body = new FormData();
    body.append('doc_type', key);
    body.append('file', file);
    const res = await post(cfg.uploadUrl, body);
    if (res.ok) {
      uploaded.add(key);
      status.className = 'doc-status ok'; status.textContent = '✓ अपलोड हो गया / Uploaded';
    } else {
      input.value = '';
      status.className = 'doc-status err'; status.textContent = '✗ ' + errorText(res.error);
    }
    if (key === 'shop_photo' && navigator.geolocation) {
      navigator.geolocation.getCurrentPosition((pos) => {
        document.getElementById('shop_lat').value = pos.coords.latitude;
        document.getElementById('shop_lng').value = pos.coords.longitude;
      });
    }
  }));

  const addrSelect = document.getElementById('f-lives_at_aadhaar_address');
  if (addrSelect) addrSelect.addEventListener('change', () => {
    document.getElementById('addr-box').classList.toggle('hidden', addrSelect.value !== 'no');
  });

  document.getElementById('next-btn').addEventListener('click', nextStep);
  document.getElementById('back-btn').addEventListener('click', () => showStep(current - 1));
  document.getElementById('apply-form').addEventListener('submit', () => {
    const btn = document.getElementById('submit-btn');
    setTimeout(() => { btn.disabled = true; btn.textContent = 'जमा हो रहा है… / Submitting…'; }, 0);
  });
  showStep(current);
})();
