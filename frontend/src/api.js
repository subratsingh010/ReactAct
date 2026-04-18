const API_BASE_URL = String(import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '')

function collectMessagesFromApiPayload(payload, bucket = []) {
  if (payload === null || payload === undefined) return bucket
  if (typeof payload === 'string' || typeof payload === 'number' || typeof payload === 'boolean') {
    const text = String(payload).trim()
    if (text) bucket.push(text)
    return bucket
  }
  if (Array.isArray(payload)) {
    payload.forEach((item) => collectMessagesFromApiPayload(item, bucket))
    return bucket
  }
  if (typeof payload === 'object') {
    for (const [key, value] of Object.entries(payload)) {
      if (key === 'warning' || key === 'warnings') continue
      if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
        const text = String(value).trim()
        if (text) bucket.push(`${key}: ${text}`)
      } else if (Array.isArray(value)) {
        value.forEach((item) => {
          const text = String(item ?? '').trim()
          if (text) bucket.push(`${key}: ${text}`)
        })
      } else {
        collectMessagesFromApiPayload(value, bucket)
      }
    }
    return bucket
  }
  return bucket
}

function extractWarningText(data) {
  if (!data || typeof data !== 'object') return ''
  const raw = data.warning ?? data.warnings ?? ''
  if (!raw) return ''
  if (typeof raw === 'string') return raw.trim()
  if (Array.isArray(raw)) return raw.map((x) => String(x ?? '').trim()).filter(Boolean).join(' | ')
  return String(raw).trim()
}

function buildApiErrorMessage(data) {
  if (data && typeof data === 'object') {
    const detail = String(data.detail || '').trim()
    if (detail) return detail
    const message = String(data.message || '').trim()
    if (message) return message
  }
  const messages = collectMessagesFromApiPayload(data, [])
  if (messages.length) return messages.join(' | ')
  return 'Request failed'
}

async function parseResponse(response) {
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    let message = buildApiErrorMessage(data)
    if (typeof message === 'string' && message.toLowerCase().includes('token not valid')) {
      message = 'Session expired. Please log in again.'
    }
    const warning = extractWarningText(data)
    if (warning) {
      message = `${message} | Warning: ${warning}`
    }
    throw new Error(message)
  }
  return data
}

function dispatchAuthChanged() {
  window.dispatchEvent(new Event('auth-changed'))
}

function clearTokens() {
  localStorage.removeItem('access')
  localStorage.removeItem('refresh')
  dispatchAuthChanged()
}

async function refreshAccessToken() {
  const refresh = localStorage.getItem('refresh')
  if (!refresh) return null

  const response = await fetch(`${API_BASE_URL}/token/refresh/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh }),
  })

  const data = await response.json().catch(() => ({}))
  if (!response.ok || !data.access) return null

  localStorage.setItem('access', data.access)
  dispatchAuthChanged()
  return data.access
}

async function authFetch(url, options = {}, accessToken) {
  const toNetworkError = (err) => {
    const msg = String(err?.message || '').trim()
    return new Error(msg || 'Network error. Please check API/server and try again.')
  }
  const makeHeaders = (token) => ({
    ...(options.headers || {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  })

  const token = accessToken || localStorage.getItem('access') || ''
  let first
  try {
    first = await fetch(url, { ...options, headers: makeHeaders(token) })
  } catch (err) {
    throw toNetworkError(err)
  }
  if (first.status !== 401) return first

  // Try refresh once, then retry.
  const nextAccess = await refreshAccessToken()
  if (!nextAccess) {
    clearTokens()
    return first
  }
  try {
    return await fetch(url, { ...options, headers: makeHeaders(nextAccess) })
  } catch (err) {
    throw toNetworkError(err)
  }
}

async function fetchAllPaginatedRows(fetchPage, params = {}) {
  const firstPage = await fetchPage({ ...params, page: 1 })
  const firstRows = Array.isArray(firstPage?.results) ? firstPage.results : []
  const totalPages = Math.max(1, Number(firstPage?.total_pages || 1))
  if (totalPages === 1) return firstRows

  const remainingPages = await Promise.all(
    Array.from({ length: totalPages - 1 }, (_, index) => fetchPage({ ...params, page: index + 2 })),
  )

  return remainingPages.reduce((allRows, pageData) => {
    const rows = Array.isArray(pageData?.results) ? pageData.results : []
    return allRows.concat(rows)
  }, [...firstRows])
}

export async function loginUser(username, password) {
  const response = await fetch(`${API_BASE_URL}/token/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  return parseResponse(response)
}

export async function signupUser(username, email, password) {
  const response = await fetch(`${API_BASE_URL}/signup/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, email, password }),
  })
  return parseResponse(response)
}

export async function fetchTrackingMailTest(accessToken, trackingId) {
  const response = await authFetch(`${API_BASE_URL}/tracking/${trackingId}/mail-test/`, {}, accessToken)
  return parseResponse(response)
}

export async function generateTrackingMailTest(accessToken, trackingId, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/tracking/${trackingId}/mail-test/`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'generate', ...(payload || {}) }),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function saveTrackingMailTest(accessToken, trackingId, previews) {
  const response = await authFetch(
    `${API_BASE_URL}/tracking/${trackingId}/mail-test/`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'save', previews }),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function parseResumePdf(file) {
  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(`${API_BASE_URL}/parse-resume/`, {
    method: 'POST',
    body: formData,
  })
  return parseResponse(response)
}

export async function fetchProfile(accessToken) {
  const response = await authFetch(`${API_BASE_URL}/profile/`, {}, accessToken)
  return parseResponse(response)
}

export async function fetchProfileConfig(accessToken) {
  const response = await authFetch(`${API_BASE_URL}/profile-config/`, {}, accessToken)
  return parseResponse(response)
}

export async function updateProfileConfig(accessToken, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/profile-config/`,
    {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload || {}),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function createResume(accessToken, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/resumes/`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function fetchResumes(accessToken) {
  const response = await authFetch(`${API_BASE_URL}/resumes/`, {}, accessToken)
  return parseResponse(response)
}

export async function fetchTailoredResumes(accessToken, params = {}) {
  const search = new URLSearchParams()
  if (params.job_id) search.set('job_id', String(params.job_id))
  if (params.q) search.set('q', String(params.q))
  const suffix = search.toString() ? `?${search.toString()}` : ''
  const response = await authFetch(`${API_BASE_URL}/tailored-resumes/${suffix}`, {}, accessToken)
  return parseResponse(response)
}

export async function createTailoredResume(accessToken, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/tailored-resumes/`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload || {}),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function fetchResume(accessToken, resumeId) {
  const response = await authFetch(`${API_BASE_URL}/resumes/${resumeId}/`, {}, accessToken)
  return parseResponse(response)
}

export async function updateResume(accessToken, resumeId, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/resumes/${resumeId}/`,
    {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function deleteResume(accessToken, resumeId) {
  const response = await authFetch(
    `${API_BASE_URL}/resumes/${resumeId}/`,
    { method: 'DELETE' },
    accessToken,
  )
  if (response.status === 204) return { ok: true }
  return parseResponse(response)
}

export async function fetchProfileInfo(accessToken) {
  const response = await authFetch(`${API_BASE_URL}/profile-info/`, {}, accessToken)
  return parseResponse(response)
}

export async function updateProfileInfo(accessToken, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/profile-info/`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function fetchProfilePanels(accessToken) {
  const response = await authFetch(`${API_BASE_URL}/profile-panels/`, {}, accessToken)
  return parseResponse(response)
}

export async function createProfilePanel(accessToken, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/profile-panels/`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function updateProfilePanel(accessToken, panelId, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/profile-panels/${panelId}/`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function deleteProfilePanel(accessToken, panelId) {
  const response = await authFetch(
    `${API_BASE_URL}/profile-panels/${panelId}/`,
    { method: 'DELETE' },
    accessToken,
  )
  if (response.status === 204) return { ok: true }
  return parseResponse(response)
}

export async function fetchWorkspaceMembers(accessToken) {
  const response = await authFetch(`${API_BASE_URL}/workspace-members/`, {}, accessToken)
  return parseResponse(response)
}

export async function createWorkspaceMember(accessToken, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/workspace-members/`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function deleteWorkspaceMember(accessToken, memberId) {
  const response = await authFetch(
    `${API_BASE_URL}/workspace-members/${memberId}/`,
    { method: 'DELETE' },
    accessToken,
  )
  if (response.status === 204) return { ok: true }
  return parseResponse(response)
}

export async function fetchAchievements(accessToken) {
  const response = await authFetch(`${API_BASE_URL}/achievements/`, {}, accessToken)
  return parseResponse(response)
}

export async function fetchTemplates(accessToken) {
  const response = await authFetch(`${API_BASE_URL}/templates/`, {}, accessToken)
  return parseResponse(response)
}

export async function createAchievement(accessToken, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/achievements/`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function createTemplate(accessToken, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/templates/`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function updateAchievement(accessToken, achievementId, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/achievements/${achievementId}/`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function updateTemplate(accessToken, templateId, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/templates/${templateId}/`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function deleteAchievement(accessToken, achievementId) {
  const response = await authFetch(
    `${API_BASE_URL}/achievements/${achievementId}/`,
    { method: 'DELETE' },
    accessToken,
  )
  if (response.status === 204) return { ok: true }
  return parseResponse(response)
}

export async function deleteTemplate(accessToken, templateId) {
  const response = await authFetch(
    `${API_BASE_URL}/templates/${templateId}/`,
    { method: 'DELETE' },
    accessToken,
  )
  if (response.status === 204) return { ok: true }
  return parseResponse(response)
}

export async function fetchInterviews(accessToken) {
  const response = await authFetch(`${API_BASE_URL}/interviews/`, {}, accessToken)
  return parseResponse(response)
}

export async function fetchLocations(accessToken) {
  const response = await authFetch(`${API_BASE_URL}/locations/`, {}, accessToken)
  return parseResponse(response)
}

export async function createInterview(accessToken, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/interviews/`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function updateInterview(accessToken, interviewId, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/interviews/${interviewId}/`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function deleteInterview(accessToken, interviewId) {
  const response = await authFetch(
    `${API_BASE_URL}/interviews/${interviewId}/`,
    { method: 'DELETE' },
    accessToken,
  )
  if (response.status === 204) return { ok: true }
  return parseResponse(response)
}

export async function tailorResume(accessToken, payload) {
  const isFormData = payload instanceof FormData
  const response = await authFetch(
    `${API_BASE_URL}/tailor-resume/`,
    {
      method: 'POST',
      ...(isFormData
        ? { body: payload }
        : {
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload || {}),
          }),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function optimizeResumeQuality(accessToken, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/optimize-resume-quality/`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload || {}),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function exportAtsPdfLocal(accessToken, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/export-ats-pdf-local/`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload || {}),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function fetchTrackingRows(accessToken, params = {}) {
  const search = new URLSearchParams()
  const keys = [
    'page',
    'page_size',
    'company_name',
    'job_id',
    'applied_date',
    'mailed',
    'last_action',
    'ordering',
  ]
  for (const key of keys) {
    const value = params[key]
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      search.set(key, String(value))
    }
  }
  const suffix = search.toString() ? `?${search.toString()}` : ''
  const response = await authFetch(`${API_BASE_URL}/tracking/${suffix}`, {}, accessToken)
  return parseResponse(response)
}

export async function fetchAllTrackingRows(accessToken, params = {}) {
  return fetchAllPaginatedRows(
    (nextParams) => fetchTrackingRows(accessToken, { page_size: 100, ...params, ...nextParams }),
    params,
  )
}

export async function createTrackingRow(accessToken, payload) {
  const isFormData = payload instanceof FormData
  const response = await authFetch(
    `${API_BASE_URL}/tracking/`,
    {
      method: 'POST',
      ...(isFormData
        ? { body: payload }
        : {
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload || {}),
          }),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function updateTrackingRow(accessToken, trackingId, payload) {
  const isFormData = payload instanceof FormData
  const response = await authFetch(
    `${API_BASE_URL}/tracking/${trackingId}/`,
    {
      method: 'PUT',
      ...(isFormData
        ? { body: payload }
        : {
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload || {}),
          }),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function deleteTrackingRow(accessToken, trackingId, options = {}) {
  const hard = Boolean(options?.hard)
  const suffix = hard ? '?delete_mode=hard' : ''
  const response = await authFetch(
    `${API_BASE_URL}/tracking/${trackingId}/${suffix}`,
    {
      method: 'DELETE',
    },
    accessToken,
  )
  if (response.status === 204) return { ok: true }
  return parseResponse(response)
}

export async function fetchTrackingRow(accessToken, trackingId) {
  const response = await authFetch(`${API_BASE_URL}/tracking/${trackingId}/`, {}, accessToken)
  return parseResponse(response)
}

export async function fetchCompanies(accessToken, params = {}) {
  const search = new URLSearchParams()
  if (params.page) search.set('page', String(params.page))
  if (params.page_size) search.set('page_size', String(params.page_size))
  if (params.scope) search.set('scope', String(params.scope))
  if (params.ready_for_tracking) search.set('ready_for_tracking', String(params.ready_for_tracking))
  const suffix = search.toString() ? `?${search.toString()}` : ''
  const response = await authFetch(`${API_BASE_URL}/companies/${suffix}`, {}, accessToken)
  return parseResponse(response)
}

export async function fetchAllCompanies(accessToken, params = {}) {
  return fetchAllPaginatedRows(
    (nextParams) => fetchCompanies(accessToken, { page_size: 100, ...params, ...nextParams }),
    params,
  )
}

export async function createCompany(accessToken, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/companies/`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function updateCompany(accessToken, companyId, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/companies/${companyId}/`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function deleteCompany(accessToken, companyId) {
  const response = await authFetch(
    `${API_BASE_URL}/companies/${companyId}/`,
    { method: 'DELETE' },
    accessToken,
  )
  if (response.status === 204) return { ok: true }
  return parseResponse(response)
}

export async function fetchEmployees(accessToken, companyId = '', options = {}) {
  const search = new URLSearchParams()
  if (companyId) search.set('company_id', String(companyId))
  if (options.scope) search.set('scope', String(options.scope))
  const suffix = search.toString() ? `?${search.toString()}` : ''
  const response = await authFetch(`${API_BASE_URL}/employees/${suffix}`, {}, accessToken)
  return parseResponse(response)
}

export async function createEmployee(accessToken, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/employees/`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function updateEmployee(accessToken, employeeId, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/employees/${employeeId}/`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function deleteEmployee(accessToken, employeeId) {
  const response = await authFetch(
    `${API_BASE_URL}/employees/${employeeId}/`,
    { method: 'DELETE' },
    accessToken,
  )
  if (response.status === 204) return { ok: true }
  return parseResponse(response)
}

export async function fetchJobs(accessToken, params = {}) {
  const search = new URLSearchParams()
  const keys = [
    'page',
    'page_size',
    'scope',
    'include_closed',
    'company_id',
    'company_name',
    'posting_date',
    'applied_date',
    'job_id',
    'role',
    'applied',
    'ordering',
  ]
  for (const key of keys) {
    const value = params[key]
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      search.set(key, String(value))
    }
  }
  const suffix = search.toString() ? `?${search.toString()}` : ''
  const response = await authFetch(`${API_BASE_URL}/jobs/${suffix}`, {}, accessToken)
  return parseResponse(response)
}

export async function fetchAllJobs(accessToken, params = {}) {
  return fetchAllPaginatedRows(
    (nextParams) => fetchJobs(accessToken, { page_size: 100, ...params, ...nextParams }),
    params,
  )
}

export async function createJob(accessToken, payload) {
  const isFormData = payload instanceof FormData
  const response = await authFetch(
    `${API_BASE_URL}/jobs/`,
    {
      method: 'POST',
      ...(isFormData
        ? { body: payload }
        : {
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {}),
          }),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function updateJob(accessToken, jobPk, payload) {
  const isFormData = payload instanceof FormData
  const response = await authFetch(
    `${API_BASE_URL}/jobs/${jobPk}/`,
    {
      method: 'PUT',
      ...(isFormData
        ? { body: payload }
        : {
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {}),
          }),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function deleteJob(accessToken, jobPk, options = {}) {
  const hard = Boolean(options?.hard)
  const suffix = hard ? '?delete_mode=hard' : ''
  const response = await authFetch(
    `${API_BASE_URL}/jobs/${jobPk}/${suffix}`,
    { method: 'DELETE' },
    accessToken,
  )
  if (response.status === 204) return { ok: true }
  return parseResponse(response)
}


export async function bulkUploadEmployees(accessToken, payloadOrFile, options = {}) {
  const isFile = Boolean(options?.isFile)
  const response = await authFetch(
    `${API_BASE_URL}/bulk-upload/employees/`,
    {
      method: 'POST',
      ...(isFile
        ? (() => {
            const formData = new FormData()
            formData.append('file', payloadOrFile)
            return { body: formData }
          })()
        : {
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payloadOrFile || {}),
          }),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function bulkUploadJobs(accessToken, payloadOrFile, options = {}) {
  const isFile = Boolean(options?.isFile)
  const response = await authFetch(
    `${API_BASE_URL}/bulk-upload/jobs/`,
    {
      method: 'POST',
      ...(isFile
        ? (() => {
            const formData = new FormData()
            formData.append('file', payloadOrFile)
            return { body: formData }
          })()
        : {
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payloadOrFile || {}),
          }),
    },
    accessToken,
  )
  return parseResponse(response)
}
