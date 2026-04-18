import { buildResumeViewModel } from './resumeShared.js'

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

function sanitizeRichHtml(value) {
  if (typeof DOMParser === 'undefined') {
    return String(value || '').trim()
  }
  const parser = new DOMParser()
  const doc = parser.parseFromString(`<div>${String(value || '')}</div>`, 'text/html')
  const root = doc.body.firstElementChild
  if (!root) return ''

  // Remove script/style tags from rich editor payload.
  root.querySelectorAll('script,style').forEach((node) => node.remove())

  const walker = doc.createTreeWalker(root, NodeFilter.SHOW_ELEMENT)
  const nodes = []
  let node = walker.nextNode()
  while (node) {
    nodes.push(node)
    node = walker.nextNode()
  }

  nodes.forEach((el) => {
    // Keep links safe.
    if (el.tagName === 'A') {
      const href = String(el.getAttribute('href') || '').trim()
      const safe = /^(https?:\/\/|mailto:|tel:)/i.test(href) ? href : ''
      el.setAttribute('href', safe)
      if (safe) {
        el.setAttribute('target', '_blank')
        el.setAttribute('rel', 'noreferrer')
      } else {
        el.removeAttribute('target')
        el.removeAttribute('rel')
      }
    }
    // Remove JS event handlers, keep formatting attrs/styles from editor.
    Array.from(el.attributes || []).forEach((attr) => {
      const name = String(attr.name || '').toLowerCase()
      if (name.startsWith('on')) el.removeAttribute(attr.name)
    })
  })

  return root.innerHTML
}

function htmlToBulletList(htmlValue) {
  const raw = String(htmlValue || '')
  if (!raw.trim()) return ''
  const rich = sanitizeRichHtml(raw)
  if (rich.trim()) return rich

  const text = plainTextFromHtml(raw)
  if (!text) return ''
  return `<p>${escapeHtml(text)}</p>`
}

function renderExperienceItem(exp) {
  const company = escapeHtml(exp.company || '')
  const title = escapeHtml(exp.title || '')
  const dates = escapeHtml([exp.startDate, exp.isCurrent ? 'Present' : exp.endDate].filter(Boolean).join(' - '))
  const content = htmlToBulletList(exp.highlights)

  return `
    <div class="resume-exp">
      <div class="resume-exp-head">
        <div class="resume-exp-left">
          ${company ? `<span class="resume-exp-company">${company}</span>` : ''}
          ${company && title ? '<span class="resume-exp-sep"> - </span>' : ''}
          ${title ? `<span class="resume-exp-title">${title}</span>` : ''}
        </div>
        <span class="resume-exp-right">${dates}</span>
      </div>
      <div class="resume-exp-body resume-rich">${content}</div>
    </div>
  `
}

function renderProjectItem(project) {
  const name = escapeHtml(project.name || '')
  const link = project.normalizedUrl
    ? `<a class="resume-link resume-project-link" href="${escapeHtml(project.normalizedUrl)}">link</a>`
    : ''
  const content = htmlToBulletList(project.highlights)

  return `
    <div class="resume-exp">
      <div class="resume-exp-head">
        <div class="resume-exp-left">
          ${name ? `<span class="resume-exp-company">${name}</span>` : ''}
          ${link}
        </div>
      </div>
      <div class="resume-exp-body resume-rich">${content}</div>
    </div>
  `
}

function renderEducationItem(edu) {
  const dateLine = [edu.startDate, edu.isCurrent ? 'Present' : edu.endDate].filter(Boolean).join(' - ')

  return `
    <div class="resume-exp">
      <div class="resume-exp-head">
        <div class="resume-exp-left">
          ${edu.institution ? `<div class="resume-edu-inst"><span class="resume-exp-company">${escapeHtml(edu.institution)}</span></div>` : ''}
          ${edu.program || edu.scoreText
            ? `<div class="resume-edu-meta">${edu.program ? `<span class="resume-exp-title">${escapeHtml(edu.program)}</span>` : ''}${
                edu.program && edu.scoreText ? '<span class="resume-exp-sep"> | </span>' : ''
              }${edu.scoreText ? `<span class="resume-exp-title">${escapeHtml(edu.scoreText)}</span>` : ''}</div>`
            : ''}
        </div>
        ${dateLine ? `<span class="resume-exp-right">${escapeHtml(dateLine)}</span>` : ''}
      </div>
    </div>
  `
}

function renderCustomSection(section, sectionClass) {
  const title = escapeHtml(section.title || 'Custom section')
  const content = htmlToBulletList(section.content) || `<p>${escapeHtml(plainTextFromHtml(section.content))}</p>`
  return `
    <section class="${sectionClass}">
      <h2>${title}</h2>
      <div class="resume-rich">${content}</div>
    </section>
  `
}

export function buildAtsPdfHtml(form) {
  const model = buildResumeViewModel(form, { forceEducationScoreWhenValue: true })
  const safeBodyFontFamily = String(model.bodyFontFamily || 'Arial, Helvetica, sans-serif').trim() || 'Arial, Helvetica, sans-serif'
  const safeFontSizePt = Number.isFinite(model.bodyFontSizePt) ? Math.max(8, Math.min(16, Number(model.bodyFontSizePt))) : 10
  const safeLineHeight = Number.isFinite(model.bodyLineHeight) ? Math.max(0.9, Math.min(2.0, Number(model.bodyLineHeight))) : 1.25
  const sectionClass = model.sectionUnderline ? 'resume-section has-underline' : 'resume-section'
  const bodyClass = ''
  const headerClass = model.sectionUnderline ? 'resume-head no-divider' : 'resume-head'
  const linksHtml = model.links
    .map((item) => `<a href="${escapeHtml(item.url)}">${escapeHtml(item.label)}</a>`)
    .join(' | ')

  const getCustomByKey = (key) => {
    if (!key.startsWith(model.customKeyPrefix)) return null
    const id = key.slice(model.customKeyPrefix.length)
    return model.customSections.find((section) => section.id === id) || null
  }

  const sections = []
  model.orderedKeys.forEach((key) => {
    if (key === 'summary') {
      if (!model.summaryEnabled || !model.summaryHtml.trim()) return
      sections.push(`
        <section class="${sectionClass}">
          <h2>${escapeHtml(model.summaryHeading || 'Summary')}</h2>
          <div class="resume-summary">${model.summaryHtml}</div>
        </section>
      `)
      return
    }

    if (key === 'skills') {
      if (!model.skillsHtml.trim()) return
      sections.push(`
        <section class="${sectionClass}">
          <h2>Skills</h2>
          <div class="resume-rich">${model.skillsHtml}</div>
        </section>
      `)
      return
    }

    if (key === 'experience') {
      if (!model.experiences.length) return
      sections.push(`
        <section class="${sectionClass}">
          <h2>Experience</h2>
          ${model.experiences.map((exp) => renderExperienceItem(exp)).join('')}
        </section>
      `)
      return
    }

    if (key === 'projects') {
      if (!model.projects.length) return
      sections.push(`
        <section class="${sectionClass}">
          <h2>Projects</h2>
          ${model.projects.map((project) => renderProjectItem(project)).join('')}
        </section>
      `)
      return
    }

    if (key === 'education') {
      if (!model.educations.length) return
      sections.push(`
        <section class="${sectionClass}">
          <h2>Education</h2>
          ${model.educations.map((edu) => renderEducationItem(edu)).join('')}
        </section>
      `)
      return
    }

    if (key.startsWith(model.customKeyPrefix)) {
      const custom = getCustomByKey(key)
      if (!custom) return
      sections.push(renderCustomSection(custom, sectionClass))
    }
  })

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>${escapeHtml(model.fullName || 'Resume')}</title>
  <style>
    @page {
      size: A4;
      margin: ${model.pageMarginIn}in;
    }

    html, body {
      margin: 0;
      padding: 0;
      background: #fff;
      color: #111827;
      font-family: ${escapeHtml(safeBodyFontFamily)};
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }

    body {
      padding: ${model.topPagePaddingIn}in ${model.pageMarginIn}in ${model.pageMarginIn}in;
      font-size: ${safeFontSizePt}pt;
      line-height: ${safeLineHeight};
    }

    .resume-sheet {
      color: #111827;
      font-family: ${escapeHtml(safeBodyFontFamily)};
      font-size: ${safeFontSizePt}pt;
      line-height: ${safeLineHeight};
    }

    .resume-head {
      margin-bottom: 4pt;
      padding-bottom: 2pt;
      text-align: center;
      border-bottom: 1px solid #d1d5db;
    }

    .resume-head.no-divider {
      border-bottom: 0;
    }

    .resume-head h1 {
      margin: 0;
      font-size: 20pt;
      font-weight: 700;
      text-align: center;
      letter-spacing: 0.02em;
    }

    .resume-head-line,
    .resume-head-links {
      color: #374151;
      font-size: inherit;
      text-align: center;
    }

    .resume-head-line {
      margin-top: 1pt;
    }

    .resume-head-links {
      margin-top: 2pt;
      word-break: break-word;
    }

    .resume-head-links a,
    .resume-link {
      color: inherit;
      text-decoration: none;
      font-weight: 400;
    }

    .resume-section {
      margin-top: 8pt;
      margin-bottom: 3pt;
    }

    .resume-section h2 {
      margin: 0 0 2pt;
      font-size: 11pt;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }

    .resume-section.has-underline h2 {
      border-bottom: 1px solid #d1d5db;
      padding-bottom: 1pt;
    }

    .resume-exp {
      margin-top: 4pt;
    }

    .resume-exp-head {
      display: flex;
      justify-content: space-between;
      gap: 12pt;
      align-items: baseline;
      font-size: inherit;
      font-weight: 700;
    }

    .resume-exp-left {
      min-width: 0;
      flex: 1;
    }

    .resume-exp-company {
      color: #111827;
      font-weight: 700;
    }

    .resume-exp-title,
    .resume-exp-sep {
      color: #111827;
    }

    .resume-exp-right,
    .resume-project-link {
      font-weight: 400;
      font-size: inherit;
      color: #374151;
      text-decoration: none;
      white-space: nowrap;
    }

    .resume-exp-body {
      margin-top: 0;
    }

    .resume-edu-inst {
      line-height: 1.25;
    }

    .resume-edu-meta {
      margin-top: 1pt;
      line-height: 1.25;
      font-weight: 400;
    }

    .resume-edu-meta .resume-exp-title,
    .resume-edu-meta .resume-exp-sep {
      font-weight: 400;
    }

    .resume-project-link {
      margin-left: 3pt;
      display: inline-block;
    }

    .resume-rich,
    .resume-summary {
      color: #111827;
    }

    .resume-rich p,
    .resume-summary p {
      margin: 2pt 0 0;
      line-height: 1.35;
    }

    .resume-rich ul,
    .resume-summary ul {
      margin: 4pt 0 0;
      padding-left: 16pt;
    }

    .resume-rich ol,
    .resume-summary ol {
      margin: 4pt 0 0;
      padding-left: 16pt;
    }

    .resume-rich li,
    .resume-summary li {
      margin: 1.5pt 0;
    }

    * {
      box-shadow: none !important;
      text-shadow: none !important;
      filter: none !important;
    }
  </style>
</head>
<body class="${bodyClass}">
  <article class="resume-sheet">
  <header class="${headerClass}">
    <h1>${escapeHtml(model.fullName || '')}</h1>
    <div class="resume-head-line">${escapeHtml(model.contactLine)}</div>
    ${linksHtml ? `<div class="resume-head-links">${linksHtml}</div>` : ''}
  </header>
  ${sections.join('')}
  </article>
</body>
</html>`
}

function escapeRegex(value) {
  return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function buildHighlightRegex(words) {
  const normalized = Array.from(
    new Set(
      (Array.isArray(words) ? words : [])
        .map((w) => String(w || '').trim())
        .filter(Boolean),
    ),
  )
    .sort((a, b) => b.length - a.length)
    .slice(0, 120)

  if (!normalized.length) return null
  const pattern = normalized.map((w) => escapeRegex(w)).join('|')
  return new RegExp(`\\b(${pattern})\\b`, 'gi')
}

function applyKeywordHighlightsToHtml(baseHtml, words) {
  if (typeof window === 'undefined' || typeof DOMParser === 'undefined') return baseHtml
  const regex = buildHighlightRegex(words)
  if (!regex) return baseHtml

  const parser = new DOMParser()
  const doc = parser.parseFromString(String(baseHtml || ''), 'text/html')
  const skipTags = new Set(['SCRIPT', 'STYLE', 'MARK', 'A'])
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT)
  const nodes = []
  let current = walker.nextNode()
  while (current) {
    nodes.push(current)
    current = walker.nextNode()
  }

  nodes.forEach((node) => {
    const parentTag = node.parentElement?.tagName || ''
    if (!node.nodeValue || skipTags.has(parentTag)) return
    const source = String(node.nodeValue || '')
    regex.lastIndex = 0
    if (!regex.test(source)) return

    regex.lastIndex = 0
    const frag = doc.createDocumentFragment()
    let last = 0
    let match = regex.exec(source)
    while (match) {
      const start = match.index
      const end = start + String(match[0]).length
      if (start > last) {
        frag.appendChild(doc.createTextNode(source.slice(last, start)))
      }
      const mark = doc.createElement('mark')
      mark.className = 'kw-highlight'
      mark.textContent = source.slice(start, end)
      frag.appendChild(mark)
      last = end
      match = regex.exec(source)
    }
    if (last < source.length) {
      frag.appendChild(doc.createTextNode(source.slice(last)))
    }
    node.parentNode?.replaceChild(frag, node)
  })

  const style = doc.createElement('style')
  style.textContent = `
    .kw-highlight {
      background: #fff3a3 !important;
      color: #111827 !important;
      padding: 0 1px;
      border-radius: 2px;
    }
  `
  doc.head.appendChild(style)
  return `<!DOCTYPE html>\n${doc.documentElement.outerHTML}`
}

export function buildAtsPdfHtmlPreserveHighlights(form) {
  const html = buildAtsPdfHtml(form)
  const parser = new DOMParser()
  const doc = parser.parseFromString(html, 'text/html')
  const style = doc.createElement('style')
  style.textContent = `
    mark, .kw-highlight {
      background: #fff3a3 !important;
      color: #111827 !important;
      padding: 0 1px;
      border-radius: 2px;
    }
  `
  doc.head.appendChild(style)
  return `<!DOCTYPE html>\n${doc.documentElement.outerHTML}`
}

export function buildAtsPdfHtmlWithHighlights(form, highlightWords = []) {
  const baseHtml = buildAtsPdfHtml(form)
  return applyKeywordHighlightsToHtml(baseHtml, highlightWords)
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
    if (!win || !bodyHtml) return

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
