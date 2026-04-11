import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import RichTextarea from '../components/RichTextarea'
import ResumeSheet from '../components/ResumeSheet'
import { createResume, fetchResume, fetchResumes, parseResumePdf, updateResume } from '../api'
import { printAtsPdf } from '../utils/resumeExport'

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

function renderSummaryByStyle(text, style) {
  // The editor stores sanitized HTML, so style is currently "auto".
  // Keep the option for future transformations.
  return String(text || '')
}

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
    const tech = String(exp.techStack || '').trim()
    const showTech = Boolean(exp.showTechUsed ?? f.showExperienceTechUsed)
    if (tech && showTech) parts.push(`Tech Stack: ${tech}`)
  })

  ;(f.projects || []).forEach((proj) => {
    const head = [proj.name, proj.url].map((v) => String(v || '').trim()).filter(Boolean).join(' | ')
    if (head) parts.push(head)
    const highlights = plainTextFromHtml(proj.highlights || '')
    if (highlights) parts.push(highlights)
    const tech = String(proj.techStack || '').trim()
    const showTech = Boolean(proj.showTechUsed ?? f.showProjectTechUsed)
    if (tech && showTech) parts.push(`Tech Stack: ${tech}`)
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

function dateKey(value, isCurrent) {
  if (isCurrent) return 999912 // treat present as newest
  const raw = String(value || '').trim()
  if (!raw) return 0

  // Accept: "Mar 2025", "2025", "2025-03"
  const parts = raw.replace(/\s+/g, ' ').split(' ')
  if (parts.length === 1) {
    const only = parts[0]
    if (/^\d{4}$/.test(only)) return Number(only) * 100 + 1
    const m = only.split('-')
    if (m.length === 2 && /^\d{4}$/.test(m[0]) && /^\d{1,2}$/.test(m[1])) {
      return Number(m[0]) * 100 + Math.max(1, Math.min(12, Number(m[1])))
    }
  }

  if (parts.length >= 2) {
    const maybeMonth = parseMonth(parts[0])
    const maybeYear = parts.find((p) => /^\d{4}$/.test(p))
    if (maybeMonth && maybeYear) return Number(maybeYear) * 100 + maybeMonth
  }

  const yearMatch = raw.match(/\b(\d{4})\b/)
  if (yearMatch) return Number(yearMatch[1]) * 100 + 1
  return 0
}

function sortNewestFirst(items, getEndKey, getStartKey) {
  return [...items].sort((a, b) => {
    const ae = getEndKey(a)
    const be = getEndKey(b)
    if (be !== ae) return be - ae
    const as = getStartKey(a)
    const bs = getStartKey(b)
    if (bs !== as) return bs - as
    return 0
  })
}

function normalizeHttpUrl(value) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const hasScheme = /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(raw)
  const candidate = hasScheme ? raw : `https://${raw}`
  try {
    const url = new URL(candidate)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return ''
    return url.toString()
  } catch {
    return ''
  }
}

function normalizeTechStackText(value) {
  return String(value || '')
    .replace(/\s*,\s*/g, ', ')
    .replace(/\s+/g, ' ')
    .trim()
}

function renderLink(label, value) {
  const url = normalizeHttpUrl(value)
  if (!url) return null
  return (
    <a key={label} href={url} target="_blank" rel="noreferrer">
      {label}
    </a>
  )
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

function inlineToHtml(text) {
  const safe = escapeHtml(text)
  // Basic tag support: [b][/b] [i][/i] [u][/u]
  return safe
    .replace(/\[b\]/gi, '<strong>')
    .replace(/\[\/b\]/gi, '</strong>')
    .replace(/\[i\]/gi, '<em>')
    .replace(/\[\/i\]/gi, '</em>')
    .replace(/\[u\]/gi, '<u>')
    .replace(/\[\/u\]/gi, '</u>')
}

function richTextToHtml(text) {
  const blocks = String(text || '')
    .split('\n\n')
    .map((b) => b.trim())
    .filter(Boolean)

  return blocks
    .map((block) => {
      const lines = block.split('\n').map((l) => l.trim())
      const isBullets = lines.length > 0 && lines.every((l) => !l || l.startsWith('- '))
      const isNumbered = lines.length > 0 && lines.every((l) => !l || /^\d+[\.\)]\s+/.test(l))

      if (isBullets) {
        const items = lines
          .filter(Boolean)
          .map((l) => `<li>${inlineToHtml(l.slice(2))}</li>`)
          .join('')
        return `<ul>${items}</ul>`
      }

      if (isNumbered) {
        const items = lines
          .filter(Boolean)
          .map((l) => `<li>${inlineToHtml(l.replace(/^\d+[\.\)]\s+/, ''))}</li>`)
          .join('')
        return `<ol>${items}</ol>`
      }

      return `<p>${inlineToHtml(block)}</p>`
    })
    .join('\n')
}

function buildDocHtml(form) {
  const fontSize = Number(form.bodyFontSizePt || 10)
  const lineHeight = Number(form.bodyLineHeight || 1)
  const safeFontSize = Number.isFinite(fontSize) ? fontSize : 10
  const safeLineHeight = Number.isFinite(lineHeight) ? lineHeight : 1
  const safeBodyFontFamily = String(form.bodyFontFamily || 'Arial, Helvetica, sans-serif')
  const marginIn = Number(form.pageMarginIn || 0.3)
  const safeMarginIn = Number.isFinite(marginIn) ? marginIn : 0.3

  const contact = [form.location, form.phone, form.email]
    .map((v) => String(v || '').trim())
    .filter(Boolean)
    .join(' | ')

  const links = (form.links || [])
    .map((l) => ({ label: String(l.label || '').trim(), url: normalizeHttpUrl(l.url) }))
    .filter((l) => l.label && l.url)
    .map((l) => `<a href="${escapeHtml(l.url)}">${escapeHtml(l.label)}</a>`)
    .join(' | ')

  const projects = (form.projects || [])
    .map((p) => {
      const name = escapeHtml(p.name || '')
      const url = normalizeHttpUrl(p.url)
      const link = url ? ` <a href="${escapeHtml(url)}" style="color:#6b778f;text-decoration:none;">link</a>` : ''
      const techRaw = normalizeTechStackText(p.techStack)
      const showTech = Boolean(p.showTechUsed ?? form.showProjectTechUsed)
      const techBlock =
        showTech && techRaw
          ? `<p style="margin:6px 0 0;font-size:${safeFontSize}pt;line-height:${safeLineHeight};color:#1f2937;"><span style="font-weight:600;letter-spacing:0.03em;color:#111827;">Tech Stack:</span> <span style="font-weight:600;">${escapeHtml(
              techRaw,
            )}</span></p>`
          : ''
      return `<div style="margin-top:10px;"><div><strong>${name}</strong>${link}</div>${richTextToHtml(
        p.highlights || '',
      )}${techBlock}</div>`
    })
    .join('')

  const experiences = (form.experiences || [])
    .map((e) => {
      const left = [e.company, e.title].map((v) => String(v || '').trim()).filter(Boolean).join(' – ')
      const right = [e.startDate, e.isCurrent ? 'Present' : e.endDate]
        .map((v) => String(v || '').trim())
        .filter(Boolean)
        .join(' – ')
      const techRaw = normalizeTechStackText(e.techStack)
      const showTech = Boolean(e.showTechUsed ?? form.showExperienceTechUsed)
      const techBlock =
        showTech && techRaw
          ? `<p style="margin:6px 0 0;font-size:${safeFontSize}pt;line-height:${safeLineHeight};color:#1f2937;"><span style="font-weight:600;letter-spacing:0.03em;color:#111827;">Tech Stack:</span> <span style="font-weight:600;">${escapeHtml(
              techRaw,
            )}</span></p>`
          : ''
      return `<div style="margin-top:10px;">
        <div style="display:flex;justify-content:space-between;gap:12px;">
          <div><strong>${inlineToHtml(left)}</strong></div>
          <div style="color:#3a4861;white-space:nowrap;">${inlineToHtml(right)}</div>
        </div>
        ${richTextToHtml(e.highlights || '')}
        ${techBlock}
      </div>`
    })
    .join('')

  const educations = (form.educations || [])
    .map((edu) => {
      const scoreType = String(edu.scoreType || 'cgpa')
      const rawScore = String(edu.scoreValue || '').trim()
      const scoreLabel = String(edu.scoreLabel || '').trim()
      const scoreText = (() => {
        if (!edu.scoreEnabled || !rawScore) return ''
        if (scoreType === 'custom') return `${scoreLabel || 'Score'}: ${rawScore}`
        if (scoreType === 'percentage') return `Percentage: ${rawScore.includes('%') ? rawScore : `${rawScore}%`}`
        return `CGPA: ${rawScore}`
      })()

      const left = [edu.institution, edu.program, scoreText]
        .map((v) => String(v || '').trim())
        .filter(Boolean)
        .join(' | ')
      const right = [edu.startDate, edu.isCurrent ? 'Present' : edu.endDate]
        .map((v) => String(v || '').trim())
        .filter(Boolean)
        .join(' – ')
      return `<div style="margin-top:8px;display:flex;justify-content:space-between;gap:12px;">
        <div><strong>${inlineToHtml(left)}</strong></div>
        <div style="color:#3a4861;white-space:nowrap;">${inlineToHtml(right)}</div>
      </div>`
    })
    .join('')

  const summaryTitle = escapeHtml(form.summaryHeading || 'Summary')
  const summarySection = form.summaryEnabled
    ? `<h3>${summaryTitle}</h3><div>${richTextToHtml(form.summary)}</div>`
    : ''
  const compactClass = 'compact'
  const headerClass = form.sectionUnderline ? 'resume-header' : 'resume-header has-underline'

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Resume</title>
  <style>
    body { font-family: ${escapeHtml(safeBodyFontFamily)}; }
    @page { size: A4; margin: ${safeMarginIn}in; }
    body { margin: 0; padding: ${safeMarginIn}in; }
    body.compact { font-size: ${Math.max(9, safeFontSize - 0.5)}pt; }
    h1 { margin: 0; text-align: center; }
    .resume-header {
      margin-bottom: 10px;
      padding-bottom: 8px;
    }
    .resume-header.has-underline {
      border-bottom: 1px solid #d1d5db;
    }
    .center { text-align: center; color: #3a4861; margin-top: 4px; }
    h3 { margin: 14px 0 8px; font-size: 12px; letter-spacing: 0.06em; text-transform: uppercase; }
    p, li { font-size: ${safeFontSize}pt; line-height: ${safeLineHeight}; margin: 6px 0; }
    .summary-block p, .summary-block li { font-size: ${safeFontSize}pt; line-height: ${safeLineHeight}; }
    body.compact h3 { margin: 10px 0 4px; }
    body.compact p,
    body.compact li { margin: 4px 0; }
    body.compact .center { margin-top: 2px; }
    body.compact ul,
    body.compact ol { margin-top: 4px; }
    body.compact .summary-block p,
    body.compact .summary-block li { margin: 4px 0; }
    ul, ol { margin: 6px 0 0; padding-left: 18px; }
    a { color: #1b2230; text-decoration: none; }
  </style>
</head>
<body class="${compactClass}">
  <header class="${headerClass}">
    <h1>${escapeHtml(form.fullName || '')}</h1>
    <div class="center">${escapeHtml(contact)}</div>
    ${links ? `<div class="center">${links}</div>` : ''}
  </header>
  ${summarySection ? `<div class="summary-block">${summarySection}</div>` : ''}
  <h3>Skills</h3>
  ${richTextToHtml(form.skills)}
  <h3>Experience</h3>
  ${experiences}
  <h3>Projects</h3>
  ${projects}
  <h3>Education</h3>
  ${educations}
</body>
</html>`
}

function ResumeBuilderPage() {
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
    pageMarginIn: 0.3,
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
        techStack: '',
        showTechUsed: false,
        highlights: '<ul><li>Write 3+ bullets. Add numbers where possible.</li></ul>',
      },
    ],
    projects: [
      {
        name: '',
        url: '',
        techStack: '',
        showTechUsed: false,
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
  const [resumeRecordId, setResumeRecordId] = useState(() => sessionStorage.getItem('builderResumeId'))
  const [saveState, setSaveState] = useState({ saving: false, message: '' })
  const [importState, setImportState] = useState({ importing: false, message: '' })
  const pdfInputRef = useRef(null)

  useEffect(() => {
    const raw = sessionStorage.getItem('builderImport')
    if (raw) {
      try {
        const imported = JSON.parse(raw)
        if (imported && typeof imported === 'object') {
          setForm((prev) => ({ ...prev, ...imported, sectionUnderline: true }))
        }
      } catch {
        // ignore
      }
      sessionStorage.removeItem('builderImport')
    }

    const id = sessionStorage.getItem('builderResumeId')
    if (id) setResumeRecordId(id)
  }, [])

  useEffect(() => {
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
        sectionUnderline: true,
        isDefaultResume: Boolean(full.is_default),
      }))
      setResumeRecordId(String(full.id))
      sessionStorage.setItem('builderResumeId', String(full.id))
    }

    const hydrateDefaultResume = async () => {
      const access = localStorage.getItem('access')
      if (!access) return

      const storedId = sessionStorage.getItem('builderResumeId')
      if (storedId) {
        try {
          const full = await fetchResume(access, storedId)
          if (cancelled) return
          setForm((prev) => ({
            ...prev,
            isDefaultResume: Boolean(full.is_default),
          }))
        } catch {
          // ignore; keep local state
        }
        if (cancelled) return
        try {
          await loadDefaultFromList(access)
        } catch {
          // ignore
        }
        return
      }

      if (sessionStorage.getItem('builderImport')) return

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
  }, [])

  const updateField = (key, value) => {
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
      setForm((prev) => ({ ...prev, ...parsed, sectionUnderline: true }))
      setImportState({ importing: false, message: `Imported ${file.name}` })
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
          techStack: '',
          showTechUsed: false,
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
        { name: '', url: '', techStack: '', showTechUsed: false, highlights: '- ' },
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

  const downloadDoc = () => {
    const html = buildDocHtml(form)
    const blob = new Blob([html], { type: 'application/msword' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    const fileSafeName = String(form.fullName || 'resume').trim().replace(/\s+/g, '_')
    link.href = url
    link.download = `${fileSafeName}.doc`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  }

  const downloadAtsPdf = () => {
    printAtsPdf(form)
  }

  const saveResumeToAccount = async () => {
    const access = localStorage.getItem('access')
    if (!access) {
      navigate('/login')
      return
    }

    try {
      setSaveState({ saving: true, message: '' })
      const derivedTitle = autoTitle
      const payload = {
        title: derivedTitle,
        builder_data: form,
        original_text: formToPlainText(form),
        is_default: Boolean(form.isDefaultResume),
      }

      const data = resumeRecordId
        ? await updateResume(access, resumeRecordId, payload)
        : await createResume(access, payload)

      setResumeRecordId(String(data.id))
      sessionStorage.setItem('builderResumeId', String(data.id))
      setForm((prev) => ({
        ...prev,
        isDefaultResume: Boolean(data.is_default),
      }))
      setSaveState({ saving: false, message: `Saved: ${new Date().toLocaleTimeString()}` })
    } catch (err) {
      setSaveState({ saving: false, message: err.message || 'Save failed' })
    }
  }

  const Actions = ({ className, includeHome }) => (
    <div className={className}>
      {includeHome && (
        <button type="button" className="secondary" onClick={openPdfPicker} disabled={importState.importing}>
          {importState.importing ? 'Importing...' : 'Import PDF'}
        </button>
      )}
      <button type="button" onClick={saveResumeToAccount} disabled={saveState.saving}>
        {saveState.saving ? 'Saving...' : 'Save'}
      </button>
      <button type="button" className="secondary" onClick={downloadDoc}>
        Download DOC
      </button>
      <button type="button" className="secondary" onClick={downloadAtsPdf}>
        ATS PDF
      </button>
      {includeHome && (
        <button type="button" className="secondary" onClick={() => navigate('/')}>
          Back Home
        </button>
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
          <h1>Resume Builder</h1>
          <p className="subtitle">Fill inputs on left. Resume updates live on right.</p>
        </div>

        <Actions className="builder-actions builder-actions-top" includeHome />

        <div className="form">
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
              checked={Boolean(form.isDefaultResume)}
              onChange={(e) => updateField('isDefaultResume', e.target.checked)}
            />
            Default resume
          </label>

          <label className="checkbox">
            <input
              type="checkbox"
              checked={Number(form.pageMarginIn || 0.3) <= 0.1}
              onChange={(e) => updateField('pageMarginIn', e.target.checked ? 0.1 : 0.3)}
            />
            Minimum margin
          </label>

          {saveState.message && <p className={saveState.message.startsWith('Saved') ? 'success' : 'error'}>{saveState.message}</p>}
          {importState.message && (
            <p className={importState.message.startsWith('Imported') ? 'success' : 'error'}>
              {importState.message}
            </p>
          )}

          <div className="section-options">
            <label>Typography</label>
            <div className="exp-row">
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
            <div className="exp-row">
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
              Controls apply to the preview and export.
            </p>
          </div>

          {showSectionOrder && (
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

          <div className="exp-editor">
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

          <input value={form.fullName} onChange={(e) => updateField('fullName', e.target.value)} placeholder="Full name" />
          <input value={form.role} onChange={(e) => updateField('role', e.target.value)} placeholder="Target role" />
          <input value={form.email} onChange={(e) => updateField('email', e.target.value)} placeholder="Email" />
          <input value={form.phone} onChange={(e) => updateField('phone', e.target.value)} placeholder="Phone" />
          <input value={form.location} onChange={(e) => updateField('location', e.target.value)} placeholder="Location" />

          <div className="exp-editor">
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

          <div className="section-options">
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

          {form.summaryEnabled && (
            <RichTextarea
              id="summary"
              label={form.summaryHeading || 'Summary'}
              value={form.summary}
              onChange={(value) => updateField('summary', value)}
              placeholder="Professional summary"
            />
          )}

          <RichTextarea
            id="skills"
            label="Skills"
            value={form.skills}
            onChange={(value) => updateField('skills', value)}
            placeholder="Add skills"
          />

          <div className="exp-editor">
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

                <div className="exp-row exp-row-tech">
                  <input
                    type="text"
                    value={exp.techStack ?? ''}
                    onChange={(e) => updateExperience(index, { techStack: e.target.value })}
                    placeholder="Tech stack (e.g. HTML, SCSS, React, Redux)"
                  />
                  <label className="checkbox exp-tech-toggle">
                    <input
                      type="checkbox"
                      checked={Boolean(exp.showTechUsed)}
                      onChange={(e) => updateExperience(index, { showTechUsed: e.target.checked })}
                    />
                    Show tech stack
                  </label>
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

          <div className="exp-editor">
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

                <div className="exp-row exp-row-tech">
                  <input
                    type="text"
                    value={proj.techStack ?? ''}
                    onChange={(e) => updateProject(index, { techStack: e.target.value })}
                    placeholder="Tech stack (e.g. React, Electron, Highcharts, Ant Design)"
                  />
                  <label className="checkbox exp-tech-toggle">
                    <input
                      type="checkbox"
                      checked={Boolean(proj.showTechUsed)}
                      onChange={(e) => updateProject(index, { showTechUsed: e.target.checked })}
                    />
                    Show tech stack
                  </label>
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

          <div className="edu-editor">
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
        </div>

      </section>

      <section className="preview-panel">
        <ResumeSheet form={form} />
      </section>
    </main>
  )
}

export default ResumeBuilderPage
