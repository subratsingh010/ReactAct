function normalizeApiBase(base) {
  const raw = String(base || '').trim()
  const fallback = 'http://127.0.0.1:8000/api'
  const value = raw || fallback
  return value.replace(/\/+$/, '')
}

const AUTH_STORAGE_KEY = 'applypilot_extension_auth'

function getApiOrigin(apiBase) {
  let parsed
  try {
    parsed = new URL(normalizeApiBase(apiBase))
  } catch {
    throw new Error('Enter a valid API base URL.')
  }
  if (!/^https?:$/.test(parsed.protocol)) {
    throw new Error('Only http and https API URLs are supported.')
  }
  return parsed.origin
}

function ensureApiAccess(apiBase, interactive = false) {
  const origin = getApiOrigin(apiBase)
  const origins = [`${origin}/*`]
  return new Promise((resolve, reject) => {
    if (!chrome.permissions?.contains) {
      resolve(origin)
      return
    }

    chrome.permissions.contains({ origins }, (hasPermission) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message || 'Could not check API access'))
        return
      }
      if (hasPermission) {
        resolve(origin)
        return
      }
      if (!interactive) {
        reject(new Error(`Grant extension access to ${origin} and try again.`))
        return
      }

      chrome.permissions.request({ origins }, (granted) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message || 'Could not request API access'))
          return
        }
        if (!granted) {
          reject(new Error(`Access to ${origin} was denied.`))
          return
        }
        resolve(origin)
      })
    })
  })
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

function getAuthState() {
  return new Promise((resolve) => {
    chrome.storage.local.get([AUTH_STORAGE_KEY], (res) => {
      const auth = res?.[AUTH_STORAGE_KEY]
      resolve({
        access: String(auth?.access || '').trim(),
        refresh: String(auth?.refresh || '').trim(),
        username: String(auth?.username || '').trim(),
        loggedInAt: Number(auth?.loggedInAt || 0) || 0,
      })
    })
  })
}

function setAuthState(nextState) {
  return new Promise((resolve) => {
    const payload = {
      access: String(nextState?.access || '').trim(),
      refresh: String(nextState?.refresh || '').trim(),
      username: String(nextState?.username || '').trim(),
      loggedInAt: Number(nextState?.loggedInAt || 0) || 0,
    }
    chrome.storage.local.set({ [AUTH_STORAGE_KEY]: payload }, () => resolve(payload))
  })
}

function clearAuthState() {
  return setAuthState({ access: '', refresh: '', username: '', loggedInAt: 0 })
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

function getOriginPattern(url) {
  let parsed
  try {
    parsed = new URL(String(url || '').trim())
  } catch {
    return ''
  }
  if (!/^https?:$/.test(parsed.protocol)) return ''
  return `${parsed.origin}/*`
}

function ensureTabOriginAccess(url, interactive = false) {
  const originPattern = getOriginPattern(url)
  if (!originPattern || !chrome.permissions?.contains) {
    return Promise.resolve(originPattern)
  }
  return new Promise((resolve, reject) => {
    chrome.permissions.contains({ origins: [originPattern] }, (hasPermission) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message || 'Could not check page access'))
        return
      }
      if (hasPermission) {
        resolve(originPattern)
        return
      }
      if (!interactive) {
        reject(new Error(`Grant extension access to ${originPattern} and try again.`))
        return
      }
      chrome.permissions.request({ origins: [originPattern] }, (granted) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message || 'Could not request page access'))
          return
        }
        if (!granted) {
          reject(new Error(`Access to ${originPattern} was denied.`))
          return
        }
        resolve(originPattern)
      })
    })
  })
}

function executeContentScript(tabId) {
  return new Promise((resolve, reject) => {
    chrome.scripting.executeScript(
      {
        target: { tabId },
        files: ['content.js'],
      },
      () => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message || 'Could not inject scraper'))
          return
        }
        resolve(true)
      },
    )
  })
}

async function extractFromActiveTab(messageType) {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true })
  const activeTab = tabs?.[0]
  if (!activeTab?.id) {
    throw new Error('No active tab found.')
  }
  const tabUrl = String(activeTab.url || '').trim()
  if (!/^https?:/i.test(tabUrl)) {
    throw new Error('Open a normal http/https page before scraping.')
  }

  await ensureTabOriginAccess(tabUrl, true)

  try {
    return await sendMessageToTab(activeTab.id, { type: messageType })
  } catch (error) {
    if (!/Receiving end does not exist|Could not reach tab content script/i.test(String(error?.message || ''))) {
      throw error
    }
  }

  await executeContentScript(activeTab.id)
  return sendMessageToTab(activeTab.id, { type: messageType })
}

async function loginWithCredentials(apiBase, username, password) {
  await ensureApiAccess(apiBase, true)
  const response = await fetch(`${normalizeApiBase(apiBase)}/token/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      username: String(username || '').trim(),
      password: String(password || ''),
    }),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok || !data?.access || !data?.refresh) {
    throw new Error(formatApiError(data) || 'Login failed')
  }
  return setAuthState({
    access: data.access,
    refresh: data.refresh,
    username: String(username || '').trim(),
    loggedInAt: Date.now(),
  })
}

async function refreshStoredSession(apiBase) {
  await ensureApiAccess(apiBase, true)
  const auth = await getAuthState()
  if (!auth.refresh) {
    await clearAuthState()
    throw new Error('No refresh token found. Please login again.')
  }

  const response = await fetch(`${normalizeApiBase(apiBase)}/token/refresh/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh: auth.refresh }),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok || !data?.access) {
    await clearAuthState()
    throw new Error('Session expired. Please login again.')
  }

  return setAuthState({
    ...auth,
    access: data.access,
    refresh: String(data.refresh || auth.refresh || '').trim(),
    loggedInAt: auth.loggedInAt || Date.now(),
  })
}

async function apiFetch(path, options = {}) {
  const apiBase = normalizeApiBase(options.apiBase)
  await ensureApiAccess(apiBase, Boolean(options.interactivePermission))
  const url = `${apiBase}${path}`

  async function requestWithToken(tok) {
    const authHeaders = tok ? { Authorization: `Bearer ${tok}` } : {}
    const response = await fetch(url, {
      method: options.method || 'GET',
      headers: {
        ...authHeaders,
        ...(options.headers || {}),
      },
      ...(options.body !== undefined ? { body: options.body } : {}),
    })
    const data = await response.json().catch(() => ({}))
    return { response, data }
  }

  let auth = await getAuthState()
  let token = auth.access
  if (options.requireAuth && !token) throw new Error('Please login in extension')

  let { response, data } = await requestWithToken(token)
  const detail = formatApiError(data)

  const tokenInvalid = response.status === 401 && /token not valid|token is invalid|token is expired/i.test(detail)
  if (tokenInvalid) {
    try {
      auth = await refreshStoredSession(apiBase)
      token = auth.access
      if (token) {
        const retry = await requestWithToken(token)
        response = retry.response
        data = retry.data
      }
    } catch (err) {
      if (options.requireAuth) {
        throw err
      }
    }
  }

  if (response.status === 401 && options.requireAuth) {
    throw new Error('Session expired. Please login again.')
  }

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${formatApiError(data)}`)
  }
  return data
}

function authSummary(auth) {
  const safeAuth = auth || {}
  const hasAccess = Boolean(String(safeAuth.access || '').trim())
  return {
    loggedIn: hasAccess,
    username: String(safeAuth.username || '').trim(),
    loggedInAt: Number(safeAuth.loggedInAt || 0) || 0,
  }
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

  if (type === 'EXTENSION_ENSURE_API_ACCESS') {
    ensureApiAccess(msg?.apiBase, Boolean(msg?.interactive))
      .then((origin) => sendResponse({ ok: true, data: { origin } }))
      .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }))
    return true
  }

  if (type === 'EXTENSION_GET_AUTH_STATE') {
    getAuthState()
      .then((auth) => sendResponse({ ok: true, data: authSummary(auth) }))
      .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }))
    return true
  }

  if (type === 'EXTENSION_LOGIN') {
    loginWithCredentials(msg?.apiBase, msg?.username, msg?.password)
      .then((auth) => sendResponse({ ok: true, data: authSummary(auth) }))
      .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }))
    return true
  }

  if (type === 'EXTENSION_REFRESH_SESSION') {
    refreshStoredSession(msg?.apiBase)
      .then((auth) => sendResponse({ ok: true, data: authSummary(auth) }))
      .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }))
    return true
  }

  if (type === 'EXTENSION_LOGOUT') {
    clearAuthState()
      .then((auth) => sendResponse({ ok: true, data: authSummary(auth) }))
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

  if (type === 'EXTENSION_EXTRACT_JD') {
    extractFromActiveTab('EXTRACT_JD')
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }))
    return true
  }

  if (type === 'EXTENSION_EXTRACT_EMPLOYEE') {
    extractFromActiveTab('EXTRACT_EMPLOYEE')
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }))
    return true
  }

  if (type === 'EXTENSION_SAVE_JOB') {
    apiFetch('/extension/jobs/', {
      method: 'POST',
      requireAuth: true,
      interactivePermission: true,
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
      interactivePermission: true,
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
