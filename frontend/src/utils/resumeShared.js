export const MIN_PAGE_MARGIN_IN = 0.2
export const DEFAULT_PAGE_MARGIN_IN = 0.3
export const TOP_PAGE_PADDING_OFFSET_IN = 0.08

const SECTION_META = [
  { key: 'summary', label: 'Summary' },
  { key: 'skills', label: 'Skills' },
  { key: 'experience', label: 'Experience' },
  { key: 'projects', label: 'Projects' },
  { key: 'education', label: 'Education' },
]

const CUSTOM_KEY_PREFIX = 'custom:'
const PLACEHOLDER_SNIPPETS = [
  'write 3+ bullets',
  'write 3 bullets',
  'add 2-3 bullet points',
  'add 2-3 bullets',
  'what you built',
  'what impact',
  'replace with your',
  'lorem ipsum',
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

function isPlaceholderText(value) {
  const low = plainTextFromHtml(value).toLowerCase()
  if (!low) return true
  if (PLACEHOLDER_SNIPPETS.some((snippet) => low.includes(snippet))) return true
  return /^(write|add|include|replace)\b[\w\s,+/%-]{0,90}$/.test(low)
}

export function normalizePageMarginIn(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return DEFAULT_PAGE_MARGIN_IN
  if (numeric <= MIN_PAGE_MARGIN_IN) return MIN_PAGE_MARGIN_IN
  return DEFAULT_PAGE_MARGIN_IN
}

export function computeTopPagePaddingIn(marginIn) {
  return Math.max(0.08, Number(marginIn) - TOP_PAGE_PADDING_OFFSET_IN)
}

export function normalizeHttpUrl(value) {
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
  if (isCurrent) return 999912
  const raw = String(value || '').trim()
  if (!raw) return 0

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

function formatEducationScore(edu, { forceWhenValue }) {
  const scoreType = String(edu?.scoreType || 'cgpa')
  const rawScore = String(edu?.scoreValue || '').trim()
  const scoreLabel = String(edu?.scoreLabel || '').trim()

  if (!rawScore) return ''
  if (!forceWhenValue && !edu?.scoreEnabled) return ''
  if (scoreType === 'custom') return `${scoreLabel || 'Score'}: ${rawScore}`
  if (scoreType === 'percentage') return `Percentage: ${rawScore.includes('%') ? rawScore : `${rawScore}%`}`
  return `CGPA: ${rawScore}`
}

function buildOrderedKeys(form) {
  const getCustomByKey = (key) => {
    if (!key.startsWith(CUSTOM_KEY_PREFIX)) return null
    const id = key.slice(CUSTOM_KEY_PREFIX.length)
    return (form.customSections || []).find((s) => s.id === id) || null
  }

  return (form.sectionOrder || SECTION_META.map((s) => s.key)).filter((k) => {
    if (SECTION_META.some((s) => s.key === k)) return true
    if (k.startsWith(CUSTOM_KEY_PREFIX)) return Boolean(getCustomByKey(k))
    return false
  })
}

export function buildResumeViewModel(form, options = {}) {
  const safeForm = form && typeof form === 'object' ? form : {}
  const forceEducationScoreWhenValue = Boolean(options.forceEducationScoreWhenValue)
  const pageMarginIn = normalizePageMarginIn(safeForm.pageMarginIn)
  const topPagePaddingIn = computeTopPagePaddingIn(pageMarginIn)

  const rawSummaryHtml = String(safeForm.summary || '')
  const rawSkillsHtml = String(safeForm.skills || '')
  const summaryHtml = isPlaceholderText(rawSummaryHtml) ? '' : rawSummaryHtml
  const skillsHtml = isPlaceholderText(rawSkillsHtml) ? '' : rawSkillsHtml

  const experiences = sortNewestFirst(
    (safeForm.experiences || []).map((exp) => ({
      ...exp,
      company: String(exp?.company || '').trim(),
      title: String(exp?.title || '').trim(),
      startDate: String(exp?.startDate || '').trim(),
      endDate: String(exp?.endDate || '').trim(),
      highlights: String(exp?.highlights || ''),
      isCurrent: Boolean(exp?.isCurrent),
    }))
      .map((exp) => {
        const highlightsText = plainTextFromHtml(exp.highlights)
        return {
          ...exp,
          highlights: isPlaceholderText(highlightsText) ? '' : exp.highlights,
        }
      })
      .filter((exp) => {
        const highlightsText = plainTextFromHtml(exp.highlights)
        return Boolean(exp.company || exp.title || highlightsText)
      }),
    (e) => dateKey(e.endDate, e.isCurrent),
    (e) => dateKey(e.startDate, false),
  )

  const projects = (safeForm.projects || [])
    .map((proj) => ({
      ...proj,
      name: String(proj?.name || '').trim(),
      normalizedUrl: normalizeHttpUrl(proj?.url),
      highlights: String(proj?.highlights || ''),
    }))
    .map((proj) => {
      const highlightsText = plainTextFromHtml(proj.highlights)
      return {
        ...proj,
        highlights: isPlaceholderText(highlightsText) ? '' : proj.highlights,
      }
    })
    .filter((proj) => {
      const highlightsText = plainTextFromHtml(proj.highlights)
      return Boolean(proj.name || highlightsText)
    })

  const educations = sortNewestFirst(
    (safeForm.educations || []).map((edu) => ({
      ...edu,
      institution: String(edu?.institution || '').trim(),
      program: String(edu?.program || '').trim(),
      startDate: String(edu?.startDate || '').trim(),
      endDate: String(edu?.endDate || '').trim(),
      isCurrent: Boolean(edu?.isCurrent),
      scoreText: formatEducationScore(edu, { forceWhenValue: forceEducationScoreWhenValue }),
    }))
      .filter((edu) => Boolean(edu.institution || edu.program || edu.scoreText)),
    (e) => dateKey(e.endDate, e.isCurrent),
    (e) => dateKey(e.startDate, false),
  )

  const customSections = (safeForm.customSections || [])
    .map((section) => ({
      id: String(section?.id || ''),
      title: String(section?.title || ''),
      content: String(section?.content || ''),
    }))
    .filter((section) => {
      const contentText = plainTextFromHtml(section.content)
      return Boolean(section.title.trim() || (contentText && !isPlaceholderText(contentText)))
    })

  const links = (safeForm.links || [])
    .map((item) => ({
      label: String(item?.label || '').trim(),
      url: normalizeHttpUrl(item?.url),
    }))
    .filter((item) => item.label && item.url)

  const contactLine = [safeForm.location, safeForm.phone, safeForm.email]
    .map((value) => String(value || '').trim())
    .filter(Boolean)
    .join(' | ')

  return {
    fullName: String(safeForm.fullName || ''),
    summaryEnabled: Boolean(safeForm.summaryEnabled),
    summaryHeading: String(safeForm.summaryHeading || 'Summary'),
    sectionUnderline: Boolean(safeForm.sectionUnderline),
    bodyFontFamily: String(safeForm.bodyFontFamily || 'Arial, Helvetica, sans-serif'),
    bodyFontSizePt: Number(safeForm.bodyFontSizePt || 10),
    bodyLineHeight: Number(safeForm.bodyLineHeight || 1),
    pageMarginIn,
    topPagePaddingIn,
    contactLine,
    links,
    summaryHtml,
    skillsHtml,
    experiences,
    projects,
    educations,
    customSections,
    customKeyPrefix: CUSTOM_KEY_PREFIX,
    orderedKeys: buildOrderedKeys(safeForm),
  }
}
