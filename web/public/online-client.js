(async () => {
  let session;
  try { const response = await fetch('/api/server/session'); if (!response.ok) return; session = await response.json(); }
  catch { return; }
  if (!session.enabled) return;
  if (!document.querySelector('link[href="/online.css"]')) {
    const style = document.createElement('link'); style.rel = 'stylesheet'; style.href = '/online.css'; document.head.append(style);
  }
  const english = () => document.querySelector('#language')?.value === 'en';
  const text = () => english() ? 'Manage the download directory through your server.' : '请通过服务器管理下载目录。';
  const adapt = () => {
    for (const badge of document.querySelectorAll('.local-badge')) if (badge.textContent !== 'ONLINE') badge.textContent = 'ONLINE';
    for (const input of document.querySelectorAll('#scan-root, #rootInput')) input.readOnly = true;
    const section = document.querySelector('#connection-section');
    if (section && !section.querySelector('.online-note')) {
      const note = document.createElement('p'); note.className = 'feature-note online-note'; note.textContent = text(); section.append(note);
    }
  };
  adapt();
  new MutationObserver(adapt).observe(document.body, { childList: true, subtree: true });
  if (location.pathname === '/classic' && typeof window.api === 'function') {
    const original = window.api;
    window.api = async function(method, ...args) {
      if (method === 'open_url') {
        let url; try { url = new URL(args[0]); } catch { return { ok: false }; }
        if (url.protocol === 'https:' && (url.hostname === 'booth.pm' || url.hostname.endsWith('.booth.pm'))) { window.open(url.href, '_blank', 'noopener'); return { ok: true }; }
        return { ok: false };
      }
      return original(method, ...args);
    };
  }
})();
