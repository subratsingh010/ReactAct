import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { fetchTrackingRow } from '../api'
import { SingleSelectDropdown } from '../components/SearchableDropdown'
import { MailTestIcon } from './TrackingMailTestPage'

const ALL_EMPLOYEES_VALUE = '__all_employees__'

function formatTemplateType(value) {
  const raw = String(value || '').trim()
  if (!raw) return '-'
  return raw.replaceAll('_', ' ')
}

function toFriendlyDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString()
}

function formatMailType(value) {
  const raw = String(value || '').trim().toLowerCase()
  if (raw === 'followed_up' || raw === 'followup') return 'Follow Up'
  if (raw === 'fresh') return 'Fresh'
  return raw ? raw.replaceAll('_', ' ') : '-'
}

function formatSendMode(value) {
  const raw = String(value || '').trim().toLowerCase()
  if (raw === 'sent') return 'On Time'
  if (raw === 'scheduled') return 'Scheduled'
  return raw ? raw.replaceAll('_', ' ') : '-'
}

function resolveTrackingSendMode(row, mailEvents, milestones) {
  if (row?.schedule_time) return 'scheduled'

  const eventModes = (Array.isArray(mailEvents) ? mailEvents : [])
    .map((item) => String(item?.send_mode || '').trim().toLowerCase())
    .filter(Boolean)
  if (eventModes.includes('scheduled')) return 'scheduled'

  const milestoneModes = (Array.isArray(milestones) ? milestones : [])
    .map((item) => String(item?.mode || '').trim().toLowerCase())
    .filter(Boolean)
  if (milestoneModes.includes('scheduled')) return 'scheduled'

  const latestEvent = [...(Array.isArray(mailEvents) ? mailEvents : [])].sort((left, right) => {
    const leftTime = new Date(left?.action_at || 0).getTime()
    const rightTime = new Date(right?.action_at || 0).getTime()
    return rightTime - leftTime
  })[0]
  if (latestEvent?.send_mode) return String(latestEvent.send_mode || '').trim().toLowerCase()

  const latestMilestone = [...(Array.isArray(milestones) ? milestones : [])].sort((left, right) => {
    const leftTime = new Date(left?.at || 0).getTime()
    const rightTime = new Date(right?.at || 0).getTime()
    return rightTime - leftTime
  })[0]
  if (latestMilestone?.mode) return String(latestMilestone.mode || '').trim().toLowerCase()

  return 'sent'
}

function formatEmployeeDeliveryLabel(item) {
  const name = String(item?.employee_name || '').trim()
  const email = String(item?.email || '').trim()
  if (name && email) return `${name} (${email})`
  if (email) return email
  if (name) return name
  return '-'
}

function formatDeliveryReason(item) {
  const reason = String(item?.reason || '').trim()
  if (!reason) return ''
  const failureType = String(item?.failure_type || '').trim().toLowerCase()
  if (failureType === 'bounced') return `Bounce: ${reason}`
  return reason
}

function formatDeliveryStatus(value) {
  const text = String(value || '').trim().toLowerCase()
  if (text === 'sent') return 'Sent'
  if (text === 'failed') return 'Failed'
  if (text === 'bounced') return 'Bounced'
  return 'Pending'
}

function actionRowsForDetail(row, filteredMailEvents) {
  const milestones = Array.isArray(row?.milestones) ? row.milestones : []
  const milestoneRows = milestones.map((item, index) => ({
    id: `milestone-${index}`,
    type: item?.type,
    mode: item?.mode,
    replied: false,
    at: item?.at,
  }))
  const eventRows = Array.isArray(filteredMailEvents)
    ? filteredMailEvents.map((item) => ({
      id: `event-${item.id}`,
      type: item.mail_type,
      mode: item.send_mode,
      replied: Boolean(item.got_replied),
      at: item.action_at,
    }))
    : []

  return [...milestoneRows, ...eventRows].sort((left, right) => {
    const leftTime = new Date(left?.at || 0).getTime()
    const rightTime = new Date(right?.at || 0).getTime()
    return leftTime - rightTime
  })
}

function TrackingDetailPage() {
  const access = localStorage.getItem('access') || ''
  const { trackingId } = useParams()
  const navigate = useNavigate()
  const [row, setRow] = useState(null)
  const [selectedEmployeeId, setSelectedEmployeeId] = useState(ALL_EMPLOYEES_VALUE)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError('')
      try {
        const data = await fetchTrackingRow(access, trackingId)
        if (!cancelled) {
          setRow(data)
          setSelectedEmployeeId(ALL_EMPLOYEES_VALUE)
        }
      } catch (err) {
        if (!cancelled) setError(err.message || 'Could not load tracking detail.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [access, trackingId])

  const employeeOptions = useMemo(() => {
    const out = []
    const seen = new Set()
    const pushOption = (idValue, nameValue) => {
      const id = String(idValue || '').trim()
      const name = String(nameValue || '').trim()
      if (!id || !name) return
      if (seen.has(id)) return
      seen.add(id)
      out.push({ id, name })
    }

    ;(Array.isArray(row?.selected_employees) ? row.selected_employees : []).forEach((item) => {
      pushOption(item?.id, item?.name)
    })

    const selectedIds = Array.isArray(row?.selected_hr_ids) ? row.selected_hr_ids : []
    const selectedNames = Array.isArray(row?.selected_hrs) ? row.selected_hrs : []
    selectedIds.forEach((id, index) => {
      pushOption(id, selectedNames[index] || `Employee #${id}`)
    })

    ;(Array.isArray(row?.mail_events) ? row.mail_events : []).forEach((item) => {
      pushOption(item?.employee_id, item?.employee_name)
    })

    return out
  }, [row])

  useEffect(() => {
    if (!employeeOptions.length) {
      setSelectedEmployeeId(ALL_EMPLOYEES_VALUE)
      return
    }
    setSelectedEmployeeId((prev) => (
      prev === ALL_EMPLOYEES_VALUE || employeeOptions.some((item) => String(item.id) === String(prev))
        ? prev
        : ALL_EMPLOYEES_VALUE
    ))
  }, [employeeOptions])

  const filteredMailEvents = Array.isArray(row?.mail_events)
    ? row.mail_events.filter((item) => {
      if (selectedEmployeeId === ALL_EMPLOYEES_VALUE) return true
      return String(item.employee_id || '') === String(selectedEmployeeId)
    })
    : []
  const actionRows = actionRowsForDetail(row, filteredMailEvents)
  const scopedEvents = filteredMailEvents
  const mailedAt = scopedEvents.length
    ? scopedEvents[0]?.action_at || ''
    : (row?.mailed_at || row?.maild_at || '')
  const repliedEvents = scopedEvents.filter((item) => Boolean(item.got_replied))
  const repliedAt = repliedEvents.length ? repliedEvents[0]?.action_at || '' : (row?.replied_at || '')
  const repliedBy = Array.from(new Set(
    repliedEvents
      .map((item) => String(item.employee_name || '').trim())
      .filter(Boolean),
  ))
  const passedEmployees = Array.isArray(row?.delivery_summary?.passed) ? row.delivery_summary.passed : []
  const failedEmployees = Array.isArray(row?.delivery_summary?.failed) ? row.delivery_summary.failed : []
  const employeeDeliveryOverview = Array.isArray(row?.employee_delivery_overview) ? row.employee_delivery_overview : []
  const trackingSendMode = resolveTrackingSendMode(row, filteredMailEvents, row?.milestones)

  return (
    <main className="page page-wide mx-auto w-full">
      <div className="tracking-head">
        <div>
          <h1>Tracking Detail</h1>
          <p className="subtitle">Summary, employee-wise mail chat history, and actions.</p>
        </div>
        <div className="actions">
          <button type="button" className="secondary tracking-icon-btn" title="Test Mail" onClick={() => navigate(`/tracking/${trackingId}/test-mail`)}><MailTestIcon /></button>
          <button type="button" className="secondary" onClick={() => navigate('/tracking', { replace: true })}>Back</button>
        </div>
      </div>

      {loading ? <p className="hint">Loading...</p> : null}
      {error ? <p className="error">{error}</p> : null}

      {row ? (
        <>
          <section className="dash-card">
            <div className="profile-section-head">
              <h2>Summary</h2>
            </div>
            <div className="tracking-detail-grid">
              <div className="tracking-detail-item"><span className="tracking-detail-label">Company</span><span className="tracking-detail-value">{row.company_name || '-'}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Job ID</span><span className="tracking-detail-value">{row.job_id || '-'}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Role</span><span className="tracking-detail-value">{row.role || '-'}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Job URL</span><span className="tracking-detail-value">{row.job_url ? <a href={row.job_url} target="_blank" rel="noreferrer">Open</a> : '-'}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Selected HR</span><span className="tracking-detail-value">{Array.isArray(row.selected_hrs) && row.selected_hrs.length ? row.selected_hrs.join(', ') : '-'}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Status</span><span className="tracking-detail-value">{row.is_open ? 'Open' : 'Closed'}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Mail Status</span><span className="tracking-detail-value">{String(row.mail_delivery_status || 'pending').replaceAll('_', ' ')}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Template Type</span><span className="tracking-detail-value">{formatTemplateType(row.template_choice)}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Mail Type</span><span className="tracking-detail-value">{formatMailType(row.mail_type)}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Send Mode</span><span className="tracking-detail-value">{formatSendMode(trackingSendMode)}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Selected Resume</span><span className="tracking-detail-value">{row.resume_preview?.title || row.tailored_resume_preview?.title || '-'}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Freeze</span><span className="tracking-detail-value">{row.is_freezed ? 'Yes' : 'No'}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Schedule Time</span><span className="tracking-detail-value">{toFriendlyDateTime(row.schedule_time)}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Created At</span><span className="tracking-detail-value">{toFriendlyDateTime(row.created_at)}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Last Updated</span><span className="tracking-detail-value">{toFriendlyDateTime(row.updated_at)}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Mailed</span><span className="tracking-detail-value">{(row.mailed || scopedEvents.length) ? 'Yes' : 'No'} {mailedAt ? `(${toFriendlyDateTime(mailedAt)})` : ''}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Got Response</span><span className="tracking-detail-value">{(row.got_replied || repliedEvents.length) ? 'Yes' : 'No'} {repliedAt ? `(${toFriendlyDateTime(repliedAt)})` : ''}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Response From Employee</span><span className="tracking-detail-value">{repliedBy.length ? repliedBy.join(', ') : '-'}</span></div>
            </div>
          </section>

          <section className="tracking-status-board">
            <article className="dash-card tracking-status-card is-pass">
              <div className="tracking-status-head">
                <h2>Passed Mail IDs</h2>
                <span className="tracking-status-count">{passedEmployees.length}</span>
              </div>
              <div className="tracking-section-scroll tracking-section-scroll-compact">
                <div className="tracking-status-list">
                {passedEmployees.length ? passedEmployees.map((item, index) => (
                  <div className="tracking-status-pill" key={`passed-${item.employee_id || item.email || index}`}>
                    <span className="tracking-status-pill-title">{formatEmployeeDeliveryLabel(item)}</span>
                  </div>
                )) : <p className="hint">No successful mails found for this tracking.</p>}
                </div>
              </div>
            </article>

            <article className="dash-card tracking-status-card is-fail">
              <div className="tracking-status-head">
                <h2>Failed Mail IDs</h2>
                <span className="tracking-status-count">{failedEmployees.length}</span>
              </div>
              <div className="tracking-section-scroll tracking-section-scroll-compact">
                <div className="tracking-status-list">
                {failedEmployees.length ? failedEmployees.map((item, index) => (
                  <div className="tracking-status-pill" key={`failed-${item.employee_id || item.email || index}`}>
                    <span className="tracking-status-pill-title">{formatEmployeeDeliveryLabel(item)}</span>
                    {formatDeliveryReason(item) ? <span className="tracking-status-pill-meta">{formatDeliveryReason(item)}</span> : null}
                  </div>
                )) : <p className="hint">No failed mails found for this tracking.</p>}
                </div>
              </div>
            </article>
          </section>

          <section className="dash-card">
            <h2>Employee Delivery Overview</h2>
            <div className="tracking-table-wrap tracking-section-scroll">
              <table className="tracking-table">
                <thead>
                  <tr>
                    <th>Employee</th>
                    <th>Mail ID</th>
                    <th>Status</th>
                    <th>Reason</th>
                    <th>Last Action</th>
                  </tr>
                </thead>
                <tbody>
                  {employeeDeliveryOverview.map((item, index) => (
                    <tr key={`overview-${item.employee_id || index}`}>
                      <td>{item.employee_name || '-'}</td>
                      <td>{item.email || '-'}</td>
                      <td>{formatDeliveryStatus(item.status)}</td>
                      <td>{formatDeliveryReason(item) || '-'}</td>
                      <td>{toFriendlyDateTime(item.action_at)}</td>
                    </tr>
                  ))}
                  {!employeeDeliveryOverview.length ? (
                    <tr><td colSpan={5}>No employee delivery details available.</td></tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </section>

          <section className="dash-card">
            <div className="tracking-detail-filter">
              <label className="tracking-detail-select">
                Select Employee
                <SingleSelectDropdown
                  value={selectedEmployeeId}
                  placeholder="Select employee"
                  clearLabel="All selected employees"
                  options={employeeOptions.map((item) => ({
                    value: String(item.id),
                    label: String(item.name || `Employee #${item.id}`),
                  }))}
                  onChange={(nextValue) => setSelectedEmployeeId(nextValue)}
                />
              </label>
            </div>
          </section>

          <section className="dash-card">
            <h2>Mail Chat History</h2>
            <div className="tracking-table-wrap tracking-section-scroll">
            <table className="tracking-table">
              <thead>
                <tr>
                  <th>Employee</th>
                  <th>To</th>
                  <th>Subject</th>
                  <th>Message / Notes</th>
                  <th>At</th>
                </tr>
              </thead>
              <tbody>
                {filteredMailEvents.map((item) => (
                  <tr key={`chat-${item.id}`}>
                    <td>{item.employee_name || '-'}</td>
                    <td>{item.to_email || '-'}</td>
                    <td>{item.subject || '-'}</td>
                    <td>{item.message || item.notes || '-'}</td>
                    <td>{toFriendlyDateTime(item.action_at)}</td>
                  </tr>
                ))}
                {!filteredMailEvents.length ? (
                  <tr><td colSpan={5}>No mail chat history available for this employee.</td></tr>
                ) : null}
              </tbody>
            </table>
            </div>
          </section>

          <section className="dash-card">
            <h2>Action Taken</h2>
            <div className="tracking-table-wrap tracking-section-scroll">
            <table className="tracking-table">
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Mode</th>
                  <th>Replied</th>
                  <th>At</th>
                </tr>
              </thead>
              <tbody>
                {actionRows.map((item) => (
                  <tr key={`action-${item.id}`}>
                    <td>{formatMailType(item.type)}</td>
                    <td>{formatSendMode(item.mode)}</td>
                    <td>{item.replied ? 'Yes' : 'No'}</td>
                    <td>{toFriendlyDateTime(item.at)}</td>
                  </tr>
                ))}
                {!actionRows.length ? (
                  <tr><td colSpan={4}>No actions available for this employee.</td></tr>
                ) : null}
              </tbody>
            </table>
            </div>
          </section>
        </>
      ) : null}
    </main>
  )
}

export default TrackingDetailPage
