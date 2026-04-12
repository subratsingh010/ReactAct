const els = {
  apiBase: document.getElementById('apiBase'),
  companyName: document.getElementById('companyName'),
  jobTitle: document.getElementById('jobTitle'),
  jobId: document.getElementById('jobId'),
  jobUrl: document.getElementById('jobUrl'),
  jdText: document.getElementById('jdText'),
  resumeFile: document.getElementById('resumeFile'),
  predefinedAnswers: document.getElementById('predefinedAnswers'),
  useAi: document.getElementById('useAi'),
  questionsOut: document.getElementById('questionsOut'),
  status: document.getElementById('status'),
  fetchJdBtn: document.getElementById('fetchJdBtn'),
  tailorBtn: document.getElementById('tailorBtn'),
  scanQuestionsBtn: document.getElementById('scanQuestionsBtn'),
  autofillBtn: document.getElementById('autofillBtn'),
}

if (window.self !== window.top) {
  document.body.classList.add('embedded')
}

function setStatus(message, isError = false) {
  els.status.textContent = message || ''
  els.status.classList.toggle('error', Boolean(isError))
}

function normalizeBase(base) {
  const v = String(base || '').trim().replace(/\/+$/, '')
  return v || 'http://127.0.0.1:8000/api'
}

function parsePredefinedMap(raw) {
  const text = String(raw || '').trim()
  if (!text) return {}
  try {
    const parsed = JSON.parse(text)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    const out = {}
    Object.entries(parsed).forEach(([k, v]) => {
      if (!k) return
      out[String(k).trim()] = String(v ?? '').trim()
    })
    return out
  } catch {
    return {}
  }
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = String(reader.result || '')
      const base64 = result.includes(',') ? result.split(',')[1] : result
      resolve(base64)
    }
    reader.onerror = () => reject(new Error('Failed to read file'))
    reader.readAsDataURL(file)
  })
}

async function getActiveTab() {
  const stored = await new Promise((resolve) => {
    chrome.storage.local.get(['panelSourceTabId'], (v) => resolve(Number(v.panelSourceTabId || 0)))
  })
  if (stored > 0) {
    try {
      const tab = await chrome.tabs.get(stored)
      if (tab?.id) return tab
    } catch {
      // fallback to current active tab
    }
  }
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true })
  return tabs[0] || null
}

function detectJobPlatform(url) {
  const value = String(url || '').toLowerCase()
  if (!value) return ''
  if (value.includes('myworkdayjobs.com') || value.includes('/workday/')) return 'workday'
  if (value.includes('boards.greenhouse.io') || value.includes('/greenhouse/')) return 'greenhouse'
  if (value.includes('linkedin.com/jobs') || value.includes('linkedin.com/easy-apply')) return 'linkedin'
  return ''
}

async function sendToActiveTab(type, payload = {}) {
  const tab = await getActiveTab()
  if (!tab?.id) throw new Error('No active tab found')
  const response = await chrome.tabs.sendMessage(tab.id, { type, ...payload })
  return response || {}
}

async function apiFetch(url, options = {}) {
  const response = await fetch(url, options)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.detail || data.message || `Request failed (${response.status})`)
  }
  return data
}

async function fetchJdFromPage() {
  try {
    setStatus('Fetching JD from active page...')
    const result = await sendToActiveTab('EXTRACT_JD')
    const jd = String(result.jdText || '').trim()
    if (!jd) throw new Error('No JD text found on this page')
    els.jdText.value = jd
    if (!els.jobUrl.value.trim()) {
      const tab = await getActiveTab()
      els.jobUrl.value = tab?.url || ''
    }
    if (!els.jobTitle.value.trim()) els.jobTitle.value = String(result.jobTitle || '').trim()
    if (!els.companyName.value.trim()) els.companyName.value = String(result.companyName || '').trim()
    setStatus(`Fetched JD (${jd.length} chars)`)
    saveSettings()
  } catch (err) {
    setStatus(err.message || 'Failed to fetch JD', true)
  }
}

async function tailorResume() {
  const apiBase = normalizeBase(els.apiBase.value)
  const jdText = String(els.jdText.value || '').trim()
  const resumeFile = els.resumeFile.files?.[0]

  if (jdText.length < 40) return setStatus('Paste/fetch full JD (min 40 chars)', true)
  if (!resumeFile) return setStatus('Upload reference resume PDF', true)

  try {
    els.tailorBtn.disabled = true
    setStatus('Parsing resume PDF...')
    const parseFd = new FormData()
    parseFd.append('file', resumeFile)
    const parsed = await apiFetch(`${apiBase}/parse-resume/`, {
      method: 'POST',
      body: parseFd,
    })

    setStatus('Tailoring resume...')
    const fd = new FormData()
    fd.append('job_description', jdText)
    fd.append('job_role', String(els.jobTitle.value || '').trim())
    fd.append('company_name', String(els.companyName.value || '').trim())
    fd.append('job_title', String(els.jobTitle.value || '').trim())
    fd.append('job_id', String(els.jobId.value || '').trim())
    fd.append('job_url', String(els.jobUrl.value || '').trim())
    fd.append('builder_data', JSON.stringify(parsed || {}))
    fd.append('preview_only', 'true')
    fd.append('force_rewrite', 'true')
    fd.append('ai_model', 'gpt-4o')
    fd.append('tailor_mode', 'complete')

    const result = await apiFetch(`${apiBase}/tailor-resume/`, {
      method: 'POST',
      body: fd,
    })

    const score = Number(result?.match_score)
    const scoreText = Number.isFinite(score) ? `${Math.round(score * 100)}%` : 'n/a'
    setStatus(`Tailored successfully (match: ${scoreText})`)
  } catch (err) {
    setStatus(err.message || 'Tailor failed', true)
  } finally {
    els.tailorBtn.disabled = false
  }
}

async function scanQuestions() {
  try {
    setStatus('Scanning form questions...')
    const result = await sendToActiveTab('SCAN_FORM_QUESTIONS')
    const questions = Array.isArray(result.questions) ? result.questions : []
    els.questionsOut.value = questions.join('\n')
    setStatus(`Found ${questions.length} questions`)
  } catch (err) {
    setStatus(err.message || 'Failed to scan questions', true)
  }
}

async function autofillForm() {
  const apiBase = normalizeBase(els.apiBase.value)
  const useAi = Boolean(els.useAi.checked)
  const predefined = parsePredefinedMap(els.predefinedAnswers.value)
  const resumeFile = els.resumeFile.files?.[0]

  try {
    els.autofillBtn.disabled = true
    setStatus('Collecting page questions...')
    const scan = await sendToActiveTab('SCAN_FORM_QUESTIONS')
    const questions = Array.isArray(scan.questions) ? scan.questions : []
    const unanswered = questions.filter((q) => !predefined[q] && !predefined[q.toLowerCase()])

    let aiMap = {}
    if (useAi && unanswered.length) {
      setStatus(`Getting AI answers for ${unanswered.length} questions...`)
      const profileContext = String(els.jdText.value || '').trim().slice(0, 3000)
      const aiResp = await apiFetch(`${apiBase}/autofill-answers/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          questions: unanswered,
          profile_context: profileContext,
        }),
      })
      const rows = Array.isArray(aiResp.answers) ? aiResp.answers : []
      rows.forEach((row) => {
        const q = String(row?.question || '').trim()
        const a = String(row?.answer || '').trim()
        if (q && a) aiMap[q] = a
      })
    }

    const finalAnswers = { ...predefined, ...aiMap }

    let resumeFileData = null
    if (resumeFile) {
      const base64 = await readFileAsBase64(resumeFile)
      resumeFileData = {
        name: resumeFile.name,
        type: resumeFile.type || 'application/pdf',
        base64,
      }
    }

    setStatus('Filling form on page...')
    const fillResp = await sendToActiveTab('FILL_FORM', {
      answers: finalAnswers,
      resumeFile: resumeFileData,
    })
    setStatus(`Filled ${fillResp.filledCount || 0} fields`)
  } catch (err) {
    setStatus(err.message || 'Autofill failed', true)
  } finally {
    els.autofillBtn.disabled = false
  }
}

function loadSettings() {
  chrome.storage.local.get(
    ['apiBase', 'companyName', 'jobTitle', 'jobId', 'jobUrl', 'predefinedAnswers', 'useAi'],
    (saved) => {
      els.apiBase.value = saved.apiBase || els.apiBase.value
      els.companyName.value = saved.companyName || ''
      els.jobTitle.value = saved.jobTitle || ''
      els.jobId.value = saved.jobId || ''
      els.jobUrl.value = saved.jobUrl || ''
      els.predefinedAnswers.value = saved.predefinedAnswers || ''
      els.useAi.checked = saved.useAi !== false
    },
  )
}

function saveSettings() {
  chrome.storage.local.set({
    apiBase: normalizeBase(els.apiBase.value),
    companyName: String(els.companyName.value || '').trim(),
    jobTitle: String(els.jobTitle.value || '').trim(),
    jobId: String(els.jobId.value || '').trim(),
    jobUrl: String(els.jobUrl.value || '').trim(),
    predefinedAnswers: String(els.predefinedAnswers.value || ''),
    useAi: Boolean(els.useAi.checked),
  })
}

async function autoInitForJobPage() {
  try {
    const tab = await getActiveTab()
    const platform = detectJobPlatform(tab?.url || '')
    if (!platform) {
      setStatus('Open Workday/Greenhouse/LinkedIn job page for auto-fetch.')
      return
    }
    if (!els.jobUrl.value.trim()) els.jobUrl.value = String(tab?.url || '')
    setStatus(`Detected ${platform}. Auto-fetching JD...`)
    if (!els.jdText.value.trim()) {
      await fetchJdFromPage()
      return
    }
    setStatus(`Detected ${platform} page.`)
  } catch (err) {
    setStatus(err.message || 'Auto-detect failed', true)
  }
}

;[
  els.apiBase,
  els.companyName,
  els.jobTitle,
  els.jobId,
  els.jobUrl,
  els.predefinedAnswers,
  els.useAi,
].forEach((el) => el.addEventListener('change', saveSettings))

els.fetchJdBtn.addEventListener('click', fetchJdFromPage)
els.tailorBtn.addEventListener('click', tailorResume)
els.scanQuestionsBtn.addEventListener('click', scanQuestions)
els.autofillBtn.addEventListener('click', autofillForm)

loadSettings()
autoInitForJobPage()

function focusSection(hashValue) {
  const hash = String(hashValue || '').toLowerCase()
  if (hash === '#autofill') {
    document.getElementById('autofillSection')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    return
  }
  document.getElementById('tailorSection')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

setTimeout(() => {
  const urlHash = String(window.location.hash || '').toLowerCase()
  if (urlHash) {
    focusSection(urlHash)
    return
  }
  chrome.storage.local.get(['panelHash'], (saved) => {
    const panelHash = String(saved.panelHash || '').toLowerCase()
    focusSection(panelHash || '#tailor')
    chrome.storage.local.set({ panelHash: '' })
  })
}, 60)
