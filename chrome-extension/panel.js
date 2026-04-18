const els = {
  apiBase: document.getElementById('apiBase'),
  status: document.getElementById('status'),
  authStatus: document.getElementById('authStatus'),
  authState: document.getElementById('authState'),
  authUser: document.getElementById('authUser'),
  authUsername: document.getElementById('authUsername'),
  authPassword: document.getElementById('authPassword'),
  loginBtn: document.getElementById('loginBtn'),
  refreshSessionBtn: document.getElementById('refreshSessionBtn'),
  logoutBtn: document.getElementById('logoutBtn'),
  jobStatus: document.getElementById('jobStatus'),
  employeeStatus: document.getElementById('employeeStatus'),
  jobCompanyName: document.getElementById('jobCompanyName'),
  jobId: document.getElementById('jobId'),
  jobRole: document.getElementById('jobRole'),
  jobLocation: document.getElementById('jobLocation'),
  postedDate: document.getElementById('postedDate'),
  jobApplied: document.getElementById('jobApplied'),
  jobLink: document.getElementById('jobLink'),
  jdText: document.getElementById('jdText'),
  fetchFromPageBtn: document.getElementById('fetchFromPageBtn'),
  saveJobBtn: document.getElementById('saveJobBtn'),
  refreshBtn: document.getElementById('refreshBtn'),
  clearJobBtn: document.getElementById('clearJobBtn'),
  empName: document.getElementById('empName'),
  empDepartment: document.getElementById('empDepartment'),
  empLinkedin: document.getElementById('empLinkedin'),
  empRole: document.getElementById('empRole'),
  empAbout: document.getElementById('empAbout'),
  empFirst: document.getElementById('empFirst'),
  empMiddle: document.getElementById('empMiddle'),
  empLast: document.getElementById('empLast'),
  empContact: document.getElementById('empContact'),
  empEmail: document.getElementById('empEmail'),
  empCompanyName: document.getElementById('empCompanyName'),
  empLocation: document.getElementById('empLocation'),
  fetchEmployeeFromPageBtn: document.getElementById('fetchEmployeeFromPageBtn'),
  saveEmployeeBtn: document.getElementById('saveEmployeeBtn'),
  clearEmployeeBtn: document.getElementById('clearEmployeeBtn'),
}

const API_BASE_STORAGE_KEY = 'applypilot_api_base'
const META_CACHE_KEY = 'applypilot_form_meta_cache'
const META_CACHE_TTL_MS = 10 * 60 * 1000

function esc(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

function setStatus(msg, isError = false) {
  els.status.textContent = String(msg || '')
  els.status.style.color = isError ? '#bf1d3d' : '#2b5fcc'
}

function setJobStatus(msg, isError = false) {
  if (!els.jobStatus) return
  els.jobStatus.textContent = String(msg || '')
  els.jobStatus.style.color = isError ? '#bf1d3d' : '#2b5fcc'
}

function setAuthStatus(msg, isError = false) {
  if (!els.authStatus) return
  els.authStatus.textContent = String(msg || '')
  els.authStatus.style.color = isError ? '#bf1d3d' : '#2b5fcc'
}

function setEmployeeStatus(msg, isError = false) {
  if (!els.employeeStatus) return
  els.employeeStatus.textContent = String(msg || '')
  els.employeeStatus.style.color = isError ? '#bf1d3d' : '#2b5fcc'
}

function validateRequiredFields(fields) {
  for (const field of fields) {
    if (!field) continue
    if (!field.checkValidity()) {
      field.reportValidity()
      return false
    }
  }
  return true
}

function selectBestRoleOption(rawRole) {
  const role = String(rawRole || '').trim().toLowerCase()
  if (!role) return
  if (role.includes('fullstack') || role.includes('full stack')) {
    els.jobRole.value = 'Fullstack Engineer'
    return
  }
  if (role.includes('backend') || role.includes('back end')) {
    els.jobRole.value = 'Backend Engineer'
    return
  }
  if (role.includes('sr') || role.includes('senior')) {
    els.jobRole.value = 'Sr. Software Engineer'
    return
  }
  if (role.includes('software')) {
    els.jobRole.value = 'Software Engineer'
  }
}

function extMessage(payload) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(payload, (res) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message || 'Extension message failed'))
        return
      }
      if (!res?.ok) {
        reject(new Error(res?.error || 'Request failed'))
        return
      }
      resolve(res.data)
    })
  })
}

function chromeStorageGet(keys) {
  return new Promise((resolve) => chrome.storage.local.get(keys, resolve))
}

function chromeStorageSet(value) {
  return new Promise((resolve) => chrome.storage.local.set(value, resolve))
}

function renderAuthState(auth) {
  const loggedIn = Boolean(auth?.loggedIn)
  if (els.authState) {
    els.authState.textContent = loggedIn ? 'Logged in' : 'Logged out'
    els.authState.classList.toggle('is-logged-out', !loggedIn)
  }
  if (els.authUser) {
    const username = String(auth?.username || '').trim()
    els.authUser.textContent = username ? `User: ${username}` : ''
  }
  if (els.loginBtn) els.loginBtn.disabled = loggedIn
  if (els.authUsername) els.authUsername.disabled = loggedIn
  if (els.authPassword) els.authPassword.disabled = loggedIn
  if (els.refreshSessionBtn) els.refreshSessionBtn.disabled = !loggedIn
  if (els.logoutBtn) els.logoutBtn.disabled = !loggedIn
}

function normalizeLocationKey(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
}

function selectBestLocationOption(rawLocation) {
  const raw = String(rawLocation || '').trim()
  if (!raw || !els.jobLocation) return
  const options = Array.from(els.jobLocation.options || [])
  if (!options.length) return

  const rawKey = normalizeLocationKey(raw)
  if (!rawKey) return

  let best = options.find((opt) => normalizeLocationKey(opt.value) === rawKey)
  if (best) {
    els.jobLocation.value = best.value
    return
  }

  const tokens = rawKey.split(' ').filter(Boolean)
  const lastToken = tokens[tokens.length - 1] || ''
  best = options.find((opt) => {
    const key = normalizeLocationKey(opt.value)
    return rawKey.includes(key) || key.includes(rawKey) || (lastToken && key.includes(lastToken))
  })
  if (best) {
    els.jobLocation.value = best.value
  }
}

function selectLocationInDropdown(selectEl, rawLocation) {
  const raw = String(rawLocation || '').trim()
  if (!raw || !selectEl) return
  const options = Array.from(selectEl.options || [])
  if (!options.length) return

  const rawKey = normalizeLocationKey(raw)
  if (!rawKey) return

  let best = options.find((opt) => normalizeLocationKey(opt.value) === rawKey)
  if (!best) {
    const tokens = rawKey.split(' ').filter(Boolean)
    const lastToken = tokens[tokens.length - 1] || ''
    best = options.find((opt) => {
      const key = normalizeLocationKey(opt.value)
      return rawKey.includes(key) || key.includes(rawKey) || (lastToken && key.includes(lastToken))
    })
  }
  if (best) selectEl.value = best.value
}

function splitEmployeeName(fullName) {
  const parts = String(fullName || '').trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return { first: '', middle: '', last: '' }
  if (parts.length === 1) return { first: parts[0], middle: '', last: '' }
  if (parts.length === 2) return { first: parts[0], middle: '', last: parts[1] }
  return {
    first: parts[0],
    middle: parts.slice(1, -1).join(' '),
    last: parts[parts.length - 1],
  }
}

function selectEmployeeRole(rawRole) {
  const role = String(rawRole || '').trim().toLowerCase()
  if (!role) return

  const isSenior = role.includes('sr') || role.includes('senior')

  if (role.includes('talent acquisition')) {
    if (isSenior) {
      els.empRole.value = 'Sr. Talent Acquisition Specialist'
      return
    }
    els.empRole.value = 'Talent Acquisition Specialist'
    return
  }
  if (role.includes('talent sourc')) {
    els.empRole.value = 'Talent Sourcer'
    return
  }
  if (role.includes('hiring manager')) {
    els.empRole.value = 'Hiring Manager'
    return
  }
  if (role.includes('hr') || role.includes('recruit') || role.includes('talent')) {
    if (isSenior) {
      els.empRole.value = 'Sr. HR Recruiter'
      return
    }
    els.empRole.value = 'HR Recruiter'
    return
  }
  if (role.includes('team lead') || role.includes('tech lead')) {
    els.empRole.value = 'Team Lead'
    return
  }
  if (role.includes('manager')) {
    els.empRole.value = 'Manager'
    return
  }

  if (role.includes('fullstack') || role.includes('full stack')) {
    els.empRole.value = isSenior ? 'Sr. Fullstack Engineer' : 'Fullstack Engineer'
    return
  }
  if (role.includes('frontend') || role.includes('front end')) {
    els.empRole.value = isSenior ? 'Sr. Frontend Engineer' : 'Frontend Engineer'
    return
  }
  if (role.includes('backend') || role.includes('back end')) {
    els.empRole.value = isSenior ? 'Sr. Backend Engineer' : 'Backend Engineer'
    return
  }
  if (role.includes('software') || role.includes('engineer') || role.includes('developer') || role.includes('sde')) {
    els.empRole.value = isSenior ? 'Sr. Software Engineer' : 'Software Engineer'
  }
}

function selectEmployeeDepartment(rawDepartment, rawRole) {
  const dep = String(rawDepartment || '').toLowerCase()
  const role = String(rawRole || '').toLowerCase()
  if (dep.includes('hr') || dep.includes('human') || dep.includes('recruit') || role.includes('recruit') || role.includes('talent')) {
    els.empDepartment.value = 'HR'
    return
  }
  if (dep.includes('data') || role.includes('data analyst') || role.includes('data engineer')) {
    els.empDepartment.value = 'Data'
    return
  }
  if (dep.includes('product') || role.includes('product manager')) {
    els.empDepartment.value = 'Product'
    return
  }
  if (dep.includes('design') || role.includes('designer')) {
    els.empDepartment.value = 'Design'
    return
  }
  if (dep.includes('sales') || role.includes('sales')) {
    els.empDepartment.value = 'Sales'
    return
  }
  if (dep.includes('market') || role.includes('marketing')) {
    els.empDepartment.value = 'Marketing'
    return
  }
  if (dep.includes('finance') || role.includes('finance')) {
    els.empDepartment.value = 'Finance'
    return
  }
  if (dep.includes('support') || role.includes('support')) {
    els.empDepartment.value = 'Support'
    return
  }
  if (dep.includes('operation') || role.includes('operation')) {
    els.empDepartment.value = 'Operations'
    return
  }
  if (role.includes('software') || role.includes('sde') || role.includes('engineer') || role.includes('developer') || role.includes('lead') || role.includes('devops') || role.includes('qa')) {
    els.empDepartment.value = 'Engineering'
  }
}

function pickTopItHubLocations(locations, count = 8) {
  const ranked = ['Bengaluru', 'Hyderabad', 'Noida', 'Delhi', 'Pune', 'Mumbai', 'Chennai', 'Gurugram']
  const byKey = new Map(
    (Array.isArray(locations) ? locations : [])
      .map((x) => String(x || '').trim())
      .filter(Boolean)
      .map((name) => [normalizeLocationKey(name), name]),
  )
  const top = []
  for (const city of ranked) {
    const hit = byKey.get(normalizeLocationKey(city)) || city
    if (hit && !top.includes(hit)) top.push(hit)
    if (top.length >= count) break
  }
  if (top.length < count) {
    for (const name of byKey.values()) {
      if (!top.includes(name)) top.push(name)
      if (top.length >= count) break
    }
  }
  return top
}

async function loadMetaAndCompanies() {
  const apiBase = els.apiBase.value.trim()
  const stored = await chromeStorageGet([META_CACHE_KEY])
  const cache = stored?.[META_CACHE_KEY]
  const canUseCache = cache
    && cache.apiBase === apiBase
    && Number(cache.savedAt || 0) > (Date.now() - META_CACHE_TTL_MS)
    && cache.data
  const meta = canUseCache ? cache.data : await extMessage({ type: 'EXTENSION_GET_FORM_META', apiBase })

  if (!canUseCache) {
    await chromeStorageSet({
      [META_CACHE_KEY]: {
        apiBase,
        savedAt: Date.now(),
        data: meta,
      },
    })
  }

  const locations = Array.isArray(meta?.location_options) ? meta.location_options : []
  const locationNames = []
  for (const item of locations) {
    const value = String(item?.value || '').trim()
    const label = String(item?.label || value).trim()
    if (!value) continue
    locationNames.push(value)
  }

  const topItHubLocations = pickTopItHubLocations(locationNames, 8)
  const jobLocationOptions = ['<option value="">Select city</option>']
  for (const city of topItHubLocations) {
    jobLocationOptions.push(`<option value="${esc(city)}">${esc(city)}</option>`)
  }
  els.jobLocation.innerHTML = jobLocationOptions.join('')

  const empLocations = topItHubLocations
  const empLocationOptions = ['<option value="">Select city</option>']
  for (const city of empLocations) {
    empLocationOptions.push(`<option value="${esc(city)}">${esc(city)}</option>`)
  }
  els.empLocation.innerHTML = empLocationOptions.join('')
}

function clearJobFields() {
  els.jobCompanyName.value = ''
  els.jobId.value = ''
  els.jobRole.value = ''
  els.jobLocation.value = ''
  els.postedDate.value = ''
  els.jobApplied.value = 'no'
  els.jobLink.value = ''
  els.jdText.value = ''
  setJobStatus('Job fields cleared')
}

async function refreshPanel() {
  await chromeStorageSet({ [META_CACHE_KEY]: null })
  await loadMetaAndCompanies()
  setStatus('Refreshed form data')
}

async function loadAuthState() {
  const apiBase = els.apiBase.value.trim()
  const auth = await extMessage({ type: 'EXTENSION_GET_AUTH_STATE', apiBase })
  renderAuthState(auth)
  return auth
}

async function loginExtension() {
  const username = String(els.authUsername?.value || '').trim()
  const password = String(els.authPassword?.value || '')
  if (!username) {
    setAuthStatus('Enter username.', true)
    els.authUsername?.focus()
    return
  }
  if (!password) {
    setAuthStatus('Enter password.', true)
    els.authPassword?.focus()
    return
  }

  const apiBase = els.apiBase.value.trim()
  const auth = await extMessage({
    type: 'EXTENSION_LOGIN',
    apiBase,
    username,
    password,
  })
  if (els.authPassword) els.authPassword.value = ''
  renderAuthState(auth)
  await loadMetaAndCompanies()
  setAuthStatus('Extension login successful.')
}

async function refreshSession() {
  const apiBase = els.apiBase.value.trim()
  const auth = await extMessage({ type: 'EXTENSION_REFRESH_SESSION', apiBase })
  renderAuthState(auth)
  setAuthStatus('Session refreshed.')
}

async function logoutExtension() {
  const apiBase = els.apiBase.value.trim()
  const auth = await extMessage({ type: 'EXTENSION_LOGOUT', apiBase })
  renderAuthState(auth)
  if (els.authPassword) els.authPassword.value = ''
  setAuthStatus('Logged out.')
}

function clearEmployeeFields() {
  els.empName.value = ''
  els.empDepartment.value = 'HR'
  els.empLinkedin.value = ''
  els.empRole.value = ''
  els.empAbout.value = ''
  els.empFirst.value = ''
  els.empMiddle.value = ''
  els.empLast.value = ''
  els.empContact.value = ''
  els.empEmail.value = ''
  els.empCompanyName.value = ''
  els.empLocation.value = ''
  setEmployeeStatus('Employee fields cleared')
}

async function fetchFromPage() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  const res = await chrome.tabs.sendMessage(tab.id, { type: 'EXTRACT_JD' })
  if (res?.jdText) els.jdText.value = res.jdText
  if (res?.jobUrl) els.jobLink.value = res.jobUrl
  if (res?.jobId) els.jobId.value = res.jobId
  if (res?.jobTitle) selectBestRoleOption(res.jobTitle)
  if (res?.companyName) els.jobCompanyName.value = res.companyName
  if (res?.location) selectBestLocationOption(res.location)

  if (res?.postedDateIso) {
    els.postedDate.value = res.postedDateIso
  }
  setJobStatus('Fetched from page')
}

async function saveJob() {
  const valid = validateRequiredFields([
    els.jobCompanyName,
    els.jobRole,
    els.jobLocation,
    els.jobLink,
  ])
  if (!valid) return

  const apiBase = els.apiBase.value.trim()
  const payload = {
    company_name: els.jobCompanyName.value.trim(),
    job_id: els.jobId.value.trim(),
    role: els.jobRole.value.trim(),
    location: els.jobLocation.value.trim(),
    posted_date: els.postedDate.value,
    applied: els.jobApplied.value,
    job_link: els.jobLink.value.trim(),
    jd: els.jdText.value.trim(),
  }
  await extMessage({ type: 'EXTENSION_SAVE_JOB', apiBase, payload })
  setJobStatus('Saved')
}

async function saveEmployee() {
  const valid = validateRequiredFields([
    els.empLinkedin,
    els.empAbout,
    els.empRole,
    els.empDepartment,
    els.empLocation,
    els.empName,
    els.empCompanyName,
  ])
  if (!valid) return

  const apiBase = els.apiBase.value.trim()
  const payload = {
    name: els.empName.value.trim(),
    first_name: els.empFirst.value.trim(),
    middle_name: els.empMiddle.value.trim(),
    last_name: els.empLast.value.trim(),
    department: els.empDepartment.value,
    linkedin_url: els.empLinkedin.value.trim(),
    company_name: els.empCompanyName.value.trim(),
    role: els.empRole.value.trim(),
    about: els.empAbout.value.trim(),
    location: els.empLocation.value.trim(),
    contact_number: els.empContact.value.trim(),
    email: els.empEmail.value.trim(),
  }
  await extMessage({ type: 'EXTENSION_SAVE_EMPLOYEE', apiBase, payload })
  setEmployeeStatus('Saved')
}

async function fetchEmployeeFromPage() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  const res = await chrome.tabs.sendMessage(tab.id, { type: 'EXTRACT_EMPLOYEE' })
  const hasAnyData = Boolean(
    String(res?.name || '').trim() ||
    String(res?.linkedinUrl || '').trim() ||
    String(res?.companyName || '').trim() ||
    String(res?.role || '').trim() ||
    String(res?.location || '').trim(),
  )
  if (!hasAnyData) {
    setEmployeeStatus('Could not extract employee data from this page.', true)
    return
  }

  if (res?.name) {
    els.empName.value = res.name
    const name = splitEmployeeName(res.name)
    if (!els.empFirst.value) els.empFirst.value = name.first
    if (!els.empMiddle.value) els.empMiddle.value = name.middle
    if (!els.empLast.value) els.empLast.value = name.last
  }
  if (res?.linkedinUrl) els.empLinkedin.value = res.linkedinUrl
  if (res?.companyName) els.empCompanyName.value = res.companyName
  if (res?.about) els.empAbout.value = res.about
  if (res?.role) selectEmployeeRole(res.role)
  selectEmployeeDepartment(res?.department, res?.role)
  if (res?.location) selectLocationInDropdown(els.empLocation, res.location)

  setEmployeeStatus('Employee data fetched from page')
}

els.fetchFromPageBtn.addEventListener('click', () => fetchFromPage().catch((err) => setJobStatus(String(err?.message || err || 'Error'), true)))
els.saveJobBtn.addEventListener('click', () => saveJob().catch((err) => setJobStatus(String(err?.message || err || 'Error'), true)))
els.refreshBtn.addEventListener('click', () => refreshPanel().catch((err) => setStatus(err.message, true)))
els.clearJobBtn.addEventListener('click', () => clearJobFields())
els.loginBtn.addEventListener('click', () => loginExtension().catch((err) => setAuthStatus(String(err?.message || err || 'Error'), true)))
els.refreshSessionBtn.addEventListener('click', () => refreshSession().catch((err) => {
  renderAuthState({ loggedIn: false, username: '' })
  setAuthStatus(String(err?.message || err || 'Error'), true)
}))
els.logoutBtn.addEventListener('click', () => logoutExtension().catch((err) => setAuthStatus(String(err?.message || err || 'Error'), true)))
els.fetchEmployeeFromPageBtn.addEventListener('click', () => fetchEmployeeFromPage().catch((err) => setEmployeeStatus(String(err?.message || err || 'Error'), true)))
els.saveEmployeeBtn.addEventListener('click', () => saveEmployee().catch((err) => setEmployeeStatus(String(err?.message || err || 'Error'), true)))
els.clearEmployeeBtn.addEventListener('click', () => clearEmployeeFields())

els.apiBase.addEventListener('change', async () => {
  const value = String(els.apiBase.value || '').trim()
  await chromeStorageSet({ [API_BASE_STORAGE_KEY]: value, [META_CACHE_KEY]: null })
})

;(async () => {
  const stored = await chromeStorageGet([API_BASE_STORAGE_KEY])
  const savedApiBase = String(stored?.[API_BASE_STORAGE_KEY] || '').trim()
  if (savedApiBase) els.apiBase.value = savedApiBase
  await loadAuthState()
  await loadMetaAndCompanies()
  setStatus('Ready')
})().catch((err) => setStatus(err.message, true))
