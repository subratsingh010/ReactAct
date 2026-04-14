import { useState } from 'react'

import { bulkUploadEmployees, bulkUploadJobs } from '../api'

const EMPLOYEE_SAMPLE = `[
  {
    "first_name": "Aman",
    "middle_name": "",
    "last_name": "Kumar",
    "role": "Talent Acquisition Specialist",
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
    "job_id": "2010707",
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

function pretty(data) {
  try {
    return JSON.stringify(data, null, 2)
  } catch {
    return String(data)
  }
}

function BulkUploadPage() {
  const access = localStorage.getItem('access') || ''

  const [employeeJson, setEmployeeJson] = useState(EMPLOYEE_SAMPLE)
  const [employeeFile, setEmployeeFile] = useState(null)
  const [employeeLoading, setEmployeeLoading] = useState(false)
  const [employeeResult, setEmployeeResult] = useState('')
  const [employeeError, setEmployeeError] = useState('')

  const [jobJson, setJobJson] = useState(JOB_SAMPLE)
  const [jobFile, setJobFile] = useState(null)
  const [jobLoading, setJobLoading] = useState(false)
  const [jobResult, setJobResult] = useState('')
  const [jobError, setJobError] = useState('')

  const submitEmployeesJson = async () => {
    setEmployeeError('')
    setEmployeeResult('')
    setEmployeeLoading(true)
    try {
      const rows = parseJsonList(employeeJson, 'employees')
      const data = await bulkUploadEmployees(access, { employees: rows })
      setEmployeeResult(pretty(data))
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
    setEmployeeResult('')
    setEmployeeLoading(true)
    try {
      const data = await bulkUploadEmployees(access, employeeFile, { isFile: true })
      setEmployeeResult(pretty(data))
    } catch (err) {
      setEmployeeError(err.message || 'Employee file upload failed.')
    } finally {
      setEmployeeLoading(false)
    }
  }

  const submitJobsJson = async () => {
    setJobError('')
    setJobResult('')
    setJobLoading(true)
    try {
      const rows = parseJsonList(jobJson, 'jobs')
      const data = await bulkUploadJobs(access, { jobs: rows })
      setJobResult(pretty(data))
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
    setJobResult('')
    setJobLoading(true)
    try {
      const data = await bulkUploadJobs(access, jobFile, { isFile: true })
      setJobResult(pretty(data))
    } catch (err) {
      setJobError(err.message || 'Job file upload failed.')
    } finally {
      setJobLoading(false)
    }
  }

  return (
    <main className="page page-wide page-plain mx-auto w-full">
      <div className="tracking-head">
        <div>
          <h1>Bulk Upload</h1>
          <p className="subtitle">Upload Employees and Jobs separately using JSON text or JSON file.</p>
        </div>
      </div>

      <section className="card" style={{ marginBottom: 16 }}>
        <h2>Employees Bulk Upload</h2>
        <p className="hint">Required fields: first_name, last_name, role, location, company, department.</p>
        <label>
          Employees JSON
          <textarea
            rows={10}
            value={employeeJson}
            onChange={(event) => setEmployeeJson(event.target.value)}
            placeholder='Paste array or { "employees": [...] }'
          />
        </label>
        <div className="actions" style={{ marginBottom: 10 }}>
          <button type="button" onClick={submitEmployeesJson} disabled={employeeLoading}>Upload Employees (JSON)</button>
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
        </div>
        {employeeError ? <p className="error">{employeeError}</p> : null}
        {employeeResult ? (
          <label>
            Employee Upload Result
            <textarea rows={12} value={employeeResult} readOnly />
          </label>
        ) : null}
      </section>

      <section className="card">
        <h2>Jobs Bulk Upload</h2>
        <p className="hint">Required fields: company, job_id, job_link. Duplicate company + job_id is rejected.</p>
        <label>
          Jobs JSON
          <textarea
            rows={10}
            value={jobJson}
            onChange={(event) => setJobJson(event.target.value)}
            placeholder='Paste array or { "jobs": [...] }'
          />
        </label>
        <div className="actions" style={{ marginBottom: 10 }}>
          <button type="button" onClick={submitJobsJson} disabled={jobLoading}>Upload Jobs (JSON)</button>
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
        </div>
        {jobError ? <p className="error">{jobError}</p> : null}
        {jobResult ? (
          <label>
            Job Upload Result
            <textarea rows={12} value={jobResult} readOnly />
          </label>
        ) : null}
      </section>
    </main>
  )
}

export default BulkUploadPage
