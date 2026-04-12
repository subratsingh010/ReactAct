import { useState } from 'react'

const initialCompanies = [
  {
    id: 1,
    name: 'Walmart Global Tech',
    careersUrl: 'https://walmart.wd5.myworkdayjobs.com/WalmartExternal',
    emailPattern: 'firstname.lastname@walmart.com',
    hrs: [
      { id: 11, name: 'Riya Sharma', role: 'Senior Recruiter', location: 'Bengaluru, India', hasAboutData: true },
      { id: 12, name: 'Amit Verma', role: 'Talent Acquisition Lead', location: 'Gurugram, India', hasAboutData: false },
    ],
  },
  {
    id: 2,
    name: 'JPMorgan Chase',
    careersUrl: '',
    emailPattern: 'first_last@jpmorgan.com',
    hrs: [
      { id: 21, name: 'Neha Kapoor', role: 'HR Business Partner', location: 'Mumbai, India', hasAboutData: true },
      { id: 22, name: 'Rohit Sinha', role: 'Technical Recruiter', location: 'Hyderabad, India', hasAboutData: true },
      { id: 23, name: 'Anjali Mehta', role: 'Talent Acquisition', location: 'Bengaluru, India', hasAboutData: false },
    ],
  },
]

function CompanyPage() {
  const [companies, setCompanies] = useState(initialCompanies)

  const addCompany = () => {
    setCompanies((prev) => [
      ...prev,
      {
        id: Date.now(),
        name: `Company ${prev.length + 1}`,
        careersUrl: '',
        emailPattern: 'firstname.lastname@company.com',
        hrs: [],
      },
    ])
  }

  const addHr = () => {
    setCompanies((prev) => {
      if (!prev.length) return prev
      const targetIndex = prev.length - 1
      const target = prev[targetIndex]
      const nextHrNumber = (target.hrs?.length || 0) + 1
      const nextHr = {
        id: Date.now(),
        name: `HR ${nextHrNumber}`,
        role: 'Recruiter',
        location: 'India',
        hasAboutData: false,
      }
      const nextCompanies = [...prev]
      nextCompanies[targetIndex] = {
        ...target,
        hrs: [...(target.hrs || []), nextHr],
      }
      return nextCompanies
    })
  }

  const editCompany = (companyId) => {
    setCompanies((prev) =>
      prev.map((company) => {
        if (company.id !== companyId) return company
        const name = window.prompt('Company name', company.name)
        if (name === null) return company
        const careersUrl = window.prompt('Workday/Careers URL (optional)', company.careersUrl || '')
        if (careersUrl === null) return company
        const emailPattern = window.prompt('Email pattern', company.emailPattern || '')
        if (emailPattern === null) return company
        return {
          ...company,
          name: name.trim() || company.name,
          careersUrl: careersUrl.trim(),
          emailPattern: emailPattern.trim() || company.emailPattern,
        }
      }),
    )
  }

  const editHr = (companyId, hrId) => {
    setCompanies((prev) =>
      prev.map((company) => {
        if (company.id !== companyId) return company
        const nextHrs = (company.hrs || []).map((hr) => {
          if (hr.id !== hrId) return hr
          const name = window.prompt('HR name', hr.name)
          if (name === null) return hr
          const role = window.prompt('HR role', hr.role)
          if (role === null) return hr
          const location = window.prompt('HR location', hr.location)
          if (location === null) return hr
          const aboutAnswer = window.prompt('Has about data? (yes/no)', hr.hasAboutData ? 'yes' : 'no')
          if (aboutAnswer === null) return hr
          const normalized = aboutAnswer.trim().toLowerCase()
          return {
            ...hr,
            name: name.trim() || hr.name,
            role: role.trim() || hr.role,
            location: location.trim() || hr.location,
            hasAboutData: normalized === 'yes' || normalized === 'y' || normalized === 'true',
          }
        })
        return { ...company, hrs: nextHrs }
      }),
    )
  }

  const deleteCompany = (companyId) => {
    setCompanies((prev) => prev.filter((company) => company.id !== companyId))
  }

  const deleteHr = (companyId, hrId) => {
    setCompanies((prev) =>
      prev.map((company) => {
        if (company.id !== companyId) return company
        return {
          ...company,
          hrs: (company.hrs || []).filter((hr) => hr.id !== hrId),
        }
      }),
    )
  }

  return (
    <main className="page page-wide page-plain mx-auto w-full">
      <div className="company-head">
        <div>
          <h1>Companies</h1>
          <p className="subtitle">Dummy company and HR data view. We can connect DB data later.</p>
        </div>
        <div className="actions">
          <button type="button" onClick={addCompany}>Add Company</button>
          <button type="button" className="secondary" onClick={addHr}>Add HRs</button>
        </div>
      </div>

      <div className="company-list">
        {companies.map((company) => (
          <section key={company.id} className="company-row">
            <div className="company-action-stack">
              <button type="button" className="company-edit-btn" onClick={() => editCompany(company.id)} title="Edit Company">
                ✎
              </button>
              <button type="button" className="company-edit-btn company-delete-btn" onClick={() => deleteCompany(company.id)} title="Delete Company">
                🗑
              </button>
            </div>
            <div className="company-title-wrap">
              <h2 className="company-title">{company.name}</h2>
              {company.careersUrl ? <p className="company-subline">{company.careersUrl}</p> : null}
              <p className="company-subline">{company.emailPattern}</p>
            </div>

            <div className="company-hr-list">
              {(company.hrs || []).map((hr) => (
                <div key={hr.id} className="company-hr-item">
                  <div className="company-action-stack company-action-stack-hr">
                    <button
                      type="button"
                      className="company-edit-btn company-edit-btn-hr"
                      onClick={() => editHr(company.id, hr.id)}
                      title="Edit HR"
                    >
                      ✎
                    </button>
                    <button
                      type="button"
                      className="company-edit-btn company-edit-btn-hr company-delete-btn"
                      onClick={() => deleteHr(company.id, hr.id)}
                      title="Delete HR"
                    >
                      🗑
                    </button>
                  </div>
                  <span className={`company-dot ${hr.hasAboutData ? 'is-green' : 'is-red'}`} />
                  <div>
                    <p className="company-hr-name">{hr.name}</p>
                    <p className="company-hr-meta">{hr.role}</p>
                    <p className="company-hr-meta">{hr.location}</p>
                  </div>
                </div>
              ))}
              {!company.hrs?.length ? <p className="hint">No HR records yet.</p> : null}
            </div>
          </section>
        ))}
      </div>
    </main>
  )
}

export default CompanyPage
