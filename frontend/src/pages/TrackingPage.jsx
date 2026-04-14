import { Fragment, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ResumeSheet from '../components/ResumeSheet'
import { MultiSelectDropdown, SingleSelectDropdown } from '../components/SearchableDropdown'

import {
  createTrackingRow,
  deleteTrackingRow,
  fetchCompanies,
  fetchEmployees,
  fetchJobs,
  fetchResumes,
  fetchTrackingRows,
  updateTrackingRow,
} from '../api'

const EMPTY_MILESTONE_DOTS = 10

function DetailIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 5c5.5 0 9.6 5.2 10.8 6.9c.3.4.3.9 0 1.3C21.6 14.8 17.5 20 12 20S2.4 14.8 1.2 13.1a1 1 0 0 1 0-1.3C2.4 10.2 6.5 5 12 5Zm0 3.5A4.5 4.5 0 1 0 12 17a4.5 4.5 0 0 0 0-9Zm0 2a2.5 2.5 0 1 1 0 5a2.5 2.5 0 0 1 0-5Z"
      />
    </svg>
  )
}

function EditIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25Zm18-11.5a1 1 0 0 0 0-1.41l-1.34-1.34a1 1 0 0 0-1.41 0l-1.13 1.13l2.75 2.75L21 5.75Z"
      />
    </svg>
  )
}

function DeleteIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M9 3h6l1 2h4v2H4V5h4l1-2Zm1 6h2v9h-2V9Zm4 0h2v9h-2V9ZM7 9h2v9H7V9Zm-1 12h12a1 1 0 0 0 1-1V8H5v12a1 1 0 0 0 1 1Z"
      />
    </svg>
  )
}

function PreviewIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 5c5.5 0 9.6 5.2 10.8 6.9c.3.4.3.9 0 1.3C21.6 14.8 17.5 20 12 20S2.4 14.8 1.2 13.1a1 1 0 0 1 0-1.3C2.4 10.2 6.5 5 12 5Zm0 3.5A4.5 4.5 0 1 0 12 17a4.5 4.5 0 0 0 0-9Zm0 2a2.5 2.5 0 1 1 0 5a2.5 2.5 0 0 1 0-5Z"
      />
    </svg>
  )
}

function toDateInput(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toISOString().slice(0, 10)
}

function nowDateTimeLocalValue() {
  const d = new Date(Date.now() - (new Date().getTimezoneOffset() * 60000))
  return d.toISOString().slice(0, 16)
}

function toDateTimeLocalInput(value) {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  const local = new Date(d.getTime() - (d.getTimezoneOffset() * 60000))
  return local.toISOString().slice(0, 16)
}

function isFollowUpTemplate(choice) {
  return ['follow_up_applied', 'follow_up_call', 'follow_up_interview'].includes(String(choice || '').trim())
}

function formatMilestoneLabel(item) {
  if (!item) return '--'
  const type = item.type === 'followup' ? 'Follow Up' : 'Fresh'
  const date = item.at ? new Date(item.at) : null
  const timeText = date && !Number.isNaN(date.getTime())
    ? `${toDateInput(item.at)} ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
    : '--'
  return `${type} | ${timeText}`
}

function rowHasFreshMilestone(row) {
  return (row?.milestones || []).some((item) => item.type === 'fresh')
}

function rowLastActionType(row) {
  const items = row?.milestones || []
  if (!items.length) return ''
  return String(items[items.length - 1]?.type || '')
}

function rowLastSendMode(row) {
  const items = row?.milestones || []
  if (!items.length) return ''
  return String(items[items.length - 1]?.mode || '')
}

function uniqueArray(values) {
  return Array.from(new Set((Array.isArray(values) ? values : []).map((x) => String(x || '').trim()).filter(Boolean)))
}

const TEMPLATE_CHOICES = [
  { value: 'cold_applied', label: 'Cold Applied' },
  { value: 'referral', label: 'Referral' },
  { value: 'job_inquire', label: 'Job Inquire' },
  { value: 'follow_up_applied', label: 'Follow Up (Applied)' },
  { value: 'follow_up_call', label: 'Follow Up (After Call)' },
  { value: 'follow_up_interview', label: 'Follow Up (After Interview)' },
  { value: 'custom', label: 'Custom' },
]

const TEMPLATE_DEPARTMENT_RULES = {
  cold_applied: ['hr'],
  follow_up_applied: ['hr'],
  follow_up_call: ['hr'],
  follow_up_interview: ['hr'],
  referral: ['engineering'],
  job_inquire: ['hr', 'engineering'],
}

function departmentBucket(value) {
  const text = String(value || '').trim().toLowerCase()
  if (!text) return 'other'
  if (text.includes('hr') || text.includes('talent') || text.includes('recruit') || text.includes('human resource')) return 'hr'
  if (text.includes('engineer') || text.includes('developer') || text.includes('sde') || text.includes('software') || text.includes('devops') || text.includes('qa') || text.includes('data')) return 'engineering'
  return 'other'
}

function departmentBucketForEmployee(employee) {
  const dept = String(employee?.department || '').trim()
  const role = String(employee?.JobRole || '').trim()
  return departmentBucket(`${dept} ${role}`.trim())
}

function resolveDepartmentBuckets({ department, selectedIds, employees }) {
  const selectedSet = new Set((Array.isArray(selectedIds) ? selectedIds : []).map((id) => String(id)))
  const selectedEmployees = (Array.isArray(employees) ? employees : []).filter((emp) => selectedSet.has(String(emp.id)))
  if (selectedEmployees.length) {
    return Array.from(new Set(selectedEmployees.map((emp) => departmentBucketForEmployee(emp))))
  }
  const fromDepartment = departmentBucket(department)
  return fromDepartment === 'other' && !String(department || '').trim() ? [] : [fromDepartment]
}

function isTemplateAllowedForBuckets(templateChoice, buckets) {
  const normalizedChoice = String(templateChoice || '').trim()
  const allowed = TEMPLATE_DEPARTMENT_RULES[normalizedChoice]
  if (!allowed || !Array.isArray(buckets) || !buckets.length) return true
  return buckets.every((bucket) => allowed.includes(bucket))
}

function getTemplateOptionsForBuckets(buckets) {
  if (!Array.isArray(buckets) || !buckets.length) return TEMPLATE_CHOICES
  return TEMPLATE_CHOICES.filter((item) => isTemplateAllowedForBuckets(item.value, buckets))
}

function getTemplateRestrictionError(templateChoice, buckets) {
  const normalizedChoice = String(templateChoice || '').trim()
  if (!normalizedChoice) return ''
  if (isTemplateAllowedForBuckets(normalizedChoice, buckets)) return ''
  const allowed = TEMPLATE_DEPARTMENT_RULES[normalizedChoice] || []
  const allowedText = allowed.map((item) => (item === 'hr' ? 'HR' : 'Engineering')).join(', ')
  return `Template "${normalizedChoice}" is only allowed for ${allowedText} department contacts.`
}

function TrackingPage() {
  const access = localStorage.getItem('access') || ''
  const navigate = useNavigate()
  const [rows, setRows] = useState([])
  const [page, setPage] = useState(1)
  const [pageSize] = useState(8)
  const [totalPages, setTotalPages] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const [createForm, setCreateForm] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filters, setFilters] = useState({
    companyName: '',
    jobId: '',
    appliedDate: '',
    mailed: 'all',
    gotReplied: 'all',
    lastAction: 'all',
  })
  const [ordering, setOrdering] = useState('-applied_at')
  const [selectedIds, setSelectedIds] = useState([])
  const [editForm, setEditForm] = useState(null)
  const [companyOptions, setCompanyOptions] = useState([])
  const [jobOptions, setJobOptions] = useState([])
  const [employeeOptions, setEmployeeOptions] = useState([])
  const [resumeOptions, setResumeOptions] = useState([])
  const [previewResume, setPreviewResume] = useState(null)

  const tailoredOptionsForJob = (jobId) => {
    const job = jobOptions.find((item) => String(item.id) === String(jobId || ''))
    if (!job) return []
    const options = Array.isArray(job.tailored_resumes) ? [...job.tailored_resumes] : []
    options.sort((a, b) => {
      const aTime = new Date(a?.created_at || 0).getTime()
      const bTime = new Date(b?.created_at || 0).getTime()
      if (aTime !== bTime) return aTime - bTime
      return Number(a?.id || 0) - Number(b?.id || 0)
    })
    return options
  }
  const load = async () => {
    if (!access) {
      setRows([])
      setLoading(false)
      return
    }
    setLoading(true)
    setError('')
    try {
      const data = await fetchTrackingRows(access, { page, page_size: pageSize })
      const list = Array.isArray(data?.results) ? data.results : (Array.isArray(data) ? data : [])
      setRows(list)
      setTotalCount(Number(data?.count || list.length || 0))
      setTotalPages(Number(data?.total_pages || 1))
      if (data?.page && Number(data.page) !== page) {
        setPage(Number(data.page))
      }
    } catch (err) {
      setError(err.message || 'Failed to load tracking rows.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [access, page, pageSize])

  useEffect(() => {
    if (!access) return
    ;(async () => {
      try {
        const [companiesData, resumesData] = await Promise.all([
          fetchCompanies(access, { page: 1, page_size: 300 }),
          fetchResumes(access).catch(() => []),
        ])
        const companyRows = Array.isArray(companiesData?.results) ? companiesData.results : []
        setCompanyOptions(companyRows)
        setResumeOptions(Array.isArray(resumesData) ? resumesData : [])
      } catch {
        setCompanyOptions([])
        setResumeOptions([])
      }
    })()
  }, [access])

  const hydrateCompanyDependent = async (companyId) => {
    if (!companyId) {
      setJobOptions([])
      setEmployeeOptions([])
      return
    }
    try {
      const [jobsData, employeesData] = await Promise.all([
        fetchJobs(access, { page: 1, page_size: 300, company_id: companyId }),
        fetchEmployees(access, companyId),
      ])
      const jobs = Array.isArray(jobsData?.results) ? jobsData.results : []
      const emps = Array.isArray(employeesData) ? employeesData : []
      setJobOptions(jobs)
      setEmployeeOptions(emps)
    } catch {
      setJobOptions([])
      setEmployeeOptions([])
    }
  }

  const openCreateForm = () => {
    setCreateForm({
      company: '',
      job: '',
      department: '',
      template_name: '',
      template_subject: '',
      template_choice: '',
      hardcoded_follow_up: true,
      schedule_time: '',
      has_attachment: false,
      resume_id: '',
      tailored_resume_id: '',
      is_freezed: false,
      mailed: false,
      got_replied: false,
      applied_date: toDateInput(new Date().toISOString()),
      posting_date: toDateInput(new Date().toISOString()),
      is_open: true,
      selected_hr_ids: [],
    })
  }

  const createRow = async () => {
    if (!createForm) return
    if (!createForm.company || !createForm.job) {
      setError('Select company and job from dropdowns.')
      return
    }
    const selectedCompany = companyOptions.find((c) => String(c.id) === String(createForm.company))
    const selectedJob = jobOptions.find((j) => String(j.id) === String(createForm.job))
    const companyName = String(selectedCompany?.name || '').trim()
    const jobId = String(selectedJob?.job_id || '').trim()
    const role = String(selectedJob?.role || '').trim()
    const jobUrl = String(selectedJob?.job_link || '').trim()
    const resolvedTemplate = createForm.template_choice === 'custom'
      ? String(createForm.template_name || '').trim()
      : String(createForm.template_choice || '').trim()
    const resolvedTemplateSubject = createForm.template_choice === 'custom'
      ? String(createForm.template_subject || '').trim()
      : ''
    const resolvedTemplateChoice = String(createForm.template_choice || '').trim() || 'cold_applied'
    const resolvedTemplateMessage = resolvedTemplateChoice === 'custom' ? resolvedTemplate : ''
    const templateRestrictionError = getTemplateRestrictionError(resolvedTemplateChoice, createDepartmentBuckets)
    if (templateRestrictionError) {
      setError(templateRestrictionError)
      return
    }
    const resolvedHardcodedFollowUp = isFollowUpTemplate(resolvedTemplateChoice)
      ? Boolean(createForm.hardcoded_follow_up)
      : true
    const resolvedScheduleTime = isFollowUpTemplate(resolvedTemplateChoice)
      ? (createForm.schedule_time || nowDateTimeLocalValue())
      : null
    try {
      const payload = {
        company: createForm.company || null,
        job: createForm.job || null,
        company_name: companyName,
        job_id: jobId,
        role,
        job_url: jobUrl,
        template_choice: resolvedTemplateChoice,
        template_subject: resolvedTemplateSubject,
        template_message: resolvedTemplateMessage,
        hardcoded_follow_up: resolvedHardcodedFollowUp,
        schedule_time: resolvedScheduleTime,
        template_name: resolvedTemplate,
        resume: createForm.has_attachment ? (createForm.resume_id || null) : null,
        tailored_resume: createForm.has_attachment ? (createForm.tailored_resume_id || null) : null,
        is_freezed: Boolean(createForm.is_freezed),
        mailed: Boolean(createForm.mailed),
        got_replied: Boolean(createForm.got_replied),
        applied_date: createForm.applied_date || null,
        posting_date: createForm.posting_date || null,
        is_open: Boolean(createForm.is_open),
        selected_hr_ids: Array.isArray(createForm.selected_hr_ids) ? createForm.selected_hr_ids : [],
      }
      const created = await createTrackingRow(access, payload)
      setRows((prev) => [created, ...prev])
      setCreateForm(null)
      await load()
    } catch (err) {
      setError(err.message || 'Could not create tracking row.')
    }
  }

  const openEditForm = (row) => {
    const incomingTemplateChoice = String(row.template_choice || '').trim()
    const computedChoice = ['cold_applied', 'referral', 'job_inquire', 'follow_up_applied', 'follow_up_call', 'follow_up_interview', 'custom'].includes(incomingTemplateChoice)
      ? incomingTemplateChoice
      : (
        ['cold_applied', 'referral', 'job_inquire', 'follow_up_applied', 'follow_up_call', 'follow_up_interview'].includes(String(row.template_name || '').trim())
          ? String(row.template_name || '').trim()
          : 'custom'
      )
    const customTemplateText = computedChoice === 'custom'
      ? String(row.template_message || row.template_name || '')
      : ''
    const customTemplateSubject = computedChoice === 'custom'
      ? String(row.template_subject || '')
      : ''
    setEditForm({
      id: row.id,
      company: row.company || '',
      job: row.job || '',
      department: '',
      company_name: row.company_name || '',
      job_id: row.job_id || '',
      role: row.role || '',
      job_url: row.job_url || '',
      template_name: customTemplateText,
      template_subject: customTemplateSubject,
      template_choice: computedChoice,
      hardcoded_follow_up: Boolean(row.hardcoded_follow_up ?? true),
      schedule_time: toDateTimeLocalInput(row.schedule_time),
      has_attachment: Boolean(row.resume_preview || row.tailored_resume),
      resume_id: row.resume_preview?.id ? String(row.resume_preview.id) : '',
      tailored_resume_id: row.tailored_resume ? String(row.tailored_resume) : '',
      is_freezed: Boolean(row.is_freezed),
      mailed: Boolean(row.mailed),
      applied_date: toDateInput(row.applied_date),
      posting_date: toDateInput(row.posting_date),
      is_open: Boolean(row.is_open),
      selected_hr_ids: Array.isArray(row.selected_hr_ids) ? row.selected_hr_ids.map((id) => String(id)) : [],
      got_replied: Boolean(row.got_replied),
    })
    hydrateCompanyDependent(row.company || '')
  }

  const saveEditForm = async () => {
    if (!editForm) return
    if (!editForm.company || !editForm.job) {
      setError('Select company and job from dropdowns.')
      return
    }
    const selectedCompany = companyOptions.find((c) => String(c.id) === String(editForm.company))
    const selectedJob = jobOptions.find((j) => String(j.id) === String(editForm.job))
    const companyName = String(selectedCompany?.name || editForm.company_name || '').trim()
    const jobId = String(selectedJob?.job_id || editForm.job_id || '').trim()
    const role = String(selectedJob?.role || editForm.role || '').trim()
    const jobUrl = String(selectedJob?.job_link || editForm.job_url || '').trim()
    const resolvedTemplate = editForm.template_choice === 'custom'
      ? String(editForm.template_name || '').trim()
      : String(editForm.template_choice || '').trim()
    const resolvedTemplateSubject = editForm.template_choice === 'custom'
      ? String(editForm.template_subject || '').trim()
      : ''
    const resolvedTemplateChoice = String(editForm.template_choice || '').trim() || 'cold_applied'
    const resolvedTemplateMessage = resolvedTemplateChoice === 'custom' ? resolvedTemplate : ''
    const templateRestrictionError = getTemplateRestrictionError(resolvedTemplateChoice, editDepartmentBuckets)
    if (templateRestrictionError) {
      setError(templateRestrictionError)
      return
    }
    const resolvedHardcodedFollowUp = isFollowUpTemplate(resolvedTemplateChoice)
      ? Boolean(editForm.hardcoded_follow_up)
      : true
    const resolvedScheduleTime = isFollowUpTemplate(resolvedTemplateChoice)
      ? (editForm.schedule_time || nowDateTimeLocalValue())
      : null
    const selectedHrIds = Array.isArray(editForm.selected_hr_ids) ? editForm.selected_hr_ids : []
    const basePayload = {
      company: editForm.company || null,
      job: editForm.job || null,
      company_name: companyName,
      job_id: jobId,
      role,
      job_url: jobUrl,
      template_choice: resolvedTemplateChoice,
      template_subject: resolvedTemplateSubject,
      template_message: resolvedTemplateMessage,
      hardcoded_follow_up: resolvedHardcodedFollowUp,
      schedule_time: resolvedScheduleTime,
      template_name: resolvedTemplate,
      resume: editForm.resume_id || null,
      tailored_resume: editForm.tailored_resume_id || null,
      is_freezed: Boolean(editForm.is_freezed),
      mailed: editForm.mailed,
      applied_date: editForm.applied_date || null,
      posting_date: editForm.posting_date || null,
      is_open: editForm.is_open,
      selected_hr_ids: selectedHrIds,
      got_replied: editForm.got_replied,
    }
    try {
      const payload = {
        ...basePayload,
        resume: editForm.has_attachment ? (editForm.resume_id || null) : null,
        tailored_resume: editForm.has_attachment ? (editForm.tailored_resume_id || null) : null,
      }
      const updated = await updateTrackingRow(access, editForm.id, payload)
      setRows((prev) => prev.map((row) => (row.id === editForm.id ? updated : row)))
      setEditForm(null)
    } catch (err) {
      setError(err.message || 'Could not save tracking row.')
    }
  }

  const removeRow = async (rowId) => {
    try {
      await deleteTrackingRow(access, rowId)
      await load()
    } catch (err) {
      setError(err.message || 'Could not delete row.')
    }
  }

  const bulkDeleteSelected = async () => {
    if (!selectedIds.length) return
    try {
      const results = await Promise.allSettled(selectedIds.map((id) => deleteTrackingRow(access, id)))
      const failed = results.filter((item) => item.status === 'rejected').length
      if (failed) {
        setError(`${failed} tracking row(s) could not be deleted.`)
      } else {
        setError('')
      }
      setSelectedIds([])
      await load()
    } catch (err) {
      setError(err.message || 'Could not delete selected tracking rows.')
    }
  }

  const bulkFreezeSelected = async () => {
    if (!selectedIds.length) return
    try {
      const targetRows = filteredRows.filter((row) => selectedIds.includes(row.id))
      const results = await Promise.allSettled(
        targetRows.map((row) => updateTrackingRow(access, row.id, { is_freezed: true })),
      )
      const failed = results.filter((item) => item.status === 'rejected').length
      if (failed) {
        setError(`${failed} tracking row(s) could not be freezed.`)
      } else {
        setError('')
      }
      setSelectedIds([])
      await load()
    } catch (err) {
      setError(err.message || 'Could not freeze selected tracking rows.')
    }
  }

  const filteredRows = useMemo(() => {
    const out = rows.filter((row) => {
      if (filters.companyName && !String(row.company_name || '').toLowerCase().includes(filters.companyName.toLowerCase())) return false
      if (filters.jobId && !String(row.job_id || '').toLowerCase().includes(filters.jobId.toLowerCase())) return false
      if (filters.appliedDate && toDateInput(row.applied_date) !== filters.appliedDate) return false
      if (filters.mailed === 'yes' && !row.mailed) return false
      if (filters.mailed === 'no' && row.mailed) return false
      if (filters.gotReplied === 'yes' && !row.got_replied) return false
      if (filters.gotReplied === 'no' && row.got_replied) return false
      const actionType = rowLastActionType(row)
      if (filters.lastAction !== 'all' && actionType !== filters.lastAction) return false
      return true
    })
    out.sort((a, b) => {
      const aApplied = new Date(a.applied_date || 0).getTime()
      const bApplied = new Date(b.applied_date || 0).getTime()
      const aCreated = new Date(a.created_at || 0).getTime()
      const bCreated = new Date(b.created_at || 0).getTime()
      const aCompany = String(a.company_name || '').toLowerCase()
      const bCompany = String(b.company_name || '').toLowerCase()
      const aJob = String(a.job_id || '').toLowerCase()
      const bJob = String(b.job_id || '').toLowerCase()
      const aRole = String(a.role || '').toLowerCase()
      const bRole = String(b.role || '').toLowerCase()

      switch (ordering) {
      case 'applied_at':
        return aApplied - bApplied
      case '-created_at':
        return bCreated - aCreated
      case 'created_at':
        return aCreated - bCreated
      case 'company_name':
        return aCompany.localeCompare(bCompany)
      case '-company_name':
        return bCompany.localeCompare(aCompany)
      case 'job_id':
        return aJob.localeCompare(bJob)
      case '-job_id':
        return bJob.localeCompare(aJob)
      case 'role':
        return aRole.localeCompare(bRole)
      case '-role':
        return bRole.localeCompare(aRole)
      case '-applied_at':
      default:
        return bApplied - aApplied
      }
    })
    return out
  }, [rows, filters, ordering])

  const createTailoredOptions = useMemo(
    () => (createForm?.job ? tailoredOptionsForJob(createForm.job) : []),
    [createForm?.job, jobOptions],
  )
  const editTailoredOptions = useMemo(
    () => (editForm?.job ? tailoredOptionsForJob(editForm.job) : []),
    [editForm?.job, jobOptions],
  )
  const orderedResumeOptions = useMemo(() => {
    const options = [...(Array.isArray(resumeOptions) ? resumeOptions : [])]
    options.sort((a, b) => {
      const aTime = new Date(a?.created_at || 0).getTime()
      const bTime = new Date(b?.created_at || 0).getTime()
      if (aTime !== bTime) return aTime - bTime
      return Number(a?.id || 0) - Number(b?.id || 0)
    })
    return options
  }, [resumeOptions])
  const activeEmployeeOptions = useMemo(
    () => (Array.isArray(employeeOptions) ? employeeOptions.filter((emp) => emp?.working_mail !== false) : []),
    [employeeOptions],
  )

  const createDepartmentBuckets = useMemo(
    () => resolveDepartmentBuckets({
      department: createForm?.department || '',
      selectedIds: createForm?.selected_hr_ids || [],
      employees: activeEmployeeOptions,
    }),
    [createForm?.department, createForm?.selected_hr_ids, activeEmployeeOptions],
  )
  const editDepartmentBuckets = useMemo(
    () => resolveDepartmentBuckets({
      department: editForm?.department || '',
      selectedIds: editForm?.selected_hr_ids || [],
      employees: activeEmployeeOptions,
    }),
    [editForm?.department, editForm?.selected_hr_ids, activeEmployeeOptions],
  )
  const createTemplateOptions = useMemo(
    () => getTemplateOptionsForBuckets(createDepartmentBuckets),
    [createDepartmentBuckets],
  )
  const editTemplateOptions = useMemo(
    () => getTemplateOptionsForBuckets(editDepartmentBuckets),
    [editDepartmentBuckets],
  )

  const allSelected = filteredRows.length > 0 && filteredRows.every((row) => selectedIds.includes(row.id))
  useEffect(() => {
    if (!createForm) return
    const currentChoice = String(createForm.template_choice || '').trim()
    if (!currentChoice) return
    if (isTemplateAllowedForBuckets(currentChoice, createDepartmentBuckets)) return
    setCreateForm((prev) => ({
      ...prev,
      template_choice: '',
      template_subject: '',
      template_name: '',
      schedule_time: '',
      hardcoded_follow_up: true,
    }))
  }, [createForm, createDepartmentBuckets])

  useEffect(() => {
    if (!editForm) return
    const currentChoice = String(editForm.template_choice || '').trim()
    if (!currentChoice) return
    if (isTemplateAllowedForBuckets(currentChoice, editDepartmentBuckets)) return
    setEditForm((prev) => ({
      ...prev,
      template_choice: '',
      template_subject: '',
      template_name: '',
      schedule_time: '',
      hardcoded_follow_up: true,
    }))
  }, [editForm, editDepartmentBuckets])

  const toggleSelect = (rowId, checked) => {
    setSelectedIds((prev) => {
      if (checked) return Array.from(new Set([...prev, rowId]))
      return prev.filter((id) => id !== rowId)
    })
  }
  const toggleSelectAll = (checked) => {
    setSelectedIds(checked ? filteredRows.map((row) => row.id) : [])
  }

  return (
    <main className="page page-wide page-plain mx-auto w-full">
      <div className="tracking-head">
        <div>
          <h1>Tracking</h1>
          <p className="subtitle">Compact tracking with HR dropdown, freeze control, and persisted wavy milestones.</p>
        </div>
        <div className="actions">
          <button type="button" className="secondary" onClick={bulkFreezeSelected} disabled={!selectedIds.length || loading}>Mark Freezed</button>
          <button type="button" className="secondary" onClick={bulkDeleteSelected} disabled={!selectedIds.length || loading}>Delete Selected</button>
          <button type="button" className="secondary" onClick={openCreateForm}>Add Tracking</button>
        </div>
      </div>

      <section className="tracking-filters filters-one-row">
        <label>Company Name<input value={filters.companyName} onChange={(event) => setFilters((prev) => ({ ...prev, companyName: event.target.value }))} /></label>
        <label>Job ID<input value={filters.jobId} onChange={(event) => setFilters((prev) => ({ ...prev, jobId: event.target.value }))} /></label>
        <label>Applied Date<input type="date" value={filters.appliedDate} onChange={(event) => setFilters((prev) => ({ ...prev, appliedDate: event.target.value }))} /></label>
        <label>Mailed<select value={filters.mailed} onChange={(event) => setFilters((prev) => ({ ...prev, mailed: event.target.value }))}><option value="all">All</option><option value="yes">Yes</option><option value="no">No</option></select></label>
        <label>Replied (got_replied)<select value={filters.gotReplied} onChange={(event) => setFilters((prev) => ({ ...prev, gotReplied: event.target.value }))}><option value="all">All</option><option value="yes">Yes</option><option value="no">No</option></select></label>
        <label>Last Action<select value={filters.lastAction} onChange={(event) => setFilters((prev) => ({ ...prev, lastAction: event.target.value }))}><option value="all">All</option><option value="fresh">Fresh</option><option value="followup">Follow Up</option></select></label>
        <label>
          Sort
          <select value={ordering} onChange={(event) => setOrdering(event.target.value)}>
            <option value="-applied_at">Applied ↓</option>
            <option value="applied_at">Applied ↑</option>
            <option value="-created_at">Created ↓</option>
            <option value="created_at">Created ↑</option>
            <option value="company_name">Company A-Z</option>
            <option value="-company_name">Company Z-A</option>
            <option value="job_id">Job ID A-Z</option>
            <option value="-job_id">Job ID Z-A</option>
            <option value="role">Role A-Z</option>
            <option value="-role">Role Z-A</option>
          </select>
        </label>
      </section>

      {error ? <p className="error">{error}</p> : null}
      {loading ? <p className="hint">Loading tracking rows...</p> : null}

      <div className="tracking-table-wrap tracking-table-wrap-compact">
        <table className="tracking-table tracking-table-compact">
          <thead>
            <tr>
              <th>
                <input type="checkbox" checked={allSelected} onChange={(event) => toggleSelectAll(event.target.checked)} />
              </th>
              <th>Company</th>
              <th>Job ID</th>
              <th>Employee</th>
              <th>Delivery Status</th>
              <th>Mailed</th>
              <th>Replied</th>
              <th>Mail Type</th>
              <th>Send</th>
              <th>Freeze</th>
              <th>Template Type</th>
              <th>Resume</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {filteredRows.map((row) => {
              const milestones = Array.isArray(row.milestones) ? row.milestones : []
              const selectedHrValues = uniqueArray(row.selected_hrs)
              const linkedPreviewResume = row.resume_preview || row.tailored_resume_preview || null

              return (
                <Fragment key={`row-wrap-${row.id}`}>
                  <tr key={`data-${row.id}`}>
                    <td>
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(row.id)}
                        onChange={(event) => toggleSelect(row.id, event.target.checked)}
                      />
                    </td>
                    <td>{row.company_name || '-'}</td>
                    <td>{row.job_id || '-'}</td>
                    <td>{selectedHrValues.length ? selectedHrValues.join(', ') : '-'}</td>
                    <td>{String(row.mail_delivery_status || 'pending').replaceAll('_', ' ')}</td>
                    <td>{row.mailed ? 'Yes' : 'No'}</td>
                    <td>{row.got_replied ? 'Yes' : 'No'}</td>
                    <td>{rowLastActionType(row) || '-'}</td>
                    <td>{rowLastSendMode(row) || '-'}</td>
                    <td>{row.is_freezed ? 'Yes' : 'No'}</td>
                    <td>{String(row.template_choice || '-').replaceAll('_', ' ')}</td>
                    <td>
                      {linkedPreviewResume ? (
                        <div className="tracking-actions-compact">
                          <button
                            type="button"
                            className="secondary tracking-icon-btn"
                            title="Review resume"
                            onClick={() => setPreviewResume(linkedPreviewResume)}
                          >
                            <PreviewIcon />
                          </button>
                        </div>
                      ) : '-'}
                    </td>
                    <td className="tracking-action-cell">
                      <div className="tracking-actions-compact">
                        <button type="button" className="secondary tracking-icon-btn" title="Detail" onClick={() => navigate(`/tracking/${row.id}`)}><DetailIcon /></button>
                        <button type="button" className="secondary tracking-icon-btn" title="Edit" onClick={() => openEditForm(row)} disabled={row.is_freezed}><EditIcon /></button>
                        <button type="button" className="tracking-remove-inline tracking-icon-btn" title="Delete" onClick={() => removeRow(row.id)}><DeleteIcon /></button>
                      </div>
                    </td>
                  </tr>
                  <tr className="tracking-milestone-row">
                    <td colSpan={13}>
                      <div className="tracking-wave-wrap">
                        <svg className="tracking-wave-svg" viewBox="0 0 1000 44" preserveAspectRatio="none" aria-hidden="true">
                          <path
                            d="M0 22 Q25 4 50 22 T100 22 T150 22 T200 22 T250 22 T300 22 T350 22 T400 22 T450 22 T500 22 T550 22 T600 22 T650 22 T700 22 T750 22 T800 22 T850 22 T900 22 T950 22 T1000 22"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.4"
                          />
                        </svg>
                        <div className="tracking-wave-points">
                          {Array.from({ length: EMPTY_MILESTONE_DOTS }).map((_, index) => {
                            const milestone = milestones[index]
                            return (
                              <div
                                key={`${row.id}-wave-${index}`}
                                className="tracking-wave-point"
                                style={{ left: `${(index / (EMPTY_MILESTONE_DOTS - 1)) * 100}%` }}
                                title={milestone ? `${milestone.type} | ${milestone.mode} | ${milestone.at}` : `Step ${index + 1}`}
                              >
                                <span className={`tracking-wave-circle ${milestone ? 'is-on' : ''}`} />
                                <span className="tracking-wave-label">{formatMilestoneLabel(milestone)}</span>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    </td>
                  </tr>
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>

      {!loading && !filteredRows.length ? <p className="hint">No rows found.</p> : null}
      <div className="table-pagination">
        <button type="button" className="secondary" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>Previous</button>
        <span>Page {page} / {Math.max(1, totalPages)} ({totalCount})</span>
        <button type="button" className="secondary" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}>Next</button>
      </div>

      {createForm ? (
        <div className="modal-overlay">
          <div className="modal-panel">
            <h2>Add Tracking</h2>
            <label>
              Company (dropdown)
              <SingleSelectDropdown
                value={createForm.company || ''}
                placeholder="Select company"
                options={companyOptions.map((company) => ({ value: String(company.id), label: String(company.name || '') }))}
                onChange={async (nextValue) => {
                  setCreateForm((prev) => ({ ...prev, company: nextValue, job: '', selected_hr_ids: [], tailored_resume_id: '' }))
                  await hydrateCompanyDependent(nextValue)
                }}
              />
            </label>
            <label>
              Department
              <SingleSelectDropdown
                value={createForm.department || ''}
                placeholder="Select department"
                options={Array.from(new Set(activeEmployeeOptions.map((emp) => String(emp.department || '').trim()).filter(Boolean))).map((dept) => ({ value: dept, label: dept }))}
                onChange={(nextValue) => setCreateForm((prev) => ({ ...prev, department: nextValue, selected_hr_ids: [] }))}
              />
            </label>
            <label>
              Employee (multi-select)
              <MultiSelectDropdown
                values={Array.isArray(createForm.selected_hr_ids) ? createForm.selected_hr_ids : []}
                placeholder="Select employee(s)"
                options={activeEmployeeOptions
                  .filter((emp) => !createForm.department || String(emp.department || '') === String(createForm.department || ''))
                  .map((emp) => ({ value: String(emp.id), label: String(emp.name || '') }))}
                onChange={(nextValues) => setCreateForm((prev) => ({ ...prev, selected_hr_ids: Array.isArray(nextValues) ? nextValues : [] }))}
              />
            </label>
            <label>
              Job (dropdown)
              <SingleSelectDropdown
                value={createForm.job || ''}
                placeholder="Select job"
                options={jobOptions.map((job) => ({ value: String(job.id), label: `${job.job_id || ''} - ${job.role || ''}` }))}
                onChange={(nextValue) => setCreateForm((prev) => ({ ...prev, job: nextValue, tailored_resume_id: '' }))}
              />
            </label>
            <label>
              Selected Job Details
              {createForm.job ? (
                <div className="hint">
                  {(() => {
                    const job = jobOptions.find((j) => String(j.id) === String(createForm.job))
                    return job ? `${job.job_id || '-'} | ${job.role || '-'} | ${job.job_link || '-'}` : 'Select job'
                  })()}
                </div>
              ) : (
                <div className="hint">Select job</div>
              )}
            </label>
            <label>
              Template
              <SingleSelectDropdown
                value={createForm.template_choice || ''}
                placeholder="Select template"
                options={createTemplateOptions}
                onChange={(nextValue) => setCreateForm((prev) => ({
                  ...prev,
                  template_choice: nextValue || '',
                  hardcoded_follow_up: isFollowUpTemplate(nextValue) ? Boolean(prev.hardcoded_follow_up ?? true) : true,
                  schedule_time: isFollowUpTemplate(nextValue) ? (prev.schedule_time || nowDateTimeLocalValue()) : '',
                  template_subject: nextValue === 'custom' ? prev.template_subject : '',
                  template_name: nextValue === 'custom' ? prev.template_name : '',
                }))}
              />
            </label>
            {!createTemplateOptions.length ? (
              <p className="hint">No template available for selected department/employee.</p>
            ) : null}
            {isFollowUpTemplate(createForm.template_choice) ? (
              <label>
                <input
                  type="checkbox"
                  checked={Boolean(createForm.hardcoded_follow_up)}
                  onChange={(event) => setCreateForm((prev) => ({ ...prev, hardcoded_follow_up: event.target.checked }))}
                />
                {' '}
                Hardcoded Follow Up
              </label>
            ) : null}
            {isFollowUpTemplate(createForm.template_choice) ? (
              <label>
                Follow Up Date & Time
                <input
                  type="datetime-local"
                  value={createForm.schedule_time || ''}
                  onChange={(event) => setCreateForm((prev) => ({ ...prev, schedule_time: event.target.value }))}
                />
              </label>
            ) : null}
            {createForm.template_choice === 'custom' ? (
              <>
                <label>
                  Subject line
                  <textarea
                    value={createForm.template_subject || ''}
                    onChange={(event) => setCreateForm((prev) => ({ ...prev, template_subject: event.target.value }))}
                    placeholder="Paste custom subject line"
                    rows={2}
                  />
                </label>
                <label>
                  Custom Template
                  <textarea
                    value={createForm.template_name || ''}
                    onChange={(event) => setCreateForm((prev) => ({ ...prev, template_name: event.target.value }))}
                    placeholder="Paste custom mail template"
                    rows={8}
                  />
                </label>
              </>
            ) : null}
            <label>
              <input
                type="checkbox"
                checked={Boolean(createForm.has_attachment)}
                onChange={(event) => setCreateForm((prev) => {
                  const checked = event.target.checked
                  if (checked) return { ...prev, has_attachment: true }
                  return {
                    ...prev,
                    has_attachment: false,
                    resume_id: '',
                    tailored_resume_id: '',
                  }
                })}
              />
              {' '}
              Attachment
            </label>
            {createForm.has_attachment ? (
              <>
                <label>
                  Resume
                  <SingleSelectDropdown
                    value={createForm.resume_id || ''}
                    placeholder="Select resume"
                    disabled={Boolean(createForm.tailored_resume_id)}
                    options={orderedResumeOptions.map((resume) => ({ value: String(resume.id), label: String(resume.title || `Resume #${resume.id}`) }))}
                    onChange={(value) => {
                      setCreateForm((prev) => ({
                        ...prev,
                        resume_id: value,
                        tailored_resume_id: value ? '' : prev.tailored_resume_id,
                      }))
                    }}
                  />
                </label>
                {createTailoredOptions.length ? (
                  <label>
                    Tailored Resume
                    <SingleSelectDropdown
                      value={createForm.tailored_resume_id || ''}
                      placeholder="Select tailored resume"
                      disabled={Boolean(createForm.resume_id)}
                      options={createTailoredOptions.map((item) => ({ value: String(item.id), label: String(item.name || `Tailored Resume #${item.id}`) }))}
                      onChange={(value) => {
                        setCreateForm((prev) => ({
                          ...prev,
                          tailored_resume_id: value,
                          resume_id: value ? '' : prev.resume_id,
                        }))
                      }}
                    />
                  </label>
                ) : null}
              </>
            ) : null}
            <label>
              <input
                type="checkbox"
                checked={Boolean(createForm.is_freezed)}
                onChange={(event) => setCreateForm((prev) => ({ ...prev, is_freezed: event.target.checked }))}
              />
              {' '}
              Freeze
            </label>
            <div className="actions">
              <button type="button" onClick={createRow}>Create</button>
              <button type="button" className="secondary" onClick={() => setCreateForm(null)}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}

      {editForm ? (
        <div className="modal-overlay">
          <div className="modal-panel">
            <h2>Edit Tracking Row</h2>
            <label>
              Company (dropdown)
              <SingleSelectDropdown
                value={editForm.company || ''}
                placeholder="Select company"
                options={companyOptions.map((company) => ({ value: String(company.id), label: String(company.name || '') }))}
                onChange={async (value) => {
                  setEditForm((prev) => ({ ...prev, company: value, job: '', selected_hr_ids: [] }))
                  await hydrateCompanyDependent(value)
                }}
              />
            </label>
            <label>
              Department
              <SingleSelectDropdown
                value={editForm.department || ''}
                placeholder="Select department"
                options={Array.from(new Set(activeEmployeeOptions.map((emp) => String(emp.department || '').trim()).filter(Boolean))).map((dept) => ({ value: dept, label: dept }))}
                onChange={(value) => setEditForm((prev) => ({ ...prev, department: value, selected_hr_ids: [] }))}
              />
            </label>
            <label>
              Employee (multi-select)
              <MultiSelectDropdown
                values={Array.isArray(editForm.selected_hr_ids) ? editForm.selected_hr_ids : []}
                placeholder="Select employee(s)"
                options={activeEmployeeOptions
                  .filter((emp) => !editForm.department || String(emp.department || '') === String(editForm.department || ''))
                  .map((emp) => ({ value: String(emp.id), label: String(emp.name || '') }))}
                onChange={(nextValues) => {
                  setEditForm((prev) => ({ ...prev, selected_hr_ids: Array.isArray(nextValues) ? nextValues : [] }))
                }}
              />
            </label>
            <label>
              Job (dropdown)
              <SingleSelectDropdown
                value={editForm.job || ''}
                placeholder="Select job"
                options={jobOptions.map((job) => ({ value: String(job.id), label: `${job.job_id || ''} - ${job.role || ''}` }))}
                onChange={(value) => {
                  setEditForm((prev) => ({
                    ...prev,
                    job: value,
                    tailored_resume_id: '',
                  }))
                }}
              />
            </label>
            <label>
              Selected Job Details
              {editForm.job ? (
                <div className="hint">
                  {(() => {
                    const job = jobOptions.find((j) => String(j.id) === String(editForm.job))
                    if (!job) return `${editForm.job_id || '-'} | ${editForm.role || '-'} | ${editForm.job_url || '-'}`
                    return `${job.job_id || '-'} | ${job.role || '-'} | ${job.job_link || '-'}`
                  })()}
                </div>
              ) : (
                <div className="hint">Select job</div>
              )}
            </label>
            <label>
              Template
              <SingleSelectDropdown
                value={editForm.template_choice || 'cold_applied'}
                placeholder="Select template"
                options={editTemplateOptions}
                onChange={(value) => setEditForm((prev) => ({
                  ...prev,
                  template_choice: value || 'cold_applied',
                  hardcoded_follow_up: isFollowUpTemplate(value) ? Boolean(prev.hardcoded_follow_up ?? true) : true,
                  schedule_time: isFollowUpTemplate(value) ? (prev.schedule_time || nowDateTimeLocalValue()) : '',
                  template_subject: value === 'custom' ? prev.template_subject : '',
                  template_name: value === 'custom' ? prev.template_name : '',
                }))}
              />
            </label>
            {!editTemplateOptions.length ? (
              <p className="hint">No template available for selected department/employee.</p>
            ) : null}
            {isFollowUpTemplate(editForm.template_choice) ? (
              <label>
                <input
                  type="checkbox"
                  checked={Boolean(editForm.hardcoded_follow_up)}
                  onChange={(event) => setEditForm((prev) => ({ ...prev, hardcoded_follow_up: event.target.checked }))}
                />
                {' '}
                Hardcoded Follow Up
              </label>
            ) : null}
            {isFollowUpTemplate(editForm.template_choice) ? (
              <label>
                Follow Up Date & Time
                <input
                  type="datetime-local"
                  value={editForm.schedule_time || ''}
                  onChange={(event) => setEditForm((prev) => ({ ...prev, schedule_time: event.target.value }))}
                />
              </label>
            ) : null}
            {editForm.template_choice === 'custom' ? (
              <>
                <label>
                  Subject line
                  <textarea
                    value={editForm.template_subject || ''}
                    onChange={(event) => setEditForm((prev) => ({ ...prev, template_subject: event.target.value }))}
                    placeholder="Paste custom subject line"
                    rows={2}
                  />
                </label>
                <label>
                  Custom Template
                  <textarea
                    value={editForm.template_name || ''}
                    onChange={(event) => setEditForm((prev) => ({ ...prev, template_name: event.target.value }))}
                    placeholder="Paste custom mail template"
                    rows={8}
                  />
                </label>
              </>
            ) : null}
            <label>
              <input
                type="checkbox"
                checked={Boolean(editForm.has_attachment)}
                onChange={(event) => setEditForm((prev) => {
                  const checked = event.target.checked
                  if (checked) return { ...prev, has_attachment: true }
                  return {
                    ...prev,
                    has_attachment: false,
                    resume_id: '',
                    tailored_resume_id: '',
                  }
                })}
              />
              {' '}
              Attachment
            </label>
            {editForm.has_attachment ? (
              <>
                <label>
                  Resume
                  <SingleSelectDropdown
                    value={editForm.resume_id || ''}
                    placeholder="Select resume"
                    disabled={Boolean(editForm.tailored_resume_id)}
                    options={orderedResumeOptions.map((resume) => ({ value: String(resume.id), label: String(resume.title || `Resume #${resume.id}`) }))}
                    onChange={(value) => {
                      setEditForm((prev) => ({
                        ...prev,
                        resume_id: value,
                        tailored_resume_id: value ? '' : prev.tailored_resume_id,
                      }))
                    }}
                  />
                </label>
                {editTailoredOptions.length ? (
                  <label>
                    Tailored Resume
                    <SingleSelectDropdown
                      value={editForm.tailored_resume_id || ''}
                      placeholder="Select tailored resume"
                      disabled={Boolean(editForm.resume_id)}
                      options={editTailoredOptions.map((item) => ({ value: String(item.id), label: String(item.name || `Tailored Resume #${item.id}`) }))}
                      onChange={(value) => {
                        setEditForm((prev) => ({
                          ...prev,
                          tailored_resume_id: value,
                          resume_id: value ? '' : prev.resume_id,
                        }))
                      }}
                    />
                  </label>
                ) : null}
              </>
            ) : null}
            <label>
              <input
                type="checkbox"
                checked={Boolean(editForm.is_freezed)}
                onChange={(event) => setEditForm((prev) => ({ ...prev, is_freezed: event.target.checked }))}
              />
              {' '}
              Freeze
            </label>
            <div className="actions">
              <button type="button" onClick={saveEditForm}>Save</button>
              <button type="button" className="secondary" onClick={() => setEditForm(null)}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}

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
              <button type="button" className="secondary" onClick={() => setPreviewResume(null)}>Close</button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  )
}

export default TrackingPage
