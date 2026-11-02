let collecting = false;
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type !== 'collect' || collecting) return;
  collecting = true; sendResponse({ accepted: true });
  (async () => {
    try {
      const { collectLibraryPages, extractLibraryPage } = await import(chrome.runtime.getURL('purchase-reader.js'));
      // Let a client-rendered library finish mounting before trying its current DOM.
      for (let attempt = 0; attempt < 30; attempt++) {
        try { extractLibraryPage(document, location.href); break; }
        catch { if (attempt === 29) throw new Error('未能读取下载库商品，请打开 BOOTH 下载库确认商品已显示。'); await new Promise(resolve => setTimeout(resolve, 500)); }
      }
      const result = await collectLibraryPages({ initialDocument: document, onProgress: progress => { void chrome.runtime.sendMessage({ type: 'progress', jobId: message.jobId, progress }).catch(() => {}); } });
      const response = await chrome.runtime.sendMessage({ type: 'complete', jobId: message.jobId, result });
      if (response?.error) throw new Error(response.error);
    } catch (error) { try { await chrome.runtime.sendMessage({ type: 'failed', jobId: message.jobId, message: error.message }); } catch {} }
    finally { collecting = false; }
  })();
});
