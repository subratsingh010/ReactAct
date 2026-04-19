import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { fetchAllCompanies, fetchAllJobs, fetchAllTrackingRows, fetchInterviews, fetchProfile } from '../api'
import { useAuth } from '../contexts/useAuth'

function formatDateTime(value) {
  if (!value) return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '-'
  return d.toLocaleString()
}

const HOME_ACTIONS = [
  { label: 'Add Job', path: '/jobs', tone: 'primary' },
  { label: 'Add Tracking', path: '/tracking', tone: 'secondary' },
  { label: 'Add Interview', path: '/profile', tone: 'secondary' },
]

function HomePage() {
  const [username, setUsername] = useState('')
  const [companies, setCompanies] = useState([])
  const [jobs, setJobs] = useState([])
  const [trackingRows, setTrackingRows] = useState([])
  const [interviews, setInterviews] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const { isLoggedIn } = useAuth()
  const displayName = String(username || '').trim()
  const capitalizedDisplayName = displayName
    ? `${displayName.charAt(0).toUpperCase()}${displayName.slice(1)}`
    : ''

  useEffect(() => {
    const run = async () => {
      const access = localStorage.getItem('access')
      if (!access) {
        setLoading(false)
        return
      }
      setLoading(true)
      setError('')
      try {
        const [profile, companyData, jobData, trackingData, interviewData] = await Promise.all([
          fetchProfile(access),
          fetchAllCompanies(access),
          fetchAllJobs(access, { scope: 'all', include_closed: false }),
          fetchAllTrackingRows(access),
          fetchInterviews(access),
        ])
        setUsername(String(profile?.username || ''))
        setCompanies(Array.isArray(companyData) ? companyData : [])
        setJobs(Array.isArray(jobData) ? jobData : [])
        setTrackingRows(Array.isArray(trackingData) ? trackingData : [])
        setInterviews(Array.isArray(interviewData) ? interviewData : [])
      } catch (err) {
        setError(err?.message || 'Failed to load dashboard data.')
      } finally {
        setLoading(false)
      }
    }
    run()
  }, [])

  const metrics = useMemo(() => {
    const openJobs = jobs.filter((row) => !row?.is_closed && !row?.is_removed).length
    const closedJobs = jobs.filter((row) => Boolean(row?.is_closed)).length
    const appliedJobs = jobs.filter((row) => Boolean(row?.applied_at)).length
    const activeTracking = trackingRows.filter((row) => !row?.is_removed).length
    const mailedCount = trackingRows.filter((row) => Boolean(row?.mailed)).length
    const repliedCount = trackingRows.filter((row) => Boolean(row?.got_replied)).length
    const freezedCount = trackingRows.filter((row) => Boolean(row?.is_freezed)).length
    const scheduledCount = trackingRows.filter((row) => Boolean(row?.schedule_time)).length
    const upcomingInterviewCount = interviews.filter((row) => {
      if (!row?.interview_at) return false
      const t = new Date(row.interview_at).getTime()
      return Number.isFinite(t) && t >= Date.now()
    }).length
    const responseRate = mailedCount ? Math.round((repliedCount / mailedCount) * 100) : 0
    return {
      companyCount: companies.length,
      openJobs,
      closedJobs,
      appliedJobs,
      activeTracking,
      mailedCount,
      repliedCount,
      freezedCount,
      scheduledCount,
      upcomingInterviewCount,
      responseRate,
    }
  }, [companies, interviews, jobs, trackingRows])

  const upcomingTracking = useMemo(() => {
    const now = Date.now()
    return trackingRows
      .filter((row) => row?.schedule_time)
      .filter((row) => {
        const t = new Date(row.schedule_time).getTime()
        return Number.isFinite(t) && t >= now
      })
      .sort((a, b) => new Date(a.schedule_time).getTime() - new Date(b.schedule_time).getTime())
      .slice(0, 8)
  }, [trackingRows])

  const upcomingInterviews = useMemo(() => {
    const now = Date.now()
    return interviews
      .filter((row) => row?.interview_at)
      .filter((row) => {
        const t = new Date(row.interview_at).getTime()
        return Number.isFinite(t) && t >= now
      })
      .sort((a, b) => new Date(a.interview_at).getTime() - new Date(b.interview_at).getTime())
      .slice(0, 8)
  }, [interviews])

  const ongoingInterviews = useMemo(() => {
    return interviews
      .filter((row) => {
        const action = String(row?.action || 'active').trim().toLowerCase()
        return action === 'active' || action === 'hold'
      })
      .sort((a, b) => {
        const aTime = new Date(a?.updated_at || a?.created_at || 0).getTime()
        const bTime = new Date(b?.updated_at || b?.created_at || 0).getTime()
        return bTime - aTime
      })
      .slice(0, 8)
  }, [interviews])

  const metricCards = [
    { label: 'Companies', value: metrics.companyCount, meta: 'Tracked organizations' },
    { label: 'Open Jobs', value: metrics.openJobs, meta: 'Active opportunities' },
    { label: 'Applied Jobs', value: metrics.appliedJobs, meta: 'Applications submitted' },
    { label: 'Active Tracking', value: metrics.activeTracking, meta: 'Rows currently managed' },
    { label: 'Closed Jobs', value: metrics.closedJobs, meta: 'Closed or archived roles' },
    { label: 'Mailed', value: metrics.mailedCount, meta: 'Rows already mailed' },
    { label: 'Replies', value: metrics.repliedCount, meta: 'Responses received' },
    { label: 'Response Rate', value: `${metrics.responseRate}%`, meta: 'Reply ratio from mailed rows' },
    { label: 'Scheduled Rows', value: metrics.scheduledCount, meta: 'Future tracking sends' },
    { label: 'Upcoming Interviews', value: metrics.upcomingInterviewCount, meta: 'Interviews ahead' },
    { label: 'Freezed Rows', value: metrics.freezedCount, meta: 'Paused tracking rows' },
  ]

  return (
    <main className="home-shell w-full">
      <div className="page page-wide home mx-auto w-full">
        <section className="home-dashboard-hero">
          <div className="tracking-head">
            <div>
              <p className="home-dashboard-eyebrow">Overview</p>
              <h1>{capitalizedDisplayName ? `Hello, ${capitalizedDisplayName}` : 'Hello'}</h1>
              <p className="subtitle home-dashboard-welcome">Welcome to Application Workflow Dashboard</p>
            </div>
            <div className="home-hero-actions">
              {HOME_ACTIONS.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  className={`home-action-btn ${item.tone === 'primary' ? 'is-primary' : ''}`}
                  onClick={() => navigate(item.path)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </section>

        {!isLoggedIn ? <p className="hint">Please login to view dashboard.</p> : null}
        {loading ? <p className="hint">Loading dashboard...</p> : null}
        {error ? <p className="error">{error}</p> : null}

        <section className="dash-card home-summary-card">
          <div className="home-summary-head">
            <div>
              <h2>What This Project Helps With</h2>
              <p className="hint">A compact job outreach workspace that keeps the full pipeline organized in one place.</p>
            </div>
          </div>
          <p className="home-summary-text">
            Manage companies, jobs, fresh mails, follow-ups, schedules, resumes, and interview progress
            without juggling spreadsheets, notes, and separate trackers.
          </p>
          <div className="home-summary-chips">
            <span className="home-summary-chip">Company & Job Tracking</span>
            <span className="home-summary-chip">Fresh & Follow-up Mails</span>
            <span className="home-summary-chip">Schedule Management</span>
            <span className="home-summary-chip">Resume & Achievement Support</span>
            <span className="home-summary-chip">Interview Progress</span>
          </div>
        </section>

        <section className="dash-card home-metrics-shell">
          <div className="home-metrics-grid">
            {metricCards.map((item) => (
              <article key={item.label} className="home-metric-card">
                <p className="kpi-label">{item.label}</p>
                <p className="kpi-value">{item.value}</p>
                <p className="kpi-meta">{item.meta}</p>
              </article>
            ))}
          </div>
        </section>

        <div className="home-hero">
          <section className="home-card home-section-card">
            <div className="home-section-head">
              <div>
                <h2>Current/Future Schedule</h2>
                <p className="hint">Nearest scheduled tracking rows, ready for review.</p>
              </div>
              <button type="button" className="home-link-btn" onClick={() => navigate('/tracking-schedule')}>View Schedule</button>
            </div>
            <div className="tracking-table-wrap tracking-table-wrap-compact home-table-wrap">
              <table className="tracking-table tracking-table-compact home-table">
                <thead>
                  <tr>
                    <th>Company</th>
                    <th>Job ID</th>
                    <th>Role</th>
                    <th>Schedule Time</th>
                  </tr>
                </thead>
                <tbody>
                    {upcomingTracking.map((row) => (
                      <tr key={row.id}>
                        <td>{row.company_name || '-'}</td>
                        <td>{row.job_id || '-'}</td>
                        <td>{row.role || row.job_role || '-'}</td>
                        <td>{formatDateTime(row.schedule_time)}</td>
                      </tr>
                    ))}
                  {!upcomingTracking.length ? (
                    <tr>
                      <td colSpan={4}><p className="hint">No current/future scheduled tracking rows.</p></td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </section>

          <section className="home-card home-section-card">
            <div className="home-section-head">
              <div>
                <h2>Interviews</h2>
                <p className="hint">See both upcoming interview timings and the interviews currently in progress.</p>
              </div>
              <button type="button" className="home-link-btn" onClick={() => navigate('/profile')}>Open Profile</button>
            </div>
            <div className="home-interview-grid">
              <div className="tracking-table-wrap tracking-table-wrap-compact home-table-wrap">
                <table className="tracking-table tracking-table-compact home-table">
                  <thead>
                    <tr>
                      <th colSpan={3}>Upcoming Interviews</th>
                    </tr>
                    <tr>
                      <th>Company</th>
                      <th>Role</th>
                      <th>When</th>
                    </tr>
                  </thead>
                  <tbody>
                    {upcomingInterviews.map((row) => (
                      <tr key={`upcoming-${row.id}`}>
                        <td>{row.company_name || '-'}</td>
                        <td>{row.job_role || '-'}</td>
                        <td>{formatDateTime(row.interview_at)}</td>
                      </tr>
                    ))}
                    {!upcomingInterviews.length ? (
                      <tr>
                        <td colSpan={3}><p className="hint">No upcoming interviews.</p></td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>

              <div className="tracking-table-wrap tracking-table-wrap-compact home-table-wrap">
                <table className="tracking-table tracking-table-compact home-table">
                  <thead>
                    <tr>
                      <th colSpan={3}>Ongoing Interviews</th>
                    </tr>
                    <tr>
                      <th>Company</th>
                      <th>Role</th>
                      <th>Stage</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ongoingInterviews.map((row) => (
                      <tr key={`ongoing-${row.id}`}>
                        <td>{row.company_name || '-'}</td>
                        <td>{row.job_role || '-'}</td>
                        <td>{String(row.stage || '-').replaceAll('_', ' ')}</td>
                      </tr>
                    ))}
                    {!ongoingInterviews.length ? (
                      <tr>
                        <td colSpan={3}><p className="hint">No ongoing interviews.</p></td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        </div>

        <footer className="home-footer">
          <p>Designed and built by Subrat for a sharper, more organized job pipeline.</p>
        </footer>
      </div>
    </main>
  )
}

export default HomePage
