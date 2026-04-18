import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { fetchAllTrackingRows } from '../api'

function OpenIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M14 5h5v5h-2V8.41l-6.29 6.3l-1.42-1.42l6.3-6.29H14V5Zm-9 2h6v2H7v8h8v-4h2v6H5V7Z"
      />
    </svg>
  )
}

function formatDateTime(value) {
  if (!value) return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '-'
  return d.toLocaleString()
}

function formatTimeUntil(value) {
  if (!value) return ''
  const target = new Date(value).getTime()
  if (!Number.isFinite(target)) return ''
  const diffMs = target - Date.now()
  if (diffMs <= 0) return 'Due now'
  const minutes = Math.round(diffMs / 60000)
  if (minutes < 60) return `In ${minutes} min`
  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  if (hours < 24) return remainingMinutes ? `In ${hours}h ${remainingMinutes}m` : `In ${hours}h`
  const days = Math.floor(hours / 24)
  const remainingHours = hours % 24
  return remainingHours ? `In ${days}d ${remainingHours}h` : `In ${days}d`
}

function formatTemplateLabel(value) {
  const raw = String(value || '').trim()
  return raw ? raw.replaceAll('_', ' ') : '-'
}

function TrackingSchedulePage() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    const run = async () => {
      setLoading(true)
      setError('')
      try {
        const access = localStorage.getItem('access')
        if (!access) {
          setRows([])
          setError('Please login first.')
          return
        }
        const list = await fetchAllTrackingRows(access)
        setRows(list)
      } catch (err) {
        setError(err?.message || 'Failed to load schedule.')
        setRows([])
      } finally {
        setLoading(false)
      }
    }
    run()
  }, [])

  const upcomingRows = useMemo(() => {
    const now = Date.now()
    return rows
      .filter((row) => row?.schedule_time)
      .filter((row) => {
        const t = new Date(row.schedule_time).getTime()
        return Number.isFinite(t) && t >= now
      })
      .sort((a, b) => new Date(a.schedule_time).getTime() - new Date(b.schedule_time).getTime())
  }, [rows])

  const nextRun = upcomingRows[0] || null
  const todayCount = useMemo(() => {
    const today = new Date().toDateString()
    return upcomingRows.filter((row) => {
      const d = new Date(row?.schedule_time || '')
      return !Number.isNaN(d.getTime()) && d.toDateString() === today
    }).length
  }, [upcomingRows])

  return (
    <main className="page page-wide mx-auto w-full">
      <section className="tracking-schedule-hero">
        <div className="tracking-head">
          <div>
            <p className="tracking-schedule-eyebrow">Planner</p>
            <h1>Tracking Schedule</h1>
            <p className="subtitle">Current and upcoming scheduled tracking rows, sorted by the nearest send time.</p>
          </div>
        </div>

        <div className="tracking-schedule-stats">
          <article className="tracking-schedule-stat">
            <span className="tracking-schedule-stat-label">Upcoming</span>
            <strong>{upcomingRows.length}</strong>
            <small>Scheduled rows in queue</small>
          </article>
          <article className="tracking-schedule-stat">
            <span className="tracking-schedule-stat-label">Today</span>
            <strong>{todayCount}</strong>
            <small>Rows planned for today</small>
          </article>
          <article className="tracking-schedule-stat tracking-schedule-stat-wide">
            <span className="tracking-schedule-stat-label">Next Run</span>
            <strong>{nextRun ? (nextRun.company_name || nextRun.job_id || 'Scheduled row') : 'No upcoming row'}</strong>
            <small>{nextRun ? `${formatDateTime(nextRun.schedule_time)} • ${formatTimeUntil(nextRun.schedule_time)}` : 'Nothing in the schedule yet'}</small>
          </article>
        </div>
      </section>

      {loading ? <p className="hint">Loading schedule...</p> : null}
      {error ? <p className="error">{error}</p> : null}

      <section className="dash-card tracking-schedule-board">
        <div className="tracking-schedule-board-head">
          <div>
            <h2>Upcoming Queue</h2>
            <p className="hint">Nearest items appear first so it is easy to spot what needs attention next.</p>
          </div>
        </div>

        <div className="tracking-table-wrap tracking-table-wrap-compact">
          <table className="tracking-table tracking-table-compact tracking-schedule-table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Job ID</th>
              <th>Role</th>
              <th>Schedule</th>
              <th>Template</th>
              <th>Open</th>
            </tr>
          </thead>
          <tbody>
            {upcomingRows.map((row) => (
              <tr key={row.id}>
                <td>
                  <div className="tracking-schedule-primary">{row?.company_name || '-'}</div>
                </td>
                <td>
                  <span className="tracking-schedule-chip">{row?.job_id || '-'}</span>
                </td>
                <td>{row?.role || row?.job_role || '-'}</td>
                <td>
                  <div className="tracking-schedule-time">
                    <strong>{formatDateTime(row?.schedule_time)}</strong>
                    <span>{formatTimeUntil(row?.schedule_time)}</span>
                  </div>
                </td>
                <td>
                  <span className="tracking-schedule-template">{formatTemplateLabel(row?.template_choice)}</span>
                </td>
                <td>
                  <button
                    type="button"
                    className="tracking-schedule-open-btn"
                    onClick={() => navigate(`/tracking/${row.id}`)}
                    title="Open tracking detail"
                    aria-label={`Open tracking detail for ${row?.company_name || 'row'}`}
                  >
                    <span>Open</span>
                    <OpenIcon />
                  </button>
                </td>
              </tr>
            ))}
            {!loading && !upcomingRows.length ? (
              <tr>
                <td colSpan={6}>
                  <div className="tracking-schedule-empty">
                    <strong>No current or future scheduled rows</strong>
                    <p className="hint">Once you schedule follow-up tracking mails, they will appear here.</p>
                  </div>
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
        </div>
      </section>
    </main>
  )
}

export default TrackingSchedulePage
