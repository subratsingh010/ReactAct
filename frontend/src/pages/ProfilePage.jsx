import { useEffect, useState } from 'react'

import profileConfigSeed from '../config/profileData.json'

const PROFILE_CONFIG_STORAGE_KEY = 'jobApplicationProfileConfig'

const personalFields = [
  ['firstName', 'First Name'],
  ['lastName', 'Last Name'],
  ['preferredName', 'Preferred Name'],
  ['suffixName', 'Suffix Name'],
  ['emailAddress', 'Email Address'],
  ['countryCode', 'Country Code'],
  ['phoneNumber', 'Phone Number'],
  ['phoneType', 'Phone Type'],
  ['birthday', 'Birthday'],
  ['location', 'Location'],
]

const addressFields = [
  ['address1', 'Address'],
  ['city', 'City'],
  ['state', 'State'],
  ['country', 'Country'],
  ['postalCode', 'Postal Code'],
]

const socialFields = [
  ['linkedinUrl', 'LinkedIn URL'],
  ['githubUrl', 'GitHub URL'],
  ['portfolioUrl', 'Portfolio URL'],
  ['otherUrl', 'Other URL'],
]

const experienceFields = [
  ['company', 'Company'],
  ['role', 'Role'],
  ['employerName', 'Employer Name'],
  ['location', 'Location'],
  ['startTime', 'Start Time'],
  ['endTime', 'End Time'],
  ['currentWorking', 'Current Working'],
  ['employmentType', 'Employment Type'],
]

const educationFields = [
  ['school', 'School'],
  ['degree', 'Degree'],
  ['fieldOfStudy', 'Field Of Study'],
  ['startTime', 'Start Time'],
  ['endTime', 'End Time'],
  ['grade', 'Grade'],
]

const projectFields = [['name', 'Project Name']]

function sectionValue(config, key) {
  return config?.[key] && typeof config[key] === 'object' ? config[key] : {}
}

function arrayValue(config, key) {
  return Array.isArray(config?.[key]) ? config[key] : []
}

function normalizeSkills(value) {
  if (!Array.isArray(value)) return []
  const out = []
  for (const item of value) {
    if (typeof item === 'string') {
      const trimmed = item.trim()
      if (trimmed) out.push(trimmed)
      continue
    }
    if (item && typeof item === 'object') {
      const raw = String(item.values || '').trim()
      if (!raw) continue
      raw.split(',').map((part) => part.trim()).filter(Boolean).forEach((part) => out.push(part))
    }
  }
  return out
}

function normalizeEmploymentRows(value) {
  const seedRows = arrayValue(profileConfigSeed, 'employmentInformation')
  if (Array.isArray(value) && value.length) {
    const rows = value
      .map((item) => {
        if (item && typeof item === 'object') {
          return {
            question: String(item.question || '').trim(),
            answer: String(item.answer || '').trim(),
          }
        }
        return { question: '', answer: '' }
      })
      .filter((row) => row.question || row.answer)
    if (rows.length) return rows
  }
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const rows = Object.entries(value)
      .map(([question, answer]) => ({
        question: String(question || '').trim(),
        answer: String(answer || '').trim(),
      }))
      .filter((row) => row.question || row.answer)
    if (rows.length) return rows
  }
  return seedRows
}

function readLocalProfileConfig() {
  const normalize = (value) => {
    const base = profileConfigSeed && typeof profileConfigSeed === 'object' ? { ...profileConfigSeed } : {}
    const incoming = value && typeof value === 'object' ? value : {}
    const merged = { ...base, ...incoming }

    const seedEmployment = Array.isArray(profileConfigSeed.employmentInformation) ? profileConfigSeed.employmentInformation : []
    merged.employmentInformation = normalizeEmploymentRows(incoming.employmentInformation)
    if (Array.isArray(merged.employmentInformation) && merged.employmentInformation.length < seedEmployment.length) {
      merged.employmentInformation = seedEmployment
    }
    merged.skills = normalizeSkills(incoming.skills ?? merged.skills)

    return merged
  }

  try {
    const raw = localStorage.getItem(PROFILE_CONFIG_STORAGE_KEY)
    if (!raw) return normalize(profileConfigSeed)
    const parsed = JSON.parse(raw)
    return normalize(parsed)
  } catch {
    return normalize(profileConfigSeed)
  }
}

function ValueGrid({ fields, values }) {
  return (
    <div className="profile-simple-grid">
      {fields.map(([key, label]) => (
        <div key={key} className="profile-read-row">
          <div className="profile-read-label">{label}</div>
          <div className="profile-read-value">{values[key] || '-'}</div>
        </div>
      ))}
    </div>
  )
}

function RepeatingReadSection({ title, rows, fields, textKey = 'highlights', textLabel = 'Highlights' }) {
  return (
    <section className="profile-simple-section">
      <h2>{title}</h2>
      <div className="profile-simple-stack" style={{ marginTop: 12 }}>
        {rows.map((row, index) => (
          <div key={`${title}-${index}`} className="profile-plain-entry">
            <ValueGrid fields={fields} values={row} />
            {textKey ? (
              <div className="profile-read-row">
                <div className="profile-read-label">{textLabel}</div>
                <div className="profile-read-value profile-read-pre">{row[textKey] || '-'}</div>
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  )
}

function ProfilePage() {
  const [config, setConfig] = useState(() => readLocalProfileConfig())
  const [status, setStatus] = useState('')

  useEffect(() => {
    // One-time migration to normalize stale local formats (objects -> rows/list).
    setConfig((prev) => ({
      ...prev,
      employmentInformation: normalizeEmploymentRows(prev?.employmentInformation),
      skills: normalizeSkills(prev?.skills),
    }))
  }, [])

  useEffect(() => {
    localStorage.setItem(PROFILE_CONFIG_STORAGE_KEY, JSON.stringify(config))
    const timer = window.setTimeout(() => setStatus('Employment Information JSON updated.'), 120)
    const clear = window.setTimeout(() => setStatus(''), 1600)
    return () => {
      window.clearTimeout(timer)
      window.clearTimeout(clear)
    }
  }, [config])

  const employmentRows = normalizeEmploymentRows(config?.employmentInformation)
  const skills = normalizeSkills(config?.skills)

  const addEmploymentRow = () => {
    const nextIndex = employmentRows.length + 1
    setConfig((prev) => ({
      ...prev,
      employmentInformation: [...arrayValue(prev, 'employmentInformation'), { question: `Question ${nextIndex}`, answer: '-' }],
    }))
  }

  return (
    <main className="page page-wide page-plain mx-auto w-full">
      <div className="profile-simple-head">
        <div>
          <h1>Profile</h1>
          <p className="subtitle">JSON-based profile. Employment Information supports edit and add.</p>
        </div>
        {status ? <p className="success">{status}</p> : null}
      </div>

      <section className="profile-simple-section">
        <h2>Personal Info</h2>
        <ValueGrid fields={personalFields} values={sectionValue(config, 'personalInfo')} />
      </section>

      <section className="profile-simple-section">
        <h2>Address</h2>
        <ValueGrid fields={addressFields} values={sectionValue(config, 'address')} />
      </section>

      <section className="profile-simple-section">
        <h2>Social URLs</h2>
        <ValueGrid fields={socialFields} values={sectionValue(config, 'socialUrls')} />
      </section>

      <section className="profile-simple-section">
        <div className="profile-simple-head-row">
          <h2>Employment Information</h2>
          <button type="button" className="secondary" onClick={addEmploymentRow}>Add</button>
        </div>
        <div className="profile-simple-stack profile-scroll-block">
          {employmentRows.map((row, index) => (
            <div key={`employment-row-${index}`} className="profile-plain-entry">
              <div className="profile-read-row">
                <div className="profile-read-label">Question</div>
                <div className="profile-read-value">{row.question || '-'}</div>
              </div>
              <div className="profile-read-row">
                <div className="profile-read-label">Answer</div>
                <div className="profile-read-value">{row.answer || '-'}</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <RepeatingReadSection
        title="Work Experience"
        rows={arrayValue(config, 'workExperiences')}
        fields={experienceFields}
      />

      <RepeatingReadSection
        title="Education"
        rows={arrayValue(config, 'education')}
        fields={educationFields}
        textKey=""
      />

      <RepeatingReadSection
        title="Projects"
        rows={arrayValue(config, 'projects')}
        fields={projectFields}
      />

      <section className="profile-simple-section">
        <h2>Skills</h2>
        <div className="profile-read-row" style={{ marginTop: 12 }}>
          <div className="profile-read-value">
            {skills.length ? skills.join(', ') : '-'}
          </div>
        </div>
      </section>
    </main>
  )
}

export default ProfilePage
