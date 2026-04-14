import { useEffect, useMemo, useState } from 'react'
import { SingleSelectDropdown } from '../components/SearchableDropdown'

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

function normalizeUrl(value) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  if (/^https?:\/\//i.test(raw)) return raw
  return `https://${raw}`
}

function splitFullName(rawName) {
  const parts = String(rawName || '').trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return { first_name: '', middle_name: '', last_name: '' }
  if (parts.length === 1) return { first_name: parts[0], middle_name: '', last_name: '' }
  if (parts.length === 2) return { first_name: parts[0], middle_name: '', last_name: parts[1] }
  return {
    first_name: parts[0],
    middle_name: parts.slice(1, -1).join(' '),
    last_name: parts[parts.length - 1],
  }
}

function mergeNameParts(firstName, middleName, lastName) {
  return [firstName, middleName, lastName].map((item) => String(item || '').trim()).filter(Boolean).join(' ')
}

function CompanyPage() {
  const access = localStorage.getItem('access') || ''
  const [companies, setCompanies] = useState([])
  const [employees, setEmployees] = useState([])
  const [page, setPage] = useState(1)
  const [pageSize] = useState(6)
  const [totalPages, setTotalPages] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const [ordering, setOrdering] = useState('name')
  const [filters, setFilters] = useState({
    company: '',
    hr: '',
    role: '',
    location: '',
  })
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

  const filteredCompanies = useMemo(() => {
    const out = companies.filter((company) => {
      const hrs = employeesByCompany[String(company.id)] || []
      const companyName = String(company.name || '').toLowerCase()
      const companyFilter = String(filters.company || '').trim().toLowerCase()
      if (companyFilter && !companyName.includes(companyFilter)) return false

      const hrFilter = String(filters.hr || '').trim().toLowerCase()
      const roleFilter = String(filters.role || '').trim().toLowerCase()
      const locationFilter = String(filters.location || '').trim().toLowerCase()
      if (!hrFilter && !roleFilter && !locationFilter) return true

      return hrs.some((hr) => {
        const hrName = String(hr.name || '').toLowerCase()
        const hrRole = String(hr.department || '').toLowerCase()
        const hrLocation = String(hr.location || '').toLowerCase()
        if (hrFilter && !hrName.includes(hrFilter)) return false
        if (roleFilter && !hrRole.includes(roleFilter)) return false
        if (locationFilter && !hrLocation.includes(locationFilter)) return false
        return true
      })
    })

    out.sort((a, b) => {
      const aName = String(a.name || '').toLowerCase()
      const bName = String(b.name || '').toLowerCase()
      const aCreated = new Date(a.created_at || 0).getTime()
      const bCreated = new Date(b.created_at || 0).getTime()
      switch (ordering) {
      case '-name':
        return bName.localeCompare(aName)
      case '-created_at':
        return bCreated - aCreated
      case 'created_at':
        return aCreated - bCreated
      case 'name':
      default:
        return aName.localeCompare(bName)
      }
    })
    return out
  }, [companies, employeesByCompany, filters, ordering])

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
        fetchCompanies(access, { page, page_size: pageSize }),
        fetchEmployees(access),
      ])
      const pagedCompanies = Array.isArray(companyRows?.results) ? companyRows.results : (Array.isArray(companyRows) ? companyRows : [])
      setCompanies(pagedCompanies)
      setTotalCount(Number(companyRows?.count || pagedCompanies.length || 0))
      setTotalPages(Number(companyRows?.total_pages || 1))
      if (companyRows?.page && Number(companyRows.page) !== page) {
        setPage(Number(companyRows.page))
      }
      setEmployees(Array.isArray(employeeRows) ? employeeRows : [])
    } catch (err) {
      setError(err.message || 'Could not load company data.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [access, page, pageSize])

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
        await updateCompanyApi(access, companyForm.id, {
          name: companyForm.name,
          mail_format: companyForm.mail_format,
          career_url: companyForm.career_url,
          workday_domain_url: companyForm.workday_domain_url,
        })
      } else {
        await createCompany(access, {
          name: companyForm.name || `Company ${companies.length + 1}`,
          mail_format: companyForm.mail_format,
          career_url: companyForm.career_url,
          workday_domain_url: companyForm.workday_domain_url,
        })
      }
      setCompanyForm(null)
      await load()
    } catch (err) {
      setError(err.message || 'Could not save company.')
    }
  }

  const removeCompany = async (companyId) => {
    try {
      await deleteCompanyApi(access, companyId)
      await load()
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
      first_name: '',
      middle_name: '',
      last_name: '',
      department: '',
      email: '',
      working_mail: true,
      contact_number: '',
      location: '',
      profile: '',
      about: '',
      personalized_template_helpful: 'partial_somewhat',
    })
  }

  const openEditEmployeeForm = (employee) => {
    const parsed = splitFullName(employee.name || '')
    setEmployeeForm({
      id: employee.id,
      company: String(employee.company || ''),
      first_name: employee.first_name || parsed.first_name,
      middle_name: employee.middle_name || parsed.middle_name,
      last_name: employee.last_name || parsed.last_name,
      department: employee.department || '',
      email: employee.email || '',
      working_mail: Boolean(employee.working_mail ?? true),
      contact_number: employee.contact_number || '',
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
    const fullName = mergeNameParts(employeeForm.first_name, employeeForm.middle_name, employeeForm.last_name)
    if (!fullName) {
      setError('Enter at least first or last name.')
      return
    }
    try {
      if (employeeForm.id) {
        const updated = await updateEmployeeApi(access, employeeForm.id, {
          company: companyId,
          name: fullName,
          first_name: employeeForm.first_name,
          middle_name: employeeForm.middle_name,
          last_name: employeeForm.last_name,
          department: employeeForm.department,
          email: employeeForm.email,
          working_mail: Boolean(employeeForm.working_mail),
          contact_number: employeeForm.contact_number,
          location: employeeForm.location,
          profile: employeeForm.profile,
          about: employeeForm.about,
          personalized_template_helpful: employeeForm.personalized_template_helpful,
        })
        setEmployees((prev) => prev.map((row) => (row.id === employeeForm.id ? updated : row)))
      } else {
        const created = await createEmployee(access, {
          company: companyId,
          name: fullName || 'HR',
          first_name: employeeForm.first_name,
          middle_name: employeeForm.middle_name,
          last_name: employeeForm.last_name,
          department: employeeForm.department,
          email: employeeForm.email,
          working_mail: Boolean(employeeForm.working_mail),
          contact_number: employeeForm.contact_number,
          location: employeeForm.location,
          profile: employeeForm.profile,
          about: employeeForm.about,
          personalized_template_helpful: employeeForm.personalized_template_helpful,
        })
        setEmployees((prev) => [...prev, created])
      }
      setEmployeeForm(null)
      await load()
    } catch (err) {
      setError(err.message || 'Could not save HR.')
    }
  }

  const removeHr = async (employeeId) => {
    try {
      await deleteEmployeeApi(access, employeeId)
      await load()
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
          <button type="button" className="secondary" onClick={openCreateEmployeeForm}>Add Employee</button>
          <button type="button" className="secondary" onClick={load}>Refresh</button>
        </div>
      </div>

      {error ? <p className="error">{error}</p> : null}
      {loading ? <p className="hint">Loading companies...</p> : null}

      <section className="tracking-filters filters-one-row">
        <label>
          Company
          <input
            value={filters.company}
            onChange={(event) => setFilters((prev) => ({ ...prev, company: event.target.value }))}
            placeholder="Company name"
          />
        </label>
        <label>
          HR Name
          <input
            value={filters.hr}
            onChange={(event) => setFilters((prev) => ({ ...prev, hr: event.target.value }))}
            placeholder="HR name"
          />
        </label>
        <label>
          Role
          <input
            value={filters.role}
            onChange={(event) => setFilters((prev) => ({ ...prev, role: event.target.value }))}
            placeholder="Role"
          />
        </label>
        <label>
          Location
          <input
            value={filters.location}
            onChange={(event) => setFilters((prev) => ({ ...prev, location: event.target.value }))}
            placeholder="Location"
          />
        </label>
        <label>
          Sort
          <select value={ordering} onChange={(event) => setOrdering(event.target.value)}>
            <option value="name">Company A-Z</option>
            <option value="-name">Company Z-A</option>
            <option value="-created_at">Created ↓</option>
            <option value="created_at">Created ↑</option>
          </select>
        </label>
      </section>

      <div className="company-list">
        {filteredCompanies.map((company) => {
          const hrs = employeesByCompany[String(company.id)] || []
          return (
            <section key={company.id} className="company-row">
              <div className="company-action-stack">
                <button type="button" className="company-edit-btn" onClick={() => openEditCompanyForm(company)} title="Edit Company">✎</button>
                <button type="button" className="company-edit-btn company-delete-btn" onClick={() => removeCompany(company.id)} title="Delete Company">🗑</button>
              </div>

              <div className="company-title-wrap">
                <h2 className="company-title">{company.name}</h2>
                <div className="company-link-row">
                  {company.workday_domain_url ? (
                    <a
                      className="company-link-btn"
                      href={normalizeUrl(company.workday_domain_url)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Workday
                    </a>
                  ) : null}
                  {company.career_url ? (
                    <a
                      className="company-link-btn secondary"
                      href={normalizeUrl(company.career_url)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Careers
                    </a>
                  ) : null}
                </div>
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
                      {hr.department ? <p className="company-hr-meta"><strong>Role:</strong> {hr.department}</p> : null}
                      {hr.email ? <p className="company-hr-meta">{hr.email}</p> : null}
                      <p className="company-hr-meta"><strong>Working Mail:</strong> {hr.working_mail ? 'Yes' : 'No'}</p>
                      {hr.contact_number ? <p className="company-hr-meta">{hr.contact_number}</p> : null}
                      {hr.location ? <p className="company-hr-meta">{hr.location}</p> : null}
                      {hr.profile ? (
                        <a
                          className="company-linkedin-btn"
                          href={normalizeUrl(hr.profile)}
                          target="_blank"
                          rel="noreferrer"
                          title="Open LinkedIn"
                          aria-label="Open LinkedIn profile"
                        >
                          in
                        </a>
                      ) : null}
                    </div>
                  </div>
                ))}
                {!hrs.length ? <p className="hint">No HR records yet.</p> : null}
              </div>
            </section>
          )
        })}
        {!loading && !filteredCompanies.length ? <p className="hint">No companies found.</p> : null}
      </div>
      <div className="table-pagination">
        <button type="button" className="secondary" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>Previous</button>
        <span>Page {page} / {Math.max(1, totalPages)} ({totalCount})</span>
        <button type="button" className="secondary" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}>Next</button>
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
              <SingleSelectDropdown
                value={employeeForm.company}
                placeholder="Select company"
                options={companies.map((company) => ({ value: String(company.id), label: String(company.name || '') }))}
                onChange={(nextValue) => setEmployeeForm((prev) => ({ ...prev, company: nextValue }))}
              />
            </label>
            <label>First Name<input value={employeeForm.first_name} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, first_name: event.target.value }))} /></label>
            <label>Middle Name<input value={employeeForm.middle_name} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, middle_name: event.target.value }))} /></label>
            <label>Last Name<input value={employeeForm.last_name} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, last_name: event.target.value }))} /></label>
            <label>Role<input value={employeeForm.department} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, department: event.target.value }))} /></label>
            <label>Email<input value={employeeForm.email} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, email: event.target.value }))} /></label>
            <label>
              <input
                type="checkbox"
                checked={Boolean(employeeForm.working_mail)}
                onChange={(event) => setEmployeeForm((prev) => ({ ...prev, working_mail: event.target.checked }))}
              />
              {' '}
              Working Mail
            </label>
            <label>Contact Number<input value={employeeForm.contact_number} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, contact_number: event.target.value }))} /></label>
            <label>Location<input value={employeeForm.location} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, location: event.target.value }))} /></label>
            <label>LinkedIn URL<input value={employeeForm.profile} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, profile: event.target.value }))} /></label>
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
