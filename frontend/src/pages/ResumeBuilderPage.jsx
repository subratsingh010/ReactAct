import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import RichTextarea from '../components/RichTextarea'
import ResumeSheet from '../components/ResumeSheet'
import { createResume } from '../api'

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
      const link = url ? ` <span style="color:#6b778f;font-style:italic;">(${escapeHtml(url)})</span>` : ''
      return `<div style="margin-top:10px;"><div><strong>${name}</strong>${link}</div>${richTextToHtml(
        p.highlights || '',
      )}</div>`
    })
    .join('')

  const experiences = (form.experiences || [])
    .map((e) => {
      const left = [e.company, e.title].map((v) => String(v || '').trim()).filter(Boolean).join(' – ')
      const right = [e.startDate, e.isCurrent ? 'Present' : e.endDate]
        .map((v) => String(v || '').trim())
        .filter(Boolean)
        .join(' – ')
      return `<div style="margin-top:10px;">
        <div style="display:flex;justify-content:space-between;gap:12px;">
          <div><strong>${inlineToHtml(left)}</strong></div>
          <div style="color:#3a4861;white-space:nowrap;">${inlineToHtml(right)}</div>
        </div>
        ${richTextToHtml(e.highlights || '')}
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
    ? `<h3>${summaryTitle}</h3>${richTextToHtml(form.summary)}`
    : ''

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Resume</title>
  <style>
    body { font-family: Calibri, Arial, sans-serif; }
    h1 { margin: 0; text-align: center; }
    .center { text-align: center; color: #3a4861; margin-top: 4px; }
    h3 { margin: 14px 0 8px; font-size: 12px; letter-spacing: 0.06em; text-transform: uppercase; }
    p, li { font-size: ${safeFontSize}pt; line-height: ${safeLineHeight}; margin: 6px 0; }
    ul, ol { margin: 6px 0 0; padding-left: 18px; }
    a { color: #1b2230; text-decoration: underline; }
  </style>
</head>
<body>
  <h1>${escapeHtml(form.fullName || '')}</h1>
  <div class="center">${escapeHtml(contact)}</div>
  ${links ? `<div class="center">${links}</div>` : ''}
  ${summarySection}
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
    bodyFontSizePt: 10,
    bodyLineHeight: 1,
    sectionOrder: ['summary', 'skills', 'experience', 'projects', 'education'],
    sectionUnderline: false,
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
  const [resumeRecordId, setResumeRecordId] = useState(() => sessionStorage.getItem('builderResumeId'))
  const [saveState, setSaveState] = useState({ saving: false, message: '' })

  useEffect(() => {
    const raw = sessionStorage.getItem('builderImport')
    if (raw) {
      try {
        const imported = JSON.parse(raw)
        if (imported && typeof imported === 'object') {
          setForm((prev) => ({ ...prev, ...imported }))
        }
      } catch {
        // ignore
      }
      sessionStorage.removeItem('builderImport')
    }

    const id = sessionStorage.getItem('builderResumeId')
    if (id) setResumeRecordId(id)
  }, [])

  const updateField = (key, value) => {
    setForm((prev) => ({ ...prev, [key]: value }))
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
        { company: '', title: '', startDate: '', endDate: '', isCurrent: true, highlights: '- ' },
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
      projects: [...(prev.projects || []), { name: '', url: '', highlights: '- ' }],
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
      }

      // Upsert by title: same title overwrites; different title creates new entry.
      const data = await createResume(access, payload)

      setResumeRecordId(String(data.id))
      sessionStorage.setItem('builderResumeId', String(data.id))
      setSaveState({ saving: false, message: `Saved: ${new Date().toLocaleTimeString()}` })
    } catch (err) {
      setSaveState({ saving: false, message: err.message || 'Save failed' })
    }
  }

  const Actions = ({ className, includeHome }) => (
    <div className={className}>
      <button type="button" onClick={saveResumeToAccount} disabled={saveState.saving}>
        {saveState.saving ? 'Saving...' : 'Save'}
      </button>
      <button type="button" className="secondary" onClick={downloadDoc}>
        Download DOC
      </button>
      <button type="button" className="secondary" onClick={() => window.print()}>
        Exact PDF (Print)
      </button>
      {includeHome && (
        <button type="button" className="secondary" onClick={() => navigate('/')}>
          Back Home
        </button>
      )}
    </div>
  )

  return (
    <main className="builder-layout">
      <section className="builder-panel">
        <div className="builder-header">
          <h1>Resume Builder</h1>
          <p className="subtitle">Fill inputs on left. Resume updates live on right.</p>
        </div>

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

          {saveState.message && <p className={saveState.message.startsWith('Saved') ? 'success' : 'error'}>{saveState.message}</p>}

          <div className="section-options">
            <label>Typography</label>
            <div className="exp-row">
              <select
                value={String(form.bodyFontSizePt || 10)}
                onChange={(e) => updateField('bodyFontSizePt', Number(e.target.value))}
              >
                <option value="9">Text size: 9</option>
                <option value="10">Text size: 10</option>
                <option value="11">Text size: 11</option>
                <option value="12">Text size: 12</option>
              </select>
              <select
                value={String(form.bodyLineHeight || 1)}
                onChange={(e) => updateField('bodyLineHeight', Number(e.target.value))}
              >
                <option value="1">Line spacing: 1.0</option>
                <option value="1.1">Line spacing: 1.1</option>
                <option value="1.15">Line spacing: 1.15</option>
                <option value="1.2">Line spacing: 1.2</option>
                <option value="1.3">Line spacing: 1.3</option>
                <option value="1.4">Line spacing: 1.4</option>
              </select>
            </div>
            <p className="hint" style={{ margin: 0 }}>
              Controls apply to the A4 preview and export.
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

        <Actions className="builder-actions" includeHome />
        <p className="builder-actions-hint">
          Use Exact PDF (Print) to export with the same design as the preview (A4).
        </p>
      </section>

      <section className="preview-panel">
        <Actions className="preview-actions" />
        <ResumeSheet form={form} />
      </section>
    </main>
  )
}

export default ResumeBuilderPage
