import { useEffect, useMemo, useState } from 'react'

import {
  createCompany,
  createEmployee,
  deleteCompany as deleteCompanyApi,
  deleteEmployee as deleteEmployeeApi,
  fetchCompanies,
  fetchEmployees,
  updateCompany as updateCompanyApi,
  updateEmployee as updateEmployeeApi,
} from '../api'

function deriveEmailPattern(company) {
  const configured = String(company?.mail_format || '').trim()
  if (configured) return configured
  const source = String(company?.workday_domain_url || company?.career_url || '').trim()
  if (!source) return 'firstname.lastname@company.com'
  try {
    const host = new URL(source).hostname.replace(/^www\./i, '')
    return `firstname.lastname@${host}`
  } catch {
    return 'firstname.lastname@company.com'
  }
}

function CompanyPage() {
  const access = localStorage.getItem('access') || ''
  const [companies, setCompanies] = useState([])
  const [employees, setEmployees] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [companyForm, setCompanyForm] = useState(null)
  const [employeeForm, setEmployeeForm] = useState(null)

  const employeesByCompany = useMemo(() => {
    const map = {}
    for (const employee of employees) {
      const key = String(employee.company || '')
      if (!map[key]) map[key] = []
      map[key].push(employee)
    }
    return map
  }, [employees])

  const load = async () => {
    if (!access) {
      setCompanies([])
      setEmployees([])
      setLoading(false)
      return
    }
    setLoading(true)
    setError('')
    try {
      const [companyRows, employeeRows] = await Promise.all([
        fetchCompanies(access),
        fetchEmployees(access),
      ])
      setCompanies(Array.isArray(companyRows) ? companyRows : [])
      setEmployees(Array.isArray(employeeRows) ? employeeRows : [])
    } catch (err) {
      setError(err.message || 'Could not load company data.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [access])

  const openCreateCompanyForm = () => {
    setCompanyForm({
      id: null,
      name: '',
      mail_format: 'firstname.lastname@company.com',
      career_url: '',
      workday_domain_url: '',
    })
  }

  const openEditCompanyForm = (company) => {
    setCompanyForm({
      id: company.id,
      name: company.name || '',
      mail_format: company.mail_format || deriveEmailPattern(company),
      career_url: company.career_url || '',
      workday_domain_url: company.workday_domain_url || '',
    })
  }

  const saveCompanyForm = async () => {
    if (!companyForm) return
    try {
      if (companyForm.id) {
        const updated = await updateCompanyApi(access, companyForm.id, {
          name: companyForm.name,
          mail_format: companyForm.mail_format,
          career_url: companyForm.career_url,
          workday_domain_url: companyForm.workday_domain_url,
        })
        setCompanies((prev) => prev.map((row) => (row.id === companyForm.id ? updated : row)))
      } else {
        const created = await createCompany(access, {
          name: companyForm.name || `Company ${companies.length + 1}`,
          mail_format: companyForm.mail_format,
          career_url: companyForm.career_url,
          workday_domain_url: companyForm.workday_domain_url,
        })
        setCompanies((prev) => [...prev, created])
      }
      setCompanyForm(null)
    } catch (err) {
      setError(err.message || 'Could not save company.')
    }
  }

  const removeCompany = async (companyId) => {
    setCompanies((prev) => prev.filter((row) => row.id !== companyId))
    setEmployees((prev) => prev.filter((row) => row.company !== companyId))
    try {
      await deleteCompanyApi(access, companyId)
    } catch (err) {
      setError(err.message || 'Could not delete company.')
    }
  }

  const openCreateEmployeeForm = () => {
    if (!companies.length) {
      setError('Create at least one company first.')
      return
    }
    const defaultCompanyId = String(companies[0].id)
    setEmployeeForm({
      id: null,
      company: defaultCompanyId,
      name: '',
      department: '',
      email: '',
      location: '',
      profile: '',
      about: '',
      personalized_template_helpful: 'partial_somewhat',
    })
  }

  const openEditEmployeeForm = (employee) => {
    setEmployeeForm({
      id: employee.id,
      company: String(employee.company || ''),
      name: employee.name || '',
      department: employee.department || '',
      email: employee.email || '',
      location: employee.location || '',
      profile: employee.profile || '',
      about: employee.about || '',
      personalized_template_helpful: employee.personalized_template_helpful || 'partial_somewhat',
    })
  }

  const saveEmployeeForm = async () => {
    if (!employeeForm) return
    const companyId = Number(employeeForm.company)
    if (!companyId) {
      setError('Select company for HR.')
      return
    }
    try {
      if (employeeForm.id) {
        const updated = await updateEmployeeApi(access, employeeForm.id, {
          company: companyId,
          name: employeeForm.name,
          department: employeeForm.department,
          email: employeeForm.email,
          location: employeeForm.location,
          profile: employeeForm.profile,
          about: employeeForm.about,
          personalized_template_helpful: employeeForm.personalized_template_helpful,
        })
        setEmployees((prev) => prev.map((row) => (row.id === employeeForm.id ? updated : row)))
      } else {
        const created = await createEmployee(access, {
          company: companyId,
          name: employeeForm.name || 'HR',
          department: employeeForm.department,
          email: employeeForm.email,
          location: employeeForm.location,
          profile: employeeForm.profile,
          about: employeeForm.about,
          personalized_template_helpful: employeeForm.personalized_template_helpful,
        })
        setEmployees((prev) => [...prev, created])
      }
      setEmployeeForm(null)
    } catch (err) {
      setError(err.message || 'Could not save HR.')
    }
  }

  const removeHr = async (employeeId) => {
    setEmployees((prev) => prev.filter((row) => row.id !== employeeId))
    try {
      await deleteEmployeeApi(access, employeeId)
    } catch (err) {
      setError(err.message || 'Could not delete HR.')
    }
  }

  return (
    <main className="page page-wide page-plain mx-auto w-full">
      <div className="company-head">
        <div>
          <h1>Companies</h1>
          <p className="subtitle">Database connected companies and HR records.</p>
        </div>
        <div className="actions">
          <button type="button" onClick={openCreateCompanyForm}>Add Company</button>
          <button type="button" className="secondary" onClick={openCreateEmployeeForm}>Add HRs</button>
          <button type="button" className="secondary" onClick={load}>Refresh</button>
        </div>
      </div>

      {error ? <p className="error">{error}</p> : null}
      {loading ? <p className="hint">Loading companies...</p> : null}

      <div className="company-list">
        {companies.map((company) => {
          const hrs = employeesByCompany[String(company.id)] || []
          return (
            <section key={company.id} className="company-row">
              <div className="company-action-stack">
                <button type="button" className="company-edit-btn" onClick={() => openEditCompanyForm(company)} title="Edit Company">✎</button>
                <button type="button" className="company-edit-btn company-delete-btn" onClick={() => removeCompany(company.id)} title="Delete Company">🗑</button>
              </div>

              <div className="company-title-wrap">
                <h2 className="company-title">{company.name}</h2>
                {company.workday_domain_url ? <p className="company-subline">{company.workday_domain_url}</p> : null}
                {!company.workday_domain_url && company.career_url ? <p className="company-subline">{company.career_url}</p> : null}
                <p className="company-subline">{deriveEmailPattern(company)}</p>
              </div>

              <div className="company-hr-list">
                {hrs.map((hr) => (
                  <div key={hr.id} className="company-hr-item">
                    <div className="company-action-stack company-action-stack-hr">
                      <button type="button" className="company-edit-btn company-edit-btn-hr" onClick={() => openEditEmployeeForm(hr)} title="Edit HR">✎</button>
                      <button type="button" className="company-edit-btn company-edit-btn-hr company-delete-btn" onClick={() => removeHr(hr.id)} title="Delete HR">🗑</button>
                    </div>
                    <span className={`company-dot ${hr.about ? 'is-green' : 'is-red'}`} />
                    <div>
                      <p className="company-hr-name">{hr.name}</p>
                      {hr.department ? <p className="company-hr-meta">{hr.department}</p> : null}
                      {hr.email ? <p className="company-hr-meta">{hr.email}</p> : null}
                      {hr.location ? <p className="company-hr-meta">{hr.location}</p> : null}
                      {hr.profile ? <p className="company-hr-meta">{hr.profile}</p> : null}
                    </div>
                  </div>
                ))}
                {!hrs.length ? <p className="hint">No HR records yet.</p> : null}
              </div>
            </section>
          )
        })}
        {!loading && !companies.length ? <p className="hint">No companies found.</p> : null}
      </div>

      {companyForm ? (
        <div className="modal-overlay">
          <div className="modal-panel">
            <h2>{companyForm.id ? 'Edit Company' : 'Add Company'}</h2>
            <label>Company Name<input value={companyForm.name} onChange={(event) => setCompanyForm((prev) => ({ ...prev, name: event.target.value }))} /></label>
            <label>Mail Format<input value={companyForm.mail_format} onChange={(event) => setCompanyForm((prev) => ({ ...prev, mail_format: event.target.value }))} /></label>
            <label>Career URL<input value={companyForm.career_url} onChange={(event) => setCompanyForm((prev) => ({ ...prev, career_url: event.target.value }))} /></label>
            <label>Workday Domain URL<input value={companyForm.workday_domain_url} onChange={(event) => setCompanyForm((prev) => ({ ...prev, workday_domain_url: event.target.value }))} /></label>
            <div className="actions">
              <button type="button" onClick={saveCompanyForm}>Save</button>
              <button type="button" className="secondary" onClick={() => setCompanyForm(null)}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}

      {employeeForm ? (
        <div className="modal-overlay">
          <div className="modal-panel">
            <h2>{employeeForm.id ? 'Edit HR' : 'Add HR'}</h2>
            <label>
              Company
              <select value={employeeForm.company} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, company: event.target.value }))}>
                <option value="">Select company</option>
                {companies.map((company) => (
                  <option key={company.id} value={company.id}>{company.name}</option>
                ))}
              </select>
            </label>
            <label>Name<input value={employeeForm.name} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, name: event.target.value }))} /></label>
            <label>Department<input value={employeeForm.department} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, department: event.target.value }))} /></label>
            <label>Email<input value={employeeForm.email} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, email: event.target.value }))} /></label>
            <label>Location<input value={employeeForm.location} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, location: event.target.value }))} /></label>
            <label>Profile<input value={employeeForm.profile} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, profile: event.target.value }))} /></label>
            <label>About<textarea rows="4" value={employeeForm.about} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, about: event.target.value }))} /></label>
            <label>
              Template Helpful
              <select value={employeeForm.personalized_template_helpful} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, personalized_template_helpful: event.target.value }))}>
                <option value="good">Good</option>
                <option value="partial_somewhat">Partial / Somewhat</option>
                <option value="never">Never</option>
              </select>
            </label>
            <div className="actions">
              <button type="button" onClick={saveEmployeeForm}>Save</button>
              <button type="button" className="secondary" onClick={() => setEmployeeForm(null)}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  )
}

export default CompanyPage
