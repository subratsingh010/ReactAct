import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { fetchTrackingRow } from '../api'
import { SingleSelectDropdown } from '../components/SearchableDropdown'
import { MailTestIcon } from './TrackingMailTestPage'
import { capitalizeFirstDisplay } from '../utils/displayText'

const ALL_EMPLOYEES_VALUE = '__all_employees__'

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

function formatChatParty(item) {
  const direction = String(item?.direction || '').trim().toLowerCase()
  if (direction === 'incoming') {
    const fromEmail = String(item?.from_email || '').trim()
    return fromEmail || (item?.employee_name || '-')
  }
  const toEmail = String(item?.to_email || '').trim()
  return toEmail || '-'
}

function formatRecipient(item) {
  const toEmail = String(item?.to_email || '').trim()
  return toEmail || '-'
}

function cleanMailBody(text, { incoming = false } = {}) {
  const normalized = String(text || '').replaceAll('\r\n', '\n').trim()
  if (!normalized) return '-'

  const lines = normalized.split('\n')
  const visibleLines = []

  for (const line of lines) {
    const trimmed = line.trim()
    if (
      incoming && (
        trimmed.startsWith('>') ||
        /^On .+wrote:$/i.test(trimmed) ||
        /^From:\s/i.test(trimmed) ||
        /^Sent:\s/i.test(trimmed) ||
        /^Subject:\s/i.test(trimmed) ||
        /^To:\s/i.test(trimmed) ||
        /^Cc:\s/i.test(trimmed)
      )
    ) {
      break
    }
    visibleLines.push(line)
  }

  const cleaned = visibleLines.join('\n').replace(/\n{3,}/g, '\n\n').trim()
  return cleaned || normalized
}

function parseMilestoneEmployeeIds(value) {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item || '').trim()).filter(Boolean)
}

function buildThreadGroups(sentEvents, receivedEvents) {
  const sent = Array.isArray(sentEvents) ? sentEvents : []
  const received = Array.isArray(receivedEvents) ? receivedEvents : []
  const groups = sent.map((item) => ({
    key: String(item?.message_id || item?.id || `${item?.action_at || 'sent'}-${item?.employee_id || 'unknown'}`),
    sent: item,
    replies: [],
  }))
  const groupByMessageId = new Map(
    groups
      .map((group) => [String(group.sent?.message_id || '').trim(), group])
      .filter(([key]) => Boolean(key)),
  )

  received.forEach((reply) => {
    const threadIds = Array.isArray(reply?.thread_message_ids) ? reply.thread_message_ids.map((item) => String(item || '').trim()) : []
    const matchedGroup = threadIds.map((id) => groupByMessageId.get(id)).find(Boolean)
    if (matchedGroup) {
      matchedGroup.replies.push(reply)
      return
    }
    groups.push({
      key: `reply-${reply?.id}`,
      sent: null,
      replies: [reply],
    })
  })

  return groups
}

function actionRowsForDetail(row) {
  const milestones = Array.isArray(row?.milestones) ? row.milestones : []
  const selectedEmployeeId = String(row?.__selectedEmployeeId || '').trim()
  const milestoneRows = milestones.map((item, index) => ({
    id: `milestone-${index}`,
    type: item?.type,
    mode: item?.mode,
    replied: false,
    at: item?.at,
    notes: item?.notes,
    employeeIds: parseMilestoneEmployeeIds(item?.employee_ids),
  })).filter((item) => {
    if (!selectedEmployeeId || selectedEmployeeId === ALL_EMPLOYEES_VALUE) return true
    return item.employeeIds.includes(selectedEmployeeId)
  })

  return milestoneRows.sort((left, right) => {
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
  const actionRows = actionRowsForDetail({ ...(row || {}), __selectedEmployeeId: selectedEmployeeId })
  const passedEmployees = Array.isArray(row?.delivery_summary?.passed) ? row.delivery_summary.passed : []
  const failedEmployees = Array.isArray(row?.delivery_summary?.failed) ? row.delivery_summary.failed : []
  const employeeDeliveryOverview = Array.isArray(row?.employee_delivery_overview) ? row.employee_delivery_overview : []
  const filteredEmployeeDeliveryOverview = employeeDeliveryOverview.filter((item) => {
    if (selectedEmployeeId === ALL_EMPLOYEES_VALUE) return true
    return String(item.employee_id || '') === String(selectedEmployeeId)
  })
  const sentMailEvents = filteredMailEvents.filter((item) => String(item?.direction || '').trim().toLowerCase() !== 'incoming')
  const receivedMailEvents = filteredMailEvents.filter((item) => String(item?.direction || '').trim().toLowerCase() === 'incoming')
  const chatThreadGroups = buildThreadGroups(sentMailEvents, receivedMailEvents)

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
              <div className="tracking-detail-item"><span className="tracking-detail-label">Company</span><span className="tracking-detail-value">{capitalizeFirstDisplay(row.company_name) || '-'}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Job ID</span><span className="tracking-detail-value">{row.job_id || '-'}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Role</span><span className="tracking-detail-value">{row.role || '-'}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Job URL</span><span className="tracking-detail-value">{row.job_url ? <a href={row.job_url} target="_blank" rel="noreferrer">Open</a> : '-'}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Selected Employee</span><span className="tracking-detail-value">{Array.isArray(row.selected_employees) && row.selected_employees.length ? row.selected_employees.map((item) => String(item?.name || '').trim()).filter(Boolean).join(', ') : '-'}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Mail Type</span><span className="tracking-detail-value">{formatMailType(row.mail_type)}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Freeze</span><span className="tracking-detail-value">{row.is_freezed ? 'Yes' : 'No'}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Created At</span><span className="tracking-detail-value">{toFriendlyDateTime(row.created_at)}</span></div>
              <div className="tracking-detail-item"><span className="tracking-detail-label">Last Updated</span><span className="tracking-detail-value">{toFriendlyDateTime(row.updated_at)}</span></div>
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
            <h2>Employee Delivery Overview</h2>
            <div className="tracking-table-wrap tracking-section-scroll">
              <table className="tracking-table">
                <thead>
                  <tr>
                    <th>Employee Name</th>
                    <th>Mail Type</th>
                    <th>Mail Mode</th>
                    <th>Employee Mail ID</th>
                    <th>Status</th>
                    <th>Sent Time</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredEmployeeDeliveryOverview.map((item, index) => (
                    <tr key={`overview-${item.employee_id || index}`}>
                      <td>{item.employee_name || '-'}</td>
                      <td>{formatMailType(item.mail_type)}</td>
                      <td>{formatSendMode(item.send_mode)}</td>
                      <td>{item.email || '-'}</td>
                      <td>{formatDeliveryStatus(item.status)}</td>
                      <td>{toFriendlyDateTime(item.action_at)}</td>
                    </tr>
                  ))}
                  {!filteredEmployeeDeliveryOverview.length ? (
                    <tr><td colSpan={6}>No employee delivery details available.</td></tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </section>

          <section className="dash-card">
            <h2>Mail Chat History</h2>
            <div className="tracking-table-wrap tracking-chat-scroll">
              <table className="tracking-table tracking-chat-table">
                <thead>
                  <tr>
                    <th>Sent Time</th>
                    <th>Mail Type</th>
                    <th>Recipient</th>
                    <th>Reply Sender</th>
                    <th>Sent Text</th>
                    <th>Received Text</th>
                    <th>Received Time</th>
                  </tr>
                </thead>
                <tbody>
                  {chatThreadGroups.length ? chatThreadGroups.flatMap((group) => {
                    if (group.replies.length) {
                      return group.replies.map((reply) => (
                        <tr key={`${group.key}-${reply.id}`}>
                          <td>{group.sent ? toFriendlyDateTime(group.sent.action_at) : '-'}</td>
                          <td>{group.sent ? formatMailType(group.sent.mail_type) : '-'}</td>
                          <td>{group.sent ? formatRecipient(group.sent) : '-'}</td>
                          <td>{formatChatParty(reply)}</td>
                          <td>
                            <div className="tracking-chat-cell">
                              <strong>{group.sent?.subject || '-'}</strong>
                              <p>{cleanMailBody(group.sent?.message || group.sent?.notes || '-')}</p>
                            </div>
                          </td>
                          <td>
                            <div className="tracking-chat-cell">
                              <strong>{reply.subject || '-'}</strong>
                              <p>{cleanMailBody(reply.message || reply.notes || '-', { incoming: true })}</p>
                            </div>
                          </td>
                          <td>{toFriendlyDateTime(reply.action_at)}</td>
                        </tr>
                      ))
                    }
                    return [
                      <tr key={`${group.key}-no-reply`}>
                        <td>{group.sent ? toFriendlyDateTime(group.sent.action_at) : '-'}</td>
                        <td>{group.sent ? formatMailType(group.sent.mail_type) : '-'}</td>
                        <td>{group.sent ? formatRecipient(group.sent) : '-'}</td>
                        <td>-</td>
                        <td>
                          <div className="tracking-chat-cell">
                            <strong>{group.sent?.subject || '-'}</strong>
                            <p>{cleanMailBody(group.sent?.message || group.sent?.notes || '-')}</p>
                          </div>
                        </td>
                        <td className="hint">No reply in this thread yet.</td>
                        <td>-</td>
                      </tr>,
                    ]
                  }) : (
                    <tr><td colSpan={7}>No mail chat history available for this employee.</td></tr>
                  )}
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
                  <tr><td colSpan={4}>No action milestones available for this employee.</td></tr>
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
