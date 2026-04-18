import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import RichTextarea from '../components/RichTextarea'
import ResumeSheet from '../components/ResumeSheet'
import { SingleSelectDropdown } from '../components/SearchableDropdown'
import {
  createTailoredResume,
  createResume,
  exportAtsPdfLocal,
  fetchAllJobs,
  fetchResume,
  fetchResumes,
  optimizeResumeQuality,
  parseResumePdf,
  tailorResume,
  updateResume,
} from '../api'
import { buildAtsPdfHtmlPreserveHighlights, printAtsPdf } from '../utils/resumeExport'
import {
  DEFAULT_PAGE_MARGIN_IN,
  MIN_PAGE_MARGIN_IN,
  normalizePageMarginIn,
} from '../utils/resumeShared'

const FONT_FAMILY_OPTIONS = [
  { label: 'Default', value: 'Arial, Helvetica, sans-serif' },
  { label: 'Arial', value: 'Arial, Helvetica, sans-serif' },
  { label: 'Calibri', value: 'Calibri, Arial, sans-serif' },
  { label: 'Cambria', value: 'Cambria, Georgia, serif' },
  { label: 'Georgia', value: 'Georgia, serif' },
  { label: 'Garamond', value: 'Garamond, Georgia, serif' },
  { label: 'Times New Roman', value: '"Times New Roman", Times, serif' },
  { label: 'Verdana', value: 'Verdana, Geneva, sans-serif' },
  { label: 'Tahoma', value: 'Tahoma, Geneva, sans-serif' },
]

const AI_MODEL_OPTIONS = [
  { label: 'GPT-4o (Default)', value: 'gpt-4o' },
  { label: 'GPT-5.4', value: 'gpt-5.4' },
  { label: 'GPT-5.4 Mini', value: 'gpt-5.4-mini' },
  { label: 'GPT-5.2', value: 'gpt-5.2' },
  { label: 'GPT-5 Nano', value: 'gpt-5-nano' },
  { label: 'O1', value: 'o1' },
]

const TAILOR_MODE_OPTIONS = [
  { label: 'Partial (Skills only)', value: 'partial' },
  { label: 'Almost Complete (Summary + Experience)', value: 'summary_experience' },
  { label: 'Complete (Summary + Experience + Projects)', value: 'complete' },
]

function plainTextFromHtml(value) {
  return String(value || '')
    .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, ' ')
    .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/\s+/g, ' ')
    .trim()
}

function formToPlainText(form) {
  const f = form || {}
  const parts = []
  ;[f.fullName, f.location, f.phone, f.email].forEach((v) => {
    const s = String(v || '').trim()
    if (s) parts.push(s)
  })

  const summary = plainTextFromHtml(f.summary || '')
  if (summary) parts.push(summary)

  const skills = plainTextFromHtml(f.skills || '')
  if (skills) parts.push(skills)

  ;(f.experiences || []).forEach((exp) => {
    const head = [exp.company, exp.title, exp.startDate, exp.isCurrent ? 'Present' : exp.endDate]
      .map((v) => String(v || '').trim())
      .filter(Boolean)
      .join(' | ')
    if (head) parts.push(head)
    const highlights = plainTextFromHtml(exp.highlights || '')
    if (highlights) parts.push(highlights)
  })

  ;(f.projects || []).forEach((proj) => {
    const head = [proj.name, proj.url].map((v) => String(v || '').trim()).filter(Boolean).join(' | ')
    if (head) parts.push(head)
    const highlights = plainTextFromHtml(proj.highlights || '')
    if (highlights) parts.push(highlights)
  })

  ;(f.educations || []).forEach((edu) => {
    const head = [edu.institution, edu.program].map((v) => String(v || '').trim()).filter(Boolean).join(' | ')
    if (head) parts.push(head)
    const dates = [edu.startDate, edu.isCurrent ? 'Present' : edu.endDate]
      .map((v) => String(v || '').trim())
      .filter(Boolean)
      .join(' – ')
    if (dates) parts.push(dates)
  })

  return parts.join('\n')
}

function cloneBuilderData(value) {
  try {
    return JSON.parse(JSON.stringify(value || {}))
  } catch {
    return {}
  }
}

function hasBuilderSubstance(builder) {
  const data = builder && typeof builder === 'object' ? builder : {}
  const hasTop = ['fullName', 'email', 'phone', 'location', 'summary', 'skills', 'role']
    .some((k) => String(data[k] || '').trim())
  const hasExp = Array.isArray(data.experiences) && data.experiences.some((exp) => {
    const company = String(exp?.company || '').trim()
    const title = String(exp?.title || '').trim()
    const highlights = plainTextFromHtml(exp?.highlights || '')
    return Boolean(company || title || highlights)
  })
  const hasProj = Array.isArray(data.projects) && data.projects.some((proj) => {
    const name = String(proj?.name || '').trim()
    const highlights = plainTextFromHtml(proj?.highlights || '')
    return Boolean(name || highlights)
  })
  return hasTop || hasExp || hasProj
}

function parseToYearMonth(value, { isEnd }) {
  const raw = String(value || '').trim()
  if (!raw) return null

  // Accept: "2025-03"
  const ym = raw.match(/^(\d{4})-(\d{1,2})$/)
  if (ym) {
    const year = Number(ym[1])
    const month = Math.max(1, Math.min(12, Number(ym[2])))
    return { year, month }
  }

  // Accept: "2025"
  const y = raw.match(/^(\d{4})$/)
  if (y) {
    const year = Number(y[1])
    const month = isEnd ? 12 : 1
    return { year, month }
  }

  // Accept: "Mar 2025"
  const parts = raw.replace(/\s+/g, ' ').split(' ')
  if (parts.length >= 2) {
    const maybeMonth = parseMonth(parts[0])
    const maybeYear = parts.find((p) => /^\d{4}$/.test(p))
    if (maybeMonth && maybeYear) return { year: Number(maybeYear), month: maybeMonth }
  }

  // Fallback: find a year
  const anyYear = raw.match(/\b(\d{4})\b/)
  if (anyYear) {
    return { year: Number(anyYear[1]), month: isEnd ? 12 : 1 }
  }

  return null
}

function yearMonthToIndex({ year, month }) {
  return year * 12 + (month - 1)
}

function computeExperienceYears(experiences) {
  const now = new Date()
  const nowYm = { year: now.getFullYear(), month: now.getMonth() + 1 }

  const exps = Array.isArray(experiences) ? experiences : []
  const starts = []
  const ends = []

  exps.forEach((exp) => {
    const startYm = parseToYearMonth(exp?.startDate, { isEnd: false })
    if (startYm) starts.push(yearMonthToIndex(startYm))

    let endYm = null
    if (exp?.isCurrent) {
      endYm = nowYm
    } else {
      endYm = parseToYearMonth(exp?.endDate, { isEnd: true }) || startYm
    }
    if (endYm) ends.push(yearMonthToIndex(endYm))
  })

  if (!starts.length || !ends.length) return 0

  const minStart = Math.min(...starts)
  const maxEnd = Math.max(...ends)
  const totalMonths = Math.max(0, maxEnd - minStart)

  let years = Math.floor(totalMonths / 12)
  const remainingMonths = totalMonths % 12

  // Your rule: only round up if remaining months > 5 (2.4y/2.5y => 2, else +1)
  if (remainingMonths > 5) years += 1
  return Math.max(0, years)
}

function makeAutoTitle(fullName, years) {
  const raw = String(fullName || '').trim().replace(/\s+/g, ' ')
  const base = raw || 'Resume'
  // Keep the visible name (casing/spaces) but strip odd characters.
  const visible = base.replace(/[^a-zA-Z0-9 ]/g, '').replace(/\s+/g, ' ').trim() || 'Resume'
  const y = Number.isFinite(years) ? years : 0
  if (y <= 0) return visible
  return `${visible} ${y} YOE`
}

function parseMonth(value) {
  const v = String(value || '').trim().toLowerCase()
  const map = {
    jan: 1,
    january: 1,
    feb: 2,
    february: 2,
    mar: 3,
    march: 3,
    apr: 4,
    april: 4,
    may: 5,
    jun: 6,
    june: 6,
    jul: 7,
    july: 7,
    aug: 8,
    august: 8,
    sep: 9,
    sept: 9,
    september: 9,
    oct: 10,
    october: 10,
    nov: 11,
    november: 11,
    dec: 12,
    december: 12,
  }
  return map[v] || null
}

function ResumeBuilderPage({
  pageTitle = 'Resume Workspace',
  subtitle = 'Edit on the left. Preview on the right.',
  importSessionKey = 'builderImport',
  resumeIdSessionKey = 'builderResumeId',
  showJdBox = false,
  jdSessionKey = 'builderJdText',
  enableTailorFlow = false,
  minimalTailorUi = false,
  referenceBuilderSessionKey = 'builderReferenceBuilder',
  referenceResumeIdSessionKey = 'builderReferenceResumeId',
  aiModelSessionKey = 'builderAiModel',
  tailorModeSessionKey = 'builderTailorMode',
  showSaveButton = true,
  disableAutoLoadDefaultResume = false,
}) {
  const navigate = useNavigate()
  const [form, setForm] = useState({
    resumeTitle: 'My Resume',
    fullName: '',
    role: '',
    email: '',
    phone: '',
    location: '',
    links: [],
    summaryEnabled: false,
    summaryHeading: 'Summary',
    summaryStyle: 'auto',
    bodyFontFamily: 'Arial, Helvetica, sans-serif',
    bodyFontSizePt: 10,
    bodyLineHeight: 1,
    pageMarginIn: DEFAULT_PAGE_MARGIN_IN,
    sectionOrder: ['summary', 'skills', 'experience', 'projects', 'education'],
    sectionUnderline: true,
    compactSpacing: true,
    isDefaultResume: false,
    customSections: [],
    summary: '',
    skills: '',
    experiences: [
      {
        company: '',
        title: '',
        startDate: '',
        endDate: '',
        isCurrent: true,
        highlights: '<ul><li>Write 3+ bullets. Add numbers where possible.</li></ul>',
      },
    ],
    projects: [
      {
        name: '',
        url: '',
        highlights: '<ul><li>Add 2-3 bullet points about what you built.</li></ul>',
      },
    ],
    educations: [
      {
        institution: '',
        program: '',
        scoreEnabled: false,
        scoreType: 'cgpa',
        scoreValue: '',
        scoreLabel: '',
        startDate: '',
        endDate: '',
        isCurrent: false,
      },
    ],
  })
  const [resumeRecordId, setResumeRecordId] = useState(() => sessionStorage.getItem(resumeIdSessionKey))
  const [resumeJobId, setResumeJobId] = useState('')
  const [saveMode, setSaveMode] = useState(() => (sessionStorage.getItem('builderSaveMode') === 'edit' ? 'edit' : 'create'))
  const [saveTarget, setSaveTarget] = useState('base')
  const [allowBaseResumeSave, setAllowBaseResumeSave] = useState(false)
  const [tailoredSourceResumeId, setTailoredSourceResumeId] = useState('')
  const [saveState, setSaveState] = useState({ saving: false, message: '' })
  const [pdfSaveState, setPdfSaveState] = useState({ saving: false, message: '' })
  const [importState, setImportState] = useState({ importing: false, message: '' })
  const [jobDescription, setJobDescription] = useState(() => sessionStorage.getItem(jdSessionKey) || '')
  const [aiModel, setAiModel] = useState(() => sessionStorage.getItem(aiModelSessionKey) || 'gpt-4o')
  const [tailorMode, setTailorMode] = useState(() => sessionStorage.getItem(tailorModeSessionKey) || 'partial')
  const [tailorState, setTailorState] = useState({
    loading: false,
    mode: '',
    message: '',
    error: '',
    keywords: [],
    matchScore: null,
  })
  const [activeTailorAction, setActiveTailorAction] = useState('')
  const [tailoredModal, setTailoredModal] = useState({
    open: false,
    name: '',
    jobId: '',
    loading: false,
    jobs: [],
  })
  const [saveModal, setSaveModal] = useState({
    open: false,
    name: '',
    jobId: '',
    loading: false,
    jobs: [],
  })
  const [tailorReferenceBuilder, setTailorReferenceBuilder] = useState(() => {
    if (!enableTailorFlow) return null
    try {
      const raw = sessionStorage.getItem(referenceBuilderSessionKey)
      if (!raw) return null
      const parsed = JSON.parse(raw)
      return parsed && typeof parsed === 'object' ? parsed : null
    } catch {
      return null
    }
  })
  const [tailorReferenceResumeId, setTailorReferenceResumeId] = useState(() => {
    if (!enableTailorFlow) return ''
    return sessionStorage.getItem(referenceResumeIdSessionKey) || localStorage.getItem('jobApplicationReferenceResumeId') || ''
  })
  const pdfInputRef = useRef(null)
  const tailorReferenceLoaded = enableTailorFlow
    ? hasBuilderSubstance(tailorReferenceBuilder || form)
    : hasBuilderSubstance(form)

  useEffect(() => {
    if (!enableTailorFlow) return
    if (tailorReferenceBuilder && typeof tailorReferenceBuilder === 'object') {
      sessionStorage.setItem(referenceBuilderSessionKey, JSON.stringify(tailorReferenceBuilder))
    } else {
      sessionStorage.removeItem(referenceBuilderSessionKey)
    }
  }, [enableTailorFlow, referenceBuilderSessionKey, tailorReferenceBuilder])

  useEffect(() => {
    if (!enableTailorFlow) return
    if (String(tailorReferenceResumeId || '').trim()) {
      sessionStorage.setItem(referenceResumeIdSessionKey, String(tailorReferenceResumeId))
    } else {
      sessionStorage.removeItem(referenceResumeIdSessionKey)
    }
  }, [enableTailorFlow, referenceResumeIdSessionKey, tailorReferenceResumeId])

  useEffect(() => {
    if (!enableTailorFlow) return
    const preferredId = localStorage.getItem('jobApplicationReferenceResumeId') || ''
    if (!preferredId || tailorReferenceBuilder || String(tailorReferenceResumeId || '').trim()) return

    let cancelled = false
    const access = localStorage.getItem('access')
    if (!access) return undefined

    const loadPreferredReference = async () => {
      try {
        const full = await fetchResume(access, preferredId)
        if (cancelled) return
        if (hasBuilderSubstance(full?.builder_data || {})) {
          setTailorReferenceBuilder(cloneBuilderData(full.builder_data || {}))
          setTailorReferenceResumeId(String(full.id))
        }
      } catch {
        // ignore
      }
    }

    loadPreferredReference()
    return () => {
      cancelled = true
    }
  }, [enableTailorFlow, tailorReferenceBuilder, tailorReferenceResumeId])

  useEffect(() => {
    if (!showJdBox) return
    const text = String(jobDescription || '')
    if (text.trim()) {
      sessionStorage.setItem(jdSessionKey, text)
      return
    }
    sessionStorage.removeItem(jdSessionKey)
  }, [jobDescription, jdSessionKey, showJdBox])

  useEffect(() => {
    if (!showJdBox) return
    const value = String(aiModel || '').trim() || 'gpt-4o'
    sessionStorage.setItem(aiModelSessionKey, value)
  }, [aiModel, aiModelSessionKey, showJdBox])

  useEffect(() => {
    if (!showJdBox) return
    const value = String(tailorMode || '').trim() || 'partial'
    sessionStorage.setItem(tailorModeSessionKey, value)
  }, [showJdBox, tailorMode, tailorModeSessionKey])

  useEffect(() => {
    sessionStorage.setItem('builderSaveMode', saveMode)
  }, [saveMode])

  useEffect(() => {
    const raw = sessionStorage.getItem(importSessionKey)
    if (raw) {
      try {
        const imported = JSON.parse(raw)
        if (imported && typeof imported === 'object') {
          setForm((prev) => ({
            ...prev,
            ...imported,
            pageMarginIn: normalizePageMarginIn(imported.pageMarginIn ?? prev.pageMarginIn),
            sectionUnderline: true,
          }))
          setResumeJobId('')
          if (enableTailorFlow && hasBuilderSubstance(imported) && !tailorReferenceBuilder) {
            setTailorReferenceBuilder(cloneBuilderData(imported))
            setTailorReferenceResumeId('')
          }
        }
      } catch {
        // ignore
      }
      sessionStorage.removeItem(importSessionKey)
    }

    const id = sessionStorage.getItem(resumeIdSessionKey)
    if (id) setResumeRecordId(id)
  }, [enableTailorFlow, importSessionKey, resumeIdSessionKey, tailorReferenceBuilder])

  useEffect(() => {
    if (disableAutoLoadDefaultResume) return
    let cancelled = false

    const loadDefaultFromList = async (access) => {
      const resumes = await fetchResumes(access)
      const defaultResume = Array.isArray(resumes) ? resumes.find((item) => item.is_default) : null
      if (!defaultResume) return
      const full = await fetchResume(access, defaultResume.id)
      if (cancelled) return
      setForm((prev) => ({
        ...prev,
        ...(full.builder_data || {}),
        pageMarginIn: normalizePageMarginIn(full.builder_data?.pageMarginIn ?? prev.pageMarginIn),
        sectionUnderline: true,
        isDefaultResume: Boolean(full.is_default),
      }))
      setResumeRecordId(String(full.id))
      setResumeJobId(full?.job ? String(full.job) : '')
      setSaveTarget(full?.is_tailored ? 'tailored' : 'base')
      sessionStorage.setItem(resumeIdSessionKey, String(full.id))
      if (enableTailorFlow && !tailorReferenceBuilder && hasBuilderSubstance(full.builder_data || {})) {
        setTailorReferenceBuilder(cloneBuilderData(full.builder_data || {}))
        setTailorReferenceResumeId(String(full.id))
      }
    }

    const hydrateDefaultResume = async () => {
      const access = localStorage.getItem('access')
      if (!access) return

      const storedId = sessionStorage.getItem(resumeIdSessionKey)
      if (storedId) {
        try {
          const full = await fetchResume(access, storedId)
          if (cancelled) return
          setForm((prev) => ({
            ...prev,
            ...(full.builder_data || {}),
            pageMarginIn: normalizePageMarginIn(full.builder_data?.pageMarginIn ?? prev.pageMarginIn),
            sectionUnderline: true,
            isDefaultResume: Boolean(full.is_default),
          }))
          setResumeRecordId(String(full.id))
          setResumeJobId(full?.job ? String(full.job) : '')
          setSaveTarget(full?.is_tailored ? 'tailored' : 'base')
          setSaveMode('edit')
          // Stored resume was loaded successfully; do not override with default resume.
          return
        } catch {
          // If stored resume is missing/invalid, fall back to default resume.
        }
        if (cancelled) return
        try {
          await loadDefaultFromList(access)
        } catch {
          // ignore
        }
        return
      }

      if (sessionStorage.getItem(importSessionKey)) return

      try {
        await loadDefaultFromList(access)
      } catch {
        // ignore
      }
    }

    hydrateDefaultResume()
    return () => {
      cancelled = true
    }
  }, [disableAutoLoadDefaultResume, enableTailorFlow, importSessionKey, resumeIdSessionKey, tailorReferenceBuilder])

  const updateField = (key, value) => {
    if (key === 'pageMarginIn') {
      setForm((prev) => ({ ...prev, pageMarginIn: normalizePageMarginIn(value) }))
      return
    }
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const openPdfPicker = () => {
    pdfInputRef.current?.click()
  }

  const handlePdfImport = async (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''

    if (!file) return

    const isPdf =
      file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
    if (!isPdf) {
      setImportState({ importing: false, message: 'Please choose a PDF file.' })
      return
    }

    try {
      setImportState({ importing: true, message: '' })
      const parsed = await parseResumePdf(file)
      setForm((prev) => ({
        ...prev,
        ...parsed,
        pageMarginIn: normalizePageMarginIn(parsed.pageMarginIn ?? prev.pageMarginIn),
        sectionUnderline: true,
      }))
      setResumeJobId('')
      if (enableTailorFlow) {
        setTailorReferenceBuilder(cloneBuilderData(parsed))
        setTailorReferenceResumeId('')
      }
      setImportState({
        importing: false,
        message: enableTailorFlow
          ? `Imported ${file.name} and set as reference resume.`
          : `Imported ${file.name}`,
      })
    } catch (err) {
      setImportState({ importing: false, message: err.message || 'Import failed' })
    }
  }

  const autoTitle = useMemo(() => {
    const years = computeExperienceYears(form.experiences || [])
    return makeAutoTitle(form.fullName, years)
  }, [form.fullName, form.experiences])

  const [showSectionOrder, setShowSectionOrder] = useState(false)
  const [dragKey, setDragKey] = useState(null)

  const reorder = (list, fromIndex, toIndex) => {
    const next = [...list]
    const [moved] = next.splice(fromIndex, 1)
    next.splice(toIndex, 0, moved)
    return next
  }

  const moveSection = (key, direction) => {
    setForm((prev) => {
      const order = prev.sectionOrder || []
      const index = order.indexOf(key)
      if (index === -1) return prev
      const nextIndex = index + direction
      if (nextIndex < 0 || nextIndex >= order.length) return prev
      return { ...prev, sectionOrder: reorder(order, index, nextIndex) }
    })
  }

  const handleDropSection = (overKey) => {
    if (!dragKey || dragKey === overKey) return
    setForm((prev) => {
      const order = prev.sectionOrder || []
      const fromIndex = order.indexOf(dragKey)
      const toIndex = order.indexOf(overKey)
      if (fromIndex === -1 || toIndex === -1) return prev
      return { ...prev, sectionOrder: reorder(order, fromIndex, toIndex) }
    })
  }

  const sectionMeta = [
    { key: 'summary', label: 'Summary' },
    { key: 'skills', label: 'Skills' },
    { key: 'experience', label: 'Experience' },
    { key: 'projects', label: 'Projects' },
    { key: 'education', label: 'Education' },
  ]

  const customKeyPrefix = 'custom:'

  const getCustomByKey = (key) => {
    if (!key.startsWith(customKeyPrefix)) return null
    const id = key.slice(customKeyPrefix.length)
    return (form.customSections || []).find((s) => s.id === id) || null
  }

  const getLabelForKey = (key) => {
    const base = sectionMeta.find((s) => s.key === key)
    if (base) return base.label
    const custom = getCustomByKey(key)
    if (custom) return custom.title?.trim() || 'Custom section'
    return key
  }

  const orderedKeys = (form.sectionOrder || sectionMeta.map((s) => s.key)).filter((k) => {
    if (sectionMeta.some((s) => s.key === k)) return true
    if (k.startsWith(customKeyPrefix)) return Boolean(getCustomByKey(k))
    return false
  })

  const addCustomSection = () => {
    const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`
    setForm((prev) => {
      const nextSections = [
        ...(prev.customSections || []),
        { id, title: 'Custom Section', content: '<ul><li>Write here...</li></ul>' },
      ]
      const nextOrder = [...(prev.sectionOrder || sectionMeta.map((s) => s.key)), `${customKeyPrefix}${id}`]
      return { ...prev, customSections: nextSections, sectionOrder: nextOrder }
    })
  }

  const updateCustomSection = (id, patch) => {
    setForm((prev) => {
      const next = [...(prev.customSections || [])]
      const index = next.findIndex((s) => s.id === id)
      if (index === -1) return prev
      next[index] = { ...next[index], ...patch }
      return { ...prev, customSections: next }
    })
  }

  const removeCustomSection = (id) => {
    setForm((prev) => {
      const nextSections = (prev.customSections || []).filter((s) => s.id !== id)
      const key = `${customKeyPrefix}${id}`
      const nextOrder = (prev.sectionOrder || []).filter((k) => k !== key)
      return { ...prev, customSections: nextSections, sectionOrder: nextOrder }
    })
  }

  const updateLink = (index, patch) => {
    setForm((prev) => {
      const next = [...(prev.links || [])]
      next[index] = { ...next[index], ...patch }
      return { ...prev, links: next }
    })
  }

  const addLink = () => {
    setForm((prev) => {
      const current = prev.links || []
      if (current.length >= 5) return prev
      return { ...prev, links: [...current, { label: '', url: '' }] }
    })
  }

  const removeLink = (index) => {
    setForm((prev) => {
      const current = [...(prev.links || [])]
      current.splice(index, 1)
      return { ...prev, links: current }
    })
  }

  const updateExperience = (index, patch) => {
    setForm((prev) => {
      const next = [...(prev.experiences || [])]
      next[index] = { ...next[index], ...patch }
      return { ...prev, experiences: next }
    })
  }

  const addExperience = () => {
    setForm((prev) => ({
      ...prev,
      experiences: [
        {
          company: '',
          title: '',
          startDate: '',
          endDate: '',
          isCurrent: true,
          highlights: '- ',
        },
        ...(prev.experiences || []),
      ],
    }))
  }

  const removeExperience = (index) => {
    setForm((prev) => {
      const current = [...(prev.experiences || [])]
      current.splice(index, 1)
      return { ...prev, experiences: current.length ? current : [] }
    })
  }

  const updateEducation = (index, patch) => {
    setForm((prev) => {
      const next = [...(prev.educations || [])]
      next[index] = { ...next[index], ...patch }
      return { ...prev, educations: next }
    })
  }

  const addEducation = () => {
    setForm((prev) => ({
      ...prev,
      educations: [
        {
          institution: '',
          program: '',
          scoreEnabled: false,
          scoreType: 'cgpa',
          scoreValue: '',
          scoreLabel: '',
          startDate: '',
          endDate: '',
          isCurrent: false,
        },
        ...(prev.educations || []),
      ],
    }))
  }

  const removeEducation = (index) => {
    setForm((prev) => {
      const current = [...(prev.educations || [])]
      current.splice(index, 1)
      return { ...prev, educations: current.length ? current : [] }
    })
  }

  const updateProject = (index, patch) => {
    setForm((prev) => {
      const next = [...(prev.projects || [])]
      next[index] = { ...next[index], ...patch }
      return { ...prev, projects: next }
    })
  }

  const addProject = () => {
    setForm((prev) => ({
      ...prev,
      projects: [
        ...(prev.projects || []),
        { name: '', url: '', highlights: '- ' },
      ],
    }))
  }

  const removeProject = (index) => {
    setForm((prev) => {
      const current = [...(prev.projects || [])]
      current.splice(index, 1)
      return { ...prev, projects: current.length ? current : [] }
    })
  }

  const downloadAtsPdf = () => {
    printAtsPdf({
      ...form,
      pageMarginIn: normalizePageMarginIn(form.pageMarginIn),
    })
  }

  const saveAtsPdfLocal = async () => {
    if (pdfSaveState.saving) return
    const access = localStorage.getItem('access')
    if (!access) {
      navigate('/login')
      return
    }

    try {
      setPdfSaveState({ saving: true, message: '' })
      const html = buildAtsPdfHtmlPreserveHighlights({
        ...form,
        pageMarginIn: normalizePageMarginIn(form.pageMarginIn),
      })
      const result = await exportAtsPdfLocal(access, {
        builder_data: form,
        html,
        resume_id: String(resumeRecordId || '').trim() || undefined,
      })
      const path = String(result?.saved_path || '').trim()
      setPdfSaveState({
        saving: false,
        message: path ? `Saved PDF: ${path}` : 'Saved PDF to Documents',
      })
    } catch (err) {
      setPdfSaveState({
        saving: false,
        message: err.message || 'Local PDF save failed',
      })
    }
  }

  const openInMainBuilder = () => {
    sessionStorage.setItem('builderImport', JSON.stringify(form))
    sessionStorage.removeItem('builderResumeId')
    navigate('/builder')
  }

  const runTailorAndSave = async () => {
    if (!showJdBox || !enableTailorFlow) return
    if (tailorState.loading) return
    setActiveTailorAction('tailor')

    const jd = String(jobDescription || '').trim()
    if (jd.length < 40) {
      setTailorState({
        loading: false,
        mode: '',
        message: '',
        error: 'Paste a full job description. Your base resume will be used as the reference. Best results: include role, required skills, responsibilities, tools/tech stack, and domain context. Recommended: 40+ words or about 200+ characters.',
        keywords: [],
        matchScore: null,
      })
      return
    }

    const access = localStorage.getItem('access')
    if (!access) {
      navigate('/login')
      return
    }

    const baseReferenceBuilder = enableTailorFlow ? tailorReferenceBuilder : form
    if (enableTailorFlow && !hasBuilderSubstance(baseReferenceBuilder || {})) {
      setTailorState({
        loading: false,
        mode: '',
        message: '',
        error: 'Upload reference resume once, then paste JD and run Tailor.',
        keywords: [],
        matchScore: null,
      })
      return
    }

    try {
      setTailorState({
        loading: true,
        mode: 'tailor',
        message: '',
        error: '',
        keywords: [],
        matchScore: null,
      })

      const formData = new FormData()
      formData.append('job_description', jd)
      formData.append('job_role', String(form.role || '').trim())
      formData.append('builder_data', JSON.stringify(baseReferenceBuilder || form))
      formData.append('min_match', '0.7')
      formData.append('max_match', '0.8')
      formData.append('preview_only', 'true')
      formData.append('ai_model', String(aiModel || 'gpt-4o'))
      formData.append('tailor_mode', String(tailorMode || 'partial'))
      if (enableTailorFlow) {
        formData.append('force_rewrite', 'true')
        if (String(tailorReferenceResumeId || '').trim()) {
          formData.append('reference_resume_id', String(tailorReferenceResumeId))
        }
      }

      const result = await tailorResume(access, formData)

      const resume = result?.resume || {}
      const incomingBuilder = resume?.builder_data && typeof resume.builder_data === 'object'
        ? resume.builder_data
        : null

      if (incomingBuilder) {
        setForm((prev) => ({
          ...prev,
          ...incomingBuilder,
          pageMarginIn: normalizePageMarginIn(incomingBuilder.pageMarginIn ?? prev.pageMarginIn),
          sectionUnderline: true,
          isDefaultResume: Boolean(resume?.is_default),
        }))
      }

      // Tailor action is preview-first. Any subsequent Save must create/update a tailored copy, never overwrite the base.
      setTailoredSourceResumeId(String(resumeRecordId || tailorReferenceResumeId || '').trim())
      setSaveTarget('tailored')
      setResumeJobId('')
      setResumeRecordId(null)
      setSaveMode('create')
      sessionStorage.removeItem(resumeIdSessionKey)

      const mode = String(result?.mode || '')
      const score = Number(result?.match_score)
      const scoreText = Number.isFinite(score) ? `${Math.round(score * 100)}%` : ''
      const message = mode === 'matched_existing'
        ? `Tailored preview ready from best match (${scoreText}). Review, then click Save.`
        : 'Tailored preview ready. Review, then click Save.'

      setTailorState({
        loading: false,
        mode: '',
        message,
        error: '',
        keywords: Array.isArray(result?.keywords) ? result.keywords : [],
        matchScore: Number.isFinite(score) ? score : null,
      })
    } catch (err) {
      setTailorState({
        loading: false,
        mode: '',
        message: '',
        error: err.message || 'Tailoring failed',
        keywords: [],
        matchScore: null,
      })
    }
  }

  const runQualityOptimize = async () => {
    if (!enableTailorFlow) return
    if (tailorState.loading) return
    setActiveTailorAction('optimize')

    const access = localStorage.getItem('access')
    if (!access) {
      navigate('/login')
      return
    }

    try {
      setTailorState({
        loading: true,
        mode: 'optimize',
        message: '',
        error: '',
        keywords: [],
        matchScore: null,
      })

      const result = await optimizeResumeQuality(access, {
        builder_data: form,
        preview_only: true,
        ai_model: String(aiModel || 'gpt-4o'),
      })

      const resume = result?.resume || {}
      const incomingBuilder = resume?.builder_data && typeof resume.builder_data === 'object'
        ? resume.builder_data
        : null

      if (incomingBuilder) {
        setForm((prev) => ({
          ...prev,
          ...incomingBuilder,
          pageMarginIn: normalizePageMarginIn(incomingBuilder.pageMarginIn ?? prev.pageMarginIn),
          sectionUnderline: true,
          isDefaultResume: Boolean(resume?.is_default),
        }))
      }

      if (saveMode === 'create') {
        setResumeJobId('')
        setResumeRecordId(null)
        sessionStorage.removeItem(resumeIdSessionKey)
      }

      setTailorState({
        loading: false,
        mode: '',
        message: 'Quality optimization ready. Review, then click Save.',
        error: '',
        keywords: [],
        matchScore: null,
      })
    } catch (err) {
      setTailorState({
        loading: false,
        mode: '',
        message: '',
        error: err.message || 'Quality optimization failed',
        keywords: [],
        matchScore: null,
      })
    }
  }

  const saveResumeToAccount = async ({ titleOverride = '', forceCreate = false, jobIdOverride = '' } = {}) => {
    const access = localStorage.getItem('access')
    if (!access) {
      navigate('/login')
      return null
    }

    try {
      setSaveState({ saving: true, message: '' })
      const derivedTitle = String(titleOverride || '').trim() || autoTitle
      const resolvedJobId = String(jobIdOverride || resumeJobId || '').trim()
      const payload = {
        title: derivedTitle,
        builder_data: form,
        original_text: formToPlainText(form),
        is_default: true,
        job: resolvedJobId ? Number(resolvedJobId) : null,
      }

      const data = (!forceCreate && resumeRecordId)
        ? await updateResume(access, resumeRecordId, payload)
        : (() => {
            if (!forceCreate && saveMode === 'edit') {
              throw new Error('Edit mode cannot create new resume. Use Add Resume (+) to create.')
            }
            return createResume(access, payload)
          })()

      setResumeRecordId(String(data.id))
      setResumeJobId(data?.job ? String(data.job) : '')
      sessionStorage.setItem(resumeIdSessionKey, String(data.id))
      setSaveMode('edit')
      setSaveTarget('base')
      setTailoredSourceResumeId('')
      setForm((prev) => ({
        ...prev,
        isDefaultResume: Boolean(data.is_default),
      }))
      setAllowBaseResumeSave(false)
      setSaveState({
        saving: false,
        message: `Saved: ${new Date().toLocaleTimeString()}`,
      })
      return data
    } catch (err) {
      setSaveState({ saving: false, message: err.message || 'Save failed' })
      return null
    }
  }

  const saveTailoredResumeToAccount = async ({ titleOverride = '', jobIdOverride = '' } = {}) => {
    const access = localStorage.getItem('access')
    if (!access) {
      navigate('/login')
      return null
    }

    try {
      setSaveState({ saving: true, message: '' })
      const derivedTitle = String(titleOverride || '').trim() || `Tailored - ${String(autoTitle || '').trim() || 'Resume'}`
      const resolvedJobId = String(jobIdOverride || resumeJobId || '').trim()
      const updatePayload = {
        title: derivedTitle,
        builder_data: form,
        original_text: formToPlainText(form),
        is_default: false,
        is_tailored: true,
        job: resolvedJobId ? Number(resolvedJobId) : null,
      }
      if (resumeRecordId && saveMode === 'edit') {
        const data = await updateResume(access, resumeRecordId, updatePayload)
        if (data?.id) {
          setResumeRecordId(String(data.id))
          setResumeJobId(data?.job ? String(data.job) : '')
          sessionStorage.setItem(resumeIdSessionKey, String(data.id))
        }
        setSaveMode('edit')
        setSaveTarget('tailored')
        setForm((prev) => ({
          ...prev,
          isDefaultResume: false,
        }))
        setSaveState({
          saving: false,
          message: `Updated tailored copy: ${new Date().toLocaleTimeString()}`,
        })
        return data
      }

      const sourceResumeId = String(tailoredSourceResumeId || resumeRecordId || tailorReferenceResumeId || '').trim()
      if (!sourceResumeId) {
        throw new Error('Load or save a base resume first before saving a tailored copy.')
      }

      const payload = {
        name: derivedTitle,
        builder_data: form,
        resume: Number(sourceResumeId),
        job: resolvedJobId ? Number(resolvedJobId) : null,
      }
      const data = await createTailoredResume(access, payload)
      if (data?.id) {
        setResumeRecordId(String(data.id))
        setResumeJobId(data?.job ? String(data.job) : '')
        sessionStorage.setItem(resumeIdSessionKey, String(data.id))
      }
      setSaveMode('edit')
      setSaveTarget('tailored')
      setForm((prev) => ({
        ...prev,
        isDefaultResume: false,
      }))
      setSaveState({
        saving: false,
        message: `Saved tailored copy: ${new Date().toLocaleTimeString()}`,
      })
      return data
    } catch (err) {
      setSaveState({ saving: false, message: err.message || 'Save failed' })
      return null
    }
  }

  const openSaveModal = async () => {
    if (saveTarget === 'base' && saveMode === 'edit' && !resumeRecordId) {
      setSaveState({ saving: false, message: 'Edit mode cannot create new resume. Use Add Resume (+).' })
      return
    }
    const access = localStorage.getItem('access')
    const suggested = saveTarget === 'tailored'
      ? `Tailored - ${String(autoTitle || '').trim() || 'Resume'}`
      : (String(autoTitle || '').trim() || 'My Resume')
    setSaveModal({
      open: true,
      name: suggested,
      jobId: resumeJobId || '',
      loading: true,
      jobs: [],
    })
    if (!access) {
      setSaveModal((prev) => ({ ...prev, loading: false }))
      return
    }
    try {
      const jobs = await fetchAllJobs(access, { ordering: '-created_at' })
      setSaveModal((prev) => ({ ...prev, loading: false, jobs }))
    } catch {
      setSaveModal((prev) => ({ ...prev, loading: false, jobs: [] }))
    }
  }

  const saveFromModal = async () => {
    const suggested = saveTarget === 'tailored'
      ? `Tailored - ${String(autoTitle || '').trim() || 'Resume'}`
      : (String(autoTitle || '').trim() || 'My Resume')
    const value = String(saveModal.name || '').trim() || suggested
    const selectedJobId = String(saveModal.jobId || '').trim()
    const saved = saveTarget === 'tailored'
      ? await saveTailoredResumeToAccount({ titleOverride: value, jobIdOverride: selectedJobId })
      : await saveResumeToAccount({ titleOverride: value, forceCreate: false, jobIdOverride: selectedJobId })
    if (saved) {
      setSaveModal((prev) => ({ ...prev, open: false }))
    }
  }

  const openSaveToTailored = async () => {
    const access = localStorage.getItem('access')
    if (!access) {
      navigate('/login')
      return
    }
    const suggested = `Tailored - ${String(autoTitle || '').trim() || 'Resume'}`
    setTailoredModal({
      open: true,
      name: suggested,
      jobId: resumeJobId || '',
      loading: true,
      jobs: [],
    })
    try {
      const jobs = await fetchAllJobs(access, { ordering: '-created_at' })
      setTailoredModal((prev) => ({ ...prev, loading: false, jobs }))
    } catch {
      setTailoredModal((prev) => ({ ...prev, loading: false, jobs: [] }))
    }
  }

  const saveToTailored = async () => {
    const access = localStorage.getItem('access')
    if (!access) {
      navigate('/login')
      return
    }
    try {
      setSaveState({ saving: true, message: '' })
      const sourceResumeId = String(tailoredSourceResumeId || resumeRecordId || tailorReferenceResumeId || '').trim()
      if (!sourceResumeId) {
        setSaveState({ saving: false, message: 'Save original resume first (or load reference resume) before Save To Tailored.' })
        return
      }
      const name = String(tailoredModal.name || '').trim() || `Tailored - ${String(autoTitle || '').trim() || 'Resume'}`
      const payload = {
        name,
        builder_data: form,
        resume: Number(sourceResumeId),
        job: tailoredModal.jobId ? Number(tailoredModal.jobId) : null,
      }
      const data = await createTailoredResume(access, payload)
      if (data?.id) {
        setResumeRecordId(String(data.id))
        setResumeJobId(data?.job ? String(data.job) : '')
        sessionStorage.setItem(resumeIdSessionKey, String(data.id))
        setSaveMode('edit')
      }
      setSaveTarget('tailored')
      setTailoredSourceResumeId(sourceResumeId)
      setForm((prev) => ({
        ...prev,
        isDefaultResume: false,
      }))
      setTailoredModal((prev) => ({ ...prev, open: false }))
      setSaveState({
        saving: false,
        message: `Saved to Tailored: ${new Date().toLocaleTimeString()}`,
      })
    } catch (err) {
      setSaveState({ saving: false, message: err.message || 'Save failed' })
    }
  }

  const Actions = ({ className, includeHome }) => (
    <div className={className}>
      <div className="builder-actions-row">
        {includeHome && (!minimalTailorUi || enableTailorFlow) && (
          <button type="button" className="secondary" onClick={openPdfPicker} disabled={importState.importing}>
            {importState.importing ? 'Importing...' : 'Import PDF'}
          </button>
        )}
        {showSaveButton && (!enableTailorFlow || allowBaseResumeSave) && (
          <button type="button" onClick={openSaveModal} disabled={saveState.saving}>
            {saveState.saving ? 'Saving...' : 'Save'}
          </button>
        )}
        {showSaveButton && enableTailorFlow && (
          <button type="button" className="secondary" onClick={openSaveToTailored} disabled={saveState.saving}>
            {saveState.saving ? 'Saving...' : 'Save To Tailored'}
          </button>
        )}
        {showJdBox && enableTailorFlow && (
          <button
            type="button"
            className={`secondary${activeTailorAction === 'optimize' ? ' is-active' : ''}${tailorState.loading && tailorState.mode === 'optimize' ? ' is-busy' : ''}`}
            onClick={runQualityOptimize}
            disabled={tailorState.loading && tailorState.mode === 'optimize'}
          >
            {tailorState.loading && tailorState.mode === 'optimize' ? 'Optimizing...' : 'Optimize'}
          </button>
        )}
        {showJdBox && enableTailorFlow && (
          <button
            type="button"
            className={`secondary${activeTailorAction === 'tailor' ? ' is-active' : ''}${tailorState.loading && tailorState.mode === 'tailor' ? ' is-busy' : ''}`}
            onClick={runTailorAndSave}
            disabled={tailorState.loading && tailorState.mode === 'tailor'}
          >
            {tailorState.loading && tailorState.mode === 'tailor' ? 'Tailoring...' : 'Tailor First'}
          </button>
        )}
        {minimalTailorUi && (
          <button type="button" className="secondary" onClick={openInMainBuilder}>
            Edit In Builder
          </button>
        )}
        <button type="button" className="secondary" onClick={downloadAtsPdf}>
          ATS PDF
        </button>
        {!enableTailorFlow && (
          <button type="button" className="secondary" onClick={saveAtsPdfLocal} disabled={pdfSaveState.saving}>
            {pdfSaveState.saving ? 'Saving PDF...' : 'Save ATS PDF Local'}
          </button>
        )}
      </div>
      {showSaveButton && enableTailorFlow && (
        <div className="builder-actions-meta">
          <label className="checkbox">
            <input
              type="checkbox"
              checked={allowBaseResumeSave}
              onChange={(e) => setAllowBaseResumeSave(e.target.checked)}
            />
            Allow saving/editing base resume
          </label>
        </div>
      )}
    </div>
  )

  return (
    <main className="builder-layout builder-page">
      <section className="builder-panel">
        <input
          ref={pdfInputRef}
          type="file"
          accept="application/pdf,.pdf"
          onChange={handlePdfImport}
          style={{ display: 'none' }}
        />
        <div className="builder-header">
          <div className="builder-header-top">
            <div>
              <h1>{pageTitle}</h1>
              <p className="builder-kicker">Career Tools</p>
            </div>
            <button type="button" className="secondary" onClick={() => navigate('/profile')}>
              Back to Profile
            </button>
          </div>
          <p className="subtitle">{subtitle}</p>
        </div>

        <Actions className="builder-actions builder-actions-top" includeHome />

        <div className="form">
          {showJdBox && (
            <div className="exp-card builder-jd-card">
              <div className="builder-section-top">
                <label htmlFor="job-description">Paste Job Description</label>
                <span className="builder-section-tag">AI Assist</span>
              </div>
              <div className="builder-control-grid">
                <label htmlFor="ai-model-select">AI Model
                  <select
                    id="ai-model-select"
                    value={aiModel}
                    onChange={(e) => setAiModel(e.target.value)}
                  >
                    {AI_MODEL_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label htmlFor="tailor-mode-select">Tailor Type
                  <select
                    id="tailor-mode-select"
                    value={tailorMode}
                    onChange={(e) => setTailorMode(e.target.value)}
                  >
                    {TAILOR_MODE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <textarea
                id="job-description"
                rows={10}
                value={jobDescription}
                onChange={(e) => setJobDescription(e.target.value)}
                placeholder="Paste a full job description here. Your base resume will be used as the reference. Best results: include role, required skills, responsibilities, tools/tech stack, and domain context. Recommended: 40+ words or about 200+ characters."
              />
              {enableTailorFlow && !tailorReferenceLoaded && (
                <p className="hint" style={{ margin: '8px 0 0' }}>
                  Upload a reference resume PDF first.
                </p>
              )}
              <p className="hint" style={{ margin: '8px 0 0' }}>
                Your base resume will be used as the reference. Best results: include role, required skills, responsibilities, tools/tech stack, and domain context.
              </p>
              <p className="hint" style={{ margin: '8px 0 0' }}>
                Optimize improves the current resume without using JD.
              </p>
              {tailorState.message && (
                <p className="success" style={{ margin: '8px 0 0' }}>
                  {tailorState.message}
                </p>
              )}
              {tailorState.error && (
                <p className="error" style={{ margin: '8px 0 0' }}>
                  {tailorState.error}
                </p>
              )}
              {tailorState.keywords.length > 0 && (
                <p className="hint" style={{ margin: '8px 0 0' }}>
                  JD keywords: {tailorState.keywords.slice(0, 30).join(', ')}
                </p>
              )}
            </div>
          )}

          {!minimalTailorUi && (
            <div className="builder-inline-settings">
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={showSectionOrder}
                  onChange={(e) => setShowSectionOrder(e.target.checked)}
                />
                Change section order
              </label>

              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={Boolean(form.sectionUnderline)}
                  onChange={(e) => updateField('sectionUnderline', e.target.checked)}
                />
                Section underline
              </label>

              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={normalizePageMarginIn(form.pageMarginIn) <= MIN_PAGE_MARGIN_IN}
                  onChange={(e) =>
                    updateField('pageMarginIn', e.target.checked ? MIN_PAGE_MARGIN_IN : DEFAULT_PAGE_MARGIN_IN)
                  }
                />
                Minimum margin
              </label>
            </div>
          )}

          {saveState.message && <p className={saveState.message.startsWith('Saved') ? 'success' : 'error'}>{saveState.message}</p>}
          {pdfSaveState.message && <p className={pdfSaveState.message.startsWith('Saved PDF') ? 'success' : 'error'}>{pdfSaveState.message}</p>}
          {(!minimalTailorUi || enableTailorFlow) && importState.message && (
            <p className={importState.message.startsWith('Imported') ? 'success' : 'error'}>
              {importState.message}
            </p>
          )}

          {!minimalTailorUi && (
            <div className="section-options builder-settings-card">
            <div className="builder-section-top">
              <label>Typography</label>
              <span className="builder-section-tag">Layout</span>
            </div>
            <div className="builder-control-grid">
              <select
                value={form.bodyFontFamily || FONT_FAMILY_OPTIONS[0].value}
                onChange={(e) => updateField('bodyFontFamily', e.target.value)}
              >
                {FONT_FAMILY_OPTIONS.map((option) => (
                  <option key={option.label} value={option.value}>
                    Font: {option.label}
                  </option>
                ))}
              </select>
              <select
                value={String(form.bodyFontSizePt || 10)}
                onChange={(e) => updateField('bodyFontSizePt', Number(e.target.value))}
              >
                <option value="9">Font size: 9</option>
                <option value="10">Font size: 10</option>
                <option value="11">Font size: 11</option>
                <option value="12">Font size: 12</option>
              </select>
            </div>
            <div className="builder-control-grid">
              <select
                value={String(form.bodyLineHeight || 1)}
                onChange={(e) => updateField('bodyLineHeight', Number(e.target.value))}
              >
                <option value="1">Spacing: 1.0</option>
                <option value="1.05">Spacing: 1.05</option>
                <option value="1.1">Spacing: 1.1</option>
                <option value="1.15">Spacing: 1.15</option>
                <option value="1.2">Spacing: 1.2</option>
                <option value="1.25">Spacing: 1.25</option>
                <option value="1.3">Spacing: 1.3</option>
                <option value="1.35">Spacing: 1.35</option>
                <option value="1.4">Spacing: 1.4</option>
              </select>
            </div>
            <p className="hint" style={{ margin: 0 }}>
              Applies to preview and export.
            </p>
            </div>
          )}

          {!minimalTailorUi && showSectionOrder && (
            <div className="section-order">
              <label>Section order (drag to reorder)</label>
              <div className="section-order-list">
                {orderedKeys.map((key) => {
                  const label = getLabelForKey(key)
                  const disabled = key === 'summary' && !form.summaryEnabled
                  return (
                    <div
                      key={key}
                      className={`section-order-item${disabled ? ' is-disabled' : ''}`}
                      draggable={!disabled}
                      onDragStart={() => setDragKey(key)}
                      onDragEnd={() => setDragKey(null)}
                      onDragOver={(e) => {
                        if (disabled) return
                        e.preventDefault()
                      }}
                      onDrop={() => handleDropSection(key)}
                      title={disabled ? 'Enable Summary to include it' : 'Drag to reorder'}
                    >
                      <span className="drag-handle" aria-hidden="true">
                        ⋮⋮
                      </span>
                      <span className="section-order-label">{label}</span>
                      <div className="section-order-actions">
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => moveSection(key, -1)}
                          disabled={orderedKeys[0] === key}
                          title="Move up"
                        >
                          ↑
                        </button>
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => moveSection(key, 1)}
                          disabled={orderedKeys[orderedKeys.length - 1] === key}
                          title="Move down"
                        >
                          ↓
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {!minimalTailorUi && (
            <div className="exp-editor builder-block">
            <div className="exp-editor-head">
              <label>Extra sections (optional)</label>
              <button type="button" className="secondary" onClick={addCustomSection}>
                Add Section
              </button>
            </div>
            {(form.customSections || []).map((section) => (
              <div key={section.id} className="exp-card">
                <div className="exp-row">
                  <input
                    type="text"
                    value={section.title || ''}
                    onChange={(e) => updateCustomSection(section.id, { title: e.target.value })}
                    placeholder="Section name (e.g. Certifications)"
                  />
                  <button
                    type="button"
                    className="secondary inline-remove-btn"
                    onClick={() => removeCustomSection(section.id)}
                    title="Remove section"
                  >
                    Remove
                  </button>
                </div>
                <RichTextarea
                  id={`custom-${section.id}`}
                  label="Content"
                  value={section.content || ''}
                  onChange={(value) => updateCustomSection(section.id, { content: value })}
                  placeholder="Write content..."
                />
              </div>
            ))}
            </div>
          )}

          {!minimalTailorUi && <input value={form.fullName} onChange={(e) => updateField('fullName', e.target.value)} placeholder="Full name" />}
          {!minimalTailorUi && <input value={form.role} onChange={(e) => updateField('role', e.target.value)} placeholder="Target role" />}
          {!minimalTailorUi && <input value={form.email} onChange={(e) => updateField('email', e.target.value)} placeholder="Email" />}
          {!minimalTailorUi && <input value={form.phone} onChange={(e) => updateField('phone', e.target.value)} placeholder="Phone" />}
          {!minimalTailorUi && <input value={form.location} onChange={(e) => updateField('location', e.target.value)} placeholder="Location" />}

          {!minimalTailorUi && (
            <div className="exp-editor builder-block">
            <div className="exp-editor-head">
              <label>Profile Links (max 5)</label>
              <button
                type="button"
                className="secondary"
                onClick={addLink}
                disabled={(form.links || []).length >= 5}
              >
                Add Link
              </button>
            </div>

            {(form.links || []).map((link, index) => (
              <div key={`link-${index}`} className="exp-card">
                <div className="exp-row">
                  <input
                    type="text"
                    value={link.label}
                    onChange={(e) => updateLink(index, { label: e.target.value })}
                    placeholder="Name (e.g. GitHub, Portfolio)"
                  />
                  <input
                    type="text"
                    value={link.url}
                    onChange={(e) => updateLink(index, { url: e.target.value })}
                    placeholder="URL (e.g. https://...)"
                  />
                </div>
                <div className="actions">
                  <button type="button" className="secondary" onClick={() => removeLink(index)}>
                    Remove
                  </button>
                </div>
              </div>
            ))}
            </div>
          )}

          {!minimalTailorUi && (
            <div className="section-options builder-settings-card">
            <label className="checkbox">
              <input
                type="checkbox"
                checked={Boolean(form.summaryEnabled)}
                onChange={(e) => updateField('summaryEnabled', e.target.checked)}
              />
              Show summary
            </label>
            <input
              type="text"
              value={form.summaryHeading}
              onChange={(e) => updateField('summaryHeading', e.target.value)}
              placeholder="Section title (e.g. Summary, Profile)"
              disabled={!form.summaryEnabled}
            />
            <select
              value={form.summaryStyle}
              onChange={(e) => updateField('summaryStyle', e.target.value)}
              disabled={!form.summaryEnabled}
            >
              <option value="auto">Auto</option>
              <option value="paragraph">Paragraph</option>
              <option value="bullets">Bullets</option>
              <option value="numbered">Numbered</option>
            </select>
            </div>
          )}

          {!minimalTailorUi && form.summaryEnabled && (
            <RichTextarea
              id="summary"
              label={form.summaryHeading || 'Summary'}
              value={form.summary}
              onChange={(value) => updateField('summary', value)}
              placeholder="Professional summary"
            />
          )}

          {!minimalTailorUi && (
            <RichTextarea
            id="skills"
            label="Skills"
            value={form.skills}
            onChange={(value) => updateField('skills', value)}
            placeholder="Add skills"
            />
          )}

          {!minimalTailorUi && (
            <div className="exp-editor builder-block">
            <div className="exp-editor-head">
              <label>Experience</label>
              <button type="button" className="secondary" onClick={addExperience}>
                Add Experience
              </button>
            </div>

            {(form.experiences || []).map((exp, index) => (
              <div key={`exp-${index}`} className="exp-card">
                <div className="exp-row">
                  <input
                    type="text"
                    value={exp.company}
                    onChange={(e) => updateExperience(index, { company: e.target.value })}
                    placeholder="Company (e.g. Inspektlabs)"
                  />
                  <input
                    type="text"
                    value={exp.title}
                    onChange={(e) => updateExperience(index, { title: e.target.value })}
                    placeholder="Role (e.g. Software Developer)"
                  />
                </div>

                <div className="exp-row">
                  <input
                    type="text"
                    value={exp.startDate || ''}
                    onChange={(e) => updateExperience(index, { startDate: e.target.value })}
                    placeholder="Start (e.g. Mar 2025)"
                  />
                  <input
                    type="text"
                    value={exp.isCurrent ? 'Present' : exp.endDate || ''}
                    onChange={(e) => updateExperience(index, { endDate: e.target.value })}
                    placeholder="End (e.g. Jan 2026)"
                    disabled={Boolean(exp.isCurrent)}
                  />
                </div>

                <div className="exp-row exp-row-actions">
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={Boolean(exp.isCurrent)}
                      onChange={(e) => updateExperience(index, { isCurrent: e.target.checked })}
                    />
                    Still working
                  </label>
                  <button
                    type="button"
                    className="secondary inline-remove-btn"
                    onClick={() => removeExperience(index)}
                    disabled={(form.experiences || []).length <= 1}
                    title="Remove experience"
                  >
                    Remove
                  </button>
                </div>

                <RichTextarea
                  id={`exp-highlights-${index}`}
                  label="Highlights"
                  value={exp.highlights}
                  onChange={(value) => updateExperience(index, { highlights: value })}
                  placeholder="- Achievement or responsibility"
                />
              </div>
            ))}
            </div>
          )}

          {!minimalTailorUi && (
            <div className="exp-editor builder-block">
            <div className="exp-editor-head">
              <label>Projects</label>
              <button type="button" className="secondary" onClick={addProject}>
                Add Project
              </button>
            </div>

            {(form.projects || []).map((proj, index) => (
              <div key={`proj-${index}`} className="exp-card">
                <div className="exp-row">
                  <input
                    type="text"
                    value={proj.name}
                    onChange={(e) => updateProject(index, { name: e.target.value })}
                    placeholder="Project name (e.g. AutoEngage)"
                  />
                  <input
                    type="text"
                    value={proj.url}
                    onChange={(e) => updateProject(index, { url: e.target.value })}
                    placeholder="Project link (optional, e.g. https://...)"
                  />
                </div>

                <RichTextarea
                  id={`proj-highlights-${index}`}
                  label="Highlights"
                  value={proj.highlights}
                  onChange={(value) => updateProject(index, { highlights: value })}
                  placeholder="- What you built\n- What impact"
                />

                <div className="actions">
                  <button
                    type="button"
                    className="secondary inline-remove-btn"
                    onClick={() => removeProject(index)}
                    disabled={(form.projects || []).length <= 1}
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
            </div>
          )}

          {!minimalTailorUi && (
            <div className="edu-editor builder-block">
            <div className="exp-editor-head">
              <label>Education</label>
              <button type="button" className="secondary" onClick={addEducation}>
                Add Education
              </button>
            </div>

            {(form.educations || []).map((edu, index) => (
              <div key={`edu-${index}`} className="exp-card">
                <div className="exp-row">
                  <input
                    type="text"
                    value={edu.institution}
                    onChange={(e) => updateEducation(index, { institution: e.target.value })}
                    placeholder="Institution (e.g. KIET Group of Institutions)"
                  />
                  <input
                    type="text"
                    value={edu.program}
                    onChange={(e) => updateEducation(index, { program: e.target.value })}
                    placeholder="Program (e.g. B.Tech in IT)"
                  />
                </div>

                <div className="exp-row">
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={Boolean(edu.scoreEnabled)}
                      onChange={(e) =>
                        updateEducation(index, {
                          scoreEnabled: e.target.checked,
                          scoreValue: e.target.checked ? edu.scoreValue : '',
                        })
                      }
                    />
                    Add score
                  </label>
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={Boolean(edu.isCurrent)}
                      onChange={(e) => updateEducation(index, { isCurrent: e.target.checked })}
                    />
                    Still studying
                  </label>
                </div>

                {edu.scoreEnabled && (
                  <div className="exp-row">
                    <select
                      value={edu.scoreType || 'cgpa'}
                      onChange={(e) =>
                        updateEducation(index, { scoreType: e.target.value, scoreLabel: '' })
                      }
                    >
                      <option value="cgpa">CGPA</option>
                      <option value="percentage">Percentage</option>
                      <option value="custom">Custom</option>
                    </select>
                    <input
                      type="text"
                      value={edu.scoreValue || ''}
                      onChange={(e) => updateEducation(index, { scoreValue: e.target.value })}
                      placeholder={
                        edu.scoreType === 'percentage'
                          ? 'e.g. 80 or 80%'
                          : edu.scoreType === 'custom'
                            ? 'Value (e.g. 3.7/4.0)'
                            : 'e.g. 8.0'
                      }
                    />
                  </div>
                )}

                {edu.scoreEnabled && edu.scoreType === 'custom' && (
                  <div className="exp-row">
                    <input
                      type="text"
                      value={edu.scoreLabel || ''}
                      onChange={(e) => updateEducation(index, { scoreLabel: e.target.value })}
                      placeholder="Label (e.g. GPA (4.0), Marks, Grade)"
                    />
                    <div />
                  </div>
                )}

                <div className="exp-row">
                  <input
                    type="text"
                    value={edu.startDate || ''}
                    onChange={(e) => updateEducation(index, { startDate: e.target.value })}
                    placeholder="Start (e.g. 2019)"
                  />
                  <input
                    type="text"
                    value={edu.isCurrent ? 'Present' : edu.endDate || ''}
                    onChange={(e) => updateEducation(index, { endDate: e.target.value })}
                    placeholder="End (e.g. 2023)"
                    disabled={Boolean(edu.isCurrent)}
                  />
                </div>

                <div className="actions">
                  <button
                    type="button"
                    className="secondary inline-remove-btn"
                    onClick={() => removeEducation(index)}
                    disabled={(form.educations || []).length <= 1}
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
            </div>
          )}
        </div>

      </section>

      <section className="preview-panel">
        <div className="preview-panel-head">
          <div>
            <h2>Live Preview</h2>
            <p className="subtitle">Preview of the final resume.</p>
          </div>
        </div>
        <ResumeSheet form={form} />
      </section>

      {tailoredModal.open ? (
        <div className="modal-overlay" onClick={() => setTailoredModal((prev) => ({ ...prev, open: false }))}>
          <div className="modal-panel builder-save-modal" onClick={(e) => e.stopPropagation()}>
            <h2>Save Tailored Resume</h2>
            <label>
              Name
              <input
                value={tailoredModal.name}
                onChange={(e) => setTailoredModal((prev) => ({ ...prev, name: e.target.value }))}
                placeholder="Enter tailored resume name"
              />
            </label>
            <label>
              Job (Optional)
              <SingleSelectDropdown
                value={tailoredModal.jobId || ''}
                placeholder="Search/select job"
                clearLabel="No job association"
                disabled={tailoredModal.loading}
                options={(Array.isArray(tailoredModal.jobs) ? tailoredModal.jobs : []).map((job) => ({
                  value: String(job.id),
                  label: `${job.job_id || '-'} | ${job.role || '-'} | ${job.company_name || '-'}`,
                }))}
                onChange={(nextValue) => setTailoredModal((prev) => ({ ...prev, jobId: nextValue }))}
              />
            </label>
            <div className="actions">
              <button type="button" onClick={saveToTailored} disabled={saveState.saving || tailoredModal.loading}>
                {saveState.saving ? 'Saving...' : 'Save'}
              </button>
              <button type="button" className="secondary" onClick={() => setTailoredModal((prev) => ({ ...prev, open: false }))}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {saveModal.open ? (
        <div className="modal-overlay" onClick={() => setSaveModal((prev) => ({ ...prev, open: false }))}>
          <div className="modal-panel builder-save-modal" onClick={(e) => e.stopPropagation()}>
            <h2>Save Resume</h2>
            <label>
              Name
              <input
                value={saveModal.name}
                onChange={(e) => setSaveModal((prev) => ({ ...prev, name: e.target.value }))}
                placeholder="Enter resume name"
              />
            </label>
            <label>
              Job (Optional)
              <SingleSelectDropdown
                value={saveModal.jobId || ''}
                placeholder="Search/select job"
                clearLabel="No job association"
                disabled={saveModal.loading}
                options={(Array.isArray(saveModal.jobs) ? saveModal.jobs : []).map((job) => ({
                  value: String(job.id),
                  label: `${job.job_id || '-'} | ${job.role || '-'} | ${job.company_name || '-'}`,
                }))}
                onChange={(nextValue) => setSaveModal((prev) => ({ ...prev, jobId: nextValue }))}
              />
            </label>
            <div className="actions">
              <button type="button" onClick={saveFromModal} disabled={saveState.saving || saveModal.loading}>
                {saveState.saving ? 'Saving...' : 'Save'}
              </button>
              <button type="button" className="secondary" onClick={() => setSaveModal((prev) => ({ ...prev, open: false }))}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  )
}

export default ResumeBuilderPage
