import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ResumeSheet from '../components/ResumeSheet'
import { MultiSelectDropdown, SingleSelectDropdown } from '../components/SearchableDropdown'

import {
  createSubjectTemplate,
  createInterview,
  deleteSubjectTemplate,
  deleteInterview,
  deleteResume,
  fetchAllJobs,
  fetchSubjectTemplates,
  fetchInterviews,
  fetchLocations,
  fetchProfile,
  fetchProfileInfo,
  fetchResumes,
  updateSubjectTemplate,
  updateInterview,
  updateProfileInfo,
} from '../api'

const EMPTY_PROFILE = {
  full_name: '',
  email: '',
  contact_number: '',
  linkedin_url: '',
  github_url: '',
  portfolio_url: '',
  resume_link: '',
  current_employer: '',
  years_of_experience: '',
  address_line_1: '',
  address_line_2: '',
  state: '',
  country: '',
  country_code: '',
  location: '',
  preferred_locations: [],
  summary: '',
  smtp_host: '',
  smtp_port: '',
  smtp_user: '',
  smtp_password: '',
  smtp_use_tls: true,
  smtp_from_email: '',
  imap_host: '',
  imap_port: '',
  imap_user: '',
  imap_password: '',
  imap_folder: '',
  openai_api_key: '',
  openai_model: '',
  ai_task_instructions: '',
}

const EMPTY_SUBJECT_TEMPLATE = {
  name: '',
  category: 'fresh',
  subject: '',
}

const SUBJECT_TEMPLATE_CATEGORY_OPTIONS = [
  { value: 'fresh', label: 'Fresh' },
  { value: 'follow_up', label: 'Follow Up' },
]

const TEMPLATE_PLACEHOLDER_KEYS = [
  'name',
  'employee_name',
  'first_name',
  'user_name',
  'employee_role',
  'department',
  'employee_department',
  'company_name',
  'current_employer',
  'role',
  'job_id',
  'job_link',
  'resume_link',
  'years_of_experience',
  'yoe',
  'interaction_time',
  'interview_round',
]

const PROGRESSION_STAGES = [
  { value: 'received_call', label: 'Received Call' },
  { value: 'assignment', label: 'Assignment' },
  { value: 'round_1', label: 'Round 1' },
  { value: 'round_2', label: 'Round 2' },
  { value: 'round_3', label: 'Round 3' },
  { value: 'round_4', label: 'Round 4' },
  { value: 'round_5', label: 'Round 5' },
  { value: 'round_6', label: 'Round 6' },
  { value: 'round_7', label: 'Round 7' },
  { value: 'round_8', label: 'Round 8' },
]

const FAILURE_STAGES = [
  { value: 'rejected', label: 'Rejected' },
  { value: 'hold', label: 'Hold' },
  { value: 'no_response', label: 'No Response' },
  { value: 'no_feedback', label: 'No Feedback' },
  { value: 'ghosted', label: 'Ghosted' },
  { value: 'skipped', label: 'Skipped' },
]

const STAGES = [...PROGRESSION_STAGES]
const INTERVIEW_ACTIONS = [{ value: 'active', label: 'Active' }, { value: 'landed_job', label: 'Landed Job' }, ...FAILURE_STAGES]
const OTHER_INTERVIEW_STAGES = [
  { value: 'received_call', label: 'Received Call' },
  { value: 'assignment', label: 'Assignment' },
]

const COUNTRY_STATE_DATA = [
  { name: 'India', code: '+91', states: ['Andhra Pradesh', 'Assam', 'Bihar', 'Chandigarh', 'Chhattisgarh', 'Delhi', 'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jammu and Kashmir', 'Jharkhand', 'Karnataka', 'Kerala', 'Madhya Pradesh', 'Maharashtra', 'Odisha', 'Punjab', 'Rajasthan', 'Tamil Nadu', 'Telangana', 'Uttar Pradesh', 'Uttarakhand', 'West Bengal'] },
  { name: 'United States', code: '+1', states: ['Alabama', 'Alaska', 'Arizona', 'California', 'Colorado', 'Florida', 'Georgia', 'Illinois', 'Massachusetts', 'Michigan', 'New Jersey', 'New York', 'North Carolina', 'Ohio', 'Pennsylvania', 'Texas', 'Virginia', 'Washington'] },
  { name: 'Canada', code: '+1', states: ['Alberta', 'British Columbia', 'Manitoba', 'New Brunswick', 'Newfoundland and Labrador', 'Nova Scotia', 'Ontario', 'Prince Edward Island', 'Quebec', 'Saskatchewan'] },
  { name: 'United Kingdom', code: '+44', states: ['England', 'Northern Ireland', 'Scotland', 'Wales'] },
  { name: 'Australia', code: '+61', states: ['Australian Capital Territory', 'New South Wales', 'Northern Territory', 'Queensland', 'South Australia', 'Tasmania', 'Victoria', 'Western Australia'] },
  { name: 'United Arab Emirates', code: '+971', states: ['Abu Dhabi', 'Ajman', 'Dubai', 'Fujairah', 'Ras Al Khaimah', 'Sharjah', 'Umm Al Quwain'] },
  { name: 'Germany', code: '+49', states: ['Baden-Wurttemberg', 'Bavaria', 'Berlin', 'Brandenburg', 'Bremen', 'Hamburg', 'Hesse', 'Lower Saxony', 'North Rhine-Westphalia', 'Saxony'] },
  { name: 'Singapore', code: '+65', states: ['Central Region', 'East Region', 'North-East Region', 'North Region', 'West Region'] },
]

const COUNTRY_OPTIONS = COUNTRY_STATE_DATA.map((item) => ({ value: item.name, label: item.name }))

function countryMeta(countryName) {
  const normalized = String(countryName || '').trim().toLowerCase()
  return COUNTRY_STATE_DATA.find((item) => item.name.toLowerCase() === normalized) || null
}

function stateOptionsForCountry(countryName, currentState = '') {
  const meta = countryMeta(countryName)
  const options = (meta?.states || []).map((state) => ({ value: state, label: state }))
  const fallback = String(currentState || '').trim()
  if (fallback && !options.some((item) => item.value === fallback)) {
    options.unshift({ value: fallback, label: fallback })
  }
  return options
}

const EMPTY_INTERVIEW = {
  job: '',
  location: '',
  company_name: '',
  job_role: '',
  job_code: '',
  stage: 'received_call',
  action: 'active',
  max_round_reached: 0,
  interview_at: '',
  notes: '',
}

function profileRows(profile) {
  const rows = [
    ['Full Name', profile.full_name],
    ['Email', profile.email],
    ['Contact Number', profile.contact_number],
    ['LinkedIn', profile.linkedin_url],
    ['GitHub', profile.github_url],
    ['Portfolio', profile.portfolio_url],
    ['Resume Link', profile.resume_link],
    ['Current Employer', profile.current_employer],
    ['Years of Experience', profile.years_of_experience],
    ['Address Line 1', profile.address_line_1],
    ['Address Line 2', profile.address_line_2],
    ['State', profile.state],
    ['Country', profile.country],
    ['Country Code', profile.country_code],
    ['Location', profile.location],
    ['Preferred Locations', Array.isArray(profile.preferred_location_names) ? profile.preferred_location_names.join(', ') : ''],
    ['Summary', profile.summary],
  ]
  return rows.filter(([, value]) => String(value || '').trim())
}

function looksLikeUrl(value) {
  const text = String(value || '').trim()
  return /^https?:\/\//i.test(text)
}

function renderProfileValue(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  if (looksLikeUrl(text)) {
    return (
      <a className="profile-info-link" href={text} target="_blank" rel="noreferrer">
        {text}
      </a>
    )
  }
  return text
}

function normalizeProfileLike(data, fallbackFullName = '') {
  const nextValue = { ...EMPTY_PROFILE, ...(data || {}) }
  nextValue.preferred_locations = Array.isArray(nextValue.preferred_locations)
    ? nextValue.preferred_locations.map((value) => String(value))
    : []
  nextValue.smtp_port = nextValue.smtp_port ? String(nextValue.smtp_port) : ''
  nextValue.imap_port = nextValue.imap_port ? String(nextValue.imap_port) : ''
  nextValue.smtp_use_tls = typeof nextValue.smtp_use_tls === 'boolean' ? nextValue.smtp_use_tls : true
  if (!String(nextValue.full_name || '').trim() && fallbackFullName) {
    nextValue.full_name = String(fallbackFullName)
  }
  return nextValue
}

function toInputDateTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toISOString().slice(0, 16)
}

function displayStage(value) {
  return STAGES.find((item) => item.value === value)?.label || value || '-'
}
function displayAction(value) {
  return INTERVIEW_ACTIONS.find((item) => item.value === value)?.label || value || '-'
}
function displayStageShort(value) {
  const round = roundValue(value)
  if (round > 0) return `R${round}`
  const raw = String(value || '').trim().toLowerCase()
  if (raw === 'received_call') return 'Received Call'
  if (raw === 'assignment') return 'Assignment'
  if (raw === 'landed_job') return 'Landed Job'
  return displayStage(value)
}
function milestoneLabel(stage, action) {
  const stageText = displayStageShort(stage)
  const actionRaw = String(action || 'active').trim().toLowerCase()
  if (!actionRaw || actionRaw === 'active') return stageText
  return `${stageText} | ${displayAction(actionRaw)}`
}
function milestoneDateText(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString()
}

function roundValue(stage) {
  const raw = String(stage || '').trim().toLowerCase()
  if (!raw.startsWith('round_')) return 0
  const value = Number(raw.replace('round_', ''))
  if (!Number.isFinite(value)) return 0
  if (value < 1 || value > 8) return 0
  return value
}

function isRoundSelectionDisabled(targetRound, rememberedRound, currentSelectedRound) {
  const safeRemembered = Math.max(Number(rememberedRound || 0), 0)
  const selected = Math.max(Number(currentSelectedRound || 0), 0)
  const nextAllowed = Math.min(safeRemembered + 1, 8)
  if (selected > 0 && targetRound === selected) return false
  return targetRound !== nextAllowed
}

function milestoneEventsForRow(row) {
  const raw = Array.isArray(row?.milestone_events) ? row.milestone_events : []
  const events = raw
    .map((event) => {
      const stage = String(event?.stage || '').trim().toLowerCase()
      const action = String(event?.action || '').trim().toLowerCase()
      return {
        stage,
        action,
        label: milestoneLabel(stage, action || 'active'),
        at: event?.at || '',
      }
    })
    .filter((event) => event.stage || event.action || event.label)
  if (!events.length) {
    return [
      {
        stage: String(row?.stage || 'received_call').trim().toLowerCase(),
        action: String(row?.action || 'active').trim().toLowerCase(),
        label: milestoneLabel(row?.stage || 'received_call', row?.action || 'active'),
        at: row?.updated_at || row?.created_at || '',
      },
    ]
  }
  return events.slice(-10)
}

function skillsPreviewFromResume(row) {
  const raw = String(row?.builder_data?.skills || '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!raw) return ''
  if (raw.length <= 72) return raw
  return `${raw.slice(0, 72).trim()}...`
}

function interviewJobDisplay(companyName, jobRole, jobCode) {
  const parts = [
    String(companyName || '').trim(),
    String(jobRole || '').trim(),
    String(jobCode || '').trim(),
  ].filter(Boolean)
  return parts.join(' | ') || '-'
}

function CloseIcon() {
  return <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="m18.3 5.71l-1.41-1.42L12 9.17L7.11 4.29L5.7 5.71L10.59 10.6L5.7 15.5l1.41 1.41L12 12l4.89 4.91l1.41-1.41l-4.89-4.9z" /></svg>
}

function ProfilePage() {
  const access = localStorage.getItem('access') || ''
  const navigate = useNavigate()

  const [profile, setProfile] = useState(EMPTY_PROFILE)
  const [editingProfile, setEditingProfile] = useState(false)
  const [profileForm, setProfileForm] = useState(EMPTY_PROFILE)
  const [profileUsername, setProfileUsername] = useState('')

  const [resumes, setResumes] = useState([])
  const [previewResume, setPreviewResume] = useState(null)

  const [subjectTemplates, setSubjectTemplates] = useState([])
  const [subjectTemplateCategoryFilter, setSubjectTemplateCategoryFilter] = useState('')
  const [showSubjectTemplateForm, setShowSubjectTemplateForm] = useState(false)
  const [editingSubjectTemplateId, setEditingSubjectTemplateId] = useState(null)
  const [subjectTemplateForm, setSubjectTemplateForm] = useState(EMPTY_SUBJECT_TEMPLATE)
  const [showSubjectTemplateHints, setShowSubjectTemplateHints] = useState(false)
  const [subjectTemplateError, setSubjectTemplateError] = useState('')
  const [subjectTemplateOk, setSubjectTemplateOk] = useState('')

  const [interviews, setInterviews] = useState([])
  const [jobOptions, setJobOptions] = useState([])
  const [locationOptions, setLocationOptions] = useState([])
  const [showInterviewForm, setShowInterviewForm] = useState(false)
  const [editingInterviewId, setEditingInterviewId] = useState(null)
  const [interviewForm, setInterviewForm] = useState(EMPTY_INTERVIEW)
  const [savingInterviewId, setSavingInterviewId] = useState(null)
  const [rowOtherStageDraft, setRowOtherStageDraft] = useState({})
  const [rowRoundStageDraft, setRowRoundStageDraft] = useState({})

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [ok, setOk] = useState('')

  const interviewCompanyOptions = useMemo(() => {
    const seen = new Set()
    const options = []
    ;(Array.isArray(jobOptions) ? jobOptions : []).forEach((job) => {
      const companyName = String(job?.company_name || '').trim()
      if (!companyName) return
      const key = companyName.toLowerCase()
      if (seen.has(key)) return
      seen.add(key)
      options.push({ value: companyName, label: companyName })
    })
    options.sort((a, b) => a.label.localeCompare(b.label))
    return options
  }, [jobOptions])

  const interviewJobOptions = useMemo(() => {
    const selectedCompany = String(interviewForm.company_name || '').trim().toLowerCase()
    return (Array.isArray(jobOptions) ? jobOptions : [])
      .filter((job) => {
        if (!selectedCompany) return false
        return String(job?.company_name || '').trim().toLowerCase() === selectedCompany
      })
      .map((job) => ({
        value: String(job.id),
        label: interviewJobDisplay(job.company_name, job.role, job.job_id),
      }))
  }, [jobOptions, interviewForm.company_name])

  const profileStateOptions = useMemo(
    () => stateOptionsForCountry(profileForm.country, profileForm.state),
    [profileForm.country, profileForm.state],
  )

  const filteredSubjectTemplates = useMemo(() => {
    const selectedCategory = String(subjectTemplateCategoryFilter || '').trim().toLowerCase()
    const rows = Array.isArray(subjectTemplates) ? subjectTemplates : []
    if (!selectedCategory) return rows
    return rows.filter((row) => String(row?.category || '').trim().toLowerCase() === selectedCategory)
  }, [subjectTemplates, subjectTemplateCategoryFilter])

  useEffect(() => {
    if (!access) return
    let cancelled = false

    const loadAll = async () => {
      setLoading(true)
      setError('')
      try {
        const [profileBase, info, resumeRows, subjectRows, interviewRows, jobsData, locationRows] = await Promise.all([
          fetchProfile(access),
          fetchProfileInfo(access),
          fetchResumes(access),
          fetchSubjectTemplates(access),
          fetchInterviews(access),
          fetchAllJobs(access),
          fetchLocations(access),
        ])
        if (cancelled) return
        const nextProfile = normalizeProfileLike(info, String(profileBase?.username || ''))
        setProfile(nextProfile)
        setProfileForm(nextProfile)
        setProfileUsername(String(profileBase?.username || ''))
        setResumes(
          Array.isArray(resumeRows)
            ? resumeRows.filter((row) => !row?.is_tailored)
            : [],
        )
        setSubjectTemplates(Array.isArray(subjectRows) ? subjectRows : [])
        setInterviews(Array.isArray(interviewRows) ? interviewRows : [])
        setJobOptions(Array.isArray(jobsData) ? jobsData : [])
        setLocationOptions(Array.isArray(locationRows) ? locationRows : [])
      } catch (err) {
        if (!cancelled) {
          setError(err.message || 'Could not load profile data.')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    loadAll()
    return () => {
      cancelled = true
    }
  }, [access])

  const saveProfile = async () => {
    try {
      setError('')
      setOk('')
      const payload = {
        ...profileForm,
        smtp_port: profileForm.smtp_port ? Number(profileForm.smtp_port) : null,
        imap_port: profileForm.imap_port ? Number(profileForm.imap_port) : null,
      }
      const updated = await updateProfileInfo(access, payload)
      const nextProfile = normalizeProfileLike(updated, profileUsername)
      setProfile(nextProfile)
      setProfileForm(nextProfile)
      setEditingProfile(false)
      setOk('Personal info updated.')
    } catch (err) {
      setError(err.message || 'Could not save personal info.')
    }
  }

  const openProfileEditor = () => {
    setError('')
    setOk('')
    setProfileForm(profile)
    setEditingProfile(true)
  }

  const closeProfileEditor = () => {
    setProfileForm(profile)
    setEditingProfile(false)
  }

  const removeResume = async (resumeId) => {
    try {
      setError('')
      setOk('')
      await deleteResume(access, resumeId)
      setResumes((prev) => prev.filter((row) => row.id !== resumeId))
      setOk('Resume deleted.')
    } catch (err) {
      setError(err.message || 'Could not delete resume.')
    }
  }

  const openResumeInBuilder = (resumeId) => {
    sessionStorage.setItem('builderSaveMode', 'edit')
    sessionStorage.removeItem('builderImport')
    sessionStorage.setItem('builderResumeId', String(resumeId))
    navigate('/builder')
  }

  const openCreateResumeInBuilder = () => {
    sessionStorage.setItem('builderSaveMode', 'create')
    sessionStorage.removeItem('builderImport')
    sessionStorage.removeItem('builderResumeId')
    navigate('/builder')
  }

  const openCreateSubjectTemplate = () => {
    setError('')
    setOk('')
    setSubjectTemplateError('')
    setSubjectTemplateOk('')
    setEditingSubjectTemplateId(null)
    setSubjectTemplateForm(EMPTY_SUBJECT_TEMPLATE)
    setShowSubjectTemplateHints(false)
    setShowSubjectTemplateForm(true)
  }

  const closeSubjectTemplateForm = () => {
    setShowSubjectTemplateForm(false)
    setEditingSubjectTemplateId(null)
    setSubjectTemplateForm(EMPTY_SUBJECT_TEMPLATE)
    setShowSubjectTemplateHints(false)
  }

  const editSubjectTemplate = (row) => {
    setError('')
    setOk('')
    setSubjectTemplateError('')
    setSubjectTemplateOk('')
    setEditingSubjectTemplateId(row.id)
    setSubjectTemplateForm({
      name: row.name || '',
      category: row.category || 'fresh',
      subject: row.subject || '',
    })
    setShowSubjectTemplateHints(false)
    setShowSubjectTemplateForm(true)
  }

  const saveSubjectTemplate = async () => {
    try {
      setSubjectTemplateError('')
      setSubjectTemplateOk('')
      const payload = {
        name: String(subjectTemplateForm.name || '').trim(),
        category: String(subjectTemplateForm.category || 'fresh').trim() || 'fresh',
        subject: String(subjectTemplateForm.subject || '').trim(),
      }
      if (!payload.name || !payload.subject) {
        setSubjectTemplateError('Subject template needs name and subject text.')
        return
      }
      if (editingSubjectTemplateId) {
        const updated = await updateSubjectTemplate(access, editingSubjectTemplateId, payload)
        setSubjectTemplates((prev) => prev.map((row) => (row.id === editingSubjectTemplateId ? updated : row)))
        setSubjectTemplateOk('Subject template updated.')
      } else {
        const created = await createSubjectTemplate(access, payload)
        setSubjectTemplates((prev) => [created, ...prev])
        setSubjectTemplateOk('Subject template added.')
      }
      closeSubjectTemplateForm()
    } catch (err) {
      setSubjectTemplateError(err.message || 'Could not save subject template.')
    }
  }

  const removeSubjectTemplate = async (id) => {
    try {
      setSubjectTemplateError('')
      setSubjectTemplateOk('')
      await deleteSubjectTemplate(access, id)
      setSubjectTemplates((prev) => prev.filter((row) => row.id !== id))
      setSubjectTemplateOk('Subject template deleted.')
    } catch (err) {
      setSubjectTemplateError(err.message || 'Could not delete subject template.')
    }
  }

  const openCreateInterviewForm = () => {
    setError('')
    setOk('')
    setEditingInterviewId(null)
    setInterviewForm(EMPTY_INTERVIEW)
    setShowInterviewForm(true)
  }

  const closeInterviewForm = () => {
    setShowInterviewForm(false)
    setEditingInterviewId(null)
    setInterviewForm(EMPTY_INTERVIEW)
  }

  const saveInterview = async () => {
    try {
      setError('')
      setOk('')
      const payload = {
        job: interviewForm.job || null,
        location: String(interviewForm.location || '').trim(),
        company_name: String(interviewForm.company_name || '').trim(),
        job_role: String(interviewForm.job_role || '').trim(),
        job_code: String(interviewForm.job_code || '').trim(),
        stage: String(interviewForm.stage || 'received_call').trim(),
        action: String(interviewForm.action || 'active').trim(),
        interview_at: interviewForm.interview_at || null,
        notes: String(interviewForm.notes || '').trim(),
      }
      if (!payload.company_name || !payload.job_role) {
        setError('Interview needs company and job role.')
        return
      }
      if (editingInterviewId) {
        const updated = await updateInterview(access, editingInterviewId, payload)
        setInterviews((prev) => prev.map((row) => (row.id === editingInterviewId ? updated : row)))
        setOk('Interview updated.')
      } else {
        const created = await createInterview(access, payload)
        setInterviews((prev) => [created, ...prev])
        setOk('Interview added.')
      }
      closeInterviewForm()
    } catch (err) {
      setError(err.message || 'Could not save interview.')
    }
  }

  const editInterview = (row) => {
    setError('')
    setOk('')
    setEditingInterviewId(row.id)
    setInterviewForm({
      job: row.job ? String(row.job) : '',
      location: row.location_name || row.location || '',
      company_name: row.company_name || '',
      job_role: row.job_role || '',
      job_code: row.job_code || '',
      stage: row.stage || 'received_call',
      action: row.action || 'active',
      max_round_reached: Number(row.max_round_reached || roundValue(row.stage) || 0),
      interview_at: toInputDateTime(row.interview_at),
      notes: row.notes || '',
    })
    setShowInterviewForm(true)
  }

  const removeInterview = async (id) => {
    try {
      await deleteInterview(access, id)
      setInterviews((prev) => prev.filter((row) => row.id !== id))
    } catch (err) {
      setError(err.message || 'Could not delete interview.')
    }
  }

  const inlineUpdateInterview = async (row, patch) => {
    try {
      setSavingInterviewId(row.id)
      const updated = await updateInterview(access, row.id, patch)
      setInterviews((prev) => prev.map((item) => (item.id === row.id ? updated : item)))
    } catch (err) {
      setError(err.message || 'Could not update interview.')
    } finally {
      setSavingInterviewId(null)
    }
  }

  return (
    <main className="page page-wide mx-auto w-full">
      <div className="tracking-head">
        <div>
          <h1>Profile</h1>
          <p className="subtitle">Personal info, resumes, subject templates, and interview milestones.</p>
        </div>
        <div className="actions">
          <button type="button" className="secondary" onClick={openCreateResumeInBuilder}>Open Resume Workspace</button>
        </div>
      </div>

      {loading ? <p className="hint">Loading profile...</p> : null}

      <section className="dash-card">
        <div className="tracking-head profile-section-head">
          <h2>Resumes</h2>
          <div className="actions">
            <button type="button" className="secondary" onClick={openCreateResumeInBuilder}>Add Resume</button>
          </div>
        </div>
        <div className="profile-resume-grid">
          {resumes.map((row) => (
            <article key={row.id} className="resume-card profile-card-shell">
              <p className="resume-card-title"><strong>{row.title || `Resume #${row.id}`}</strong></p>
              {row.job_label ? <p className="hint">Job: {row.job_label}</p> : null}
              {row.source_resume_title ? <p className="hint">Source: {row.source_resume_title}</p> : null}
              {skillsPreviewFromResume(row) ? <p className="hint">Skills: {skillsPreviewFromResume(row)}</p> : null}
              <p className="resume-card-meta">Updated: {row.updated_at ? new Date(row.updated_at).toLocaleString() : '-'}</p>
              <div className="resume-card-actions">
                <button type="button" className="secondary" onClick={() => setPreviewResume(row)}>Preview</button>
                <button type="button" className="secondary" onClick={() => openResumeInBuilder(row.id)}>Edit</button>
                <button type="button" className="secondary" onClick={() => removeResume(row.id)}>Delete</button>
              </div>
            </article>
          ))}
          {!resumes.length ? <p className="hint">No resumes yet.</p> : null}
        </div>
      </section>

      <section className="dash-card">
        <div className="tracking-head profile-section-head">
          <h2>Personal Info</h2>
          <div className="actions">
            <button type="button" className="secondary" onClick={openProfileEditor}>Edit Info</button>
          </div>
        </div>
        <div className="profile-info-grid">
          {profileRows(profile).map(([label, value]) => (
            <div key={label} className="profile-info-item">
              <span className="profile-info-label">{label}</span>
              <span className="profile-info-value">{renderProfileValue(value)}</span>
            </div>
          ))}
          {!profileRows(profile).length ? (
            <div className="profile-info-item">
              <span className="profile-info-label">Full Name</span>
              <span className="profile-info-value">{profileUsername || '-'}</span>
            </div>
          ) : null}
        </div>
      </section>

      <section className="dash-card">
        <div className="tracking-head profile-section-head">
          <h2>Subject Templates</h2>
          <div className="actions profile-template-head-actions">
            <div className="profile-template-filter">
              <SingleSelectDropdown
                value={subjectTemplateCategoryFilter}
                placeholder="Category"
                searchPlaceholder="Search category"
                clearLabel="All Categories"
                options={SUBJECT_TEMPLATE_CATEGORY_OPTIONS}
                onChange={(nextValue) => setSubjectTemplateCategoryFilter(nextValue || '')}
              />
            </div>
            <button type="button" className="secondary" onClick={openCreateSubjectTemplate}>Add Subject Template</button>
          </div>
        </div>
        <p className="hint">Manage your own reusable subject templates here. These will appear in the tracking subject dropdown.</p>
        {subjectTemplateError ? <p className="error">{subjectTemplateError}</p> : null}
        {subjectTemplateOk ? <p className="success">{subjectTemplateOk}</p> : null}
        <div className="profile-ach-grid">
          {filteredSubjectTemplates.map((row) => (
            <article key={row.id} className="profile-template-row">
              <div className="profile-template-main">
                <p className="profile-template-title"><strong>{row.name || '-'}</strong></p>
                <p className="hint">{String(row.category || 'general').replaceAll('_', ' ')}</p>
                <p className="profile-template-snippet">{row.subject || '-'}</p>
              </div>
              <div className="profile-template-actions">
                <button type="button" className="secondary" onClick={() => editSubjectTemplate(row)}>Edit</button>
                <button type="button" className="secondary" onClick={() => removeSubjectTemplate(row.id)}>Delete</button>
              </div>
            </article>
          ))}
          {!subjectTemplates.length ? <p className="hint">No subject templates yet.</p> : null}
          {subjectTemplates.length && !filteredSubjectTemplates.length ? <p className="hint">No subject templates in this category.</p> : null}
        </div>
      </section>

      <section className="dash-card">
        <div className="tracking-head profile-section-head">
          <h2>Interview Section</h2>
          <div className="actions">
            <button type="button" className="secondary" onClick={openCreateInterviewForm}>Add Interview</button>
          </div>
        </div>

        <div className="grid gap-4">
          {interviews.map((row) => {
            const rememberedRound = Number(row.max_round_reached || 0)
            const nextRound = Math.min(Math.max(rememberedRound + 1, 1), 8)
            const otherStageValueDraft = typeof rowOtherStageDraft[row.id] === 'string' ? rowOtherStageDraft[row.id] : ''
            const roundStageValueDraft = typeof rowRoundStageDraft[row.id] === 'string' ? rowRoundStageDraft[row.id] : ''
            const action = String(row.action || 'active').toLowerCase()
            const isHold = action === 'hold'
            const isLanded = action === 'landed_job'
            const isFailure = ['rejected', 'no_response', 'no_feedback', 'ghosted', 'skipped'].includes(action)
            const isActive = action === 'active'
            const showFutureDots = isActive || isHold
            const eventSteps = milestoneEventsForRow(row)
            const reachedCount = Math.max(1, Math.min(10, eventSteps.length))
            const totalDots = showFutureDots ? 10 : reachedCount
            const currentDotIndex = reachedCount - 1
            return (
              <article key={row.id} className="profile-interview-card">
                <div className="profile-interview-head">
                  <p className="profile-interview-title">{interviewJobDisplay(row.company_name, row.job_role, row.job_code)}</p>
                  <div className="tracking-actions-compact">
                    <button type="button" className="secondary" onClick={() => editInterview(row)}>Edit</button>
                    <button type="button" className="secondary" onClick={() => removeInterview(row.id)}>Delete</button>
                  </div>
                </div>
                <div className="profile-form-grid profile-form-grid-tight profile-interview-controls">
                  <label>Other Stage
                    <SingleSelectDropdown
                      value={otherStageValueDraft}
                      placeholder="Select stage"
                      disabled={savingInterviewId === row.id || String(row.action || 'active').toLowerCase() !== 'active'}
                      options={OTHER_INTERVIEW_STAGES.map((item) => ({ value: item.value, label: item.label }))}
                      onChange={(nextStage) => {
                        if (!nextStage) return
                        setRowOtherStageDraft((prev) => ({ ...prev, [row.id]: nextStage }))
                        inlineUpdateInterview(row, { stage: nextStage })
                        setRowOtherStageDraft((prev) => {
                          const next = { ...prev }
                          delete next[row.id]
                          return next
                        })
                        setRowRoundStageDraft((prev) => {
                          const next = { ...prev }
                          delete next[row.id]
                          return next
                        })
                      }}
                    />
                  </label>
                  <label>Round Stage
                    <SingleSelectDropdown
                      value={roundStageValueDraft}
                      placeholder="Select round"
                      disabled={savingInterviewId === row.id || String(row.action || 'active').toLowerCase() !== 'active'}
                      options={Array.from({ length: 8 }, (_, idx) => {
                        const targetRound = idx + 1
                        const currentSelectedRound = roundValue(roundStageValueDraft || `round_${nextRound}`)
                        const isDisabled = isRoundSelectionDisabled(targetRound, rememberedRound, currentSelectedRound)
                        return {
                          value: `round_${targetRound}`,
                          label: `Round ${targetRound}${isDisabled ? ' (Locked)' : ''}`,
                        }
                      })}
                      onChange={(nextStage) => {
                        if (!nextStage) return
                        const targetRound = roundValue(nextStage)
                        const currentSelectedRound = roundValue(roundStageValueDraft || `round_${nextRound}`)
                        if (isRoundSelectionDisabled(targetRound, rememberedRound, currentSelectedRound)) return
                        setRowRoundStageDraft((prev) => ({ ...prev, [row.id]: nextStage }))
                        inlineUpdateInterview(row, { stage: nextStage })
                        setRowRoundStageDraft((prev) => {
                          const next = { ...prev }
                          delete next[row.id]
                          return next
                        })
                        setRowOtherStageDraft((prev) => {
                          const next = { ...prev }
                          delete next[row.id]
                          return next
                        })
                      }}
                    />
                  </label>
                </div>
                <div className="profile-form-grid profile-form-grid-tight profile-interview-action-row">
                  <label>Action
                    <SingleSelectDropdown
                      value={row.action || 'active'}
                      placeholder="Select action"
                      disabled={savingInterviewId === row.id}
                      options={INTERVIEW_ACTIONS.map((item) => ({ value: item.value, label: item.label }))}
                      onChange={(nextValue) => inlineUpdateInterview(row, { action: nextValue || 'active' })}
                    />
                  </label>
                </div>
                {row.location_name ? <p className="hint profile-form-note">Location: {row.location_name}</p> : null}
                <div className="profile-milestone-wrap">
                  {Array.from({ length: totalDots }, (_, index) => (
                    <div key={`${row.id}-step-${index}`} className="profile-milestone-node">
                      <span
                        className={[
                          'profile-milestone-dot',
                          (() => {
                            if (index === currentDotIndex && isHold) return 'is-blue'
                            if (index === currentDotIndex && isFailure) return 'is-red'
                            if (index < currentDotIndex) return 'is-active'
                            if (index === currentDotIndex && !isFailure && !isHold) return 'is-active'
                            return ''
                          })(),
                        ].join(' ').trim()}
                      >
                        {index === currentDotIndex && isLanded ? '✅' : ''}
                      </span>
                      <span className="profile-milestone-label">{eventSteps[index]?.label || ''}</span>
                      <span className="profile-milestone-date">{milestoneDateText(eventSteps[index]?.at)}</span>
                      {index < totalDots - 1 ? (
                        <span
                          className={[
                            'profile-milestone-line',
                            index < currentDotIndex ? 'is-active' : '',
                          ].join(' ').trim()}
                        />
                      ) : null}
                    </div>
                  ))}
                </div>
                {row.notes ? <p className="profile-interview-notes">{row.notes}</p> : null}
              </article>
            )
          })}
          {!interviews.length ? <p className="hint">No interview entries yet.</p> : null}
        </div>
      </section>

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
              <button type="button" className="secondary tracking-icon-btn" title="Close" aria-label="Close" onClick={() => setPreviewResume(null)}><CloseIcon /></button>
            </div>
          </div>
        </div>
      ) : null}

      {editingProfile ? (
        <div className="modal-overlay" onClick={closeProfileEditor}>
          <div className="modal-panel profile-modal-panel" onClick={(event) => event.stopPropagation()}>
            <h2>Edit Personal Info</h2>
            <div className="profile-form-grid profile-interview-form-grid">
              <label>Full Name<input value={profileForm.full_name} onChange={(e) => setProfileForm((p) => ({ ...p, full_name: e.target.value }))} /></label>
              <label>Email<input value={profileForm.email} onChange={(e) => setProfileForm((p) => ({ ...p, email: e.target.value }))} /></label>
              <label>Contact Number<input value={profileForm.contact_number} onChange={(e) => setProfileForm((p) => ({ ...p, contact_number: e.target.value }))} /></label>
              <label>Address Line 1<input value={profileForm.address_line_1} onChange={(e) => setProfileForm((p) => ({ ...p, address_line_1: e.target.value }))} /></label>
              <label>Address Line 2<input value={profileForm.address_line_2} onChange={(e) => setProfileForm((p) => ({ ...p, address_line_2: e.target.value }))} /></label>
              <label>Country
                <SingleSelectDropdown
                  value={profileForm.country || ''}
                  placeholder="Select country"
                  searchPlaceholder="Search country"
                  options={COUNTRY_OPTIONS}
                  onChange={(nextValue) => {
                    const selectedCountry = String(nextValue || '').trim()
                    const meta = countryMeta(selectedCountry)
                    setProfileForm((p) => {
                      const nextState = meta?.states?.includes(String(p.state || '').trim()) ? p.state : ''
                      return {
                        ...p,
                        country: selectedCountry,
                        state: nextState,
                        country_code: meta?.code || p.country_code,
                      }
                    })
                  }}
                />
              </label>
              <label>State
                <SingleSelectDropdown
                  value={profileForm.state || ''}
                  placeholder={profileForm.country ? 'Select state' : 'Select country first'}
                  searchPlaceholder="Search state"
                  options={profileStateOptions}
                  onChange={(nextValue) => setProfileForm((p) => ({ ...p, state: nextValue || '' }))}
                />
              </label>
              <label>Country Code<input value={profileForm.country_code} onChange={(e) => setProfileForm((p) => ({ ...p, country_code: e.target.value }))} placeholder="+91" /></label>
              <label>Location<input value={profileForm.location} onChange={(e) => setProfileForm((p) => ({ ...p, location: e.target.value }))} /></label>
              <label>Preferred Locations
                <MultiSelectDropdown
                  values={Array.isArray(profileForm.preferred_locations) ? profileForm.preferred_locations : []}
                  placeholder="Select preferred locations"
                  searchPlaceholder="Search location"
                  options={locationOptions.map((location) => ({ value: String(location.id), label: String(location.name || '') }))}
                  onChange={(nextValues) => setProfileForm((p) => ({
                    ...p,
                    preferred_locations: Array.isArray(nextValues) ? nextValues : [],
                  }))}
                />
              </label>
              <label>Current Employer<input value={profileForm.current_employer} onChange={(e) => setProfileForm((p) => ({ ...p, current_employer: e.target.value }))} /></label>
              <label>Years of Experience<input value={profileForm.years_of_experience} onChange={(e) => setProfileForm((p) => ({ ...p, years_of_experience: e.target.value }))} /></label>
              <label>LinkedIn URL<input value={profileForm.linkedin_url} onChange={(e) => setProfileForm((p) => ({ ...p, linkedin_url: e.target.value }))} /></label>
              <label>GitHub URL<input value={profileForm.github_url} onChange={(e) => setProfileForm((p) => ({ ...p, github_url: e.target.value }))} /></label>
              <label>Portfolio URL<input value={profileForm.portfolio_url} onChange={(e) => setProfileForm((p) => ({ ...p, portfolio_url: e.target.value }))} /></label>
              <label>Resume Link<input value={profileForm.resume_link} onChange={(e) => setProfileForm((p) => ({ ...p, resume_link: e.target.value }))} /></label>
              <label>Summary<textarea rows={3} value={profileForm.summary} onChange={(e) => setProfileForm((p) => ({ ...p, summary: e.target.value }))} /></label>
              <label>SMTP Host<input value={profileForm.smtp_host} onChange={(e) => setProfileForm((p) => ({ ...p, smtp_host: e.target.value }))} /></label>
              <label>SMTP Port<input value={profileForm.smtp_port} onChange={(e) => setProfileForm((p) => ({ ...p, smtp_port: e.target.value.replace(/[^\d]/g, '') }))} placeholder="587" /></label>
              <label>SMTP User<input value={profileForm.smtp_user} onChange={(e) => setProfileForm((p) => ({ ...p, smtp_user: e.target.value }))} /></label>
              <label>SMTP Password<input type="password" value={profileForm.smtp_password} onChange={(e) => setProfileForm((p) => ({ ...p, smtp_password: e.target.value }))} autoComplete="new-password" /></label>
              <label>SMTP From Email<input value={profileForm.smtp_from_email} onChange={(e) => setProfileForm((p) => ({ ...p, smtp_from_email: e.target.value }))} /></label>
              <label className="profile-checkbox-label">
                <span>SMTP Use TLS</span>
                <input type="checkbox" checked={!!profileForm.smtp_use_tls} onChange={(e) => setProfileForm((p) => ({ ...p, smtp_use_tls: e.target.checked }))} />
              </label>
              <label>IMAP Host<input value={profileForm.imap_host} onChange={(e) => setProfileForm((p) => ({ ...p, imap_host: e.target.value }))} /></label>
              <label>IMAP Port<input value={profileForm.imap_port} onChange={(e) => setProfileForm((p) => ({ ...p, imap_port: e.target.value.replace(/[^\d]/g, '') }))} placeholder="993" /></label>
              <label>IMAP User<input value={profileForm.imap_user} onChange={(e) => setProfileForm((p) => ({ ...p, imap_user: e.target.value }))} /></label>
              <label>IMAP Password<input type="password" value={profileForm.imap_password} onChange={(e) => setProfileForm((p) => ({ ...p, imap_password: e.target.value }))} autoComplete="new-password" /></label>
              <label>IMAP Folder<input value={profileForm.imap_folder} onChange={(e) => setProfileForm((p) => ({ ...p, imap_folder: e.target.value }))} placeholder="INBOX" /></label>
              <label>OpenAI API Key<input type="password" value={profileForm.openai_api_key} onChange={(e) => setProfileForm((p) => ({ ...p, openai_api_key: e.target.value }))} autoComplete="new-password" /></label>
              <label>OpenAI Model<input value={profileForm.openai_model} onChange={(e) => setProfileForm((p) => ({ ...p, openai_model: e.target.value }))} placeholder="gpt-4o" /></label>
            </div>
            <div className="actions">
              <button type="button" onClick={saveProfile}>Save</button>
              <button type="button" className="secondary" onClick={closeProfileEditor}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}

      {showInterviewForm ? (
        <div className="modal-overlay" onClick={closeInterviewForm}>
          <div className="modal-panel profile-modal-panel" onClick={(event) => event.stopPropagation()}>
            <h2>{editingInterviewId ? 'Edit Interview' : 'Add Interview'}</h2>
            <div className="profile-form-grid profile-interview-form-grid">
              <label>Company
                <SingleSelectDropdown
                  value={interviewForm.company_name}
                  placeholder="Select company"
                  options={interviewCompanyOptions}
                  onChange={(nextValue) => setInterviewForm((p) => ({
                    ...p,
                    company_name: nextValue || '',
                    job: '',
                    job_role: '',
                    job_code: '',
                  }))}
                />
              </label>
              <label>Select Job
                <SingleSelectDropdown
                  value={interviewForm.job}
                  placeholder={interviewForm.company_name ? 'Select job' : 'Select company first'}
                  options={interviewJobOptions}
                  disabled={!interviewForm.company_name}
                  onChange={(e) => {
                    const selectedId = String(e || '')
                    const selectedJob = jobOptions.find((item) => String(item.id) === selectedId)
                    setInterviewForm((p) => ({
                      ...p,
                      job: selectedId,
                      company_name: selectedJob?.company_name || p.company_name,
                      job_role: selectedJob?.role || p.job_role,
                      job_code: selectedJob?.job_id || p.job_code,
                    }))
                  }}
                />
              </label>
              <label>Job Role<input value={interviewForm.job_role} onChange={(e) => setInterviewForm((p) => ({ ...p, job_role: e.target.value }))} /></label>
              <label>Job ID<input value={interviewForm.job_code} onChange={(e) => setInterviewForm((p) => ({ ...p, job_code: e.target.value }))} /></label>
              <label>Location<input list="interview-location-options" value={interviewForm.location || ''} onChange={(e) => setInterviewForm((p) => ({ ...p, location: e.target.value }))} placeholder="Interview location" /></label>
              <datalist id="interview-location-options">
                {locationOptions.map((location) => (
                  <option key={`interview-location-${location.id}`} value={String(location.name || '')} />
                ))}
              </datalist>
              <label>Interview At<input type="datetime-local" value={interviewForm.interview_at} onChange={(e) => setInterviewForm((p) => ({ ...p, interview_at: e.target.value }))} /></label>
              <label className="md:col-span-2">Notes<textarea rows={3} value={interviewForm.notes} onChange={(e) => setInterviewForm((p) => ({ ...p, notes: e.target.value }))} /></label>
            </div>
            <div className="actions">
              <button type="button" onClick={saveInterview}>{editingInterviewId ? 'Update' : 'Create'}</button>
              <button type="button" className="secondary" onClick={closeInterviewForm}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}

      {showSubjectTemplateForm ? (
        <div className="modal-overlay" onClick={closeSubjectTemplateForm}>
          <div className="modal-panel profile-modal-panel" onClick={(event) => event.stopPropagation()}>
            <h2>{editingSubjectTemplateId ? 'Edit Subject Template' : 'Add Subject Template'}</h2>
            <div className="profile-form-grid">
              <label>Name<input value={subjectTemplateForm.name} onChange={(e) => setSubjectTemplateForm((p) => ({ ...p, name: e.target.value }))} /></label>
              <label>Category<select value={subjectTemplateForm.category || 'fresh'} onChange={(e) => setSubjectTemplateForm((p) => ({ ...p, category: e.target.value }))}><option value="fresh">Fresh</option><option value="follow_up">Follow Up</option></select></label>
              <label>
                Subject
                <input
                  value={subjectTemplateForm.subject}
                  onChange={(e) => setSubjectTemplateForm((p) => ({ ...p, subject: e.target.value }))}
                  placeholder="Example: Application for {role} at {company_name} | {job_id}"
                />
              </label>
              <div className="profile-template-hint-panel">
                <button
                  type="button"
                  className="secondary profile-template-hint-toggle"
                  onClick={() => setShowSubjectTemplateHints((current) => !current)}
                >
                  {showSubjectTemplateHints ? 'Hide Hints' : 'Show Hints'}
                </button>
                {showSubjectTemplateHints ? (
                  <div className="profile-template-hint-box">
                    <p className="hint profile-form-note">Use placeholders in the subject like <code>{'{user_name}'}</code>, <code>{'{role}'}</code>, <code>{'{company_name}'}</code>, <code>{'{job_id}'}</code>, or <code>{'{years_of_experience}'}</code>.</p>
                    <div className="profile-template-hint-chips">
                      {TEMPLATE_PLACEHOLDER_KEYS.map((key) => (
                        <code key={`subject-template-key-${key}`} className="profile-template-hint-chip">{`{${key}}`}</code>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
            <div className="actions">
              <button type="button" onClick={saveSubjectTemplate}>{editingSubjectTemplateId ? 'Update' : 'Create'}</button>
              <button type="button" className="secondary" onClick={closeSubjectTemplateForm}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}

      {error ? <p className="error">{error}</p> : null}
      {ok ? <p className="success">{ok}</p> : null}
    </main>
  )
}

export default ProfilePage
