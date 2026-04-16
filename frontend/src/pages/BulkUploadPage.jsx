import { useState } from 'react'

import { bulkUploadEmployees, bulkUploadJobs } from '../api'

const EMPLOYEE_SAMPLE = `[
  {
    "first_name": "Aman",
    "middle_name": "",
    "last_name": "Kumar",
    "JobRole": "Talent Acquisition Specialist",
    "location": "Bengaluru",
    "company": "Mastercard",
    "department": "HR",
    "email": "aman.kumar@mastercard.com",
    "contact_number": "+91-9000000000"
  }
]`

const JOB_SAMPLE = `[
  {
    "company": "Mastercard",
    "job_link": "https://example.com/jobs/2010707",
    "role": "SDE"
  }
]`

function parseJsonList(raw, keyName) {
  const text = String(raw || '').trim()
  if (!text) throw new Error(`Enter ${keyName} JSON.`)
  let parsed
  try {
    parsed = JSON.parse(text)
  } catch (err) {
    throw new Error(`Invalid ${keyName} JSON: ${err.message}`)
  }
  if (Array.isArray(parsed)) return parsed
  if (parsed && typeof parsed === 'object' && Array.isArray(parsed[keyName])) return parsed[keyName]
  throw new Error(`${keyName} JSON must be an array or object containing "${keyName}" array.`)
}

function ResultSummary({ title, data, kind }) {
  if (!data || typeof data !== 'object') return null
  const box = kind === 'employee' ? data.employees : data.jobs
  if (!box || typeof box !== 'object') return null

  const errors = Array.isArray(box.errors) ? box.errors : []
  const hasErrors = errors.length > 0

  return (
    <section className={`bulk-result ${hasErrors ? 'is-error' : 'is-success'}`}>
      <h3 className="bulk-result-title">{title}</h3>
      <div className="bulk-result-stats">
        <span className="bulk-stat-chip">Received: {Number(box.received || 0)}</span>
        <span className="bulk-stat-chip">Created: {Number(box.created || 0)}</span>
        <span className="bulk-stat-chip">Company Created: {Number(box.company_created || 0)}</span>
        {kind === 'job' ? (
          <>
            <span className="bulk-stat-chip">Duplicate in file: {Number(box.duplicate_in_file || 0)}</span>
            <span className="bulk-stat-chip">Duplicate in DB: {Number(box.duplicate_in_db || 0)}</span>
          </>
        ) : null}
      </div>
      {hasErrors ? (
        <>
          <p className="error">Row errors: {errors.length}</p>
          <div className="bulk-error-list">
            {errors.map((item, index) => {
              const rowNo = Number(item?.row || 0)
              const message = typeof item?.error === 'string' ? item.error : JSON.stringify(item?.error || {})
              return (
                <p key={`${kind}-err-${index}`}>
                  Row {rowNo || '-'}: {message}
                </p>
              )
            })}
          </div>
        </>
      ) : (
        <p className="bulk-success-text">Upload completed with no row errors.</p>
      )}
    </section>
  )
}

function BulkUploadPage() {
  const access = localStorage.getItem('access') || ''

  const [employeeJson, setEmployeeJson] = useState('')
  const [employeeFile, setEmployeeFile] = useState(null)
  const [employeeLoading, setEmployeeLoading] = useState(false)
  const [employeeResult, setEmployeeResult] = useState(null)
  const [employeeError, setEmployeeError] = useState('')

  const [jobJson, setJobJson] = useState('')
  const [jobFile, setJobFile] = useState(null)
  const [jobLoading, setJobLoading] = useState(false)
  const [jobResult, setJobResult] = useState(null)
  const [jobError, setJobError] = useState('')

  const submitEmployeesJson = async () => {
    setEmployeeError('')
    setEmployeeResult(null)
    setEmployeeLoading(true)
    try {
      const rows = parseJsonList(employeeJson, 'employees')
      const data = await bulkUploadEmployees(access, { employees: rows })
      setEmployeeResult(data)
    } catch (err) {
      setEmployeeError(err.message || 'Employee upload failed.')
    } finally {
      setEmployeeLoading(false)
    }
  }

  const submitEmployeesFile = async () => {
    if (!employeeFile) {
      setEmployeeError('Select an employee JSON file first.')
      return
    }
    setEmployeeError('')
    setEmployeeResult(null)
    setEmployeeLoading(true)
    try {
      const data = await bulkUploadEmployees(access, employeeFile, { isFile: true })
      setEmployeeResult(data)
    } catch (err) {
      setEmployeeError(err.message || 'Employee file upload failed.')
    } finally {
      setEmployeeLoading(false)
    }
  }

  const submitJobsJson = async () => {
    setJobError('')
    setJobResult(null)
    setJobLoading(true)
    try {
      const rows = parseJsonList(jobJson, 'jobs')
      const data = await bulkUploadJobs(access, { jobs: rows })
      setJobResult(data)
    } catch (err) {
      setJobError(err.message || 'Job upload failed.')
    } finally {
      setJobLoading(false)
    }
  }

  const submitJobsFile = async () => {
    if (!jobFile) {
      setJobError('Select a job JSON file first.')
      return
    }
    setJobError('')
    setJobResult(null)
    setJobLoading(true)
    try {
      const data = await bulkUploadJobs(access, jobFile, { isFile: true })
      setJobResult(data)
    } catch (err) {
      setJobError(err.message || 'Job file upload failed.')
    } finally {
      setJobLoading(false)
    }
  }

  return (
    <main className="page page-wide page-plain mx-auto w-full bulk-shell">
      <div className="tracking-head">
        <div>
          <h1>Bulk Upload</h1>
          <p className="subtitle">Upload Employees and Jobs separately using JSON text or JSON file.</p>
        </div>
      </div>
      <section className="bulk-banner">
        <p>Tip: paste JSON and upload directly, or choose `.json` files. Results show created rows, duplicates, and row-level errors.</p>
      </section>

      <div className="bulk-grid">
        <section className="bulk-panel">
          <h2>Employees Bulk Upload</h2>
          <p className="hint">Required fields: first_name, last_name, JobRole, location, company, department.</p>
          <label>
            Employees JSON
            <textarea
              rows={11}
              value={employeeJson}
              onChange={(event) => setEmployeeJson(event.target.value)}
              placeholder={EMPLOYEE_SAMPLE}
            />
          </label>
          <div className="actions">
            <button type="button" onClick={submitEmployeesJson} disabled={employeeLoading}>Upload Employees (JSON)</button>
            <button type="button" className="secondary" onClick={() => setEmployeeJson(EMPLOYEE_SAMPLE)} disabled={employeeLoading}>Reset Sample</button>
          </div>
          <label>
            Employees JSON File
            <input
              type="file"
              accept="application/json,.json"
              onChange={(event) => setEmployeeFile(event.target.files?.[0] || null)}
            />
          </label>
          <div className="actions">
            <button type="button" className="secondary" onClick={submitEmployeesFile} disabled={employeeLoading}>Upload Employees (File)</button>
            {employeeFile ? <span className="hint">Selected: {employeeFile.name}</span> : null}
          </div>
          {employeeError ? <p className="error">{employeeError}</p> : null}
          <ResultSummary title="Employee Upload Result" data={employeeResult} kind="employee" />
        </section>

        <section className="bulk-panel">
          <h2>Jobs Bulk Upload</h2>
          <p className="hint">Required fields: company, job_link. `job_id` is optional and will be generated if missing.</p>
          <label>
            Jobs JSON
            <textarea
              rows={11}
              value={jobJson}
              onChange={(event) => setJobJson(event.target.value)}
              placeholder={JOB_SAMPLE}
            />
          </label>
          <div className="actions">
            <button type="button" onClick={submitJobsJson} disabled={jobLoading}>Upload Jobs (JSON)</button>
            <button type="button" className="secondary" onClick={() => setJobJson(JOB_SAMPLE)} disabled={jobLoading}>Reset Sample</button>
          </div>
          <label>
            Jobs JSON File
            <input
              type="file"
              accept="application/json,.json"
              onChange={(event) => setJobFile(event.target.files?.[0] || null)}
            />
          </label>
          <div className="actions">
            <button type="button" className="secondary" onClick={submitJobsFile} disabled={jobLoading}>Upload Jobs (File)</button>
            {jobFile ? <span className="hint">Selected: {jobFile.name}</span> : null}
          </div>
          {jobError ? <p className="error">{jobError}</p> : null}
          <ResultSummary title="Job Upload Result" data={jobResult} kind="job" />
        </section>
      </div>
    </main>
  )
}

export default BulkUploadPage
