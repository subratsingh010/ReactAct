import { Fragment, useEffect, useMemo, useState } from 'react'

import {
  createTrackingRow,
  deleteTrackingRow,
  fetchEmployees,
  fetchTrackingRows,
  updateTrackingRow,
} from '../api'

const ACTION_STATE_KEY = 'trackingActionState'
const EMPTY_MILESTONE_DOTS = 10

function readActionState() {
  try {
    const raw = localStorage.getItem(ACTION_STATE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function hasFreshMilestone(actionState) {
  return (actionState?.milestones || []).some((item) => item.type === 'fresh')
}

function lastActionType(actionState) {
  const items = actionState?.milestones || []
  if (!items.length) return ''
  return String(items[items.length - 1]?.type || '')
}

function toDateInput(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toISOString().slice(0, 10)
}

function nowDateInput() {
  return toDateInput(new Date().toISOString())
}

function nowDateTimeInput() {
  const now = new Date()
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 16)
}

function TrackingPage() {
  const access = localStorage.getItem('access') || ''
  const [rows, setRows] = useState([])
  const [employees, setEmployees] = useState([])
  const [selectedIds, setSelectedIds] = useState([])
  const [actionByRow, setActionByRow] = useState(() => readActionState())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filters, setFilters] = useState({
    companyName: '',
    jobId: '',
    appliedDate: '',
    mailed: 'all',
    gotReplied: 'all',
    lastAction: 'all',
    orderByApplied: 'desc',
  })
  const [editForm, setEditForm] = useState(null)

  useEffect(() => {
    localStorage.setItem(ACTION_STATE_KEY, JSON.stringify(actionByRow))
  }, [actionByRow])

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      if (!access) {
        setRows([])
        setLoading(false)
        return
      }
      setLoading(true)
      setError('')
      try {
        const data = await fetchTrackingRows(access)
        const employeeRows = await fetchEmployees(access)
        if (cancelled) return
        const list = Array.isArray(data) ? data : []
        setEmployees(Array.isArray(employeeRows) ? employeeRows : [])
        setRows(list)
        setActionByRow((prev) => {
          const next = { ...prev }
          for (const row of list) {
            const key = String(row.id)
            if (!next[key]) {
              next[key] = {
                actionType: 'fresh',
                sendMode: 'now',
                actionAt: '',
                milestones: [],
              }
            }
          }
          return next
        })
      } catch (err) {
        if (!cancelled) setError(err.message || 'Failed to load tracking rows.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [access])

  const hrMapByCompanyName = useMemo(() => {
    const map = {}
    for (const employee of employees) {
      const companyName = String(employee.company_name || '').trim()
      if (!companyName) continue
      if (!map[companyName]) map[companyName] = []
      map[companyName].push(String(employee.name || '').trim())
    }
    return map
  }, [employees])

  const createRow = async () => {
    try {
      const created = await createTrackingRow(access, {
        company_name: 'New Company',
        job_id: '',
        mailed: false,
        applied_date: nowDateInput(),
        posting_date: nowDateInput(),
        is_open: true,
        available_hrs: [],
        selected_hrs: [],
        got_replied: false,
      })
      setRows((prev) => [created, ...prev])
      setActionByRow((prev) => ({
        ...prev,
        [String(created.id)]: {
          actionType: 'fresh',
          sendMode: 'now',
          actionAt: '',
          milestones: [],
        },
      }))
    } catch (err) {
      setError(err.message || 'Could not create tracking row.')
    }
  }

  const openEditForm = (row) => {
    setEditForm({
      id: row.id,
      company_name: row.company_name || '',
      job_id: row.job_id || '',
      mailed: Boolean(row.mailed),
      applied_date: toDateInput(row.applied_date),
      posting_date: toDateInput(row.posting_date),
      is_open: Boolean(row.is_open),
      available_hrs: Array.isArray(row.available_hrs) ? row.available_hrs : [],
      selected_hrs: Array.isArray(row.selected_hrs) ? row.selected_hrs : [],
      got_replied: Boolean(row.got_replied),
    })
  }

  const saveEditForm = async () => {
    if (!editForm) return
    const payload = {
      company_name: editForm.company_name,
      job_id: editForm.job_id,
      mailed: editForm.mailed,
      applied_date: editForm.applied_date || null,
      posting_date: editForm.posting_date || null,
      is_open: editForm.is_open,
      available_hrs: editForm.available_hrs,
      selected_hrs: editForm.selected_hrs,
      got_replied: editForm.got_replied,
    }
    setRows((prev) => prev.map((row) => (row.id === editForm.id ? { ...row, ...payload } : row)))
    try {
      await updateTrackingRow(access, editForm.id, payload)
      setEditForm(null)
    } catch (err) {
      setError(err.message || 'Could not save tracking row.')
    }
  }

  const removeRow = async (rowId) => {
    setRows((prev) => prev.filter((row) => row.id !== rowId))
    setSelectedIds((prev) => prev.filter((id) => id !== rowId))
    try {
      await deleteTrackingRow(access, rowId)
    } catch (err) {
      setError(err.message || 'Could not delete row.')
    }
  }

  const removeSelected = async () => {
    const toDelete = [...selectedIds]
    setRows((prev) => prev.filter((row) => !toDelete.includes(row.id)))
    setSelectedIds([])
    await Promise.all(
      toDelete.map(async (id) => {
        try {
          await deleteTrackingRow(access, id)
        } catch {
          // ignore individual failures; page refresh can recover
        }
      }),
    )
  }

  const toggleSelect = (rowId, checked) => {
    setSelectedIds((prev) => {
      if (checked) return Array.from(new Set([...prev, rowId]))
      return prev.filter((id) => id !== rowId)
    })
  }

  const allSelected = rows.length > 0 && rows.every((row) => selectedIds.includes(row.id))
  const toggleSelectAll = (checked) => {
    setSelectedIds(checked ? rows.map((row) => row.id) : [])
  }

  const setActionField = (rowId, key, value) => {
    setActionByRow((prev) => {
      const current = prev[String(rowId)] || {
        actionType: 'fresh',
        sendMode: 'now',
        actionAt: '',
        milestones: [],
      }
      return {
        ...prev,
        [String(rowId)]: {
          ...current,
          [key]: value,
        },
      }
    })
  }

  const applyAction = (rowId) => {
    setActionByRow((prev) => {
      const current = prev[String(rowId)] || { actionType: 'fresh', sendMode: 'now', actionAt: '', milestones: [] }
      const canFollowUp = hasFreshMilestone(current)
      const type = canFollowUp ? current.actionType : 'fresh'
      if (type === 'followup' && !canFollowUp) return prev
      if (current.sendMode === 'schedule' && !current.actionAt) return prev

      const at = current.sendMode === 'now' ? new Date().toISOString() : current.actionAt
      const nextMilestones = [
        ...(current.milestones || []),
        {
          type,
          mode: current.sendMode === 'now' ? 'sent' : 'scheduled',
          at,
        },
      ].slice(-EMPTY_MILESTONE_DOTS)

      return {
        ...prev,
        [String(rowId)]: {
          ...current,
          milestones: nextMilestones,
        },
      }
    })
  }

  const filteredRows = useMemo(() => {
    const out = rows.filter((row) => {
      if (filters.companyName && !String(row.company_name || '').toLowerCase().includes(filters.companyName.toLowerCase())) return false
      if (filters.jobId && !String(row.job_id || '').toLowerCase().includes(filters.jobId.toLowerCase())) return false
      if (filters.appliedDate && toDateInput(row.applied_date) !== filters.appliedDate) return false
      if (filters.mailed === 'yes' && !row.mailed) return false
      if (filters.mailed === 'no' && row.mailed) return false
      if (filters.gotReplied === 'yes' && !row.got_replied) return false
      if (filters.gotReplied === 'no' && row.got_replied) return false
      const actionType = lastActionType(actionByRow[String(row.id)])
      if (filters.lastAction !== 'all' && actionType !== filters.lastAction) return false
      return true
    })
    out.sort((a, b) => {
      const aTime = new Date(a.applied_date || 0).getTime()
      const bTime = new Date(b.applied_date || 0).getTime()
      return filters.orderByApplied === 'asc' ? aTime - bTime : bTime - aTime
    })
    return out
  }, [rows, filters, actionByRow])

  return (
    <main className="page page-wide page-plain mx-auto w-full">
      <div className="tracking-head">
        <div>
          <h1>Tracking</h1>
          <p className="subtitle">DB-backed job tracking. Action, send mode, and milestones are local per row.</p>
        </div>
        <div className="actions">
          <button type="button" className="secondary" onClick={createRow}>Add Row</button>
          <button type="button" className="secondary" onClick={removeSelected}>Remove Selected</button>
        </div>
      </div>

      <section className="tracking-filters">
        <label>Company Name<input value={filters.companyName} onChange={(event) => setFilters((prev) => ({ ...prev, companyName: event.target.value }))} /></label>
        <label>Job ID<input value={filters.jobId} onChange={(event) => setFilters((prev) => ({ ...prev, jobId: event.target.value }))} /></label>
        <label>Applied Date<input type="date" value={filters.appliedDate} onChange={(event) => setFilters((prev) => ({ ...prev, appliedDate: event.target.value }))} /></label>
        <label>Mailed<select value={filters.mailed} onChange={(event) => setFilters((prev) => ({ ...prev, mailed: event.target.value }))}><option value="all">All</option><option value="yes">Yes</option><option value="no">No</option></select></label>
        <label>Got Replied<select value={filters.gotReplied} onChange={(event) => setFilters((prev) => ({ ...prev, gotReplied: event.target.value }))}><option value="all">All</option><option value="yes">Yes</option><option value="no">No</option></select></label>
        <label>Last Action<select value={filters.lastAction} onChange={(event) => setFilters((prev) => ({ ...prev, lastAction: event.target.value }))}><option value="all">All</option><option value="fresh">Fresh</option><option value="followup">Follow Up</option></select></label>
        <label>Order By Applied<select value={filters.orderByApplied} onChange={(event) => setFilters((prev) => ({ ...prev, orderByApplied: event.target.value }))}><option value="desc">Newest</option><option value="asc">Oldest</option></select></label>
      </section>

      {error ? <p className="error">{error}</p> : null}
      {loading ? <p className="hint">Loading tracking rows...</p> : null}

      <div className="tracking-table-wrap">
        <table className="tracking-table">
          <thead>
            <tr>
              <th><input type="checkbox" checked={allSelected} onChange={(event) => toggleSelectAll(event.target.checked)} /></th>
              <th>Company Name</th>
              <th>Job ID</th>
              <th>Mailed</th>
              <th>Applied Date</th>
              <th>Posting Date</th>
              <th>Is Open</th>
              <th>Available HRs</th>
              <th>Got Replied</th>
              <th>Action</th>
              <th>Time / Date</th>
              <th>Send</th>
              <th>Edit</th>
              <th>Remove</th>
            </tr>
          </thead>
          <tbody>
            {filteredRows.map((row) => {
              const rowAction = actionByRow[String(row.id)] || { actionType: 'fresh', sendMode: 'now', actionAt: '', milestones: [] }
              const canFollowUp = hasFreshMilestone(rowAction)
              const milestones = rowAction.milestones || []
              const availableHrs = hrMapByCompanyName[String(row.company_name || '').trim()] || (Array.isArray(row.available_hrs) ? row.available_hrs : [])

              return (
                <Fragment key={`row-wrap-${row.id}`}>
                  <tr key={`data-${row.id}`}>
                    <td><input type="checkbox" checked={selectedIds.includes(row.id)} onChange={(event) => toggleSelect(row.id, event.target.checked)} /></td>
                    <td>{row.company_name || '-'}</td>
                    <td>{row.job_id || '-'}</td>
                    <td>{row.mailed ? 'Yes' : 'No'}</td>
                    <td>{toDateInput(row.applied_date) || '-'}</td>
                    <td>{toDateInput(row.posting_date) || '-'}</td>
                    <td>{row.is_open ? 'Yes' : 'No'}</td>
                    <td>{availableHrs.length ? availableHrs.join(', ') : '-'}</td>
                    <td>{row.got_replied ? 'Yes' : 'No'}</td>
                    <td>
                      <select
                        value={rowAction.actionType}
                        onChange={(event) => setActionField(row.id, 'actionType', event.target.value)}
                      >
                        <option value="fresh">Fresh Mail</option>
                        <option value="followup" disabled={!canFollowUp}>Follow Up</option>
                      </select>
                    </td>
                    <td>
                      <input
                        type="datetime-local"
                        value={rowAction.actionAt || ''}
                        onChange={(event) => setActionField(row.id, 'actionAt', event.target.value)}
                        disabled={rowAction.sendMode === 'now'}
                      />
                    </td>
                    <td>
                      <div className="tracking-send-cell">
                        <select value={rowAction.sendMode} onChange={(event) => setActionField(row.id, 'sendMode', event.target.value)}>
                          <option value="now">Send Now</option>
                          <option value="schedule">Schedule Future</option>
                        </select>
                        <button type="button" onClick={() => applyAction(row.id)}>Apply</button>
                      </div>
                    </td>
                    <td><button type="button" className="secondary" onClick={() => openEditForm(row)}>Edit</button></td>
                    <td><button type="button" className="tracking-remove-inline" onClick={() => removeRow(row.id)}>Remove</button></td>
                  </tr>
                  <tr className="tracking-milestone-row">
                    <td />
                    <td colSpan={13}>
                      <div className="tracking-dot-line">
                        {Array.from({ length: EMPTY_MILESTONE_DOTS }).map((_, index) => {
                          const milestone = milestones[index]
                          return (
                            <span
                              key={`${row.id}-dot-${index}`}
                              className={`tracking-circle-dot ${milestone ? 'is-on' : ''}`}
                              title={milestone ? `${milestone.type} | ${milestone.mode} | ${milestone.at}` : `Step ${index + 1}`}
                            />
                          )
                        })}
                      </div>
                    </td>
                  </tr>
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>

      {!loading && !filteredRows.length ? <p className="hint">No rows found.</p> : null}

      {editForm ? (
        <div className="modal-overlay">
          <div className="modal-panel">
            <h2>Edit Tracking Row</h2>
            <label>Company Name<input value={editForm.company_name} onChange={(event) => setEditForm((prev) => ({ ...prev, company_name: event.target.value }))} /></label>
            <label>Job ID<input value={editForm.job_id} onChange={(event) => setEditForm((prev) => ({ ...prev, job_id: event.target.value }))} /></label>
            <label>Mailed<select value={editForm.mailed ? 'yes' : 'no'} onChange={(event) => setEditForm((prev) => ({ ...prev, mailed: event.target.value === 'yes' }))}><option value="yes">Yes</option><option value="no">No</option></select></label>
            <label>Applied Date<input type="date" value={editForm.applied_date || ''} onChange={(event) => setEditForm((prev) => ({ ...prev, applied_date: event.target.value }))} /></label>
            <label>Posting Date<input type="date" value={editForm.posting_date || ''} onChange={(event) => setEditForm((prev) => ({ ...prev, posting_date: event.target.value }))} /></label>
            <label>Is Open<select value={editForm.is_open ? 'yes' : 'no'} onChange={(event) => setEditForm((prev) => ({ ...prev, is_open: event.target.value === 'yes' }))}><option value="yes">Yes</option><option value="no">No</option></select></label>
            <label>Available HRs (comma separated)<input value={editForm.available_hrs.join(', ')} onChange={(event) => setEditForm((prev) => ({ ...prev, available_hrs: event.target.value.split(',').map((x) => x.trim()).filter(Boolean) }))} /></label>
            <label>
              Selected HRs
              <select
                multiple
                value={editForm.selected_hrs}
                onChange={(event) => {
                  const values = Array.from(event.target.selectedOptions).map((option) => option.value)
                  setEditForm((prev) => ({ ...prev, selected_hrs: values }))
                }}
              >
                {editForm.available_hrs.map((hr) => (
                  <option key={hr} value={hr}>{hr}</option>
                ))}
              </select>
            </label>
            <label>Got Replied<select value={editForm.got_replied ? 'yes' : 'no'} onChange={(event) => setEditForm((prev) => ({ ...prev, got_replied: event.target.value === 'yes' }))}><option value="yes">Yes</option><option value="no">No</option></select></label>
            <div className="actions">
              <button type="button" onClick={saveEditForm}>Save</button>
              <button type="button" className="secondary" onClick={() => setEditForm(null)}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  )
}

export default TrackingPage
