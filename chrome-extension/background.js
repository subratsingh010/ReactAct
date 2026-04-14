function normalizeApiBase(base) {
  const raw = String(base || '').trim()
  const fallback = 'http://127.0.0.1:8000/api'
  const value = raw || fallback
  return value.replace(/\/+$/, '')
}

async function openSidePanelForTab(tab, path = 'panel.html') {
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

function getToken() {
  return new Promise((resolve) => {
    chrome.storage.local.get(['token'], (res) => {
      resolve(String(res?.token || '').trim())
    })
  })
}

function setToken(token) {
  return new Promise((resolve) => {
    chrome.storage.local.set({ token: String(token || '').trim() }, () => resolve())
  })
}

function sendMessageToTab(tabId, payload) {
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, payload, (res) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message || 'Could not reach tab content script'))
        return
      }
      resolve(res || {})
    })
  })
}

async function tryAutoTokenFromOpenAppTabs() {
  const tabs = await chrome.tabs.query({})
  const appTabs = tabs.filter((tab) => {
    const u = String(tab?.url || '')
    return u.startsWith('http://127.0.0.1:5173') || u.startsWith('http://localhost:5173') || u.startsWith('http://127.0.0.1:5174') || u.startsWith('http://localhost:5174')
  })
  for (const tab of appTabs) {
    if (!tab?.id) continue
    try {
      const res = await sendMessageToTab(tab.id, { type: 'GET_LOCAL_ACCESS_TOKEN' })
      const token = String(res?.token || '').trim()
      if (token) {
        await setToken(token)
        return token
      }
    } catch {
      // ignore tab errors and try next tab
    }
  }
  return ''
}

async function apiFetch(path, options = {}) {
  let token = await getToken()
  if (!token) {
    token = await tryAutoTokenFromOpenAppTabs()
  }
  if (options.requireAuth && !token) {
    throw new Error('Please login in web app')
  }

  const apiBase = normalizeApiBase(options.apiBase)
  const url = `${apiBase}${path}`
  const authHeaders = token ? { Authorization: `Bearer ${token}` } : {}

  const response = await fetch(url, {
    method: options.method || 'GET',
    headers: {
      ...authHeaders,
      ...(options.headers || {}),
    },
    ...(options.body !== undefined ? { body: options.body } : {}),
  })

  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = formatApiError(data)
    throw new Error(`HTTP ${response.status}: ${detail}`)
  }
  return data
}

function formatApiError(data) {
  if (!data || typeof data !== 'object') return 'API request failed'
  if (typeof data.detail === 'string' && data.detail.trim()) return data.detail.trim()
  if (typeof data.message === 'string' && data.message.trim()) return data.message.trim()

  const keys = Object.keys(data)
  if (!keys.length) return 'API request failed'
  const firstKey = keys[0]
  const value = data[firstKey]
  if (Array.isArray(value) && value.length) {
    return `${firstKey}: ${String(value[0])}`
  }
  if (typeof value === 'string' && value.trim()) {
    return `${firstKey}: ${value.trim()}`
  }
  try {
    return JSON.stringify(data)
  } catch {
    return 'API request failed'
  }
}

chrome.runtime.onInstalled.addListener(() => {
  if (!chrome.sidePanel?.setPanelBehavior) return
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {})
})

chrome.action.onClicked.addListener(async (tab) => {
  try {
    await openSidePanelForTab(tab, 'panel.html')
  } catch {
    // no-op
  }
})

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const type = msg?.type
  if (!type) return false

  if (type === 'OPEN_EXTENSION_PAGE') {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const activeTab = tabs?.[0]
      if (!activeTab?.id) {
        sendResponse({ ok: false, mode: 'none', reason: 'missing_tab' })
        return
      }
      openSidePanelForTab(activeTab, 'panel.html')
        .then(() => sendResponse({ ok: true, mode: 'sidepanel' }))
        .catch(() => sendResponse({ ok: false, mode: 'none', reason: 'open_failed' }))
    })
    return true
  }

  if (type === 'EXTENSION_GET_FORM_META') {
    apiFetch('/extension/form-meta/', { apiBase: msg?.apiBase })
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }))
    return true
  }

  if (type === 'EXTENSION_SEARCH_COMPANIES') {
    const q = encodeURIComponent(String(msg?.q || '').trim())
    apiFetch(`/extension/companies/?q=${q}`, { apiBase: msg?.apiBase })
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }))
    return true
  }

  if (type === 'EXTENSION_SAVE_JOB') {
    apiFetch('/extension/jobs/', {
      method: 'POST',
      requireAuth: true,
      apiBase: msg?.apiBase,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(msg?.payload || {}),
    })
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }))
    return true
  }

  if (type === 'EXTENSION_SAVE_EMPLOYEE') {
    apiFetch('/extension/employees/', {
      method: 'POST',
      requireAuth: true,
      apiBase: msg?.apiBase,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(msg?.payload || {}),
    })
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }))
    return true
  }

  return false
})
