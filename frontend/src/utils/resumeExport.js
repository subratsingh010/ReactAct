function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
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

function htmlToBulletList(htmlValue) {
  const raw = String(htmlValue || '')
  if (!raw.trim()) return ''

  const parser = new DOMParser()
  const doc = parser.parseFromString(raw, 'text/html')
  const listItems = Array.from(doc.querySelectorAll('li'))
    .map((li) => String(li.textContent || '').replace(/\s+/g, ' ').trim())
    .filter(Boolean)

  if (listItems.length) {
    return `<ul>${listItems.map((line) => `<li>${escapeHtml(line)}</li>`).join('')}</ul>`
  }

  const text = plainTextFromHtml(raw)
  if (!text) return ''
  return `<p>${escapeHtml(text)}</p>`
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

function renderContact(form) {
  const links = (form.links || [])
    .map((item) => {
      const label = String(item.label || '').trim()
      const url = normalizeHttpUrl(item.url)
      if (!label || !url) return ''
      return `<a href="${escapeHtml(url)}">${escapeHtml(label)}</a>`
    })
    .filter(Boolean)
    .join(' | ')

  const contactLine = [form.location, form.phone, form.email]
    .map((value) => String(value || '').trim())
    .filter(Boolean)
    .join(' | ')

  return {
    contactLine,
    links,
  }
}

function renderTechStackLine(techStack, show) {
  if (!show) return ''
  const text = normalizeTechStackText(techStack)
  if (!text) return ''
  return `<p class="entry-tech-stack entry-tech-stack--end"><span class="entry-tech-stack-label">Tech Stack:</span> <span class="entry-tech-stack-items">${escapeHtml(text)}</span></p>`
}

function renderExperienceItem(exp, form) {
  const legacy = form && typeof form === 'object' ? form : {}
  const title = escapeHtml([exp.company, exp.title].filter(Boolean).join(' - '))
  const dates = escapeHtml([exp.startDate, exp.isCurrent ? 'Present' : exp.endDate].filter(Boolean).join(' - '))
  const tech = renderTechStackLine(exp.techStack, Boolean(exp.showTechUsed ?? legacy.showExperienceTechUsed))
  const bullets = htmlToBulletList(exp.highlights)

  return `
    <div class="entry">
      <div class="entry-head">
        <span>${title}</span>
        <span class="entry-dates">${dates}</span>
      </div>
      ${bullets}
      ${tech}
    </div>
  `
}

function renderProjectItem(proj, form) {
  const legacy = form && typeof form === 'object' ? form : {}
  const name = escapeHtml(proj.name || '')
  const url = normalizeHttpUrl(proj.url)
  const link = url ? `<a class="entry-link project-link" href="${escapeHtml(url)}">link</a>` : ''
  const tech = renderTechStackLine(proj.techStack, Boolean(proj.showTechUsed ?? legacy.showProjectTechUsed))
  const bullets = htmlToBulletList(proj.highlights)

  return `
    <div class="entry">
      <div class="entry-head">
        <span>${name}${link}</span>
      </div>
      ${bullets}
      ${tech}
    </div>
  `
}

function renderEducationItem(edu) {
  const schoolBits = [edu.institution, edu.program].filter(Boolean).join(' - ')
  const scoreType = String(edu.scoreType || 'cgpa')
  const rawScore = String(edu.scoreValue || '').trim()
  const scoreLabel = String(edu.scoreLabel || '').trim()
  const scoreText = (() => {
    if (!edu.scoreEnabled || !rawScore) return ''
    if (scoreType === 'custom') return `${scoreLabel || 'Score'}: ${rawScore}`
    if (scoreType === 'percentage') return `Percentage: ${rawScore.includes('%') ? rawScore : `${rawScore}%`}`
    return `CGPA: ${rawScore}`
  })()
  const dateLine = [edu.startDate, edu.isCurrent ? 'Present' : edu.endDate].filter(Boolean).join(' - ')
  const meta = [scoreText, dateLine].filter(Boolean).join(' | ')

  return `
    <div class="entry">
      <div class="entry-head">
        <span>${escapeHtml(schoolBits)}</span>
        <span class="entry-dates">${escapeHtml(meta)}</span>
      </div>
    </div>
  `
}

function renderCustomItem(section) {
  const title = escapeHtml(section.title || 'Custom section')
  const content = htmlToBulletList(section.content) || `<p>${escapeHtml(plainTextFromHtml(section.content))}</p>`
  return `
    <div class="entry">
      <div class="entry-head">
        <span>${title}</span>
      </div>
      ${content}
    </div>
  `
}

export function buildAtsPdfHtml(form) {
  const safeForm = form && typeof form === 'object' ? form : {}
  const sectionClass = safeForm.sectionUnderline ? 'section has-underline' : 'section'
  const bodyClass = 'compact'
  const headerClass = safeForm.sectionUnderline ? 'header' : 'header has-underline'
  const marginIn = Number(safeForm.pageMarginIn || 0.3)
  const safeMarginIn = Number.isFinite(marginIn) ? marginIn : 0.3
  const { contactLine, links } = renderContact(safeForm)
  const summaryHtml = String(safeForm.summary || '').trim()
  const skillsHtml = String(safeForm.skills || '').trim()

  const sections = []

  if (safeForm.summaryEnabled && summaryHtml) {
    sections.push(`
      <section class="${sectionClass}">
        <h2>${escapeHtml(safeForm.summaryHeading || 'Summary')}</h2>
        <div class="section-body">${summaryHtml}</div>
      </section>
    `)
  }

  if (skillsHtml) {
    sections.push(`
      <section class="${sectionClass}">
        <h2>Skills</h2>
        <div class="section-body">${skillsHtml}</div>
      </section>
    `)
  }

  if ((safeForm.experiences || []).length) {
    sections.push(`
      <section class="${sectionClass}">
        <h2>Experience</h2>
        ${(safeForm.experiences || []).map((exp) => renderExperienceItem(exp, safeForm)).join('')}
      </section>
    `)
  }

  if ((safeForm.projects || []).length) {
    sections.push(`
      <section class="${sectionClass}">
        <h2>Projects</h2>
        ${(safeForm.projects || []).map((proj) => renderProjectItem(proj, safeForm)).join('')}
      </section>
    `)
  }

  if ((safeForm.educations || []).length) {
    sections.push(`
      <section class="${sectionClass}">
        <h2>Education</h2>
        ${(safeForm.educations || []).map((edu) => renderEducationItem(edu)).join('')}
      </section>
    `)
  }

  if ((safeForm.customSections || []).length) {
    sections.push(`
      <section class="${sectionClass}">
        ${(safeForm.customSections || []).map((section) => renderCustomItem(section)).join('')}
      </section>
    `)
  }

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>${escapeHtml(safeForm.fullName || 'Resume')}</title>
  <style>
    @page {
      size: A4;
      margin: ${safeMarginIn}in;
    }

    html, body {
      margin: 0;
      padding: 0;
      background: #fff;
      color: #111827;
      font-family: Arial, Helvetica, sans-serif;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }

    body {
      padding: ${safeMarginIn}in;
      font-size: 10pt;
      line-height: 1.35;
    }

    body.compact {
      font-size: 9.5pt;
      line-height: 1.25;
    }

    h1 {
      margin: 0;
      font-size: 20pt;
      font-weight: 700;
      text-align: center;
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }

    .contact {
      margin-top: 3pt;
      text-align: center;
      font-size: 9.5pt;
    }

    .contact a {
      color: inherit;
      text-decoration: none;
    }

    .header {
      margin-bottom: 8pt;
      padding-bottom: 6pt;
      text-align: center;
    }

    .header.has-underline {
      border-bottom: 1px solid #d1d5db;
    }

    .section {
      margin-top: 8pt;
    }

    body.compact .section {
      margin-top: 4pt;
    }

    .section h2 {
      margin: 0 0 2pt;
      font-size: 11pt;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }

    .section.has-underline h2 {
      border-bottom: 1px solid #d1d5db;
      padding-bottom: 1pt;
    }

    body.compact .section h2 {
      margin: 0 0 1pt;
    }

    .section p {
      margin: 2pt 0 0;
      font-size: 9.5pt;
      line-height: 1.35;
    }

    body.compact .section p {
      margin: 1pt 0 0;
      line-height: 1.25;
    }

    .entry {
      margin-top: 4pt;
    }

    body.compact .entry {
      margin-top: 2pt;
    }

    .entry-head {
      display: flex;
      justify-content: space-between;
      gap: 12pt;
      align-items: baseline;
      font-size: 9.75pt;
      font-weight: 700;
    }

    .entry-dates,
    .entry-link {
      font-weight: 400;
      font-size: 9pt;
      color: #374151;
      text-decoration: none;
      white-space: nowrap;
    }

    .project-link {
      margin-left: 3pt;
      display: inline-block;
      text-decoration: none;
    }

    .entry-tech-stack {
      display: block;
      font-size: inherit;
      line-height: inherit;
    }

    .entry-tech-stack--end {
      margin-top: 5pt;
    }

    body.compact .entry-tech-stack--end {
      margin-top: 3pt;
    }

    .entry-tech-stack-label {
      flex: 0 0 auto;
      font-weight: 600;
      letter-spacing: 0.03em;
      color: #0f172a;
    }

    .entry-tech-stack-items {
      color: #1f2937;
      font-weight: 600;
    }

    ul {
      margin: 4pt 0 0;
      padding-left: 16pt;
    }

    body.compact ul {
      margin-top: 2pt;
    }

    li {
      margin: 1.5pt 0;
      font-size: 9.5pt;
      line-height: 1.3;
    }

    body.compact li {
      margin: 1pt 0;
      line-height: 1.2;
    }

    .plain-links {
      margin-top: 7pt;
      text-align: center;
      font-size: 9pt;
      word-break: break-word;
    }

    .plain-links a {
      color: inherit;
      text-decoration: none;
    }

    * {
      box-shadow: none !important;
      text-shadow: none !important;
      filter: none !important;
    }
  </style>
</head>
<body class="${bodyClass}">
  <header class="${headerClass}">
    <h1>${escapeHtml(safeForm.fullName || '')}</h1>
    <div class="contact">${escapeHtml(contactLine)}</div>
    ${links ? `<div class="plain-links">${links}</div>` : ''}
  </header>
  ${sections.join('')}
</body>
</html>`
}

export function printAtsPdf(form) {
  const html = buildAtsPdfHtml(form)
  const iframe = document.createElement('iframe')
  iframe.setAttribute('aria-hidden', 'true')
  iframe.style.position = 'fixed'
  iframe.style.right = '0'
  iframe.style.bottom = '0'
  iframe.style.width = '0'
  iframe.style.height = '0'
  iframe.style.border = '0'
  iframe.style.visibility = 'hidden'

  let printed = false
  let cleanupTimer = null
  let pollTimer = null

  const cleanup = () => {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    if (cleanupTimer) {
      clearTimeout(cleanupTimer)
      cleanupTimer = null
    }
    cleanupTimer = setTimeout(() => {
      iframe.remove()
    }, 1000)
  }

  const triggerPrint = () => {
    if (printed) return
    const win = iframe.contentWindow
    const doc = iframe.contentDocument
    const bodyHtml = String(doc?.body?.innerHTML || '').trim()
    if (!win || !bodyHtml) {
      return
    }

    printed = true
    const finish = () => cleanup()
    win.onafterprint = finish
    win.focus()
    try {
      win.print()
    } catch {
      finish()
    }
  }

  document.body.appendChild(iframe)
  iframe.srcdoc = html

  pollTimer = setInterval(() => {
    triggerPrint()
    if (printed && pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }, 80)
}
