import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { fetchResume, fetchResumes } from '../api'

const PROFILE_STORAGE_KEY = 'jobApplicationProfile'
const PROFILE_QA_KEY = 'jobApplicationProfileQa'
const PROFILE_REFERENCE_RESUME_KEY = 'jobApplicationReferenceResumeId'

const defaultProfile = {
  firstName: 'subrat',
  lastName: 'singh',
  preferredName: 'subrat',
  suffixName: 'singh',
  email: 'subratsingh010@gmail.com',
  phone: '+918546075639',
  birthday: '2000-12-30',
  location: 'Gurugram, HR, India',
  address1: '2121, Sukhrali Rd, near Sector 17 A, Sukhrali, Market, Gurugram, Haryana 122007',
  address2: '-',
  address3: '-',
  postalCode: '122007',
  ethnicity: 'South Asian',
  workUs: 'No',
  workCanada: 'No',
  workUk: 'No',
  visaSponsorship: 'No',
  disability: 'Yes',
  lgbtq: 'No',
  gender: 'Male',
  linkedinUrl: 'https://www.linkedin.com/in/subrat-s-81720a22a',
  githubUrl: 'https://github.com/subrasinght010',
  portfolioUrl: '-',
  otherUrl: 'https://leetcode.com/u/subrat010/',
}

const defaultQa = [
  { id: crypto.randomUUID(), question: 'Current employer', answer: 'Inspektlabs' },
  { id: crypto.randomUUID(), question: 'Years of experience', answer: '3+' },
]

const personalFields = [
  ['firstName', 'First Name'],
  ['lastName', 'Last Name'],
  ['preferredName', 'Preferred Name'],
  ['suffixName', 'Suffix Name'],
  ['email', 'Email Address'],
  ['phone', 'Phone Number'],
  ['birthday', 'Birthday'],
  ['location', 'Location'],
  ['address1', 'Address'],
  ['address2', 'Address 2'],
  ['address3', 'Address 3'],
  ['postalCode', 'Postal Code'],
]

const employmentFields = [
  ['ethnicity', 'What is your ethnicity?'],
  ['workUs', 'Are you authorized to work in the US?'],
  ['workCanada', 'Are you authorized to work in Canada?'],
  ['workUk', 'Are you authorized to work in the United Kingdom?'],
  ['visaSponsorship', 'Will you now or in the future require sponsorship for employment visa status?'],
  ['disability', 'Do you have a disability?'],
  ['lgbtq', 'Do you identify as LGBTQ+?'],
  ['gender', 'What is your gender?'],
]

const linkFields = [
  ['linkedinUrl', 'LinkedIn URL'],
  ['githubUrl', 'GitHub URL'],
  ['portfolioUrl', 'Portfolio URL'],
  ['otherUrl', 'Other URL'],
]

function readJsonStorage(key, fallback) {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return fallback
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : fallback
  } catch {
    return fallback
  }
}

function plainText(value) {
  return String(value || '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function ProfilePage() {
  const navigate = useNavigate()
  const [profile, setProfile] = useState(() => ({
    ...defaultProfile,
    ...readJsonStorage(PROFILE_STORAGE_KEY, {}),
  }))
  const [qaRows, setQaRows] = useState(() => {
    const parsed = readJsonStorage(PROFILE_QA_KEY, defaultQa)
    return Array.isArray(parsed) && parsed.length ? parsed : defaultQa
  })
  const [resumes, setResumes] = useState([])
  const [referenceResumeId, setReferenceResumeId] = useState(() => localStorage.getItem(PROFILE_REFERENCE_RESUME_KEY) || '')
  const [referenceResume, setReferenceResume] = useState(null)
  const [status, setStatus] = useState('')

  useEffect(() => {
    localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(profile))
    setStatus('Profile saved locally for autofill.')
    const timer = window.setTimeout(() => setStatus(''), 1400)
    return () => window.clearTimeout(timer)
  }, [profile])

  useEffect(() => {
    localStorage.setItem(PROFILE_QA_KEY, JSON.stringify(qaRows))
    setStatus('Question bank saved locally.')
    const timer = window.setTimeout(() => setStatus(''), 1400)
    return () => window.clearTimeout(timer)
  }, [qaRows])

  useEffect(() => {
    if (String(referenceResumeId || '').trim()) {
      localStorage.setItem(PROFILE_REFERENCE_RESUME_KEY, String(referenceResumeId))
      sessionStorage.setItem('tailoredBuilderReferenceResumeId', String(referenceResumeId))
    } else {
      localStorage.removeItem(PROFILE_REFERENCE_RESUME_KEY)
      sessionStorage.removeItem('tailoredBuilderReferenceResumeId')
    }
  }, [referenceResumeId])

  useEffect(() => {
    let cancelled = false
    const access = localStorage.getItem('access')
    if (!access) return undefined

    const loadResumes = async () => {
      try {
        const list = await fetchResumes(access)
        if (cancelled) return
        const rows = Array.isArray(list) ? list : []
        setResumes(rows)
        if (!referenceResumeId) {
          const defaultResume = rows.find((item) => item.is_default)
          if (defaultResume?.id) {
            setReferenceResumeId(String(defaultResume.id))
          }
        }
      } catch {
        if (!cancelled) setResumes([])
      }
    }

    loadResumes()
    return () => {
      cancelled = true
    }
  }, [referenceResumeId])

  useEffect(() => {
    let cancelled = false
    const access = localStorage.getItem('access')
    if (!access || !referenceResumeId) {
      setReferenceResume(null)
      return undefined
    }

    const loadReferenceResume = async () => {
      try {
        const resume = await fetchResume(access, referenceResumeId)
        if (!cancelled) setReferenceResume(resume || null)
      } catch {
        if (!cancelled) setReferenceResume(null)
      }
    }

    loadReferenceResume()
    return () => {
      cancelled = true
    }
  }, [referenceResumeId])

  const updateProfile = (key, value) => {
    setProfile((prev) => ({ ...prev, [key]: value }))
  }

  const updateQa = (id, key, value) => {
    setQaRows((prev) => prev.map((row) => (row.id === id ? { ...row, [key]: value } : row)))
  }

  const addQa = () => {
    setQaRows((prev) => [...prev, { id: crypto.randomUUID(), question: '', answer: '' }])
  }

  const removeQa = (id) => {
    setQaRows((prev) => prev.filter((row) => row.id !== id))
  }

  const openReferenceResume = async () => {
    const access = localStorage.getItem('access')
    if (!access || !referenceResumeId) return
    try {
      const resume = await fetchResume(access, referenceResumeId)
      if (!resume?.id) return
      sessionStorage.setItem('builderImport', JSON.stringify(resume.builder_data || {}))
      sessionStorage.setItem('builderResumeId', String(resume.id))
      navigate('/builder')
    } catch {
      // ignore for now
    }
  }

  return (
    <main className="page page-wide mx-auto w-full">
      <div className="profile-simple-head">
        <div>
          <h1>Profile</h1>
          <p className="subtitle">Simple profile data for autofill, auto apply, and tailored resume reference.</p>
        </div>
        {status ? <p className="success">{status}</p> : null}
      </div>

      <section className="profile-simple-section">
        <h2>Personal Info</h2>
        <div className="profile-simple-grid">
          {personalFields.map(([key, label]) => (
            <label key={key}>
              {label}
              <input value={profile[key]} onChange={(event) => updateProfile(key, event.target.value)} />
            </label>
          ))}
        </div>
      </section>

      <section className="profile-simple-section">
        <h2>Employment Information</h2>
        <div className="profile-simple-grid">
          {employmentFields.map(([key, label]) => (
            <label key={key}>
              {label}
              <input value={profile[key]} onChange={(event) => updateProfile(key, event.target.value)} />
            </label>
          ))}
        </div>
      </section>

      <section className="profile-simple-section">
        <h2>Reference Resume</h2>
        <p className="hint">Tailored resume flow will keep using this resume until you change it here.</p>
        <div className="profile-simple-actions">
          <label className="profile-simple-grow">
            Select Resume
            <select value={referenceResumeId} onChange={(event) => setReferenceResumeId(event.target.value)}>
              <option value="">Choose resume</option>
              {resumes.map((resume) => (
                <option key={resume.id} value={resume.id}>
                  {resume.title || `Resume ${resume.id}`}{resume.is_default ? ' (Default)' : ''}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="secondary" onClick={openReferenceResume} disabled={!referenceResumeId}>
            Open In Builder
          </button>
        </div>
        {referenceResume?.builder_data ? (
          <div className="profile-simple-stack" style={{ marginTop: 16 }}>
            {plainText(referenceResume.builder_data.summary || '') ? (
              <div className="profile-simple-qa">
                <h2>Summary</h2>
                <p>{plainText(referenceResume.builder_data.summary || '')}</p>
              </div>
            ) : null}

            {plainText(referenceResume.builder_data.skills || '') ? (
              <div className="profile-simple-qa">
                <h2>Skills</h2>
                <p>{plainText(referenceResume.builder_data.skills || '')}</p>
              </div>
            ) : null}

            {Array.isArray(referenceResume.builder_data.experiences) && referenceResume.builder_data.experiences.length ? (
              <div className="profile-simple-qa">
                <h2>Experience</h2>
                <div className="profile-simple-stack">
                  {referenceResume.builder_data.experiences.map((item, index) => (
                    <div key={`${item.company || 'exp'}-${index}`}>
                      <strong>{item.company || 'Company'}{item.title ? ` - ${item.title}` : ''}</strong>
                      <p className="hint">{[item.location, item.startDate, item.endDate].filter(Boolean).join(' | ')}</p>
                      <p>{plainText(item.highlights || '')}</p>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {Array.isArray(referenceResume.builder_data.educations) && referenceResume.builder_data.educations.length ? (
              <div className="profile-simple-qa">
                <h2>Education</h2>
                <div className="profile-simple-stack">
                  {referenceResume.builder_data.educations.map((item, index) => (
                    <div key={`${item.institution || 'edu'}-${index}`}>
                      <strong>{item.institution || 'Institution'}</strong>
                      <p>{[item.program, item.scoreValue].filter(Boolean).join(' | ')}</p>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {Array.isArray(referenceResume.builder_data.projects) && referenceResume.builder_data.projects.length ? (
              <div className="profile-simple-qa">
                <h2>Projects</h2>
                <div className="profile-simple-stack">
                  {referenceResume.builder_data.projects.map((item, index) => (
                    <div key={`${item.name || 'project'}-${index}`}>
                      <strong>{item.name || 'Project'}</strong>
                      <p>{plainText(item.highlights || '')}</p>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      <section className="profile-simple-section">
        <h2>Portfolio & Links</h2>
        <div className="profile-simple-grid">
          {linkFields.map(([key, label]) => (
            <label key={key}>
              {label}
              <input value={profile[key]} onChange={(event) => updateProfile(key, event.target.value)} />
            </label>
          ))}
        </div>
      </section>

      <section className="profile-simple-section">
        <div className="profile-simple-head-row">
          <div>
            <h2>Extra Questions & Answers</h2>
            <p className="hint">Add custom question-answer pairs for future auto apply and autofill.</p>
          </div>
          <button type="button" className="secondary" onClick={addQa}>Add Question</button>
        </div>
        <div className="profile-simple-stack">
          {qaRows.map((row, index) => (
            <div key={row.id} className="profile-simple-qa">
              <label>
                Question {index + 1}
                <input value={row.question} onChange={(event) => updateQa(row.id, 'question', event.target.value)} />
              </label>
              <label>
                Answer
                <textarea rows="3" value={row.answer} onChange={(event) => updateQa(row.id, 'answer', event.target.value)} />
              </label>
              <button type="button" className="secondary" onClick={() => removeQa(row.id)}>
                Remove
              </button>
            </div>
          ))}
        </div>
      </section>
    </main>
  )
}

export default ProfilePage
