const API_BASE_URL = 'http://127.0.0.1:8000/api'

async function parseResponse(response) {
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    let message = data.detail || data.message || 'Request failed'
    if (typeof message === 'string' && message.toLowerCase().includes('token not valid')) {
      message = 'Session expired. Please log in again.'
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
  const makeHeaders = (token) => ({
    ...(options.headers || {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  })

  const token = accessToken || localStorage.getItem('access') || ''
  const first = await fetch(url, { ...options, headers: makeHeaders(token) })
  if (first.status !== 401) return first

  // Try refresh once, then retry.
  const nextAccess = await refreshAccessToken()
  if (!nextAccess) {
    clearTokens()
    return first
  }
  return fetch(url, { ...options, headers: makeHeaders(nextAccess) })
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

export async function createJobRole(accessToken, payload) {
  const response = await authFetch(
    `${API_BASE_URL}/job-roles/`,
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

export async function runAnalysis(accessToken, resumeId, jobRoleId, keywords, profiles, profileKeywords) {
  const response = await authFetch(
    `${API_BASE_URL}/run-analysis/`,
    {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      resume_id: resumeId,
      job_role_id: jobRoleId || null,
      keywords,
      profiles: profiles || [],
      profile_keywords: profileKeywords || null,
    }),
    },
    accessToken,
  )
  return parseResponse(response)
}

export async function fetchAnalyses(accessToken, resumeId) {
  const url = resumeId ? `${API_BASE_URL}/analyses/?resume_id=${encodeURIComponent(resumeId)}` : `${API_BASE_URL}/analyses/`
  const response = await authFetch(url, {}, accessToken)
  return parseResponse(response)
}

export async function fetchResumes(accessToken) {
  const response = await authFetch(`${API_BASE_URL}/resumes/`, {}, accessToken)
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
