import { useCallback, useEffect, useMemo, useState } from 'react'
import { SingleSelectDropdown } from '../components/SearchableDropdown'
import { capitalizeFirstDisplay } from '../utils/displayText'

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

const DEPARTMENT_OPTIONS = [
  'HR',
  'Engineering',
  'DevOps',
  'Data',
  'Product',
  'Design',
  'Marketing',
  'Sales',
  'Operations',
  'Other',
]

function CompanyPage() {
  const access = localStorage.getItem('access') || ''
  const [companies, setCompanies] = useState([])
  const [employees, setEmployees] = useState([])
  const [page, setPage] = useState(1)
  const pageSize = 6
  const [ordering, setOrdering] = useState('name')
  const [filters, setFilters] = useState({
    company: '',
    hr: '',
    role: '',
    location: '',
  })
  const [companyFormError, setCompanyFormError] = useState('')
  const [employeeFormError, setEmployeeFormError] = useState('')
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
      if (!hrs.length) return false
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

  const departmentOptions = useMemo(() => {
    const fromData = employees
      .map((item) => String(item?.department || '').trim())
      .filter(Boolean)
    return Array.from(new Set([...DEPARTMENT_OPTIONS, ...fromData]))
  }, [employees])

  const totalCount = filteredCompanies.length
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))
  const totalEmployees = employees.length
  const workingMailCount = employees.filter((item) => Boolean(item?.working_mail)).length
  const activeCompanyCount = companies.filter((company) => (employeesByCompany[String(company.id)] || []).length > 0).length
  const pagedCompanies = useMemo(() => {
    const start = (page - 1) * pageSize
    return filteredCompanies.slice(start, start + pageSize)
  }, [filteredCompanies, page, pageSize])

  const load = useCallback(async () => {
    if (!access) {
      setCompanies([])
      setEmployees([])
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const [firstCompanyPage, employeeRows] = await Promise.all([
        fetchCompanies(access, { page: 1, page_size: 200 }),
        fetchEmployees(access, '', { scope: 'all' }),
      ])
      const firstRows = Array.isArray(firstCompanyPage?.results) ? firstCompanyPage.results : []
      let allCompanies = [...firstRows]
      const serverTotalPages = Number(firstCompanyPage?.total_pages || 1)
      if (serverTotalPages > 1) {
        const restPages = await Promise.all(
          Array.from({ length: serverTotalPages - 1 }, (_, idx) =>
            fetchCompanies(access, { page: idx + 2, page_size: 200 }),
          ),
        )
        restPages.forEach((pageData) => {
          const rows = Array.isArray(pageData?.results) ? pageData.results : []
          allCompanies = allCompanies.concat(rows)
        })
      }
      setCompanies(allCompanies)
      setEmployees(Array.isArray(employeeRows) ? employeeRows : [])
    } catch (err) {
      console.error(err.message || 'Could not load company data.')
    } finally {
      setLoading(false)
    }
  }, [access])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    setPage(1)
  }, [filters, ordering])

  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
  }, [page, totalPages])

  const openCreateCompanyForm = () => {
    setCompanyFormError('')
    setCompanyForm({
      id: null,
      name: '',
      mail_format: 'firstname.lastname@company.com',
      career_url: '',
      workday_domain_url: '',
    })
  }

  const openEditCompanyForm = (company) => {
    setCompanyFormError('')
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
    setCompanyFormError('')
    const companyName = String(companyForm.name || '').trim()
    if (!companyName) {
      setCompanyFormError('Company name is required.')
      return
    }
    const payload = {
      name: companyName,
      mail_format: String(companyForm.mail_format || '').trim(),
      career_url: normalizeUrl(companyForm.career_url),
      workday_domain_url: normalizeUrl(companyForm.workday_domain_url),
    }
    try {
      if (companyForm.id) {
        await updateCompanyApi(access, companyForm.id, payload)
      } else {
        await createCompany(access, payload)
      }
      setCompanyForm(null)
      await load()
    } catch (err) {
      setCompanyFormError(err.message || 'Could not save company.')
    }
  }

  const removeCompany = async (companyId) => {
    try {
      await deleteCompanyApi(access, companyId)
      await load()
    } catch (err) {
      console.error(err.message || 'Could not delete company.')
    }
  }

  const openCreateEmployeeForm = () => {
    setEmployeeFormError('')
    if (!companies.length) {
      setEmployeeFormError('Create at least one company first.')
      return
    }
    const defaultCompanyId = String(companies[0].id)
    setEmployeeForm({
      id: null,
      company: defaultCompanyId,
      first_name: '',
      middle_name: '',
      last_name: '',
      role: 'HR',
      department: '',
      email: '',
      working_mail: true,
      contact_number: '',
      location: '',
      profile: '',
      about: '',
      personalized_template: '',
      personalized_template_helpful: 'partial_somewhat',
    })
  }

  const openEditEmployeeForm = (employee) => {
    setEmployeeFormError('')
    const parsed = splitFullName(employee.name || '')
    setEmployeeForm({
      id: employee.id,
      company: String(employee.company || ''),
      first_name: employee.first_name || parsed.first_name,
      middle_name: employee.middle_name || parsed.middle_name,
      last_name: employee.last_name || parsed.last_name,
      role: employee.role || employee.JobRole || '',
      department: employee.department || '',
      email: employee.email || '',
      working_mail: Boolean(employee.working_mail ?? true),
      contact_number: employee.contact_number || '',
      location: employee.location || '',
      profile: employee.profile || '',
      about: employee.about || '',
      personalized_template: employee.personalized_template || '',
      personalized_template_helpful: employee.personalized_template_helpful || 'partial_somewhat',
    })
  }

  const saveEmployeeForm = async () => {
    if (!employeeForm) return
    setEmployeeFormError('')
    const companyId = Number(employeeForm.company)
    if (!companyId) {
      setEmployeeFormError('Select company for employee.')
      return
    }
    const firstName = String(employeeForm.first_name || '').trim()
    const lastName = String(employeeForm.last_name || '').trim()
    const department = String(employeeForm.department || '').trim()
    const role = String(employeeForm.role || '').trim()
    if (!firstName) {
      setEmployeeFormError('First name is required.')
      return
    }
    if (!lastName) {
      setEmployeeFormError('Last name is required.')
      return
    }
    if (!department) {
      setEmployeeFormError('Department is required.')
      return
    }
    if (!role) {
      setEmployeeFormError('Role is required.')
      return
    }
    const fullName = mergeNameParts(firstName, employeeForm.middle_name, lastName)
    try {
      if (employeeForm.id) {
        const updated = await updateEmployeeApi(access, employeeForm.id, {
          company: companyId,
          name: fullName,
          first_name: firstName,
          middle_name: employeeForm.middle_name,
          last_name: lastName,
          role,
          department,
          email: employeeForm.email,
          working_mail: Boolean(employeeForm.working_mail),
          contact_number: employeeForm.contact_number,
          location: employeeForm.location,
          profile: employeeForm.profile,
          about: employeeForm.about,
          personalized_template: employeeForm.personalized_template,
          personalized_template_helpful: employeeForm.personalized_template_helpful,
        })
        setEmployees((prev) => prev.map((row) => (row.id === employeeForm.id ? updated : row)))
      } else {
        const created = await createEmployee(access, {
          company: companyId,
          name: fullName,
          first_name: firstName,
          middle_name: employeeForm.middle_name,
          last_name: lastName,
          role,
          department,
          email: employeeForm.email,
          working_mail: Boolean(employeeForm.working_mail),
          contact_number: employeeForm.contact_number,
          location: employeeForm.location,
          profile: employeeForm.profile,
          about: employeeForm.about,
          personalized_template: employeeForm.personalized_template,
          personalized_template_helpful: employeeForm.personalized_template_helpful,
        })
        setEmployees((prev) => [...prev, created])
      }
      setEmployeeForm(null)
      await load()
    } catch (err) {
      setEmployeeFormError(err.message || 'Could not save employee.')
    }
  }

  const removeHr = async (employeeId) => {
    try {
      await deleteEmployeeApi(access, employeeId)
      await load()
    } catch (err) {
      console.error(err.message || 'Could not delete employee.')
    }
  }

  return (
    <main className="page page-wide mx-auto w-full">
      <div className="company-head">
        <div>
          <h1>Companies</h1>
          <p className="subtitle">Filter companies and employee contacts by name, role, and location.</p>
        </div>
        <div className="actions">
          <button type="button" onClick={openCreateCompanyForm}>Add Company</button>
          <button type="button" className="secondary" onClick={openCreateEmployeeForm}>Add Employee</button>
        </div>
      </div>

      <div className="company-summary-bar">
        <span>{companies.length} companies</span>
        <span>{activeCompanyCount} active</span>
        <span>{totalEmployees} contacts</span>
        <span>{workingMailCount} working mails</span>
        <span>{totalCount} matched</span>
      </div>

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
          Employee Name
          <input
            value={filters.hr}
            onChange={(event) => setFilters((prev) => ({ ...prev, hr: event.target.value }))}
            placeholder="Employee name"
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
        {pagedCompanies.map((company) => {
          const hrs = employeesByCompany[String(company.id)] || []
          return (
            <section key={company.id} className="company-row">
              <div className="company-row-head">
                <div className="company-title-wrap">
                  <h2 className="company-title">{capitalizeFirstDisplay(company.name)}</h2>
                  <p className="company-subline">
                  {hrs.length} contact{hrs.length === 1 ? '' : 's'}
                  {' | '}
                  {hrs.filter((item) => item.working_mail).length} working mails
                  {' | '}
                  {deriveEmailPattern(company)}
                  </p>
                </div>
                <div className="company-top-actions">
                  <button type="button" className="company-edit-btn company-edit-btn-text" onClick={() => openEditCompanyForm(company)} title="Edit Company">Edit</button>
                  <button type="button" className="company-edit-btn company-edit-btn-text company-delete-btn" onClick={() => removeCompany(company.id)} title="Delete Company">Delete</button>
                </div>
              </div>

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

              <div className="company-hr-list">
                {hrs.map((hr) => (
                  <div key={hr.id} className="company-hr-item">
                    <span
                      className={`company-dot ${hr.working_mail ? 'is-green' : 'is-red'}`}
                      title={hr.working_mail ? 'Working mail' : 'Mail not working'}
                      aria-label={hr.working_mail ? 'Working mail' : 'Mail not working'}
                    />
                    <div className="company-hr-body">
                      <p className="company-hr-name">{hr.name}</p>
                      <p className="company-hr-meta"><strong>Role:</strong> {String(hr.role || hr.JobRole || '').trim() || 'HR'}</p>
                      {String(hr.department || '').trim() && String(hr.department || '').trim().toLowerCase() !== 'hr' ? (
                        <p className="company-hr-meta"><strong>Department:</strong> {hr.department}</p>
                      ) : null}
                      {hr.email ? <p className="company-hr-meta">{hr.email}</p> : null}
                      {hr.contact_number ? <p className="company-hr-meta">{hr.contact_number}</p> : null}
                      {hr.location ? <p className="company-hr-meta">{hr.location}</p> : null}
                      <div className="company-hr-actions">
                        {hr.profile ? (
                          <a
                            className="company-linkedin-btn"
                            href={normalizeUrl(hr.profile)}
                            target="_blank"
                            rel="noreferrer"
                            title="Open LinkedIn"
                            aria-label="Open LinkedIn profile"
                          >
                            LinkedIn
                          </a>
                        ) : null}
                        <button type="button" className="company-edit-btn company-edit-btn-text" onClick={() => openEditEmployeeForm(hr)} title="Edit Employee">Edit</button>
                        <button type="button" className="company-edit-btn company-edit-btn-text company-delete-btn" onClick={() => removeHr(hr.id)} title="Delete Employee">Delete</button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )
        })}
        {!loading && !totalCount ? <p className="hint">No companies found.</p> : null}
      </div>
      <div className="table-pagination">
        <button type="button" className="secondary" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>Previous</button>
        <span>Page {page} / {Math.max(1, totalPages)} ({totalCount})</span>
        <button type="button" className="secondary" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}>Next</button>
      </div>

      {companyForm ? (
        <div className="modal-overlay" onClick={() => { setCompanyForm(null); setCompanyFormError('') }}>
          <div className="modal-panel jobs-modal-panel" onClick={(event) => event.stopPropagation()}>
            <div className="tracking-modal-head">
              <h2>{companyForm.id ? 'Edit Company' : 'Add Company'}</h2>
              <p className="subtitle">Set the company identity, mail pattern, and hiring links cleanly.</p>
            </div>
            <div className="tracking-form-grid jobs-form-grid">
            <div className="tracking-form-section-title tracking-form-span-2">Company Details</div>
            <label>Company Name<input value={companyForm.name} onChange={(event) => setCompanyForm((prev) => ({ ...prev, name: event.target.value }))} /></label>
            <label>Mail Format<input value={companyForm.mail_format} onChange={(event) => setCompanyForm((prev) => ({ ...prev, mail_format: event.target.value }))} /></label>
            <div className="tracking-form-section-title tracking-form-span-2">Links</div>
            <label>Career URL<input value={companyForm.career_url} onChange={(event) => setCompanyForm((prev) => ({ ...prev, career_url: event.target.value }))} /></label>
            <label>Workday Domain URL<input value={companyForm.workday_domain_url} onChange={(event) => setCompanyForm((prev) => ({ ...prev, workday_domain_url: event.target.value }))} /></label>
            </div>
            {companyFormError ? <p className="error">{companyFormError}</p> : null}
            <div className="actions">
              <button type="button" onClick={saveCompanyForm}>Save</button>
              <button type="button" className="secondary" onClick={() => { setCompanyForm(null); setCompanyFormError('') }}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}

      {employeeForm ? (
        <div className="modal-overlay" onClick={() => { setEmployeeForm(null); setEmployeeFormError('') }}>
          <div className="modal-panel jobs-modal-panel" onClick={(event) => event.stopPropagation()}>
            <div className="tracking-modal-head">
              <h2>{employeeForm.id ? 'Edit Employee' : 'Add Employee'}</h2>
              <p className="subtitle">Capture contact identity, role, workability, and profile details in one clean form.</p>
            </div>
            <div className="tracking-form-grid jobs-form-grid">
            <div className="tracking-form-section-title tracking-form-span-2">Identity</div>
            <label>
              Company
              <SingleSelectDropdown
                value={employeeForm.company}
                placeholder="Select company"
                options={companies.map((company) => ({ value: String(company.id), label: capitalizeFirstDisplay(company.name) }))}
                onChange={(nextValue) => setEmployeeForm((prev) => ({ ...prev, company: nextValue }))}
              />
            </label>
            <label>First Name<input value={employeeForm.first_name} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, first_name: event.target.value }))} /></label>
            <label>Middle Name<input value={employeeForm.middle_name} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, middle_name: event.target.value }))} /></label>
            <label>Last Name<input value={employeeForm.last_name} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, last_name: event.target.value }))} /></label>
            <div className="tracking-form-section-title tracking-form-span-2">Role & Contact</div>
            <label>JobRole<input value={employeeForm.role} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, role: event.target.value }))} placeholder="SDE, Team Lead, Recruiter..." /></label>
            <label>
              Department
              <select value={employeeForm.department} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, department: event.target.value }))}>
                <option value="">Select department</option>
                {departmentOptions.map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
            </label>
            <label>Email<input value={employeeForm.email} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, email: event.target.value }))} /></label>
            <label className="tracking-check-row tracking-form-span-2">
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
            <div className="tracking-form-section-title tracking-form-span-2">Profile & Notes</div>
            <label>LinkedIn URL<input value={employeeForm.profile} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, profile: event.target.value }))} /></label>
            <label className="tracking-form-span-2">About<textarea rows="4" value={employeeForm.about} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, about: event.target.value }))} /></label>
            <label className="tracking-form-span-2">
              Personalized Template
              <textarea
                rows="5"
                value={employeeForm.personalized_template || ''}
                onChange={(event) => setEmployeeForm((prev) => ({ ...prev, personalized_template: event.target.value }))}
                placeholder="Store a reusable personalized intro for this employee"
              />
            </label>
            <label>
              Helpful
              <select value={employeeForm.personalized_template_helpful} onChange={(event) => setEmployeeForm((prev) => ({ ...prev, personalized_template_helpful: event.target.value }))}>
                <option value="good">Good</option>
                <option value="partial_somewhat">Partial / Somewhat</option>
                <option value="never">Never</option>
              </select>
            </label>
            </div>
            {employeeFormError ? <p className="error">{employeeFormError}</p> : null}
            <div className="actions">
              <button type="button" onClick={saveEmployeeForm}>Save</button>
              <button type="button" className="secondary" onClick={() => { setEmployeeForm(null); setEmployeeFormError('') }}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  )
}

export default CompanyPage
