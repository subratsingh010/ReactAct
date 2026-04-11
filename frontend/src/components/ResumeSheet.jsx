import { useMemo } from 'react'

function renderSummaryByStyle(text) {
  // The builder stores sanitized HTML already.
  return String(text || '')
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

function techStackBlock(techStack) {
  const text = String(techStack || '')
    .replace(/\s*,\s*/g, ', ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!text) return null
  return (
    <p className="resume-tech-stack resume-tech-stack--end" role="group" aria-label="Tech stack">
      <span className="resume-tech-stack-label">Tech Stack:</span>{' '}
      <span className="resume-tech-stack-items">{text}</span>
    </p>
  )
}

function buildOrderedKeys(form) {
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

  return (form.sectionOrder || sectionMeta.map((s) => s.key)).filter((k) => {
    if (sectionMeta.some((s) => s.key === k)) return true
    if (k.startsWith(customKeyPrefix)) return Boolean(getCustomByKey(k))
    return false
  })
}

export default function ResumeSheet({ form }) {
  const safeForm = form && typeof form === 'object' ? form : {}

  const orderedKeys = useMemo(() => buildOrderedKeys(safeForm), [safeForm])
  const bodyFontSize = Number(safeForm.bodyFontSizePt || 10)
  const bodyLineHeight = Number(safeForm.bodyLineHeight || 1)
  const bodyFontFamily = String(safeForm.bodyFontFamily || 'Arial, Helvetica, sans-serif')
  const pageMarginIn = Number(safeForm.pageMarginIn || 0.3)
  const safePageMarginIn = Number.isFinite(pageMarginIn) ? pageMarginIn : 0.3
  const compactSpacing = true

  const parsed = useMemo(
    () => ({
      summary: renderSummaryByStyle(safeForm.summary, safeForm.summaryStyle),
      skills: String(safeForm.skills || ''),
      experiences: sortNewestFirst(
        (safeForm.experiences || []).map((exp) => ({
          ...exp,
          techStack: String(exp.techStack || ''),
          highlights: String(exp.highlights || ''),
        })),
        (e) => dateKey(e.endDate, e.isCurrent),
        (e) => dateKey(e.startDate, false),
      ),
      projects: (safeForm.projects || []).map((proj) => ({
        ...proj,
        techStack: String(proj.techStack || ''),
        normalizedUrl: normalizeHttpUrl(proj.url),
        highlights: String(proj.highlights || ''),
      })),
      educations: sortNewestFirst(
        (safeForm.educations || []).map((edu) => ({ ...edu })),
        (e) => dateKey(e.endDate, e.isCurrent),
        (e) => dateKey(e.startDate, false),
      ),
      customSections: safeForm.customSections || [],
    }),
    [safeForm],
  )

  const customKeyPrefix = 'custom:'
  const getCustomByKey = (key) => {
    if (!key.startsWith(customKeyPrefix)) return null
    const id = key.slice(customKeyPrefix.length)
    return (safeForm.customSections || []).find((s) => s.id === id) || null
  }

  const sectionClass = `resume-section${safeForm.sectionUnderline ? ' has-underline' : ''}`

  return (
    <article
      className={`resume-sheet${compactSpacing ? ' is-compact' : ''}`}
      style={{
      '--resume-font-family': bodyFontFamily,
      '--resume-font-size': `${Number.isFinite(bodyFontSize) ? bodyFontSize : 10}pt`,
      '--resume-line-height': `${Number.isFinite(bodyLineHeight) ? bodyLineHeight : 1}`,
      '--resume-sheet-padding': `${safePageMarginIn}in`,
    }}
    >
      <header className={`resume-head${safeForm.sectionUnderline ? ' no-divider' : ''}`}>
        <h2>{safeForm.fullName || 'Your Name'}</h2>
        <p className="resume-head-line">
          {[safeForm.location, safeForm.phone, safeForm.email]
            .map((v) => String(v || '').trim())
            .filter(Boolean)
            .join(' | ')}
        </p>
        {(() => {
          const nodes = (safeForm.links || [])
            .map((item) => renderLink(String(item.label || '').trim() || 'link', item.url))
            .filter(Boolean)
          if (!nodes.length) return null
          return (
            <p className="resume-head-links">
              {nodes.reduce((acc, node, idx) => {
                if (idx === 0) return [node]
                return [...acc, ' | ', node]
              }, [])}
            </p>
          )
        })()}
      </header>

      {orderedKeys.map((key) => {
        if (key === 'summary') {
          if (!safeForm.summaryEnabled) return null
          return (
            <div key="summary" className={sectionClass}>
              <h3>{safeForm.summaryHeading || 'Summary'}</h3>
              <div className="resume-summary" dangerouslySetInnerHTML={{ __html: parsed.summary }} />
            </div>
          )
        }

        if (key === 'skills') {
          return (
            <div key="skills" className={sectionClass}>
              <h3>Skills</h3>
              <div className="resume-rich" dangerouslySetInnerHTML={{ __html: parsed.skills }} />
            </div>
          )
        }

        if (key === 'experience') {
          return (
            <div key="experience" className={sectionClass}>
              <h3>Experience</h3>
              {parsed.experiences.map((exp, index) => (
                <div key={`exp-prev-${index}`} className="resume-exp">
                  <div className="resume-exp-head">
                    <div className="resume-exp-left">
                      <span className="resume-exp-company">{exp.company || ''}</span>
                      {exp.company?.trim() && exp.title?.trim() && (
                        <span className="resume-exp-sep"> – </span>
                      )}
                      <span className="resume-exp-title">{exp.title || ''}</span>
                    </div>
                    <div className="resume-exp-right">
                      {[exp.startDate, exp.isCurrent ? 'Present' : exp.endDate]
                        .map((v) => String(v || '').trim())
                        .filter(Boolean)
                        .join(' – ')}
                    </div>
                  </div>
                  <div className="resume-exp-body">
                    <div className="resume-rich" dangerouslySetInnerHTML={{ __html: exp.highlights }} />
                    {Boolean(exp.showTechUsed ?? safeForm.showExperienceTechUsed) &&
                      techStackBlock(exp.techStack)}
                  </div>
                </div>
              ))}
            </div>
          )
        }

        if (key === 'projects') {
          return (
            <div key="projects" className={sectionClass}>
              <h3>Projects</h3>
              {parsed.projects.map((proj, index) => (
                <div key={`proj-prev-${index}`} className="resume-exp">
                  <div className="resume-exp-head">
                    <div className="resume-exp-left">
                      <span className="resume-exp-company">{proj.name || ''}</span>
                      {proj.normalizedUrl && (
                        <a
                          className="resume-link resume-project-link"
                          href={proj.normalizedUrl}
                          target="_blank"
                          rel="noreferrer"
                          data-url={proj.normalizedUrl}
                        >
                          link
                        </a>
                      )}
                    </div>
                    <div className="resume-exp-right" />
                  </div>
                  <div className="resume-exp-body">
                    <div className="resume-rich" dangerouslySetInnerHTML={{ __html: proj.highlights }} />
                    {Boolean(proj.showTechUsed ?? safeForm.showProjectTechUsed) &&
                      techStackBlock(proj.techStack)}
                  </div>
                </div>
              ))}
            </div>
          )
        }

        if (key === 'education') {
          return (
            <div key="education" className={sectionClass}>
              <h3>Education</h3>
              {(parsed.educations || []).map((edu, index) => {
                const scoreType = String(edu.scoreType || 'cgpa')
                const rawScore = String(edu.scoreValue || '').trim()
                const scoreLabel = String(edu.scoreLabel || '').trim()

                const scoreText = (() => {
                  if (!edu.scoreEnabled || !rawScore) return ''

                  if (scoreType === 'custom') {
                    const label = scoreLabel || 'Score'
                    return `${label}: ${rawScore}`
                  }

                  if (scoreType === 'percentage') {
                    const score = rawScore.includes('%') ? rawScore : `${rawScore}%`
                    return `Percentage: ${score}`
                  }

                  return `CGPA: ${rawScore}`
                })()

                const right = [edu.startDate, edu.isCurrent ? 'Present' : edu.endDate]
                  .map((v) => String(v || '').trim())
                  .filter(Boolean)
                  .join(' – ')

                return (
                  <div key={`edu-prev-${index}`} className="resume-exp">
                    <div className="resume-exp-head">
                      <div className="resume-exp-left">
                        <div className="resume-edu-inst">
                          <span className="resume-exp-company">
                            {edu.institution?.trim() || ''}
                          </span>
                        </div>
                        {(edu.program?.trim() || scoreText) && (
                          <div className="resume-edu-meta">
                            {edu.program?.trim() && (
                              <span className="resume-exp-title">
                                {edu.program?.trim() || ''}
                              </span>
                            )}
                            {edu.program?.trim() && scoreText && (
                              <span className="resume-exp-sep"> | </span>
                            )}
                            {scoreText && <span className="resume-exp-title">{scoreText}</span>}
                          </div>
                        )}
                      </div>
                      <div className="resume-exp-right">{right}</div>
                    </div>
                  </div>
                )
              })}
            </div>
          )
        }

        if (key.startsWith(customKeyPrefix)) {
          const custom = getCustomByKey(key)
          if (!custom) return null
          return (
            <div key={key} className={sectionClass}>
              <h3>{custom.title?.trim() || 'Custom section'}</h3>
              <div className="resume-rich" dangerouslySetInnerHTML={{ __html: String(custom.content || '') }} />
            </div>
          )
        }

        return null
      })}
    </article>
  )
}
