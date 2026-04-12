async function openSidePanelForTab(tab, path = 'popup.html') {
  const tabId = tab?.id
  if (!tabId || !chrome.sidePanel) return false

  await chrome.sidePanel.setOptions({
    tabId,
    path,
    enabled: true,
  })
  try {
    await chrome.sidePanel.open({ tabId })
  } catch {
    const windowId = tab?.windowId
    if (!windowId) throw new Error('missing_window_id')
    await chrome.sidePanel.open({ windowId })
  }
  return true
}

chrome.runtime.onInstalled.addListener(() => {
  if (!chrome.sidePanel?.setPanelBehavior) return
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {})
})

chrome.action.onClicked.addListener(async (tab) => {
  try {
    await openSidePanelForTab(tab, 'popup.html')
  } catch {
    // no-op
  }
})

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type !== 'OPEN_EXTENSION_PAGE') return
  const path = 'popup.html'
  const handleOpen = (activeTab) => {
    if (!activeTab?.id) {
      sendResponse({ ok: false, mode: 'none', reason: 'missing_tab' })
      return
    }
    openSidePanelForTab(activeTab, path)
      .then(() => sendResponse({ ok: true, mode: 'sidepanel' }))
      .catch(() => sendResponse({ ok: false, mode: 'none', reason: 'open_failed' }))
  }
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    handleOpen(tabs?.[0])
  })
  return true
})
