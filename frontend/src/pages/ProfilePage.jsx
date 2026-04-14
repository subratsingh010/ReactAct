import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ResumeSheet from '../components/ResumeSheet'

import {
  createAchievement,
  createInterview,
  deleteAchievement,
  deleteInterview,
  deleteResume,
  fetchAchievements,
  fetchInterviews,
  fetchJobs,
  fetchLocations,
  fetchProfile,
  fetchProfileInfo,
  fetchResumes,
  updateAchievement,
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
  current_employer: '',
  years_of_experience: '',
  location: '',
  summary: '',
}

const EMPTY_ACH = {
  name: '',
  achievement: '',
  skills: '',
}

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
    ['Location', profile.location],
    ['Summary', profile.summary],
  ]
  return rows.filter(([, value]) => String(value || '').trim())
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

function stageTypeFromValue(stage) {
  return roundValue(stage) > 0 ? 'round' : 'other'
}

function otherStageValue(stage) {
  return String(stage || '').toLowerCase() === 'assignment' ? 'assignment' : 'received_call'
}

function isRoundSelectionDisabled(targetRound, rememberedRound, currentSelectedRound) {
  const safeRemembered = Math.max(Number(rememberedRound || 0), 0)
  const selected = Math.max(Number(currentSelectedRound || 0), 0)
  const nextAllowed = Math.min(safeRemembered + 1, 8)
  if (selected > 0 && targetRound === selected) return false
  return targetRound !== nextAllowed
}

function pickNextRound(rememberedRound, currentSelectedRound) {
  const remembered = Math.max(Number(rememberedRound || 0), 0)
  if (currentSelectedRound > remembered && currentSelectedRound <= 8) return currentSelectedRound
  return Math.min(remembered + 1, 8)
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

function AddIcon() {
  return <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M11 4h2v7h7v2h-7v7h-2v-7H4v-2h7z" /></svg>
}
function EditIcon() {
  return <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25Zm18-11.5a1 1 0 0 0 0-1.41l-1.34-1.34a1 1 0 0 0-1.41 0l-1.13 1.13l2.75 2.75L21 5.75Z" /></svg>
}
function DeleteIcon() {
  return <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M9 3h6l1 2h4v2H4V5h4l1-2Zm1 6h2v9h-2V9Zm4 0h2v9h-2V9ZM7 9h2v9H7V9Zm-1 12h12a1 1 0 0 0 1-1V8H5v12a1 1 0 0 0 1 1Z" /></svg>
}
function PreviewIcon() {
  return <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 5c5.5 0 9.6 5.2 10.8 6.9c.3.4.3.9 0 1.3C21.6 14.8 17.5 20 12 20S2.4 14.8 1.2 13.1a1 1 0 0 1 0-1.3C2.4 10.2 6.5 5 12 5Zm0 3.5A4.5 4.5 0 1 0 12 17a4.5 4.5 0 0 0 0-9Zm0 2a2.5 2.5 0 1 1 0 5a2.5 2.5 0 0 1 0-5Z" /></svg>
}
function SaveIcon() {
  return <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4Zm-5 16a3 3 0 1 1 0-6a3 3 0 0 1 0 6Zm3-10H5V5h10v4Z" /></svg>
}
function CloseIcon() {
  return <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="m18.3 5.71l-1.41-1.42L12 9.17L7.11 4.29L5.7 5.71L10.59 10.6L5.7 15.5l1.41 1.41L12 12l4.89 4.91l1.41-1.41l-4.89-4.9z" /></svg>
}
function BuilderIcon() {
  return <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M22.7 19l-9.1-9.1c.9-2.3.4-5-1.5-6.9A5.7 5.7 0 0 0 4 3.1L7.4 6.5L5.9 8L2.5 4.6a5.7 5.7 0 0 0-.1 8.1c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1a1.2 1.2 0 0 0 1.7 0l2.6-2.6a1.2 1.2 0 0 0 0-1.7Z" /></svg>
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

  const [achievements, setAchievements] = useState([])
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
  const [rowStageTypeDraft, setRowStageTypeDraft] = useState({})
  const [rowStageValueDraft, setRowStageValueDraft] = useState({})

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [ok, setOk] = useState('')

  const loadAll = async () => {
    setLoading(true)
    setError('')
    try {
      const [profileBase, info, resumeRows, achRows, interviewRows, jobsData, locationRows] = await Promise.all([
        fetchProfile(access),
        fetchProfileInfo(access),
        fetchResumes(access),
        fetchAchievements(access),
        fetchInterviews(access),
        fetchJobs(access, { page: 1, page_size: 500 }),
        fetchLocations(access),
      ])
      const nextProfile = { ...EMPTY_PROFILE, ...(info || {}) }
      if (!String(nextProfile.full_name || '').trim()) {
        nextProfile.full_name = String(profileBase?.username || '')
      }
      setProfile(nextProfile)
      setProfileForm(nextProfile)
      setProfileUsername(String(profileBase?.username || ''))
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
    sessionStorage.setItem('builderResumeId', String(resumeId))
    navigate('/builder')
  }

  const saveAchievement = async () => {
    try {
      setError('')
      setOk('')
      const payload = {
        name: String(achForm.name || '').trim(),
        achievement: String(achForm.achievement || '').trim(),
        skills: String(achForm.skills || '').trim(),
      }
      if (!payload.name || !payload.achievement) {
        setError('Achievement needs name and achievement text.')
        return
      }
      if (editingAchId) {
        const updated = await updateAchievement(access, editingAchId, payload)
        setAchievements((prev) => prev.map((row) => (row.id === editingAchId ? updated : row)))
        setOk('Achievement updated.')
      } else {
        const created = await createAchievement(access, payload)
        setAchievements((prev) => [created, ...prev])
        setOk('Achievement added.')
      }
      setAchForm(EMPTY_ACH)
      setEditingAchId(null)
      setShowAchForm(false)
    } catch (err) {
      setError(err.message || 'Could not save achievement.')
    }
  }

  const editAchievement = (row) => {
    setEditingAchId(row.id)
    setAchForm({
      name: row.name || '',
      achievement: row.achievement || '',
      skills: row.skills || '',
    })
    setShowAchForm(true)
  }

  const removeAchievement = async (id) => {
    try {
      await deleteAchievement(access, id)
      setAchievements((prev) => prev.filter((row) => row.id !== id))
    } catch (err) {
      setError(err.message || 'Could not delete achievement.')
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

  const formRememberedRound = Number(interviewForm.max_round_reached || 0)
  const formNextRound = Math.min(Math.max(formRememberedRound + 1, 1), 8)
  const formRoundSelectValue = roundValue(interviewForm.stage) > formRememberedRound
    ? interviewForm.stage
    : `round_${formNextRound}`

  return (
    <main className="page page-wide mx-auto w-full">
      <div className="tracking-head">
        <div>
          <h1>Profile</h1>
          <p className="subtitle">Personal info, achievements, resumes, and interview milestones.</p>
        </div>
        <div className="actions">
          <button type="button" className="secondary tracking-icon-btn" title="Resume Builder" aria-label="Resume Builder" onClick={() => navigate('/builder')}><BuilderIcon /></button>
        </div>
      </div>

      {loading ? <p className="hint">Loading profile...</p> : null}

      <section className="dash-card">
        <div className="tracking-head">
          <h2>Resumes</h2>
          <div className="actions">
            <button type="button" className="secondary tracking-icon-btn" title="Add Resume" aria-label="Add Resume" onClick={() => navigate('/builder')}><AddIcon /></button>
          </div>
        </div>
        <div className="profile-resume-grid">
          {resumes.map((row) => (
            <article key={row.id} className="rounded-xl border border-slate-200 p-4">
              <p><strong>{row.title || `Resume #${row.id}`}</strong></p>
              {skillsPreviewFromResume(row) ? <p className="hint">Skills: {skillsPreviewFromResume(row)}</p> : null}
              <p className="hint">Updated: {row.updated_at ? new Date(row.updated_at).toLocaleString() : '-'}</p>
              <div className="actions">
                <button type="button" className="secondary tracking-icon-btn" title="Preview" aria-label="Preview" onClick={() => setPreviewResume(row)}><PreviewIcon /></button>
                <button type="button" className="secondary tracking-icon-btn" title="Edit" aria-label="Edit" onClick={() => openResumeInBuilder(row.id)}><EditIcon /></button>
                <button type="button" className="secondary tracking-icon-btn" title="Delete" aria-label="Delete" onClick={() => removeResume(row.id)}><DeleteIcon /></button>
              </div>
            </article>
          ))}
          {!resumes.length ? <p className="hint">No resumes yet.</p> : null}
        </div>
      </section>

      <section className="dash-card">
        <div className="tracking-head">
          <h2>Personal Info</h2>
          <div className="actions">
            {!editingProfile ? (
              <button type="button" className="secondary tracking-icon-btn" title="Edit" aria-label="Edit" onClick={() => setEditingProfile(true)}><EditIcon /></button>
            ) : null}
          </div>
        </div>
        {!editingProfile ? (
          <div className="grid gap-3 md:grid-cols-2">
            {profileRows(profile).map(([label, value]) => (
              <p key={label}><strong>{label}:</strong> {String(value)}</p>
            ))}
            {!profileRows(profile).length ? <p><strong>Full Name:</strong> {profileUsername || '-'}</p> : null}
          </div>
        ) : (
          <>
            <div className="grid gap-3 md:grid-cols-2">
              <label>Full Name<input value={profileForm.full_name} onChange={(e) => setProfileForm((p) => ({ ...p, full_name: e.target.value }))} /></label>
              <label>Email<input value={profileForm.email} onChange={(e) => setProfileForm((p) => ({ ...p, email: e.target.value }))} /></label>
              <label>Contact Number<input value={profileForm.contact_number} onChange={(e) => setProfileForm((p) => ({ ...p, contact_number: e.target.value }))} /></label>
              <label>Location<input value={profileForm.location} onChange={(e) => setProfileForm((p) => ({ ...p, location: e.target.value }))} /></label>
              <label>Current Employer<input value={profileForm.current_employer} onChange={(e) => setProfileForm((p) => ({ ...p, current_employer: e.target.value }))} /></label>
              <label>Years of Experience<input value={profileForm.years_of_experience} onChange={(e) => setProfileForm((p) => ({ ...p, years_of_experience: e.target.value }))} /></label>
              <label>LinkedIn URL<input value={profileForm.linkedin_url} onChange={(e) => setProfileForm((p) => ({ ...p, linkedin_url: e.target.value }))} /></label>
              <label>GitHub URL<input value={profileForm.github_url} onChange={(e) => setProfileForm((p) => ({ ...p, github_url: e.target.value }))} /></label>
              <label>Portfolio URL<input value={profileForm.portfolio_url} onChange={(e) => setProfileForm((p) => ({ ...p, portfolio_url: e.target.value }))} /></label>
              <label>Summary<textarea rows={3} value={profileForm.summary} onChange={(e) => setProfileForm((p) => ({ ...p, summary: e.target.value }))} /></label>
            </div>
            <div className="actions">
              <button type="button" className="tracking-icon-btn" title="Save" aria-label="Save" onClick={saveProfile}><SaveIcon /></button>
              <button type="button" className="secondary tracking-icon-btn" title="Cancel" aria-label="Cancel" onClick={() => { setProfileForm(profile); setEditingProfile(false) }}><CloseIcon /></button>
            </div>
          </>
        )}
      </section>

      <section className="dash-card">
        <div className="tracking-head">
          <h2>Achievements</h2>
          <div className="actions">
            <button type="button" className="secondary tracking-icon-btn" title="Add Achievement" aria-label="Add Achievement" onClick={() => { setShowAchForm((v) => !v); setEditingAchId(null); setAchForm(EMPTY_ACH) }}><AddIcon /></button>
          </div>
        </div>
        {showAchForm ? (
          <>
            <div className="grid gap-3 md:grid-cols-2">
              <label>Name<input value={achForm.name} onChange={(e) => setAchForm((p) => ({ ...p, name: e.target.value }))} /></label>
              <label>Skills<input value={achForm.skills} onChange={(e) => setAchForm((p) => ({ ...p, skills: e.target.value }))} placeholder="Python, React, AWS" /></label>
              <label className="md:col-span-2">Achievement<textarea rows={3} value={achForm.achievement} onChange={(e) => setAchForm((p) => ({ ...p, achievement: e.target.value }))} /></label>
            </div>
            <div className="actions">
              <button type="button" className="tracking-icon-btn" title={editingAchId ? 'Update' : 'Create'} aria-label={editingAchId ? 'Update' : 'Create'} onClick={saveAchievement}><SaveIcon /></button>
              <button type="button" className="secondary tracking-icon-btn" title="Cancel" aria-label="Cancel" onClick={() => { setShowAchForm(false); setEditingAchId(null); setAchForm(EMPTY_ACH) }}><CloseIcon /></button>
            </div>
          </>
        ) : null}
        <div className="profile-ach-grid">
          {achievements.map((row) => (
            <article key={row.id} className="rounded-xl border border-slate-200 p-4">
              <p><strong>{row.name || '-'}</strong></p>
              <p className="hint">{row.skills || '-'}</p>
              <p>{row.achievement || '-'}</p>
              <div className="actions">
                <button type="button" className="secondary tracking-icon-btn" title="Edit" aria-label="Edit" onClick={() => editAchievement(row)}><EditIcon /></button>
                <button type="button" className="secondary tracking-icon-btn" title="Delete" aria-label="Delete" onClick={() => removeAchievement(row.id)}><DeleteIcon /></button>
              </div>
            </article>
          ))}
          {!achievements.length ? <p className="hint">No achievements yet.</p> : null}
        </div>
      </section>

      <section className="dash-card">
        <div className="tracking-head">
          <h2>Interview Section</h2>
          <div className="actions">
            <button type="button" className="secondary tracking-icon-btn" title="Add Interview" aria-label="Add Interview" onClick={() => { setShowInterviewForm((v) => !v); setEditingInterviewId(null); setInterviewForm(EMPTY_INTERVIEW) }}><AddIcon /></button>
          </div>
        </div>
        {showInterviewForm ? (
          <>
            <div className="grid gap-3 md:grid-cols-2">
              <label>Select Job
                <select
                  value={interviewForm.job}
                  onChange={(e) => {
                    const selectedId = String(e.target.value || '')
                    const selectedJob = jobOptions.find((item) => String(item.id) === selectedId)
                    setInterviewForm((p) => ({
                      ...p,
                      job: selectedId,
                      company_name: selectedJob?.company_name || p.company_name,
                      job_role: selectedJob?.role || p.job_role,
                      job_code: selectedJob?.job_id || p.job_code,
                    }))
                  }}
                >
                  <option value="">Select job</option>
                  {jobOptions.map((job) => (
                    <option key={job.id} value={job.id}>
                      {`${job.job_id || '-'} | ${job.company_name || '-'} | ${job.role || '-'}`}
                    </option>
                  ))}
                </select>
              </label>
              <label>Company<input value={interviewForm.company_name} readOnly /></label>
              <label>Job Role<input value={interviewForm.job_role} readOnly /></label>
              <label>Job ID<input value={interviewForm.job_code} readOnly /></label>
              <label>Location
                <select value={interviewForm.location_ref} onChange={(e) => setInterviewForm((p) => ({ ...p, location_ref: e.target.value }))}>
                  <option value="">Select location</option>
                  {locationOptions.map((location) => (
                    <option key={location.id} value={location.id}>{location.name}</option>
                  ))}
                </select>
              </label>
              <label>Stage Type
                <select
                  value={stageTypeFromValue(interviewForm.stage)}
                  onChange={(e) => {
                    const nextType = e.target.value
                    if (nextType === 'round') {
                      const rememberedRound = Number(interviewForm.max_round_reached || 0)
                      const currentSelectedRound = roundValue(interviewForm.stage)
                      const nextRound = pickNextRound(rememberedRound, currentSelectedRound)
                      setInterviewForm((p) => ({ ...p, stage: `round_${nextRound}` }))
                      return
                    }
                    setInterviewForm((p) => ({ ...p, stage: otherStageValue(p.stage) }))
                  }}
                >
                  <option value="other">Other Stage</option>
                  <option value="round">Round Stage</option>
                </select>
              </label>
              <label>Stage
                {stageTypeFromValue(interviewForm.stage) === 'round' ? (
                  <select value={formRoundSelectValue} onChange={(e) => setInterviewForm((p) => ({ ...p, stage: e.target.value }))}>
                    {Array.from({ length: 8 }, (_, idx) => {
                      const targetRound = idx + 1
                      const currentSelectedRound = roundValue(formRoundSelectValue)
                      const isDisabled = isRoundSelectionDisabled(targetRound, formRememberedRound, currentSelectedRound)
                      return (
                        <option key={`form-round-${targetRound}`} value={`round_${targetRound}`} disabled={isDisabled}>
                          {`Round ${targetRound}`}
                        </option>
                      )
                    })}
                  </select>
                ) : (
                  <select value={otherStageValue(interviewForm.stage)} onChange={(e) => setInterviewForm((p) => ({ ...p, stage: e.target.value }))}>
                    {OTHER_INTERVIEW_STAGES.map((item) => (
                      <option key={item.value} value={item.value}>{item.label}</option>
                    ))}
                  </select>
                )}
              </label>
              <label>Action
                <select value={interviewForm.action} onChange={(e) => setInterviewForm((p) => ({ ...p, action: e.target.value }))}>
                  {INTERVIEW_ACTIONS.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </label>
              <label>Interview At<input type="datetime-local" value={interviewForm.interview_at} onChange={(e) => setInterviewForm((p) => ({ ...p, interview_at: e.target.value }))} /></label>
              <label className="md:col-span-2">Notes<textarea rows={3} value={interviewForm.notes} onChange={(e) => setInterviewForm((p) => ({ ...p, notes: e.target.value }))} /></label>
            </div>
            <div className="actions">
              <button type="button" className="tracking-icon-btn" title={editingInterviewId ? 'Update' : 'Create'} aria-label={editingInterviewId ? 'Update' : 'Create'} onClick={saveInterview}><SaveIcon /></button>
              <button type="button" className="secondary tracking-icon-btn" title="Cancel" aria-label="Cancel" onClick={() => { setShowInterviewForm(false); setEditingInterviewId(null); setInterviewForm(EMPTY_INTERVIEW) }}><CloseIcon /></button>
            </div>
          </>
        ) : null}

        <div className="grid gap-4">
          {interviews.map((row) => {
            const stageTypeDraft = String(rowStageTypeDraft[row.id] || '')
            const effectiveStageType = stageTypeDraft || stageTypeFromValue(row.stage)
            const rememberedRound = Number(row.max_round_reached || 0)
            const nextRound = Math.min(Math.max(rememberedRound + 1, 1), 8)
            const stageValueDraft = typeof rowStageValueDraft[row.id] === 'string' ? rowStageValueDraft[row.id] : ''
            const stageSelectValue = stageValueDraft
            const action = String(row.action || 'active').toLowerCase()
            const isHold = action === 'hold'
            const isFailure = ['rejected', 'no_response', 'no_feedback', 'ghosted', 'skipped'].includes(action)
            const isActive = action === 'active'
            const showFutureDots = isActive || isHold
            const eventSteps = milestoneEventsForRow(row)
            const reachedCount = Math.max(1, Math.min(10, eventSteps.length))
            const totalDots = showFutureDots ? 10 : reachedCount
            const currentDotIndex = reachedCount - 1
            return (
              <article key={row.id} className="rounded-xl border border-slate-200 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p><strong>{row.company_name}</strong> | {row.job_role} | {row.job_code || '-'}</p>
                  <div className="tracking-actions-compact">
                    <button type="button" className="secondary tracking-icon-btn" title="Edit" aria-label="Edit" onClick={() => editInterview(row)}><EditIcon /></button>
                    <button type="button" className="secondary tracking-icon-btn" title="Delete" aria-label="Delete" onClick={() => removeInterview(row.id)}><DeleteIcon /></button>
                  </div>
                </div>
                <div className="grid gap-2 md:grid-cols-2">
                  <label>Stage Type
                    <select
                      value={effectiveStageType}
                      disabled={savingInterviewId === row.id || String(row.action || 'active').toLowerCase() !== 'active'}
                      onChange={(e) => {
                        const nextType = e.target.value
                        setRowStageTypeDraft((prev) => ({ ...prev, [row.id]: nextType }))
                        setRowStageValueDraft((prev) => ({ ...prev, [row.id]: '' }))
                      }}
                    >
                      <option value="other">Other Stage</option>
                      <option value="round">Round Stage</option>
                    </select>
                  </label>
                  <label>Stage
                    <select
                      value={stageSelectValue}
                      disabled={savingInterviewId === row.id || String(row.action || 'active').toLowerCase() !== 'active'}
                      onChange={(e) => {
                        const nextStage = e.target.value
                        if (!nextStage) return
                        setRowStageValueDraft((prev) => ({ ...prev, [row.id]: nextStage }))
                        inlineUpdateInterview(row, { stage: nextStage })
                        setRowStageTypeDraft((prev) => {
                          const next = { ...prev }
                          delete next[row.id]
                          return next
                        })
                        setRowStageValueDraft((prev) => {
                          const next = { ...prev }
                          delete next[row.id]
                          return next
                        })
                      }}
                    >
                      {effectiveStageType === 'round' ? (
                        <>
                          <option value="">Select round</option>
                          {Array.from({ length: 8 }, (_, idx) => {
                            const targetRound = idx + 1
                            const currentSelectedRound = roundValue(stageSelectValue || `round_${nextRound}`)
                            const isDisabled = isRoundSelectionDisabled(targetRound, rememberedRound, currentSelectedRound)
                            return (
                              <option key={`row-${row.id}-round-${targetRound}`} value={`round_${targetRound}`} disabled={isDisabled}>
                                {`Round ${targetRound}`}
                              </option>
                            )
                          })}
                        </>
                      ) : (
                        <>
                          <option value="">Select stage</option>
                          {OTHER_INTERVIEW_STAGES.map((item) => (
                            <option key={`row-${row.id}-${item.value}`} value={item.value}>{item.label}</option>
                          ))}
                        </>
                      )}
                    </select>
                  </label>
                </div>
                <div className="grid gap-2 md:grid-cols-2">
                  <label>Action
                    <select
                      value={row.action || 'active'}
                      disabled={savingInterviewId === row.id}
                      onChange={(e) => inlineUpdateInterview(row, { action: e.target.value })}
                    >
                      {INTERVIEW_ACTIONS.map((item) => (
                        <option key={item.value} value={item.value}>{item.label}</option>
                      ))}
                    </select>
                  </label>
                </div>
                {row.location_name ? <p className="hint">Location: {row.location_name}</p> : null}
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
                      />
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
