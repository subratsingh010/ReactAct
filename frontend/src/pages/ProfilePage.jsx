import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ResumeSheet from '../components/ResumeSheet'
import { MultiSelectDropdown, SingleSelectDropdown } from '../components/SearchableDropdown'

import {
  createProfilePanel,
  createTemplate,
  createInterview,
  createWorkspaceMember,
  deleteProfilePanel,
  deleteTemplate,
  deleteInterview,
  deleteResume,
  deleteWorkspaceMember,
  fetchTemplates,
  fetchInterviews,
  fetchJobs,
  fetchLocations,
  fetchProfile,
  fetchProfileInfo,
  fetchProfilePanels,
  fetchResumes,
  fetchWorkspaceMembers,
  updateProfilePanel,
  updateTemplate,
  updateInterview,
  updateProfileInfo,
} from '../api'

const MAX_PROFILE_PANELS = 2

const EMPTY_PROFILE = {
  full_name: '',
  email: '',
  contact_number: '',
  linkedin_url: '',
  github_url: '',
  portfolio_url: '',
  current_employer: '',
  years_of_experience: '',
  address_line_1: '',
  address_line_2: '',
  state: '',
  country: '',
  country_code: '',
  location: '',
  location_ref: '',
  preferred_location_refs: [],
  summary: '',
}

const EMPTY_PROFILE_PANEL = {
  title: '',
  ...EMPTY_PROFILE,
}

const EMPTY_ACH = {
  name: '',
  category: 'general',
  paragraph: '',
}

const TEMPLATE_CATEGORY_OPTIONS = [
  { value: '', label: 'All Categories' },
  { value: 'personalized', label: 'Personalized' },
  { value: 'opening', label: 'Opening' },
  { value: 'experience', label: 'Experience' },
  { value: 'closing', label: 'Closing' },
  { value: 'general', label: 'General' },
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

const EMPTY_INTERVIEW = {
  job: '',
  location_ref: '',
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

function profilePanelTitle(panel, index) {
  const explicitTitle = String(panel?.title || '').trim()
  if (explicitTitle) return explicitTitle
  const fullName = String(panel?.full_name || '').trim()
  if (fullName) return fullName
  return `Profile Panel ${index + 1}`
}

function normalizeProfileLike(data, fallbackFullName = '') {
  const nextValue = { ...EMPTY_PROFILE, ...(data || {}) }
  nextValue.location_ref = nextValue.location_ref ? String(nextValue.location_ref) : ''
  nextValue.preferred_location_refs = Array.isArray(nextValue.preferred_location_refs)
    ? nextValue.preferred_location_refs.map((value) => String(value))
    : []
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
  const [profilePanels, setProfilePanels] = useState([])
  const [showProfilePanelForm, setShowProfilePanelForm] = useState(false)
  const [editingProfilePanelId, setEditingProfilePanelId] = useState(null)
  const [profilePanelForm, setProfilePanelForm] = useState(EMPTY_PROFILE_PANEL)
  const [workspaceMembers, setWorkspaceMembers] = useState([])
  const [workspaceMemberUsername, setWorkspaceMemberUsername] = useState('')

  const [resumes, setResumes] = useState([])
  const [previewResume, setPreviewResume] = useState(null)

  const [achievements, setAchievements] = useState([])
  const [templateCategoryFilter, setTemplateCategoryFilter] = useState('')
  const [showAchForm, setShowAchForm] = useState(false)
  const [editingAchId, setEditingAchId] = useState(null)
  const [achForm, setAchForm] = useState(EMPTY_ACH)

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

  const interviewLocationName = useMemo(() => {
    if (!interviewForm.location_ref) return ''
    const match = (Array.isArray(locationOptions) ? locationOptions : []).find(
      (location) => String(location?.id) === String(interviewForm.location_ref),
    )
    return String(match?.name || '').trim()
  }, [interviewForm.location_ref, locationOptions])

  const filteredAchievements = useMemo(() => {
    const selectedCategory = String(templateCategoryFilter || '').trim().toLowerCase()
    if (!selectedCategory) return Array.isArray(achievements) ? achievements : []
    return (Array.isArray(achievements) ? achievements : []).filter(
      (row) => String(row?.category || '').trim().toLowerCase() === selectedCategory,
    )
  }, [achievements, templateCategoryFilter])

  const loadAll = async () => {
    setLoading(true)
    setError('')
    try {
      const [profileBase, info, panelRows, memberRows, resumeRows, achRows, interviewRows, jobsData, locationRows] = await Promise.all([
        fetchProfile(access),
        fetchProfileInfo(access),
        fetchProfilePanels(access).catch(() => []),
        fetchWorkspaceMembers(access).catch(() => []),
        fetchResumes(access),
        fetchTemplates(access),
        fetchInterviews(access),
        fetchJobs(access, { page: 1, page_size: 500 }),
        fetchLocations(access),
      ])
      const nextProfile = normalizeProfileLike(info, String(profileBase?.username || ''))
      setProfile(nextProfile)
      setProfileForm(nextProfile)
      setProfileUsername(String(profileBase?.username || ''))
      setProfilePanels(
        (Array.isArray(panelRows) ? panelRows : []).map((row) => ({
          ...normalizeProfileLike(row),
          id: row.id,
          title: String(row?.title || '').trim(),
          created_at: row?.created_at || '',
          updated_at: row?.updated_at || '',
          location_name: String(row?.location_name || '').trim(),
          preferred_location_names: Array.isArray(row?.preferred_location_names) ? row.preferred_location_names : [],
        })),
      )
      setWorkspaceMembers(Array.isArray(memberRows) ? memberRows : [])
      setResumes(Array.isArray(resumeRows) ? resumeRows : [])
      setAchievements(Array.isArray(achRows) ? achRows : [])
      setInterviews(Array.isArray(interviewRows) ? interviewRows : [])
      setJobOptions(Array.isArray(jobsData?.results) ? jobsData.results : [])
      setLocationOptions(Array.isArray(locationRows) ? locationRows : [])
    } catch (err) {
      setError(err.message || 'Could not load profile data.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!access) return
    loadAll()
  }, [access])

  const saveProfile = async () => {
    try {
      setError('')
      setOk('')
      const payload = { ...profileForm }
      const updated = await updateProfileInfo(access, payload)
      setProfile({ ...EMPTY_PROFILE, ...(updated || {}) })
      setProfileForm({ ...EMPTY_PROFILE, ...(updated || {}) })
      setEditingProfile(false)
      setOk('Personal info updated.')
    } catch (err) {
      setError(err.message || 'Could not save personal info.')
    }
  }

  const openCreateProfilePanel = () => {
    setError('')
    setOk('')
    setEditingProfilePanelId(null)
    setProfilePanelForm({
      ...EMPTY_PROFILE_PANEL,
      title: `Profile Panel ${profilePanels.length + 1}`,
      full_name: profile.full_name || profileUsername || '',
      email: profile.email || '',
    })
    setShowProfilePanelForm(true)
  }

  const openEditProfilePanel = (row) => {
    setError('')
    setOk('')
    setEditingProfilePanelId(row.id)
    setProfilePanelForm({
      title: String(row?.title || '').trim(),
      ...normalizeProfileLike(row),
    })
    setShowProfilePanelForm(true)
  }

  const saveProfilePanel = async () => {
    try {
      setError('')
      setOk('')
      const payload = {
        ...profilePanelForm,
        title: String(profilePanelForm.title || '').trim(),
      }
      const updated = editingProfilePanelId
        ? await updateProfilePanel(access, editingProfilePanelId, payload)
        : await createProfilePanel(access, payload)
      const normalized = {
        ...normalizeProfileLike(updated),
        id: updated.id,
        title: String(updated?.title || '').trim(),
        created_at: updated?.created_at || '',
        updated_at: updated?.updated_at || '',
        location_name: String(updated?.location_name || '').trim(),
        preferred_location_names: Array.isArray(updated?.preferred_location_names) ? updated.preferred_location_names : [],
      }
      if (editingProfilePanelId) {
        setProfilePanels((prev) => prev.map((row) => (row.id === editingProfilePanelId ? normalized : row)))
        setOk('Profile panel updated.')
      } else {
        setProfilePanels((prev) => [normalized, ...prev].slice(0, MAX_PROFILE_PANELS))
        setOk('Profile panel added.')
      }
      setProfilePanelForm(EMPTY_PROFILE_PANEL)
      setEditingProfilePanelId(null)
      setShowProfilePanelForm(false)
    } catch (err) {
      setError(err.message || 'Could not save profile panel.')
    }
  }

  const removeProfilePanel = async (panelId) => {
    try {
      setError('')
      setOk('')
      await deleteProfilePanel(access, panelId)
      setProfilePanels((prev) => prev.filter((row) => row.id !== panelId))
      if (editingProfilePanelId === panelId) {
        setEditingProfilePanelId(null)
        setProfilePanelForm(EMPTY_PROFILE_PANEL)
        setShowProfilePanelForm(false)
      }
      setOk('Profile panel deleted.')
    } catch (err) {
      setError(err.message || 'Could not delete profile panel.')
    }
  }

  const saveWorkspaceMember = async () => {
    try {
      setError('')
      setOk('')
      const username = String(workspaceMemberUsername || '').trim()
      if (!username) {
        setError('Enter second account username.')
        return
      }
      const created = await createWorkspaceMember(access, { username })
      setWorkspaceMembers((prev) => [created])
      setWorkspaceMemberUsername('')
      setOk('Second account linked.')
    } catch (err) {
      setError(err.message || 'Could not link second account.')
    }
  }

  const removeWorkspaceMember = async (memberId) => {
    try {
      setError('')
      setOk('')
      await deleteWorkspaceMember(access, memberId)
      setWorkspaceMembers([])
      setOk('Second account removed.')
    } catch (err) {
      setError(err.message || 'Could not remove second account.')
    }
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
    sessionStorage.setItem('builderResumeId', String(resumeId))
    navigate('/builder')
  }

  const openCreateResumeInBuilder = () => {
    sessionStorage.setItem('builderSaveMode', 'create')
    sessionStorage.removeItem('builderResumeId')
    navigate('/builder')
  }

  const saveAchievement = async () => {
    try {
      setError('')
      setOk('')
      const payload = {
        name: String(achForm.name || '').trim(),
        category: String(achForm.category || 'general').trim() || 'general',
        paragraph: String(achForm.paragraph || '').trim(),
      }
      if (!payload.name || !payload.paragraph) {
        setError('Template needs name and paragraph text.')
        return
      }
      if (editingAchId) {
        const updated = await updateTemplate(access, editingAchId, payload)
        setAchievements((prev) => prev.map((row) => (row.id === editingAchId ? updated : row)))
        setOk('Template updated.')
      } else {
        const created = await createTemplate(access, payload)
        setAchievements((prev) => [created, ...prev])
        setOk('Template added.')
      }
      setAchForm(EMPTY_ACH)
      setEditingAchId(null)
      setShowAchForm(false)
    } catch (err) {
      setError(err.message || 'Could not save template.')
    }
  }

  const editAchievement = (row) => {
    setEditingAchId(row.id)
    setAchForm({
      name: row.name || '',
      category: row.category || 'general',
      paragraph: row.paragraph || '',
    })
    setShowAchForm(true)
  }

  const removeAchievement = async (id) => {
    try {
      await deleteTemplate(access, id)
      setAchievements((prev) => prev.filter((row) => row.id !== id))
    } catch (err) {
      setError(err.message || 'Could not delete template.')
    }
  }

  const saveInterview = async () => {
    try {
      setError('')
      setOk('')
      const payload = {
        job: interviewForm.job || null,
        location_ref: interviewForm.location_ref || null,
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
      setInterviewForm(EMPTY_INTERVIEW)
      setEditingInterviewId(null)
      setShowInterviewForm(false)
    } catch (err) {
      setError(err.message || 'Could not save interview.')
    }
  }

  const editInterview = (row) => {
    setEditingInterviewId(row.id)
    setInterviewForm({
      job: row.job ? String(row.job) : '',
      location_ref: row.location_ref ? String(row.location_ref) : '',
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
          <p className="subtitle">Personal info, templates, resumes, and interview milestones.</p>
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
            {!editingProfile ? (
              <button type="button" className="secondary" onClick={() => setEditingProfile(true)}>Edit Info</button>
            ) : null}
          </div>
        </div>
        {!editingProfile ? (
          <div className="profile-info-grid">
            {profileRows(profile).map(([label, value]) => (
              <div key={label} className="profile-info-item">
                <span className="profile-info-label">{label}</span>
                <span className="profile-info-value">{String(value)}</span>
              </div>
            ))}
            {!profileRows(profile).length ? (
              <div className="profile-info-item">
                <span className="profile-info-label">Full Name</span>
                <span className="profile-info-value">{profileUsername || '-'}</span>
              </div>
            ) : null}
          </div>
        ) : (
          <>
            <div className="profile-form-grid">
              <label>Full Name<input value={profileForm.full_name} onChange={(e) => setProfileForm((p) => ({ ...p, full_name: e.target.value }))} /></label>
              <label>Email<input value={profileForm.email} onChange={(e) => setProfileForm((p) => ({ ...p, email: e.target.value }))} /></label>
              <label>Contact Number<input value={profileForm.contact_number} onChange={(e) => setProfileForm((p) => ({ ...p, contact_number: e.target.value }))} /></label>
              <label>Address Line 1<input value={profileForm.address_line_1} onChange={(e) => setProfileForm((p) => ({ ...p, address_line_1: e.target.value }))} /></label>
              <label>Address Line 2<input value={profileForm.address_line_2} onChange={(e) => setProfileForm((p) => ({ ...p, address_line_2: e.target.value }))} /></label>
              <label>State<input value={profileForm.state} onChange={(e) => setProfileForm((p) => ({ ...p, state: e.target.value }))} /></label>
              <label>Country<input value={profileForm.country} onChange={(e) => setProfileForm((p) => ({ ...p, country: e.target.value }))} /></label>
              <label>Country Code<input value={profileForm.country_code} onChange={(e) => setProfileForm((p) => ({ ...p, country_code: e.target.value }))} placeholder="+91" /></label>
              <label>Location<input value={profileForm.location} onChange={(e) => setProfileForm((p) => ({ ...p, location: e.target.value }))} /></label>
              <label>Location Ref
                <SingleSelectDropdown
                  value={profileForm.location_ref || ''}
                  placeholder="Select location"
                  options={locationOptions.map((location) => ({ value: String(location.id), label: String(location.name || '') }))}
                  onChange={(nextValue) => {
                    const selected = locationOptions.find((item) => String(item.id) === String(nextValue || ''))
                    setProfileForm((p) => ({
                      ...p,
                      location_ref: nextValue || '',
                      location: selected?.name || p.location,
                    }))
                  }}
                />
              </label>
              <label className="md:col-span-2">Preferred Locations
                <MultiSelectDropdown
                  values={Array.isArray(profileForm.preferred_location_refs) ? profileForm.preferred_location_refs : []}
                  placeholder="Select preferred locations"
                  searchPlaceholder="Search location"
                  options={locationOptions.map((location) => ({ value: String(location.id), label: String(location.name || '') }))}
                  onChange={(nextValues) => setProfileForm((p) => ({
                    ...p,
                    preferred_location_refs: Array.isArray(nextValues) ? nextValues : [],
                  }))}
                />
              </label>
              <label>Current Employer<input value={profileForm.current_employer} onChange={(e) => setProfileForm((p) => ({ ...p, current_employer: e.target.value }))} /></label>
              <label>Years of Experience<input value={profileForm.years_of_experience} onChange={(e) => setProfileForm((p) => ({ ...p, years_of_experience: e.target.value }))} /></label>
              <label>LinkedIn URL<input value={profileForm.linkedin_url} onChange={(e) => setProfileForm((p) => ({ ...p, linkedin_url: e.target.value }))} /></label>
              <label>GitHub URL<input value={profileForm.github_url} onChange={(e) => setProfileForm((p) => ({ ...p, github_url: e.target.value }))} /></label>
              <label>Portfolio URL<input value={profileForm.portfolio_url} onChange={(e) => setProfileForm((p) => ({ ...p, portfolio_url: e.target.value }))} /></label>
              <label>Summary<textarea rows={3} value={profileForm.summary} onChange={(e) => setProfileForm((p) => ({ ...p, summary: e.target.value }))} /></label>
            </div>
            <div className="actions">
              <button type="button" onClick={saveProfile}>Save</button>
              <button type="button" className="secondary" onClick={() => { setProfileForm(profile); setEditingProfile(false) }}>Cancel</button>
            </div>
          </>
        )}
      </section>

      <section className="dash-card">
        <div className="tracking-head profile-section-head">
          <h2>Profile Panels</h2>
          <div className="actions">
            <button
              type="button"
              className="secondary"
              onClick={openCreateProfilePanel}
              disabled={profilePanels.length >= MAX_PROFILE_PANELS}
            >
              Add Panel
            </button>
          </div>
        </div>
        <p className="hint">Keep one owner profile and one additional profile. Max {MAX_PROFILE_PANELS} panels.</p>
        {showProfilePanelForm ? (
          <>
            <div className="profile-form-grid">
              <label>Panel Name<input value={profilePanelForm.title} onChange={(e) => setProfilePanelForm((p) => ({ ...p, title: e.target.value }))} placeholder="Backend Panel, Recruiter Panel..." /></label>
              <label>Full Name<input value={profilePanelForm.full_name} onChange={(e) => setProfilePanelForm((p) => ({ ...p, full_name: e.target.value }))} /></label>
              <label>Email<input value={profilePanelForm.email} onChange={(e) => setProfilePanelForm((p) => ({ ...p, email: e.target.value }))} /></label>
              <label>Contact Number<input value={profilePanelForm.contact_number} onChange={(e) => setProfilePanelForm((p) => ({ ...p, contact_number: e.target.value }))} /></label>
              <label>Current Employer<input value={profilePanelForm.current_employer} onChange={(e) => setProfilePanelForm((p) => ({ ...p, current_employer: e.target.value }))} /></label>
              <label>Years of Experience<input value={profilePanelForm.years_of_experience} onChange={(e) => setProfilePanelForm((p) => ({ ...p, years_of_experience: e.target.value }))} /></label>
              <label>LinkedIn URL<input value={profilePanelForm.linkedin_url} onChange={(e) => setProfilePanelForm((p) => ({ ...p, linkedin_url: e.target.value }))} /></label>
              <label>GitHub URL<input value={profilePanelForm.github_url} onChange={(e) => setProfilePanelForm((p) => ({ ...p, github_url: e.target.value }))} /></label>
              <label>Portfolio URL<input value={profilePanelForm.portfolio_url} onChange={(e) => setProfilePanelForm((p) => ({ ...p, portfolio_url: e.target.value }))} /></label>
              <label>Location<input value={profilePanelForm.location} onChange={(e) => setProfilePanelForm((p) => ({ ...p, location: e.target.value }))} /></label>
              <label>Location Ref
                <SingleSelectDropdown
                  value={profilePanelForm.location_ref || ''}
                  placeholder="Select location"
                  options={locationOptions.map((location) => ({ value: String(location.id), label: String(location.name || '') }))}
                  onChange={(nextValue) => {
                    const selected = locationOptions.find((item) => String(item.id) === String(nextValue || ''))
                    setProfilePanelForm((p) => ({
                      ...p,
                      location_ref: nextValue || '',
                      location: selected?.name || p.location,
                    }))
                  }}
                />
              </label>
              <label className="md:col-span-2">Preferred Locations
                <MultiSelectDropdown
                  values={Array.isArray(profilePanelForm.preferred_location_refs) ? profilePanelForm.preferred_location_refs : []}
                  placeholder="Select preferred locations"
                  searchPlaceholder="Search location"
                  options={locationOptions.map((location) => ({ value: String(location.id), label: String(location.name || '') }))}
                  onChange={(nextValues) => setProfilePanelForm((p) => ({
                    ...p,
                    preferred_location_refs: Array.isArray(nextValues) ? nextValues : [],
                  }))}
                />
              </label>
              <label className="md:col-span-2">Summary<textarea rows={3} value={profilePanelForm.summary} onChange={(e) => setProfilePanelForm((p) => ({ ...p, summary: e.target.value }))} /></label>
            </div>
            <div className="actions">
              <button type="button" onClick={saveProfilePanel}>{editingProfilePanelId ? 'Update' : 'Create'}</button>
              <button type="button" className="secondary" onClick={() => { setShowProfilePanelForm(false); setEditingProfilePanelId(null); setProfilePanelForm(EMPTY_PROFILE_PANEL) }}>Cancel</button>
            </div>
          </>
        ) : null}
        <div className="profile-panel-grid">
          {profilePanels.map((row, index) => (
            <article key={row.id} className="profile-card-shell profile-panel-card">
              <div className="profile-panel-head">
                <div>
                  <p className="profile-panel-title">{profilePanelTitle(row, index)}</p>
                  {row.updated_at ? <p className="profile-panel-meta">Updated: {new Date(row.updated_at).toLocaleString()}</p> : null}
                </div>
                <div className="actions">
                  <button type="button" className="secondary" onClick={() => openEditProfilePanel(row)}>Edit</button>
                  <button type="button" className="secondary" onClick={() => removeProfilePanel(row.id)}>Delete</button>
                </div>
              </div>
              <div className="profile-info-grid">
                {profileRows(row).map(([label, value]) => (
                  <div key={`${row.id}-${label}`} className="profile-info-item">
                    <span className="profile-info-label">{label}</span>
                    <span className="profile-info-value">{String(value)}</span>
                  </div>
                ))}
                {!profileRows(row).length ? (
                  <div className="profile-info-item">
                    <span className="profile-info-label">Panel</span>
                    <span className="profile-info-value">No data yet.</span>
                  </div>
                ) : null}
              </div>
            </article>
          ))}
          {!profilePanels.length ? <p className="hint">No extra profile panels yet.</p> : null}
        </div>
      </section>

      <section className="dash-card">
        <div className="tracking-head profile-section-head">
          <h2>Workspace Access</h2>
        </div>
        <p className="hint">Owner keeps full access. Second account can create companies, jobs, and employees with its own login.</p>
        <div className="profile-form-grid">
          <label>
            Second Account Username
            <input
              value={workspaceMemberUsername}
              onChange={(e) => setWorkspaceMemberUsername(e.target.value)}
              placeholder="Enter username"
              disabled={workspaceMembers.length >= 1}
            />
          </label>
        </div>
        <div className="actions">
          <button type="button" onClick={saveWorkspaceMember} disabled={workspaceMembers.length >= 1}>Link Account</button>
        </div>
        <div className="profile-panel-grid">
          {workspaceMembers.map((row) => (
            <article key={row.id} className="profile-card-shell profile-panel-card">
              <div className="profile-panel-head">
                <div>
                  <p className="profile-panel-title">{row.member_username || '-'}</p>
                  <p className="profile-panel-meta">{row.member_email || 'No email'}</p>
                </div>
                <div className="actions">
                  <button type="button" className="secondary" onClick={() => removeWorkspaceMember(row.id)}>Remove</button>
                </div>
              </div>
              <div className="profile-info-grid">
                <div className="profile-info-item">
                  <span className="profile-info-label">Access</span>
                  <span className="profile-info-value">Create companies, jobs, and employees, and view owner companies/jobs/employees</span>
                </div>
                <div className="profile-info-item">
                  <span className="profile-info-label">Login</span>
                  <span className="profile-info-value">Independent login works on different tabs and devices.</span>
                </div>
              </div>
            </article>
          ))}
          {!workspaceMembers.length ? <p className="hint">No second account linked yet.</p> : null}
        </div>
      </section>

      <section className="dash-card">
        <div className="tracking-head profile-section-head">
          <h2>Templates</h2>
          <div className="actions profile-template-head-actions">
            <div className="profile-template-filter">
              <SingleSelectDropdown
                value={templateCategoryFilter}
                placeholder="Category"
                searchPlaceholder="Search category"
                clearLabel="All Categories"
                options={TEMPLATE_CATEGORY_OPTIONS}
                onChange={(nextValue) => setTemplateCategoryFilter(nextValue || '')}
              />
            </div>
            <button type="button" className="secondary" onClick={() => { setShowAchForm((v) => !v); setEditingAchId(null); setAchForm(EMPTY_ACH) }}>{showAchForm ? 'Close Form' : 'Add Template'}</button>
          </div>
        </div>
        {showAchForm ? (
          <>
            <div className="profile-form-grid">
              <label>Name<input value={achForm.name} onChange={(e) => setAchForm((p) => ({ ...p, name: e.target.value }))} /></label>
              <label>Category<select value={achForm.category || 'general'} onChange={(e) => setAchForm((p) => ({ ...p, category: e.target.value }))}><option value="personalized">Personalized</option><option value="opening">Opening</option><option value="experience">Experience</option><option value="closing">Closing</option><option value="general">General</option></select></label>
              <label className="md:col-span-2">Paragraph<textarea rows={4} value={achForm.paragraph} onChange={(e) => setAchForm((p) => ({ ...p, paragraph: e.target.value }))} /></label>
            </div>
            <div className="actions">
              <button type="button" onClick={saveAchievement}>{editingAchId ? 'Update' : 'Create'}</button>
              <button type="button" className="secondary" onClick={() => { setShowAchForm(false); setEditingAchId(null); setAchForm(EMPTY_ACH) }}>Cancel</button>
            </div>
          </>
        ) : null}
        <div className="profile-ach-grid">
          {filteredAchievements.map((row) => (
            <article key={row.id} className="profile-template-row">
              <div className="profile-template-main">
                <p className="profile-template-title"><strong>{row.name || '-'}</strong></p>
                <p className="hint">{String(row.category || 'general').replaceAll('_', ' ')}</p>
                <p className="profile-template-snippet">{row.paragraph || '-'}</p>
              </div>
              <div className="profile-template-actions">
                <button type="button" className="secondary" onClick={() => editAchievement(row)}>Edit</button>
                <button type="button" className="secondary" onClick={() => removeAchievement(row.id)}>Delete</button>
              </div>
            </article>
          ))}
          {!achievements.length ? <p className="hint">No templates yet.</p> : null}
          {achievements.length && !filteredAchievements.length ? <p className="hint">No templates in this category.</p> : null}
        </div>
      </section>

      <section className="dash-card">
        <div className="tracking-head profile-section-head">
          <h2>Interview Section</h2>
          <div className="actions">
            <button type="button" className="secondary" onClick={() => { setShowInterviewForm((v) => !v); setEditingInterviewId(null); setInterviewForm(EMPTY_INTERVIEW) }}>{showInterviewForm ? 'Close Form' : 'Add Interview'}</button>
          </div>
        </div>
        {showInterviewForm ? (
          <>
            <div className="profile-form-grid">
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
              {interviewLocationName ? <div className="hint profile-form-note">Location: {interviewLocationName}</div> : null}
              <label>Interview At<input type="datetime-local" value={interviewForm.interview_at} onChange={(e) => setInterviewForm((p) => ({ ...p, interview_at: e.target.value }))} /></label>
              <label className="md:col-span-2">Notes<textarea rows={3} value={interviewForm.notes} onChange={(e) => setInterviewForm((p) => ({ ...p, notes: e.target.value }))} /></label>
            </div>
            <div className="actions">
              <button type="button" onClick={saveInterview}>{editingInterviewId ? 'Update' : 'Create'}</button>
              <button type="button" className="secondary" onClick={() => { setShowInterviewForm(false); setEditingInterviewId(null); setInterviewForm(EMPTY_INTERVIEW) }}>Cancel</button>
            </div>
          </>
        ) : null}

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
                <div className="profile-form-grid profile-form-grid-tight">
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
                <div className="profile-form-grid profile-form-grid-tight">
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
                {row.notes ? <p>{row.notes}</p> : null}
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

      {error ? <p className="error">{error}</p> : null}
      {ok ? <p className="success">{ok}</p> : null}
    </main>
  )
}

export default ProfilePage
