import { useCallback, useEffect, useState } from 'react'
import ResumeSheet from '../components/ResumeSheet'
import { SingleSelectDropdown } from '../components/SearchableDropdown'

import { createJob, deleteJob, fetchCompanies, fetchJobs, updateJob } from '../api'

const ROLE_PRESETS = ['Backend', 'Software', 'Fullstack']

function toDateInput(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toISOString().slice(0, 10)
}

function formatDisplayDate(value) {
  if (!value) return '—'
  const s = String(value).slice(0, 10)
  return s || '—'
}

function normalizeUrl(value) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  if (/^https?:\/\//i.test(raw)) return raw
  return `https://${raw}`
}

function ExternalLinkIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" className="jobs-link-icon">
      <path
        fill="currentColor"
        d="M14 3h2.997v5h-2.005V5.41l-9.3 9.295l-1.416-1.418L14.586 4H14V3zm-9 2.997h6v2H7v10h10v-4.01h2V18a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5.997a2 2 0 0 1 2-2z"
      />
    </svg>
  )
}

function PencilIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1.003 1.003 0 0 0 0-1.42l-2.34-2.34a1.003 1.003 0 0 0-1.42 0l-1.83 1.83l3.75 3.75l1.84-1.82z"
      />
    </svg>
  )
}

function PreviewIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 5c5.5 0 9.6 5.2 10.8 6.9c.3.4.3.9 0 1.3C21.6 14.8 17.5 20 12 20S2.4 14.8 1.2 13.1a1 1 0 0 1 0-1.3C2.4 10.2 6.5 5 12 5Zm0 3.5A4.5 4.5 0 1 0 12 17a4.5 4.5 0 0 0 0-9Zm0 2a2.5 2.5 0 1 1 0 5a2.5 2.5 0 0 1 0-5Z"
      />
    </svg>
  )
}

function emptyJobForm() {
  return {
    editingId: null,
    company: '',
    new_company_name: '',
    job_id: '',
    role: '',
    job_link: '',
    jd_text: '',
    date_of_posting: toDateInput(new Date().toISOString()),
    applied_at: '',
    is_closed: false,
  }
}

function JobsPage() {
  const access = localStorage.getItem('access') || ''
  const [rows, setRows] = useState([])
  const [page, setPage] = useState(1)
  const [pageSize] = useState(10)
  const [totalPages, setTotalPages] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const [companyOptions, setCompanyOptions] = useState([])
  const [companyReloadTick, setCompanyReloadTick] = useState(0)
  const [jobForm, setJobForm] = useState(null)
  const [loading, setLoading] = useState(true)
  const [formError, setFormError] = useState('')
  const [filters, setFilters] = useState({
    companyName: '',
    postingDate: '',
    appliedDate: '',
    jobId: '',
    role: '',
  })
  const [ordering, setOrdering] = useState('-date_of_posting')
  const [previewResume, setPreviewResume] = useState(null)
  const [selectedIds, setSelectedIds] = useState([])

  const bumpFilters = (patch) => {
    setFilters((prev) => ({ ...prev, ...patch }))
    setPage(1)
  }

  const load = useCallback(async () => {
    if (!access) {
      setRows([])
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const data = await fetchJobs(access, {
        page,
        page_size: pageSize,
        company_name: filters.companyName.trim() || undefined,
        posting_date: filters.postingDate || undefined,
        applied_date: filters.appliedDate || undefined,
        job_id: filters.jobId.trim() || undefined,
        role: filters.role.trim() || undefined,
        ordering,
      })
      const list = Array.isArray(data?.results) ? data.results : []
      setRows(list)
      setTotalCount(Number(data?.count ?? list.length))
      setTotalPages(Number(data?.total_pages || 1))
    } catch (err) {
      console.error(err.message || 'Failed to load jobs.')
    } finally {
      setLoading(false)
    }
  }, [access, page, pageSize, filters, ordering])

  useEffect(() => {
    setSelectedIds((prev) => prev.filter((id) => rows.some((row) => row.id === id)))
  }, [rows])

  const allSelected = rows.length > 0 && rows.every((row) => selectedIds.includes(row.id))
  const toggleSelect = (rowId, checked) => {
    setSelectedIds((prev) => {
      if (checked) return Array.from(new Set([...prev, rowId]))
      return prev.filter((id) => id !== rowId)
    })
  }
  const toggleSelectAll = (checked) => {
    if (!checked) {
      setSelectedIds([])
      return
    }
    setSelectedIds(rows.map((row) => row.id))
  }

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!access) return
    let cancelled = false
    ;(async () => {
      try {
        const data = await fetchCompanies(access, { page: 1, page_size: 200 })
        const list = Array.isArray(data?.results) ? data.results : []
        if (!cancelled) setCompanyOptions(list)
      } catch {
        if (!cancelled) setCompanyOptions([])
      }
    })()
    return () => {
      cancelled = true
    }
  }, [access, companyReloadTick])

  const openCreateForm = () => {
    setFormError('')
    setJobForm(emptyJobForm())
  }

  const openEditForm = (row) => {
    setFormError('')
    setJobForm({
      editingId: row.id,
      company: row.company != null ? String(row.company) : '',
      new_company_name: '',
      job_id: row.job_id || '',
      role: row.role || '',
      job_link: row.job_link || '',
      jd_text: row.jd_text || '',
      date_of_posting: toDateInput(row.date_of_posting),
      applied_at: toDateInput(row.applied_at),
      is_closed: Boolean(row.is_closed),
    })
  }

  const appendCompanyToPayload = (payload, companySel, newCompanyRaw) => {
    const rawNew = String(newCompanyRaw || '').trim()
    if (rawNew) {
      return { ...payload, new_company_name: rawNew }
    }
    if (companySel) {
      return { ...payload, company: Number(companySel) }
    }
    return payload
  }

  const submitJobForm = async () => {
    if (!jobForm) return
    const jobId = String(jobForm.job_id || '').trim()
    const role = String(jobForm.role || '').trim()
    const companySel = String(jobForm.company || '').trim()
    const rawNew = String(jobForm.new_company_name || '').trim()
    if (!jobId || !role) {
      setFormError('Job ID and Role are required.')
      return
    }
    if (!rawNew && !companySel) {
      setFormError('Select a company or enter a new company name.')
      return
    }
    setFormError('')
    try {
      const jd = String(jobForm.jd_text || '')
      const base = {
        job_id: jobId,
        role,
        job_link: normalizeUrl(jobForm.job_link),
        jd_text: jd,
        date_of_posting: jobForm.date_of_posting || null,
        applied_at: jobForm.applied_at || null,
        is_closed: Boolean(jobForm.is_closed),
      }

      let jsonPayload = { ...base }
      jsonPayload = appendCompanyToPayload(jsonPayload, companySel, rawNew)
      if (jobForm.editingId) {
        await updateJob(access, jobForm.editingId, jsonPayload)
      } else {
        await createJob(access, jsonPayload)
      }
      setJobForm(null)
      setCompanyReloadTick((t) => t + 1)
      await load()
    } catch (err) {
      setFormError(err.message || 'Could not save job.')
    }
  }

  const bulkDeleteSelected = async () => {
    if (!selectedIds.length) return
    try {
      await Promise.allSettled(selectedIds.map((id) => deleteJob(access, id)))
      setSelectedIds([])
      await load()
    } catch (err) {
      console.error(err.message || 'Could not delete selected jobs.')
    }
  }

  const bulkMarkClosed = async () => {
    if (!selectedIds.length) return
    try {
      const targetRows = rows.filter((row) => selectedIds.includes(row.id))
      await Promise.allSettled(
        targetRows.map((row) => updateJob(access, row.id, { is_closed: true })),
      )
      setSelectedIds([])
      await load()
    } catch (err) {
      console.error(err.message || 'Could not mark selected jobs as closed.')
    }
  }

  return (
    <main className="page page-wide mx-auto w-full">
      <section className="jobs-topbar">
        <div className="tracking-head">
          <div>
            <h1>Jobs</h1>
            <p className="subtitle">Filter, edit, and manage company-linked roles in one place.</p>
          </div>
          <div className="actions">
            <button type="button" className="secondary" onClick={bulkMarkClosed} disabled={!selectedIds.length || loading}>Mark Closed</button>
            <button type="button" className="secondary" onClick={bulkDeleteSelected} disabled={!selectedIds.length || loading}>Delete Selected</button>
            <button type="button" className="secondary" onClick={openCreateForm}>Add job</button>
          </div>
        </div>

        <div className="jobs-summary-bar">
          <span>{totalCount} jobs</span>
          <span>{selectedIds.length} selected</span>
          <span>{rows.filter((row) => !row?.is_closed && !row?.is_removed).length} open on page</span>
        </div>
      </section>

      <section className="tracking-filters filters-one-row jobs-filters-one-row">
        <label>
          Company
          <input
            value={filters.companyName}
            onChange={(e) => bumpFilters({ companyName: e.target.value })}
            placeholder="Contains…"
          />
        </label>
        <label>
          Posting
          <input
            type="date"
            value={filters.postingDate}
            onChange={(e) => bumpFilters({ postingDate: e.target.value })}
          />
        </label>
        <label>
          Applied
          <input
            type="date"
            value={filters.appliedDate}
            onChange={(e) => bumpFilters({ appliedDate: e.target.value })}
          />
        </label>
        <label>
          Job ID
          <input value={filters.jobId} onChange={(e) => bumpFilters({ jobId: e.target.value })} placeholder="Contains…" />
        </label>
        <label>
          Role
          <input value={filters.role} onChange={(e) => bumpFilters({ role: e.target.value })} placeholder="Contains…" />
        </label>
        <label>
          Sort
          <select
            value={ordering}
            onChange={(e) => {
              setOrdering(e.target.value)
              setPage(1)
            }}
          >
            <option value="-date_of_posting">Posting ↓</option>
            <option value="date_of_posting">Posting ↑</option>
            <option value="-applied_at">Applied ↓</option>
            <option value="applied_at">Applied ↑</option>
            <option value="-created_at">Created ↓</option>
            <option value="created_at">Created ↑</option>
            <option value="role">Role A–Z</option>
            <option value="-role">Role Z–A</option>
            <option value="job_id">Job ID A–Z</option>
            <option value="-job_id">Job ID Z–A</option>
            <option value="company_name">Company A–Z</option>
            <option value="-company_name">Company Z–A</option>
          </select>
        </label>
      </section>

      {loading ? <p className="hint">Loading jobs…</p> : null}

      <div className="tracking-table-wrap tracking-table-wrap-compact jobs-table-wrap">
        <table className="tracking-table tracking-table-compact jobs-table">
          <thead>
            <tr>
              <th>
                <input type="checkbox" checked={allSelected} onChange={(event) => toggleSelectAll(event.target.checked)} />
              </th>
              <th>Job ID</th>
              <th>Company</th>
              <th>Role</th>
              <th>Posting date</th>
              <th>Resume</th>
              <th>Job link</th>
              <th>Applied date</th>
              <th>Edit</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(row.id)}
                    onChange={(event) => toggleSelect(row.id, event.target.checked)}
                  />
                </td>
                <td className="jobs-id-cell">{row.job_id || '—'}</td>
                <td className="jobs-company-cell">{row.company_name || '—'}</td>
                <td className="jobs-role-cell">{row.role || '—'}</td>
                <td className="jobs-date-cell">{formatDisplayDate(row.date_of_posting)}</td>
                <td className="jobs-tailored-cell">
                  {row.resume_preview ? (
                    <div className="tracking-actions-compact">
                      <button
                        type="button"
                        className="secondary tracking-icon-btn"
                        title="Preview resume"
                        onClick={() => setPreviewResume(row.resume_preview)}
                      >
                        <PreviewIcon />
                      </button>
                    </div>
                  ) : (
                    ''
                  )}
                </td>
                <td className="jobs-link-cell">
                  {row.job_link ? (
                    <a
                      href={row.job_link}
                      target="_blank"
                      rel="noreferrer"
                      className="jobs-external-link"
                      title={row.job_link}
                      aria-label="Open job posting in new tab"
                    >
                      <ExternalLinkIcon />
                    </a>
                  ) : (
                    '—'
                  )}
                </td>
                <td className="jobs-date-cell">{formatDisplayDate(row.applied_at)}</td>
                <td className="jobs-edit-cell">
                  <button
                    type="button"
                    className="secondary jobs-edit-btn"
                    onClick={() => openEditForm(row)}
                    aria-label="Edit job"
                    title="Edit job"
                  >
                    <PencilIcon />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!loading && !rows.length ? <p className="hint">No jobs found.</p> : null}

      <div className="table-pagination">
        <button type="button" className="secondary" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>
          Previous
        </button>
        <span>
          Page {page} / {Math.max(1, totalPages)} ({totalCount})
        </span>
        <button
          type="button"
          className="secondary"
          onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          disabled={page >= totalPages}
        >
          Next
        </button>
      </div>

      {jobForm ? (
        <div className="modal-overlay">
          <div className="modal-panel modal-panel-jobs jobs-modal-panel">
            <div className="tracking-modal-head">
              <h2>{jobForm.editingId ? 'Edit job' : 'Add job'}</h2>
              <p className="subtitle">Keep the company, role, posting details, and resume link structured in one place.</p>
            </div>
            <div className="tracking-form-grid jobs-form-grid">
            <div className="tracking-form-section-title tracking-form-span-2">Company</div>
            <label>
              Company (existing)
              <SingleSelectDropdown
                value={jobForm.company}
                placeholder="Select company"
                options={companyOptions.map((c) => ({ value: String(c.id), label: String(c.name || '') }))}
                onChange={(nextValue) => setJobForm((prev) => ({ ...prev, company: nextValue }))}
              />
            </label>
            <label>
              New company name
              <input
                value={jobForm.new_company_name}
                onChange={(e) => setJobForm((prev) => ({ ...prev, new_company_name: e.target.value }))}
                placeholder="Creates company if not already listed"
              />
            </label>
            <p className="hint jobs-form-hint tracking-form-span-2">If the company is missing, type a name below. Extra spaces are removed; matching names reuse one company.</p>
            <div className="tracking-form-section-title tracking-form-span-2">Role & Identity</div>
            <label>
              Job ID*
              <input value={jobForm.job_id} onChange={(e) => setJobForm((prev) => ({ ...prev, job_id: e.target.value }))} />
            </label>
            <label>
              Role* (preset or custom)
              <input
                value={jobForm.role}
                onChange={(e) => setJobForm((prev) => ({ ...prev, role: e.target.value }))}
                list="job-role-presets-list"
                placeholder="Pick a preset or type your own"
              />
            </label>
            <datalist id="job-role-presets-list">
              {ROLE_PRESETS.map((r) => (
                <option key={r} value={r} />
              ))}
            </datalist>
            <div className="jobs-role-chips tracking-form-span-2">
              {ROLE_PRESETS.map((r) => (
                <button
                  key={r}
                  type="button"
                  className="secondary jobs-role-chip"
                  onClick={() => setJobForm((prev) => ({ ...prev, role: r }))}
                >
                  {r}
                </button>
              ))}
            </div>
            <div className="tracking-form-section-title tracking-form-span-2">Links & Dates</div>
            <label>
              Job link
              <input value={jobForm.job_link} onChange={(e) => setJobForm((prev) => ({ ...prev, job_link: e.target.value }))} />
            </label>
            <label>
              JD text
              <textarea
                rows={4}
                value={jobForm.jd_text}
                onChange={(e) => setJobForm((prev) => ({ ...prev, jd_text: e.target.value }))}
              />
            </label>
            <label>
              Date of posting
              <input
                type="date"
                value={jobForm.date_of_posting || ''}
                onChange={(e) => setJobForm((prev) => ({ ...prev, date_of_posting: e.target.value }))}
              />
            </label>
            <label>
              Applied date
              <input
                type="date"
                value={jobForm.applied_at || ''}
                onChange={(e) => setJobForm((prev) => ({ ...prev, applied_at: e.target.value }))}
              />
            </label>
            {jobForm.editingId ? (
              <div className="jobs-checkbox-row tracking-form-span-2">
                <label className="tracking-check jobs-form-check jobs-form-check-card">
                  <input
                    type="checkbox"
                    checked={jobForm.is_closed}
                    onChange={(e) => setJobForm((prev) => ({ ...prev, is_closed: e.target.checked }))}
                  />
                  <span>Closed (yes)</span>
                </label>
              </div>
            ) : null}
            </div>
            {formError ? <p className="error">{formError}</p> : null}
            <div className="actions">
              <button type="button" onClick={submitJobForm}>{jobForm.editingId ? 'Save' : 'Create'}</button>
              <button type="button" className="secondary" onClick={() => { setJobForm(null); setFormError('') }}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}

      {previewResume ? (
        <div className="modal-overlay" onClick={() => setPreviewResume(null)}>
          <div className="modal-panel" style={{ width: 'min(920px, 96vw)' }} onClick={(event) => event.stopPropagation()}>
            <h2>Resume Preview</h2>
            <p className="subtitle">{previewResume.title || 'Resume'}</p>
            {previewResume.builder_data && Object.keys(previewResume.builder_data).length ? (
              <section className="preview-only" style={{ maxHeight: '80vh', overflow: 'auto' }}>
                <ResumeSheet form={previewResume.builder_data} />
              </section>
            ) : (
              <p className="hint">No builder data available for preview.</p>
            )}
            <div className="actions">
              <button type="button" className="secondary" onClick={() => setPreviewResume(null)}>Close</button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  )
}

export default JobsPage
