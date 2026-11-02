try {
  const session = await fetch('/api/desktop/session').then(r => r.json());
  if (session.enabled) {
    // BOOTH links belong in the user's default browser, outside the app profile.
    const openBoothLink = async event => {
      if (event.defaultPrevented || (event.type === 'click' ? event.button !== 0 : event.button !== 1)) return;
      const link = event.target.closest?.('a[href]');
      if (!link || link.hasAttribute('download')) return;
      let url;
      try { url = new URL(link.href); } catch { return; }
      if (url.protocol !== 'https:' || url.username || url.password || !(url.hostname === 'booth.pm' || url.hostname.endsWith('.booth.pm'))) return;
      event.preventDefault();
      try {
        const response = await fetch('/api/open_url', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-BoothNest-Token': session.token },
          body: JSON.stringify({ args: [url.href] }),
        });
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || response.statusText);
      } catch (error) {
        const message = document.querySelector('#language')?.value === 'en'
          ? 'Could not open the default browser. Please try again.'
          : '无法使用默认浏览器打开链接，请重试。';
        window.alert(message + '\n' + error.message);
      }
    };
    document.addEventListener('click', openBoothLink, true);
    document.addEventListener('auxclick', openBoothLink, true);
    const send = action => fetch('/api/desktop/' + action, { method: 'POST', headers: { 'X-BoothNest-Token': session.token }, keepalive: true }).catch(() => {});
    send('heartbeat'); setInterval(() => send('heartbeat'), 2000);
    window.addEventListener('pageshow', () => send('heartbeat'));
    window.addEventListener('pagehide', () => send('closed'));
  }
} catch {}
