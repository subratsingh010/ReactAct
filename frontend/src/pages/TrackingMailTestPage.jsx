import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { fetchTrackingMailTest, fetchTrackingRow, generateTrackingMailTest, saveTrackingMailTest } from '../api'
import { capitalizeFirstDisplay } from '../utils/displayText'

function MailTestIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M4.75 5A2.75 2.75 0 0 0 2 7.75v8.5A2.75 2.75 0 0 0 4.75 19h14.5A2.75 2.75 0 0 0 22 16.25v-8.5A2.75 2.75 0 0 0 19.25 5H4.75Zm.41 1.5h13.68c.37 0 .72.14.98.39l-7.07 5.42a1.25 1.25 0 0 1-1.52 0L4.18 6.89c.26-.25.61-.39.98-.39Zm-1.66 1.46l5.5 4.21l-5.5 4.23V7.96Zm17 0v8.44L15 12.17l5.5-4.21Zm-10.28 5.54l.1.07a2.75 2.75 0 0 0 3.36 0l.1-.07l5.37 4.12a1.2 1.2 0 0 1-.2.02H4.75a1.2 1.2 0 0 1-.2-.02l5.67-4.35Z"
      />
    </svg>
  )
}

function TrackingMailTestPage() {
  const access = localStorage.getItem('access') || ''
  const { trackingId } = useParams()
  const navigate = useNavigate()
  const [row, setRow] = useState(null)
  const [previews, setPreviews] = useState([])
  const [approved, setApproved] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [options, setOptions] = useState({
    tone: 'professional',
    length: 'balanced',
    char_limit: '900',
    custom_prompt: '',
  })

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError('')
      try {
        const [tracking, saved] = await Promise.all([
          fetchTrackingRow(access, trackingId),
          fetchTrackingMailTest(access, trackingId),
        ])
        if (!cancelled) {
          setRow(tracking)
          setApproved(Array.isArray(saved?.approved_test_mail_payloads) ? saved.approved_test_mail_payloads : [])
          setPreviews(Array.isArray(saved?.approved_test_mail_payloads) ? saved.approved_test_mail_payloads : [])
        }
      } catch (err) {
        if (!cancelled) setError(err.message || 'Could not load mail test panel.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [access, trackingId])

  const aiEnabled = useMemo(() => {
    const mode = String(row?.compose_mode || '').trim().toLowerCase()
    return mode === 'complete_ai'
  }, [row])

  const generate = async (withRegenerateOptions = false) => {
    setGenerating(true)
    setMessage('')
    setError('')
    try {
      const data = await generateTrackingMailTest(access, trackingId, withRegenerateOptions && aiEnabled ? { regenerate_options: options } : {})
      setPreviews(Array.isArray(data?.previews) ? data.previews : [])
      setMessage(withRegenerateOptions ? 'Preview regenerated.' : 'Preview generated.')
    } catch (err) {
      setError(err.message || 'Could not generate mail preview.')
    } finally {
      setGenerating(false)
    }
  }

  const save = async () => {
    setSaving(true)
    setMessage('')
    setError('')
    try {
      const data = await saveTrackingMailTest(access, trackingId, previews)
      const nextApproved = Array.isArray(data?.approved_test_mail_payloads) ? data.approved_test_mail_payloads : []
      setApproved(nextApproved)
      setPreviews(nextApproved)
      setMessage('Approved mail preview saved. Cron will use this content later.')
    } catch (err) {
      setError(err.message || 'Could not save mail preview.')
    } finally {
      setSaving(false)
    }
  }

  const updatePreview = (index, key, value) => {
    setPreviews((prev) => prev.map((item, idx) => (idx === index ? { ...item, [key]: value } : item)))
  }

  return (
    <main className="page page-wide mx-auto w-full">
      <div className="tracking-head">
        <div>
          <h1>Tracking Mail Test</h1>
          <p className="subtitle">Preview the exact mail per employee before cron sends it.</p>
        </div>
        <div className="actions">
          <button type="button" className="secondary" onClick={() => navigate('/tracking')}>Back To Tracking</button>
        </div>
      </div>

      {loading ? <p className="hint">Loading...</p> : null}
      {error ? <p className="error">{error}</p> : null}
      {message ? <p className="hint">{message}</p> : null}

      {row ? (
        <>
          <section className="dash-card">
            <div className="profile-section-head">
              <h2>Tracking Snapshot</h2>
            </div>
            <div className="tracking-detail-grid">
              <div className="tracking-detail-item"><span className="tracking-detail-label">Company</span><span className="tracking-detail-value">{capitalizeFirstDisplay(row.company_name) || '-'}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Role</span><span className="tracking-detail-value">{row.role || '-'}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Template</span><span className="tracking-detail-value">{String(row.template_choice || '-').replaceAll('_', ' ')}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Compose Mode</span><span className="tracking-detail-value">{String(row.compose_mode || '-').replaceAll('_', ' ')}</span></div>
            </div>
          </section>

          <section className="dash-card">
            <div className="profile-section-head">
              <h2>Test Controls</h2>
            </div>
            {aiEnabled ? (
              <div className="tracking-form-grid">
                <label>
                  Tone
                  <select value={options.tone} onChange={(event) => setOptions((prev) => ({ ...prev, tone: event.target.value }))}>
                    <option value="professional">Professional</option>
                    <option value="formal">Formal</option>
                    <option value="friendly">Friendly</option>
                    <option value="concise">Concise</option>
                  </select>
                </label>
                <label>
                  Length
                  <select value={options.length} onChange={(event) => setOptions((prev) => ({ ...prev, length: event.target.value }))}>
                    <option value="balanced">Balanced</option>
                    <option value="short">Short</option>
                    <option value="very_short">Very Short</option>
                    <option value="detailed">Detailed</option>
                  </select>
                </label>
                <label>
                  Max Body Chars
                  <input value={options.char_limit} onChange={(event) => setOptions((prev) => ({ ...prev, char_limit: event.target.value }))} />
                </label>
                <label className="tracking-form-span-2">
                  Extra Prompt
                  <textarea rows={3} value={options.custom_prompt} onChange={(event) => setOptions((prev) => ({ ...prev, custom_prompt: event.target.value }))} placeholder="Example: make it more confident, shorten second paragraph, keep under 700 chars." />
                </label>
              </div>
            ) : null}
            <div className="actions">
              <button type="button" onClick={() => generate(false)} disabled={generating}>{generating ? 'Generating...' : 'Test Mail'}</button>
              {aiEnabled ? <button type="button" className="secondary" onClick={() => generate(true)} disabled={generating}>{generating ? 'Regenerating...' : 'Regenerate With Options'}</button> : null}
              <button type="button" className="secondary" onClick={save} disabled={saving || !previews.length}>{saving ? 'Saving...' : 'Save Approved Mail'}</button>
            </div>
            {!aiEnabled ? <p className="hint">Mail preview uses your selected templates. If you choose a personalized template, that content is added as the employee-specific intro block.</p> : null}
          </section>

          <section className="tracking-mail-preview-list">
            {previews.map((item, index) => (
              <article className="dash-card tracking-mail-preview-card" key={`preview-${item.employee_id || index}`}>
                <div className="tracking-status-head">
                  <div>
                    <h2>{item.employee_name || `Employee #${item.employee_id || index + 1}`}</h2>
                    <p className="subtitle">{item.email || '-'}</p>
                  </div>
                  <span className="tracking-status-count">{index + 1}</span>
                </div>
                <label>
                  Subject
                  <input value={item.subject || ''} onChange={(event) => updatePreview(index, 'subject', event.target.value)} />
                </label>
                <label>
                  Body
                  <textarea rows={12} value={item.body || ''} onChange={(event) => updatePreview(index, 'body', event.target.value)} />
                </label>
              </article>
            ))}
            {!previews.length && !loading ? <p className="hint">Use Test Mail to build previews for all selected employees.</p> : null}
          </section>

          {approved.length ? (
            <section className="dash-card">
              <h2>Saved Preview</h2>
              <p className="hint">The scheduler and cron will reuse the saved subject/body for matching employees.</p>
            </section>
          ) : null}
        </>
      ) : null}
    </main>
  )
}

export { MailTestIcon }
export default TrackingMailTestPage
