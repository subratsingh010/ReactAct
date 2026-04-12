(function () {
  function norm(value) {
    return String(value || '').toLowerCase().replace(/\s+/g, ' ').trim()
  }

  function getVisible(el) {
    if (!el) return false
    const style = window.getComputedStyle(el)
    return style.display !== 'none' && style.visibility !== 'hidden' && el.offsetParent !== null
  }

  function getFieldLabel(el) {
    const id = el.id ? String(el.id) : ''
    if (id) {
      const byFor = document.querySelector(`label[for="${CSS.escape(id)}"]`)
      if (byFor) return byFor.textContent || ''
    }
    const parentLabel = el.closest('label')
    if (parentLabel) return parentLabel.textContent || ''
    const aria = el.getAttribute('aria-label') || ''
    if (aria) return aria
    const ph = el.getAttribute('placeholder') || ''
    if (ph) return ph
    const name = el.getAttribute('name') || ''
    return name
  }

  function extractJobDescription() {
    const candidates = [
      document.querySelector('article'),
      document.querySelector('[data-testid*="job"]'),
      document.querySelector('[class*="job"]'),
      document.querySelector('main'),
      document.body,
    ].filter(Boolean)
    let best = ''
    candidates.forEach((node) => {
      const text = String(node.innerText || '').trim()
      if (text.length > best.length) best = text
    })
    return best
  }

  function extractJobMeta() {
    const titleCandidates = [
      document.querySelector('h1'),
      document.querySelector('[data-test*="job-title"]'),
      document.querySelector('[class*="job-title"]'),
      document.querySelector('meta[property="og:title"]'),
    ].filter(Boolean)
    const companyCandidates = [
      document.querySelector('[data-test*="company"]'),
      document.querySelector('[class*="company"]'),
      document.querySelector('a[href*="/company/"]'),
      document.querySelector('meta[property="og:site_name"]'),
    ].filter(Boolean)

    const getText = (node) => {
      if (!node) return ''
      if (node.tagName === 'META') return String(node.getAttribute('content') || '').trim()
      return String(node.textContent || '').replace(/\s+/g, ' ').trim()
    }

    let jobTitle = ''
    for (const node of titleCandidates) {
      const t = getText(node)
      if (t && t.length >= 2) {
        jobTitle = t
        break
      }
    }
    let companyName = ''
    for (const node of companyCandidates) {
      const t = getText(node)
      if (t && t.length >= 2) {
        companyName = t
        break
      }
    }
    return { jobTitle, companyName }
  }

  function collectFields() {
    const fields = Array.from(document.querySelectorAll('input, textarea, select')).filter((el) => getVisible(el))
    return fields
      .filter((el) => {
        const type = norm(el.getAttribute('type') || '')
        return type !== 'hidden' && type !== 'submit' && type !== 'button'
      })
      .map((el) => ({
        el,
        type: norm(el.tagName === 'SELECT' ? 'select' : el.getAttribute('type') || el.tagName),
        label: String(getFieldLabel(el) || '').replace(/\s+/g, ' ').trim(),
        name: String(el.getAttribute('name') || '').trim(),
        id: String(el.id || '').trim(),
      }))
  }

  function questionList() {
    const fields = collectFields()
    const out = []
    const seen = new Set()
    fields.forEach((f) => {
      const q = f.label || f.name || f.id
      const key = norm(q)
      if (!key || seen.has(key)) return
      seen.add(key)
      out.push(q)
    })
    return out
  }

  function bestAnswer(field, answers) {
    const entries = Object.entries(answers || {})
    if (!entries.length) return ''

    const targets = [
      norm(field.label),
      norm(field.name),
      norm(field.id),
    ].filter(Boolean)

    for (const t of targets) {
      for (const [k, v] of entries) {
        const nk = norm(k)
        if (!nk) continue
        if (t === nk || t.includes(nk) || nk.includes(t)) return String(v || '')
      }
    }
    return ''
  }

  function trigger(el) {
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
  }

  function parseBool(value) {
    const v = norm(value)
    return ['yes', 'true', '1', 'y', 'checked'].includes(v)
  }

  function pickSelectOption(selectEl, answer) {
    const desired = norm(answer)
    if (!desired) return false
    const options = Array.from(selectEl.options || [])
    let match = options.find((o) => norm(o.textContent) === desired || norm(o.value) === desired)
    if (!match) {
      match = options.find((o) => norm(o.textContent).includes(desired) || desired.includes(norm(o.textContent)))
    }
    if (!match) return false
    selectEl.value = match.value
    trigger(selectEl)
    return true
  }

  async function uploadResumeToMatchingFileInputs(fileData) {
    if (!fileData?.base64) return 0
    const bytes = Uint8Array.from(atob(String(fileData.base64)), (c) => c.charCodeAt(0))
    const file = new File([bytes], fileData.name || 'resume.pdf', { type: fileData.type || 'application/pdf' })
    const dt = new DataTransfer()
    dt.items.add(file)

    const fileInputs = Array.from(document.querySelectorAll('input[type="file"]')).filter((el) => getVisible(el))
    let uploaded = 0
    fileInputs.forEach((input) => {
      const meta = norm(`${getFieldLabel(input)} ${input.name || ''} ${input.id || ''}`)
      if (!meta || (!meta.includes('resume') && !meta.includes('cv') && !meta.includes('upload'))) return
      input.files = dt.files
      trigger(input)
      uploaded += 1
    })
    return uploaded
  }

  async function fillForm(answers, resumeFile) {
    const fields = collectFields()
    let filled = 0
    for (const field of fields) {
      const answer = bestAnswer(field, answers)
      if (!answer) continue

      if (field.type === 'select') {
        if (pickSelectOption(field.el, answer)) filled += 1
        continue
      }

      if (field.type === 'checkbox') {
        field.el.checked = parseBool(answer)
        trigger(field.el)
        filled += 1
        continue
      }

      if (field.type === 'radio') {
        const groupName = field.el.name
        if (!groupName) continue
        const radios = Array.from(document.querySelectorAll(`input[type="radio"][name="${CSS.escape(groupName)}"]`))
        const desired = norm(answer)
        let chosen = radios.find((r) => {
          const text = norm(`${getFieldLabel(r)} ${r.value || ''}`)
          return text === desired || text.includes(desired) || desired.includes(text)
        })
        if (!chosen && radios.length) chosen = radios[0]
        if (chosen) {
          chosen.checked = true
          trigger(chosen)
          filled += 1
        }
        continue
      }

      if (field.type !== 'file') {
        field.el.value = answer
        trigger(field.el)
        filled += 1
      }
    }

    const uploaded = await uploadResumeToMatchingFileInputs(resumeFile)
    return { filledCount: filled + uploaded }
  }

  function ensureFloatingLaunchers() {
    const staleRoots = Array.from(document.querySelectorAll('#resume-tailor-floating-root'))
    staleRoots.forEach((node) => node.remove())
    const staleButtons = Array.from(document.querySelectorAll('.rt-launcher, .rt-tailor, .rt-autofill, .rt-launcher-single'))
    staleButtons.forEach((node) => node.remove())
    const staleTips = Array.from(document.querySelectorAll('#rtTip, .rt-tip'))
    staleTips.forEach((node) => node.remove())
    const staleDrawer = Array.from(document.querySelectorAll('#resume-tailor-panel, .rt-panel-head, .rt-panel-iframe'))
    staleDrawer.forEach((node) => node.remove())

    const root = document.createElement('div')
    root.id = 'resume-tailor-floating-root'
    root.innerHTML = `
      <style>
        #resume-tailor-floating-root {
          position: static;
          z-index: 2147483000;
        }
        .rt-launcher-single {
          position: fixed;
          right: 0;
          top: 50%;
          width: 64px;
          height: 74px;
          border: 0;
          border-radius: 18px 0 0 18px;
          margin: 0;
          transform: translate(84%, -50%);
          transition: transform .16s ease, box-shadow .16s ease;
          cursor: pointer;
          box-shadow: 0 10px 24px rgba(15, 23, 42, 0.24);
          display: flex;
          align-items: center;
          justify-content: center;
          color: #fff;
          background: rgba(41, 37, 36, 0.92);
        }
        .rt-launcher-single:hover {
          transform: translate(72%, -50%);
          box-shadow: 0 14px 32px rgba(15, 23, 42, 0.28);
        }
        .rt-launcher-single img {
          width: 24px;
          height: 24px;
          border-radius: 6px;
        }
        .rt-launcher-single.hidden {
          opacity: 0;
          pointer-events: none;
        }
        @media (max-width: 900px) {
          .rt-launcher-single {
            width: 58px;
            height: 70px;
            border-radius: 16px 0 0 16px;
            transform: translate(82%, -50%);
          }
          .rt-launcher-single:hover {
            transform: translate(70%, -50%);
          }
        }
        #resume-tailor-panel {
          position: fixed;
          top: 0;
          right: 0;
          width: min(430px, 94vw);
          height: 100vh;
          z-index: 2147483001;
          background: #f8fbff;
          border-left: 1px solid #dbe6f3;
          box-shadow: 0 22px 48px rgba(15, 23, 42, 0.18);
          overflow: hidden;
          opacity: 0;
          pointer-events: none;
          transform: translateX(calc(100% + 24px));
          transition: transform .2s ease, opacity .2s ease;
        }
        #resume-tailor-panel.open {
          opacity: 1;
          pointer-events: auto;
          transform: translateX(0);
        }
        .rt-panel-head {
          height: 44px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 0 12px;
          background: #0f172a;
          color: #e2e8f0;
          border-bottom: 1px solid #1e293b;
          font: 600 13px/1.2 "Segoe UI", "SF Pro Text", -apple-system, sans-serif;
        }
        .rt-panel-close {
          width: 26px;
          height: 26px;
          border: 0;
          border-radius: 999px;
          background: #334155;
          color: #f8fafc;
          cursor: pointer;
          font: 700 14px/1 "Segoe UI", sans-serif;
        }
        .rt-panel-close:hover {
          background: #475569;
        }
        .rt-panel-iframe {
          width: 100%;
          height: calc(100% - 44px);
          border: 0;
          background: #f1f5f9;
        }
        @media (max-width: 900px) {
          #resume-tailor-panel {
            width: 96vw;
            height: 100vh;
          }
        }
      </style>
      <button class="rt-launcher-single" title="Open Resume Tailor Panel">
        <img alt="Tailor" src="${chrome.runtime.getURL('assets/icon64.png')}" />
      </button>
      <aside id="resume-tailor-panel" aria-hidden="true">
        <div class="rt-panel-head">
          <span>Resume Tailor + AutoFill</span>
          <button class="rt-panel-close" type="button">×</button>
        </div>
        <iframe
          class="rt-panel-iframe"
          src="${chrome.runtime.getURL('popup.html?embedded=1')}"
          loading="lazy"
        ></iframe>
      </aside>
    `

    const launcher = root.querySelector('.rt-launcher-single')
    const panel = root.querySelector('#resume-tailor-panel')
    const closeBtn = root.querySelector('.rt-panel-close')

    const setPanelOpen = (isOpen) => {
      panel?.classList.toggle('open', Boolean(isOpen))
      panel?.setAttribute('aria-hidden', isOpen ? 'false' : 'true')
      launcher?.classList.toggle('hidden', Boolean(isOpen))
    }

    launcher?.addEventListener('click', () => setPanelOpen(true))
    closeBtn?.addEventListener('click', () => setPanelOpen(false))

    document.documentElement.appendChild(root)
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    const type = msg?.type
    if (type === 'EXTRACT_JD') {
      const meta = extractJobMeta()
      sendResponse({
        jdText: extractJobDescription(),
        jobTitle: meta.jobTitle,
        companyName: meta.companyName,
      })
      return
    }
    if (type === 'SCAN_FORM_QUESTIONS') {
      sendResponse({ questions: questionList() })
      return
    }
    if (type === 'FILL_FORM') {
      fillForm(msg.answers || {}, msg.resumeFile || null)
        .then((result) => sendResponse(result))
        .catch((err) => sendResponse({ filledCount: 0, error: err?.message || 'fill failed' }))
      return true
    }
  })

  ensureFloatingLaunchers()
})()
