import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ResumeSheet from '../components/ResumeSheet'
import { MultiSelectDropdown, SingleSelectDropdown } from '../components/SearchableDropdown'
import { MailTestIcon } from './TrackingMailTestPage'
import { capitalizeFirstDisplay } from '../utils/displayText'

import {
  createTrackingRow,
  deleteTrackingRow,
  fetchAllCompanies,
  fetchAllJobs,
  fetchSubjectTemplates,
  fetchTemplates,
  fetchEmployees,
  fetchProfile,
  fetchResumes,
  fetchTailoredResumes,
  fetchTrackingRow,
  fetchTrackingRows,
  updateTrackingRow,
} from '../api'

const EMPTY_MILESTONE_DOTS = 20
const TRACKING_TEMPLATE_SLOT_COUNT = 2
const WAVE_INSET_PX = 88
const WAVE_POINT_SPACING_PX = 50
const WAVE_SVG_TOP_PX = 11
const WAVE_SVG_HEIGHT_PX = 16
const WAVE_DOT_SIZE_PX = 8
const WAVE_VIEWBOX_WIDTH = 1000
const WAVE_VIEWBOX_HEIGHT = 44
function DetailIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M4 5.75A1.75 1.75 0 0 1 5.75 4h12.5A1.75 1.75 0 0 1 20 5.75v12.5A1.75 1.75 0 0 1 18.25 20H5.75A1.75 1.75 0 0 1 4 18.25V5.75Zm3 1.75a.75.75 0 0 0-.75.75v8.5c0 .41.34.75.75.75h10a.75.75 0 0 0 .75-.75v-8.5a.75.75 0 0 0-.75-.75H7Zm1.5 2h7a.75.75 0 0 1 0 1.5h-7a.75.75 0 0 1 0-1.5Zm0 3.5h7a.75.75 0 0 1 0 1.5h-7a.75.75 0 0 1 0-1.5Z"
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

function SendNowIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M3.4 20.4L21 12L3.4 3.6L3.3 10l12.2 2l-12.2 2z"
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

function formatShortDateTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString([], {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatInteractionTimeValue(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value || '').trim()
  return date.toLocaleString([], {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function isFollowUpTemplate(choice) {
  return ['follow_up_applied', 'follow_up_call', 'follow_up_interview', 'follow_up_referral'].includes(String(choice || '').trim())
}

function formatMilestoneLabel(item) {
  if (!item) return '--'
  const type = item.type === 'followup' ? 'Follow Up' : 'Fresh'
  const date = item.at ? new Date(item.at) : null
  const timeText = date && !Number.isNaN(date.getTime())
    ? `${toDateInput(item.at)} ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
    : '--'
  const notes = String(item.notes || '').trim()
  const count = Number(item.count || 1)
  const countText = count > 1 ? `x${count}` : ''
  return [type, timeText, notes, countText].filter(Boolean).join(' | ')
}

function formatMilestoneCode(item) {
  if (!item) return '--'
  const base = item.type === 'followup' ? 'FU' : 'F'
  const count = Number(item.count || 1)
  return count > 1 ? `${base} x${count}` : base
}

function rowHasFreshMilestone(row) {
  return (row?.milestones || []).some((item) => item.type === 'fresh')
}

function rowLastActionType(row) {
  const items = row?.milestones || []
  if (items.length) return String(items[items.length - 1]?.type || '')
  const mailType = String(row?.mail_type || '').trim().toLowerCase()
  if (mailType === 'followed_up') return 'followup'
  if (mailType === 'fresh') return 'fresh'
  return ''
}

function rowLastSendMode(row) {
  return row?.schedule_time ? 'scheduled' : 'On Time'
}

function uniqueArray(values) {
  return Array.from(new Set((Array.isArray(values) ? values : []).map((x) => String(x || '').trim()).filter(Boolean)))
}

function sortTextValues(values) {
  return Array.from(new Set((Array.isArray(values) ? values : []).map((value) => String(value || '').trim()).filter(Boolean)))
    .sort((left, right) => left.localeCompare(right))
}

function normalizeId(value) {
  return String(value || '').trim()
}

function humanizeLabel(value, fallback = '-') {
  const text = String(value || '').trim()
  if (!text) return fallback
  return text.replaceAll('_', ' ')
}

function templateOwnerLabel(row) {
  return String(row?.owner_label || row?.owner_name || '').trim() || 'template'
}

function templateDisplayName(row) {
  const rawName = String(row?.name || 'Template').trim() || 'Template'
  return rawName.replace(/^\[system seed\]\s*/i, '').trim() || rawName
}

function formatTemplateLibraryLabel(row) {
  const category = humanizeLabel(row?.category, 'general')
  const name = templateDisplayName(row)
  return `${category} - ${name} | ${templateOwnerLabel(row)}`
}

function formatMailTypeLabel(value) {
  const text = String(value || '').trim().toLowerCase()
  return text === 'followup' || text === 'followed_up' ? 'Follow Up' : 'Fresh'
}

function formatSendModeLabel(value) {
  const text = String(value || '').trim().toLowerCase()
  if (!text) return '-'
  if (text === 'sent' || text === 'on time') return 'On Time'
  if (text === 'scheduled') return 'Scheduled'
  return humanizeLabel(text)
}

function formatStatusLabel(value) {
  const text = String(value || 'pending').trim().toLowerCase()
  if (text === 'sent_via_cron') return 'Bounce Verifying'
  if (text === 'successful_sent') return 'Successful Sent'
  if (text === 'mail_bounced') return 'Mail Bounced'
  if (text === 'partial_sent') return 'Partially'
  if (text === 'failed') return 'Failed'
  return 'Pending'
}

function subjectBaseValues(form, companies, jobs) {
  const selectedCompany = (Array.isArray(companies) ? companies : []).find((item) => String(item.id) === String(form?.company || ''))
  const selectedJob = (Array.isArray(jobs) ? jobs : []).find((item) => String(item.id) === String(form?.job || ''))
  const companyName = capitalizeFirstDisplay(selectedCompany?.name || form?.company_name || 'Company') || 'Company'
  const role = String(selectedJob?.role || form?.role || 'Role').trim() || 'Role'
  const jobId = String(selectedJob?.job_id || form?.job_id || '').trim()
  return { companyName, role, jobId }
}

function renderSubjectTemplateValue(template, companies, jobs, yearsOfExperience = '', profileFullName = '') {
  return renderSubjectTextValue(template?.subject || '', template, companies, jobs, yearsOfExperience, profileFullName)
}

function renderSubjectTextValue(subject, form, companies, jobs, yearsOfExperience = '', profileFullName = '') {
  if (!subject) return ''
  const { companyName, role, jobId } = subjectBaseValues(form, companies, jobs)
  const experience = String(yearsOfExperience || '').trim()
  const userName = String(profileFullName || '').trim()
  const interactionTime = formatInteractionTimeValue(form?.interaction_time)
  const interviewRound = String(form?.interview_round || '').trim()
  const replacements = {
    name: '',
    employee_name: '',
    first_name: '',
    user_name: userName,
    employee_role: '',
    department: '',
    employee_department: '',
    company_name: companyName,
    current_employer: companyName,
    role,
    job_id: jobId,
    job_link: '',
    resume_link: '',
    years_of_experience: experience,
    yoe: experience,
    interaction_time: interactionTime,
    interview_round: interviewRound,
  }
  return String(subject || '')
    .replace(/\{([a-z_]+)\}|\[([a-z_]+)\]/gi, (_, curlyKey, squareKey) => {
      const key = String(curlyKey || squareKey || '').trim().toLowerCase()
      return replacements[key] ?? ''
    })
    .replace(/\s+/g, ' ')
    .trim()
}

function subjectOptionsForForm(form, companies, jobs, yearsOfExperience = '', subjectTemplates = [], profileFullName = '') {
  const { companyName, role, jobId } = subjectBaseValues(form, companies, jobs)
  const withJobId = jobId ? ` (Job ID: ${jobId})` : ''
  const yoe = String(yearsOfExperience || '').trim()
  const yoeSuffix = yoe ? ` | ${yoe.toLowerCase().replace(/\s+/g, '')}` : ''
  const mailType = String(form?.mail_type || 'fresh').trim().toLowerCase()
  const subjectCategory = mailType === 'followed_up' ? 'follow_up' : 'fresh'
  const subjectCategoryLabel = subjectCategory === 'follow_up' ? 'Follow Up' : 'Fresh'
  const templateChoice = String(form?.template_choice || form?.template_name || '').trim().toLowerCase()
  let templates = []
  if (templateChoice === 'referral') {
    templates = [
      { name: 'Referral Request', value: `Referral request for ${role} at ${companyName}${withJobId}${yoeSuffix}` },
      { name: 'Referral Request Short', value: `Referral request | ${role} | ${companyName}${yoeSuffix}` },
    ]
  } else if (templateChoice === 'job_inquire') {
    templates = [
      { name: 'Job Inquiry', value: `Question about ${role} at ${companyName}${withJobId}${yoeSuffix}` },
      { name: 'Job Inquiry Short', value: `Job inquiry | ${role} | ${companyName}${yoeSuffix}` },
    ]
  } else if (templateChoice === 'follow_up_referral') {
    templates = [
      { name: 'Referral Follow Up', value: `Follow up on referral request for ${role} at ${companyName}${yoeSuffix}` },
      { name: 'Referral Follow Up Short', value: `Referral follow up | ${role} | ${companyName}${yoeSuffix}` },
    ]
  } else if (mailType === 'followed_up') {
    templates = [
      { name: 'Application Follow Up', value: `Follow up on my application for ${role} at ${companyName}${yoeSuffix}` },
      { name: 'Application Follow Up Short', value: `Application follow up | ${role} | ${companyName}${yoeSuffix}` },
    ]
  } else {
    templates = [
      { name: 'Application', value: `Application for ${role} at ${companyName}${withJobId}${yoeSuffix}` },
      { name: 'Application Short', value: `Application for ${role} | ${companyName}${yoeSuffix}` },
    ]
  }
  const generatedOptions = templates
    .filter((item) => String(item?.value || '').trim())
    .filter((item, index, arr) => arr.findIndex((entry) => String(entry?.value || '').trim() === String(item?.value || '').trim()) === index)
    .map((item) => ({
      value: item.value,
      label: `${subjectCategoryLabel} - ${item.name} | system`,
    }))

  const savedOptions = (Array.isArray(subjectTemplates) ? subjectTemplates : [])
    .filter((row) => String(row?.category || '').trim().toLowerCase() === subjectCategory)
    .map((row) => {
      const rendered = renderSubjectTemplateValue({ ...form, subject: row?.subject }, companies, jobs, yearsOfExperience, profileFullName)
      if (!rendered) return null
      const templateName = String(row?.name || '').trim() || 'Untitled'
      return {
        value: rendered,
        label: `${subjectCategoryLabel} - ${templateName} | user`,
      }
    })
    .filter(Boolean)

  const merged = []
  const seen = new Set()
  for (const option of [...savedOptions, ...generatedOptions]) {
    const value = String(option?.value || '').trim()
    if (!value || seen.has(value)) continue
    seen.add(value)
    merged.push(option)
  }
  return merged
}

const TEMPLATE_CHOICES = [
  { value: 'cold_applied', label: 'Cold Applied' },
  { value: 'referral', label: 'Referral' },
  { value: 'job_inquire', label: 'Job Inquire' },
  { value: 'follow_up_applied', label: 'Follow Up (Applied)' },
  { value: 'follow_up_referral', label: 'Follow Up (Referral)' },
  { value: 'follow_up_call', label: 'Follow Up (After Call)' },
  { value: 'follow_up_interview', label: 'Follow Up (After Interview)' },
  { value: 'custom', label: 'Custom' },
]

const MAIL_TYPE_OPTIONS = [
  { value: 'fresh', label: 'Fresh' },
  { value: 'followed_up', label: 'Follow Up' },
]

const SEND_MODE_OPTIONS = [
  { value: 'sent', label: 'Manual Send' },
  { value: 'scheduled', label: 'Schedule' },
]

const TEMPLATE_DEPARTMENT_RULES = {
  cold_applied: ['hr'],
  follow_up_applied: ['hr'],
  follow_up_referral: ['engineering'],
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
  const role = employeeRoleValue(employee)
  return departmentBucket(`${dept} ${role}`.trim())
}

function employeeLocationValue(employee) {
  return String(employee?.location_name || employee?.location || '').trim()
}

function employeeRoleValue(employee) {
  return String(employee?.role || employee?.JobRole || '').trim()
}

function jobLocationValue(job) {
  return String(job?.location_name || job?.location || '').trim()
}

function companyDropdownOptions(options, selectedValue = '', selectedLabel = '') {
  const baseOptions = Array.isArray(options) ? options : []
  const selectedId = String(selectedValue || '').trim()
  const selectedName = String(selectedLabel || '').trim()
  if (!selectedId) return baseOptions
  if (baseOptions.some((item) => String(item?.id) === selectedId)) return baseOptions
  return [{ id: selectedId, name: selectedName || 'Selected Company' }, ...baseOptions]
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

function isTemplateAllowedForMailType(templateChoice, mailType) {
  const normalizedChoice = String(templateChoice || '').trim()
  const normalizedMailType = String(mailType || 'fresh').trim().toLowerCase()
  if (!normalizedChoice) return true
  if (normalizedMailType === 'followed_up') return isFollowUpTemplate(normalizedChoice)
  return !isFollowUpTemplate(normalizedChoice)
}

function mailTypeOptionsForRow(hasFreshMilestone) {
  if (hasFreshMilestone) return MAIL_TYPE_OPTIONS
  return MAIL_TYPE_OPTIONS.filter((item) => item.value === 'fresh')
}

function isTemplateAllowed(templateChoice, buckets, mailType) {
  return isTemplateAllowedForBuckets(templateChoice, buckets) && isTemplateAllowedForMailType(templateChoice, mailType)
}

function mergeAchievementOptions(baseOptions, selectedMeta) {
  const rows = Array.isArray(baseOptions) ? [...baseOptions] : []
  const selectedId = String(selectedMeta?.id || '').trim()
  if (!selectedId) return rows
  if (rows.some((item) => String(item?.id || '') === selectedId)) return rows
  return [
    {
      id: selectedId,
      name: String(selectedMeta?.name || 'Template').trim() || 'Template',
      paragraph: String(selectedMeta?.text || '').trim(),
      category: String(selectedMeta?.category || 'general').trim() || 'general',
      owner_name: String(selectedMeta?.owner_name || '').trim(),
      owner_label: String(selectedMeta?.owner_label || '').trim() || 'template',
      is_system: Boolean(selectedMeta?.is_system),
    },
    ...rows,
  ]
}

function filterAchievementOptionsForMode(options) {
  return (Array.isArray(options) ? options : []).filter((item) => {
    const category = String(item?.category || '').trim().toLowerCase()
    return category !== 'personalized' && category !== 'follow_up'
  })
}

function templateSelectionError(templateChoice, values, options) {
  const ids = orderedAchievementIds(values)
  const normalizedMailType = String(templateChoice || 'fresh').trim().toLowerCase() || 'fresh'
  if (normalizedMailType === 'followed_up') {
    if (!ids.length) return 'For follow up, select at least 1 template.'
    if (ids.length > 2) return 'For follow up, select at most 2 templates.'
    const rows = ids
      .map((id) => (Array.isArray(options) ? options.find((item) => String(item?.value || item?.id || '') === String(id)) : null))
      .filter(Boolean)
    if (rows.length !== ids.length) return 'One or more selected follow-up templates were not found.'
    const categories = rows.map((item) => String(item?.category || 'follow_up').trim().toLowerCase())
    if (categories.some((category) => category !== 'follow_up')) return 'For follow up, use only Follow Up templates.'
    return ''
  }
  if (!ids.length) return 'Select at least one template.'
  if (ids.length > 5) return 'Select at most 5 templates.'
  const rows = ids
    .map((id) => (Array.isArray(options) ? options.find((item) => String(item?.id || '') === String(id)) : null))
    .filter(Boolean)
  if (rows.length !== ids.length) return 'One or more selected templates were not found.'
  return ''
}

function selectedTemplatePreviewRows(values, options) {
  const ids = orderedAchievementIds(values).slice(0, TRACKING_TEMPLATE_SLOT_COUNT)
  const source = Array.isArray(options) ? options : []
  return ids
    .map((id) => source.find((item) => String(item?.id || item?.value || '') === String(id)))
    .filter(Boolean)
    .map((item) => ({
      id: String(item?.id || item?.value || ''),
      label: formatTemplateLibraryLabel(item),
      text: String(item?.paragraph || item?.achievement || '').trim(),
    }))
    .filter((item) => item.text)
}

function orderedAchievementIds(values) {
  const out = []
  const seen = new Set()
  ;(Array.isArray(values) ? values : []).forEach((value) => {
    const text = String(value || '').trim()
    if (!text || seen.has(text)) return
    seen.add(text)
    out.push(text)
  })
  return out.slice(0, 5)
}

function buildFollowUpCandidates(row) {
  const selectedEmployees = Array.isArray(row?.selected_employees) ? row.selected_employees : []
  const selectedNameById = new Map(
    selectedEmployees
      .map((item) => [normalizeId(item?.id), item])
      .filter(([id]) => Boolean(id)),
  )
  const eventMap = new Map()
  ;(Array.isArray(row?.mail_events) ? row.mail_events : []).forEach((item) => {
    const employeeId = normalizeId(item?.employee_id)
    const status = String(item?.status || '').trim().toLowerCase()
    if (!employeeId || status !== 'sent') return
    const previous = eventMap.get(employeeId)
    const nextActionAt = new Date(item?.action_at || 0).getTime()
    const prevActionAt = new Date(previous?.action_at || 0).getTime()
    if (!previous || nextActionAt >= prevActionAt) {
      eventMap.set(employeeId, item)
    }
  })

  return Array.from(eventMap.entries())
    .map(([id, event]) => {
      const employee = selectedNameById.get(id)
      const name = String(employee?.name || event?.employee_name || '').trim() || `Employee #${id}`
      const email = String(employee?.email || event?.to_email || '').trim()
      const replied = Boolean(event?.got_replied)
      return {
        id,
        name,
        email,
        location_name: employeeLocationValue(employee),
        department: String(employee?.department || '').trim(),
        role: employeeRoleValue(employee),
        JobRole: employeeRoleValue(employee),
        replied,
        last_action_at: String(event?.action_at || '').trim(),
        last_action_label: formatShortDateTime(event?.action_at),
      }
    })
    .sort((left, right) => {
      if (left.replied !== right.replied) return left.replied ? -1 : 1
      return left.name.localeCompare(right.name)
    })
}

function syncLegacyAchievementFields(form, options) {
  const ids = orderedAchievementIds(form?.achievement_ids_ordered).slice(0, TRACKING_TEMPLATE_SLOT_COUNT)
  const first = (Array.isArray(options) ? options : []).find((item) => String(item?.id || '') === String(ids[0] || ''))
  return {
    ...form,
    achievement_ids_ordered: ids,
    template_ids_ordered: ids,
    achievement_id: first ? String(first.id) : '',
    achievement_name: first ? String(first.name || '') : '',
    achievement_text: first ? String(first.paragraph || '') : '',
  }
}

function categoryPriorityForTemplateSlot(category, index) {
  const normalizedCategory = String(category || 'general').trim().toLowerCase()
  if (index === 0) {
    if (normalizedCategory === 'opening') return 0
    if (normalizedCategory === 'experience') return 1
    if (normalizedCategory === 'general') return 2
    if (normalizedCategory === 'closing') return 3
    return 4
  }
  if (index === 1) {
    if (normalizedCategory === 'experience') return 0
    if (normalizedCategory === 'general') return 1
    if (normalizedCategory === 'opening') return 2
    if (normalizedCategory === 'closing') return 3
    return 4
  }
  if (index === 2) {
    if (normalizedCategory === 'closing') return 0
    if (normalizedCategory === 'general') return 1
    if (normalizedCategory === 'experience') return 2
    if (normalizedCategory === 'opening') return 3
    return 4
  }
  if (normalizedCategory === 'general') return 0
  if (normalizedCategory === 'experience') return 1
  if (normalizedCategory === 'closing') return 2
  if (normalizedCategory === 'opening') return 3
  return 4
}

function hardcodedAchievementOptionsForIndex(options, values, index) {
  const ids = Array.isArray(values) ? values.map((value) => String(value || '').trim()) : []
  const selectedByOthers = new Set(
    ids
      .map((value, currentIndex) => (currentIndex === index ? '' : value))
      .filter(Boolean),
  )
  return (Array.isArray(options) ? options : [])
    .filter((item) => !selectedByOthers.has(String(item?.id || '')))
    .sort((left, right) => {
      const categoryDiff = categoryPriorityForTemplateSlot(left?.category, index) - categoryPriorityForTemplateSlot(right?.category, index)
      if (categoryDiff !== 0) return categoryDiff
      return String(left?.name || '').localeCompare(String(right?.name || ''))
    })
}

function hardcodedAchievementSlotDisabled(values, index) {
  if (index === 0) return false
  const ids = Array.isArray(values) ? values : []
  return !String(ids[index - 1] || '').trim()
}

function updateHardcodedAchievementIds(values, index, nextValue) {
  const nextIds = Array.from(
    { length: TRACKING_TEMPLATE_SLOT_COUNT },
    (_, currentIndex) => String((Array.isArray(values) ? values[currentIndex] : '') || '').trim(),
  )
  nextIds[index] = String(nextValue || '').trim()
  for (let currentIndex = index + 1; currentIndex < nextIds.length; currentIndex += 1) {
    if (!nextIds[currentIndex - 1]) nextIds[currentIndex] = ''
  }
  return nextIds
}

function initialDepartmentFromRow(row) {
  const selectedEmployees = Array.isArray(row?.selected_employees) ? row.selected_employees : []
  const firstDepartment = String(selectedEmployees[0]?.department || '').trim()
  if (firstDepartment) return firstDepartment
  return ''
}

function initialEmployeeLocationFromRow(row) {
  const selectedEmployees = Array.isArray(row?.selected_employees) ? row.selected_employees : []
  const firstLocation = employeeLocationValue(selectedEmployees[0])
  if (firstLocation) return firstLocation
  return ''
}

function initialRoleFromRow(row) {
  const selectedEmployees = Array.isArray(row?.selected_employees) ? row.selected_employees : []
  const firstRole = employeeRoleValue(selectedEmployees[0])
  if (firstRole) return firstRole
  return ''
}

function localDateKey(value) {
  const date = value ? new Date(value) : null
  if (!date || Number.isNaN(date.getTime())) return ''
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function rowEmployeeNames(row) {
  return uniqueArray(
    (Array.isArray(row?.selected_employees) ? row.selected_employees : [])
      .map((item) => String(item?.name || '').trim()),
  )
}

function rowFreshNamesToday(row, todayKey) {
  const names = rowEmployeeNames(row)
  if (!todayKey || !names.length) return []
  const milestones = Array.isArray(row?.milestones) ? row.milestones : []
  const hasFreshToday = milestones.some((item) => String(item?.type || '').trim().toLowerCase() === 'fresh' && localDateKey(item?.at) === todayKey)
  return hasFreshToday ? names : []
}

function employeeNamesFromSelection(selectedIds, employees) {
  const selectedSet = new Set((Array.isArray(selectedIds) ? selectedIds : []).map((id) => String(id)))
  return uniqueArray(
    (Array.isArray(employees) ? employees : [])
      .filter((emp) => selectedSet.has(String(emp?.id)))
      .map((emp) => String(emp?.name || '').trim()),
  )
}

function buildImmediateTrackingRuleWarning({
  form,
  rows,
  employees,
  currentRowId = null,
  hasFreshMilestone = false,
  followUpCandidates = [],
}) {
  if (!form) return ''
  const mailType = String(form.mail_type || 'fresh').trim().toLowerCase()
  const todayKey = localDateKey(new Date())

  if (mailType === 'followed_up') {
    if (!hasFreshMilestone) return 'First time mail must be Fresh before any Follow Up mail.'
    if (!Array.isArray(followUpCandidates) || !followUpCandidates.length) {
      return 'No contacted employee is available for follow up yet. Send Fresh mail first.'
    }
    return ''
  }

  const selectedCompanyId = String(form.company || '').trim()
  const selectedJobId = String(form.job || '').trim()
  if (selectedCompanyId && selectedJobId) {
    const duplicateRow = (Array.isArray(rows) ? rows : []).find((row) => (
      Number(row?.id) !== Number(currentRowId || 0)
      && String(row?.mail_type || 'fresh').trim().toLowerCase() === 'fresh'
      && String(row?.company || '').trim() === selectedCompanyId
      && String(row?.job || '').trim() === selectedJobId
    ))
    if (duplicateRow) {
      const companyName = capitalizeFirstDisplay(duplicateRow?.company_name || '') || 'this company'
      const roleName = String(duplicateRow?.job_role || duplicateRow?.role || '').trim() || 'this job'
      return `Tracking already exists for ${companyName} | ${roleName}. Keep a single tracking row per company + job and edit the existing one instead.`
    }
  }

  const selectedNames = employeeNamesFromSelection(form.selected_hr_ids, employees)
  if (!selectedNames.length) return ''
  const selectedSet = new Set(selectedNames.map((name) => name.toLowerCase()))
  const overlap = uniqueArray(
    (Array.isArray(rows) ? rows : [])
      .filter((row) => Number(row?.id) !== Number(currentRowId || 0))
      .flatMap((row) => rowFreshNamesToday(row, todayKey))
      .filter((name) => selectedSet.has(String(name || '').trim().toLowerCase())),
  )
  if (overlap.length) {
    return `Fresh mail is already used today for: ${overlap.join(', ')}. Use Follow Up, choose different employees, or send tomorrow.`
  }
  return ''
}

function isImmediateRuleMessage(message) {
  const text = String(message || '').trim()
  if (!text) return false
  return [
    'Tracking already exists for ',
    'Fresh mail is already used today for:',
    'First time mail must be Fresh before any Follow Up mail.',
    'No contacted employee is available for follow up yet. Send Fresh mail first.',
  ].some((prefix) => text.startsWith(prefix))
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
  const [createFormError, setCreateFormError] = useState('')
  const [editFormError, setEditFormError] = useState('')
  const [filters, setFilters] = useState({
    companyName: '',
    jobId: '',
    appliedDate: '',
    mailed: 'all',
    lastAction: 'all',
  })
  const [ordering, setOrdering] = useState('-applied_at')
  const [selectedIds, setSelectedIds] = useState([])
  const [editForm, setEditForm] = useState(null)
  const [companyOptions, setCompanyOptions] = useState([])
  const [jobOptions, setJobOptions] = useState([])
  const [employeeOptions, setEmployeeOptions] = useState([])
  const [resumeOptions, setResumeOptions] = useState([])
  const [tailoredResumeOptions, setTailoredResumeOptions] = useState([])
  const [achievementOptions, setAchievementOptions] = useState([])
  const [subjectTemplateOptions, setSubjectTemplateOptions] = useState([])
  const [profileYoe, setProfileYoe] = useState('')
  const [profileFullName, setProfileFullName] = useState('')
  const [previewResume, setPreviewResume] = useState(null)
  const [employeePreview, setEmployeePreview] = useState(null)
  const [sendingRowId, setSendingRowId] = useState(null)
  const [sendConfirmRow, setSendConfirmRow] = useState(null)
  const [sendConfirmError, setSendConfirmError] = useState('')
  const prevCreateSubjectOptionsRef = useRef([])
  const prevEditSubjectOptionsRef = useRef([])
  const employeePreviewRef = useRef(null)

  const associatedResumeOptionsForJob = useCallback((jobId) => {
    const job = jobOptions.find((item) => String(item.id) === String(jobId || ''))
    if (!job) return []
    const options = Array.isArray(job.associated_resumes) ? [...job.associated_resumes] : []
    options.sort((a, b) => {
      return Number(b?.id || 0) - Number(a?.id || 0)
    })
    return options.map((item) => ({
      value: String(item.id),
      label: `${String(item.title || `Resume #${item.id}`)}${item.is_tailored ? ' | Tailored' : ' | Base'}`,
      isTailored: Boolean(item.is_tailored),
    }))
  }, [jobOptions])
  const load = useCallback(async () => {
    if (!access) {
      setRows([])
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const data = await fetchTrackingRows(access, {
        page,
        page_size: pageSize,
        company_name: filters.companyName.trim() || undefined,
        job_id: filters.jobId.trim() || undefined,
        applied_date: filters.appliedDate || undefined,
        mailed: filters.mailed !== 'all' ? filters.mailed : undefined,
        last_action: filters.lastAction !== 'all' ? filters.lastAction : undefined,
        ordering,
      })
      const list = Array.isArray(data?.results) ? data.results : (Array.isArray(data) ? data : [])
      setRows(list)
      setTotalCount(Number(data?.count || list.length || 0))
      setTotalPages(Number(data?.total_pages || 1))
      if (data?.page && Number(data.page) !== page) {
        setPage(Number(data.page))
      }
    } catch (err) {
      console.error(err.message || 'Failed to load tracking rows.')
    } finally {
      setLoading(false)
    }
  }, [access, filters, ordering, page, pageSize])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    setPage(1)
  }, [filters, ordering])

  useEffect(() => {
    if (!access) return
    ;(async () => {
      try {
        const [companyRows, resumesData, tailoredData, achievementsData, subjectTemplatesData, profileData] = await Promise.all([
          fetchAllCompanies(access, { scope: 'all', ready_for_tracking: true }),
          fetchResumes(access).catch(() => []),
          fetchTailoredResumes(access).catch(() => []),
          fetchTemplates(access).catch(() => []),
          fetchSubjectTemplates(access).catch(() => []),
          fetchProfile(access).catch(() => ({})),
        ])
        setCompanyOptions(companyRows)
        setResumeOptions(Array.isArray(resumesData) ? resumesData : [])
        setTailoredResumeOptions(Array.isArray(tailoredData) ? tailoredData : [])
        setAchievementOptions(Array.isArray(achievementsData) ? achievementsData : [])
        setSubjectTemplateOptions(Array.isArray(subjectTemplatesData) ? subjectTemplatesData : [])
        setProfileYoe(String(profileData?.years_of_experience || '').trim())
        setProfileFullName(String(profileData?.full_name || '').trim())
      } catch {
        setCompanyOptions([])
        setResumeOptions([])
        setTailoredResumeOptions([])
        setAchievementOptions([])
        setSubjectTemplateOptions([])
        setProfileYoe('')
        setProfileFullName('')
      }
    })()
  }, [access])

  const hydrateCompanyDependent = async (companyId) => {
    if (!companyId) {
      setJobOptions([])
      setEmployeeOptions([])
      return { jobs: [], employees: [] }
    }
    try {
      const [jobs, employeesData] = await Promise.all([
        fetchAllJobs(access, { company_id: companyId, scope: 'all', include_closed: false }),
        fetchEmployees(access, companyId, { scope: 'all' }),
      ])
      const emps = Array.isArray(employeesData) ? employeesData : []
      setJobOptions(jobs)
      setEmployeeOptions(emps)
      return { jobs, employees: emps }
    } catch {
      setJobOptions([])
      setEmployeeOptions([])
      return { jobs: [], employees: [] }
    }
  }

  const openCreateForm = () => {
    setCreateFormError('')
    setCreateForm({
      company: '',
      job: '',
      employee_location: '',
      department: '',
      employee_role: '',
      mail_type: 'fresh',
      send_mode: 'sent',
      schedule_time: '',
      has_attachment: false,
      achievement_id: '',
      achievement_ids_ordered: [],
      template_ids_ordered: [],
      personalized_template_id: '',
      use_hardcoded_personalized_intro: false,
      achievement_name: '',
      achievement_text: '',
      attachment_source: '',
      resume_id: '',
      tailored_resume_id: '',
      template_subject: '',
      interaction_time: nowDateTimeLocalValue(),
      interview_round: '',
      is_freezed: false,
      mailed: false,
      applied_date: toDateInput(new Date().toISOString()),
      posting_date: toDateInput(new Date().toISOString()),
      is_open: true,
      selected_hr_ids: [],
    })
  }

  const createRow = async () => {
    if (!createForm) return
    if (createBlockedMessage) {
      setCreateFormError(createBlockedMessage)
      return
    }
    if (!createForm.company) {
      setCreateFormError('Select company from dropdown.')
      return
    }
    if (!createForm.department) {
      setCreateFormError('Department is mandatory.')
      return
    }
    if (!Array.isArray(createForm.selected_hr_ids) || !createForm.selected_hr_ids.length) {
      setCreateFormError('Select at least one employee.')
      return
    }
    if (!createForm.job) {
      setCreateFormError('Job is mandatory.')
      return
    }
    const createAchievementIds = orderedAchievementIds(createForm.achievement_ids_ordered)
    if (!createForm.mail_type) {
      setCreateFormError('Mail Type is mandatory.')
      return
    }
    if (createForm.send_mode === 'scheduled' && !createForm.schedule_time) {
      setCreateFormError('Date & Time is mandatory for scheduled mail.')
      return
    }
    const selectedCompany = companyOptions.find((c) => String(c.id) === String(createForm.company))
    const selectedJob = jobOptions.find((j) => String(j.id) === String(createForm.job))
    const companyName = String(selectedCompany?.name || '').trim()
    const jobId = String(selectedJob?.job_id || '').trim()
    const role = String(selectedJob?.role || '').trim()
    const jobUrl = String(selectedJob?.job_link || '').trim()
    const createTemplateError = templateSelectionError(
      createForm.mail_type,
      createAchievementIds,
      createForm.mail_type === 'followed_up' ? followUpTemplateOptions : createAchievementOptionsForMode,
    )
    if (createTemplateError) {
      setCreateFormError(createTemplateError)
      return
    }
    if (createForm.mail_type !== 'followed_up' && createForm.use_hardcoded_personalized_intro && !String(createForm.personalized_template_id || '').trim()) {
      setCreateFormError('Select one Personalized template when personalized intro is checked.')
      return
    }
    if (createForm.mail_type === 'followed_up') {
      setCreateFormError('First time mail must be Fresh before any Folloup mail.')
      return
    }
    const resolvedScheduleTime = createForm.send_mode === 'scheduled'
      ? (createForm.schedule_time || nowDateTimeLocalValue())
      : null
    try {
      setCreateFormError('')
      const payload = {
        company: createForm.company || null,
        job: createForm.job || null,
        template: createAchievementIds[0] || null,
        template_id: createAchievementIds[0] || null,
        template_ids_ordered: createAchievementIds,
        personalized_template: createForm.mail_type === 'followed_up'
          ? null
          : (createForm.use_hardcoded_personalized_intro ? (createForm.personalized_template_id || null) : null),
        use_hardcoded_personalized_intro: Boolean(createForm.use_hardcoded_personalized_intro),
        achievement: createAchievementIds[0] || null,
        achievement_ids_ordered: createAchievementIds,
        company_name: companyName,
        job_id: jobId,
        role,
        job_url: jobUrl,
        schedule_time: resolvedScheduleTime,
        mail_type: createForm.mail_type || 'fresh',
        template_subject: String(createForm.template_subject || '').trim(),
        interaction_time: String(createForm.interaction_time || '').trim(),
        interview_round: String(createForm.interview_round || '').trim(),
        resume: createForm.has_attachment ? (createForm.resume_id || null) : null,
        tailored_resume: createForm.has_attachment ? (createForm.tailored_resume_id || null) : null,
        is_freezed: Boolean(createForm.is_freezed),
        mailed: Boolean(createForm.mailed),
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
      setCreateFormError(err.message || 'Could not create tracking row.')
    }
  }

  const openEditForm = async (row) => {
    setEditFormError('')
    try {
      const fullRow = await fetchTrackingRow(access, row.id).catch(() => row)
      const hydrated = await hydrateCompanyDependent(fullRow.company || '')
      const matchingJob = (Array.isArray(hydrated?.jobs) ? hydrated.jobs : []).find((job) => String(job.id) === String(fullRow.job || ''))
      const associatedRows = Array.isArray(matchingJob?.associated_resumes) ? matchingJob.associated_resumes : []
      const associatedResumeIdSet = new Set(associatedRows.map((item) => String(item?.id || '')))
      const attachmentSource = fullRow.tailored_resume
        ? (associatedResumeIdSet.has(String(fullRow.tailored_resume)) ? 'associated' : 'tailored')
        : (fullRow.resume_preview?.id
          ? (associatedResumeIdSet.has(String(fullRow.resume_preview.id)) ? 'associated' : 'base')
          : '')
      setEditForm({
        id: fullRow.id,
        company: fullRow.company || '',
        job: fullRow.job || '',
        employee_location: initialEmployeeLocationFromRow(fullRow),
        department: initialDepartmentFromRow(fullRow),
        employee_role: initialRoleFromRow(fullRow),
        company_name: fullRow.company_name || '',
        job_id: fullRow.job_id || '',
        role: fullRow.role || '',
        job_url: fullRow.job_url || '',
        mail_type: String(fullRow.mail_type || 'fresh').trim() || 'fresh',
        send_mode: fullRow.schedule_time ? 'scheduled' : 'sent',
        initial_action_type: rowLastActionType(fullRow) || '',
        initial_send_mode: fullRow.schedule_time ? 'scheduled' : 'sent',
        initial_milestone_count: Array.isArray(fullRow.milestones) ? fullRow.milestones.length : 0,
        has_fresh_milestone: rowHasFreshMilestone(fullRow),
        initial_mail_type: String(fullRow.mail_type || 'fresh').trim() || 'fresh',
        initial_selected_hr_ids: Array.isArray(fullRow.selected_hr_ids) ? fullRow.selected_hr_ids.map((id) => String(id)) : [],
        schedule_time: toDateTimeLocalInput(fullRow.schedule_time),
        has_attachment: Boolean(fullRow.resume_preview || fullRow.tailored_resume),
        achievement_id: fullRow.achievement_id ? String(fullRow.achievement_id) : '',
        achievement_ids_ordered: Array.isArray(fullRow.achievement_ids_ordered) && fullRow.achievement_ids_ordered.length
          ? fullRow.achievement_ids_ordered.map((id) => String(id)).slice(0, TRACKING_TEMPLATE_SLOT_COUNT)
          : (String(fullRow.mail_type || 'fresh').trim() === 'followed_up' && fullRow.personalized_template_id
            ? [String(fullRow.personalized_template_id)]
            : (fullRow.achievement_id ? [String(fullRow.achievement_id)] : [])),
        template_ids_ordered: Array.isArray(fullRow.template_ids_ordered)
          ? fullRow.template_ids_ordered.map((id) => String(id)).slice(0, TRACKING_TEMPLATE_SLOT_COUNT)
          : (Array.isArray(fullRow.achievement_ids_ordered)
            ? fullRow.achievement_ids_ordered.map((id) => String(id)).slice(0, TRACKING_TEMPLATE_SLOT_COUNT)
            : (fullRow.achievement_id ? [String(fullRow.achievement_id)] : [])),
        personalized_template_id: fullRow.personalized_template_id ? String(fullRow.personalized_template_id) : '',
        use_hardcoded_personalized_intro: Boolean(fullRow.use_hardcoded_personalized_intro),
        template_subject: String(fullRow.template_subject || '').trim(),
        interaction_time: toDateTimeLocalInput(fullRow.interaction_time) || '',
        interview_round: String(fullRow.interview_round || '').trim(),
        achievement_name: fullRow.achievement_name || '',
        achievement_text: fullRow.achievement_text || '',
        attachment_source: attachmentSource,
        resume_id: fullRow.resume_preview?.id ? String(fullRow.resume_preview.id) : '',
        tailored_resume_id: fullRow.tailored_resume ? String(fullRow.tailored_resume) : '',
        is_freezed: Boolean(fullRow.is_freezed),
        mailed: Boolean(fullRow.mailed),
        applied_date: toDateInput(fullRow.applied_date),
        posting_date: toDateInput(fullRow.posting_date),
        is_open: Boolean(fullRow.is_open),
        selected_hr_ids: Array.isArray(fullRow.selected_hr_ids) ? fullRow.selected_hr_ids.map((id) => String(id)) : [],
        follow_thread_id: Array.isArray(fullRow.selected_hr_ids) && fullRow.selected_hr_ids.length ? String(fullRow.selected_hr_ids[0]) : '',
        follow_thread_ids: Array.isArray(fullRow.selected_hr_ids) ? fullRow.selected_hr_ids.map((id) => String(id)) : [],
        selected_employees: Array.isArray(fullRow.selected_employees) ? fullRow.selected_employees : [],
        mail_events: Array.isArray(fullRow.mail_events) ? fullRow.mail_events : [],
      })
    } catch (err) {
      setEditFormError(err.message || 'Could not load tracking row.')
    }
  }

  const saveEditForm = async () => {
    if (!editForm) return
    if (editBlockedMessage) {
      setEditFormError(editBlockedMessage)
      return
    }
    if (!editForm.company) {
      setEditFormError('Select company from dropdown.')
      return
    }
    if (!editForm.department) {
      setEditFormError('Department is mandatory.')
      return
    }
    if (!Array.isArray(editForm.selected_hr_ids) || !editForm.selected_hr_ids.length) {
      setEditFormError(editForm.mail_type === 'followed_up' ? 'Select at least one thread.' : 'Select at least one employee.')
      return
    }
    if (!editForm.job) {
      setEditFormError('Job is mandatory.')
      return
    }
    const editAchievementIds = orderedAchievementIds(editForm.achievement_ids_ordered)
    if (!editForm.mail_type) {
      setEditFormError('Mail Type is mandatory.')
      return
    }
    if (editForm.send_mode === 'scheduled' && !editForm.schedule_time) {
      setEditFormError('Date & Time is mandatory for scheduled mail.')
      return
    }
    const selectedCompany = companyOptions.find((c) => String(c.id) === String(editForm.company))
    const selectedJob = jobOptions.find((j) => String(j.id) === String(editForm.job))
    const companyName = String(selectedCompany?.name || editForm.company_name || '').trim()
    const jobId = String(selectedJob?.job_id || editForm.job_id || '').trim()
    const role = String(selectedJob?.role || editForm.role || '').trim()
    const jobUrl = String(selectedJob?.job_link || editForm.job_url || '').trim()
    const editTemplateError = templateSelectionError(
      editForm.mail_type,
      editAchievementIds,
      editForm.mail_type === 'followed_up' ? followUpTemplateOptions : editAchievementOptionsForMode,
    )
    if (editTemplateError) {
      setEditFormError(editTemplateError)
      return
    }
    if (editForm.mail_type !== 'followed_up' && editForm.use_hardcoded_personalized_intro && !String(editForm.personalized_template_id || '').trim()) {
      setEditFormError('Select one Personalized template when personalized intro is checked.')
      return
    }
    if (editForm.mail_type === 'followed_up' && !editHasFreshMilestone) {
      setEditFormError('First time mail must be Fresh before any Follow Up mail.')
      return
    }
    if (editForm.mail_type === 'followed_up' && !editFollowUpCandidateIds.length) {
      setEditFormError('No contacted employee is available for follow up yet. Send Fresh mail first.')
      return
    }
    const resolvedScheduleTime = editForm.send_mode === 'scheduled'
      ? (editForm.schedule_time || nowDateTimeLocalValue())
      : null
    const selectedHrIds = Array.isArray(editForm.selected_hr_ids) ? editForm.selected_hr_ids : []
    if (editForm.mail_type === 'followed_up') {
      const allowedIds = new Set(editFollowUpCandidateIds.map((id) => String(id)))
      const followThreadIds = Array.isArray(editForm.follow_thread_ids) ? editForm.follow_thread_ids.map((id) => String(id)) : []
      const effectiveSelectedIds = followThreadIds.length ? followThreadIds : (editForm.follow_thread_id ? [String(editForm.follow_thread_id)] : selectedHrIds)
      if (!effectiveSelectedIds.length) {
        setEditFormError('At least one Follow Thread ID is mandatory.')
        return
      }
      const invalidIds = effectiveSelectedIds.filter((id) => !allowedIds.has(String(id)))
      if (invalidIds.length) {
        setEditFormError('Follow up can only be sent to employees who already received mail in this tracking row.')
        return
      }
    }
    const basePayload = {
      company: editForm.company || null,
      job: editForm.job || null,
      template: editAchievementIds[0] || null,
      template_id: editAchievementIds[0] || null,
      template_ids_ordered: editAchievementIds,
      personalized_template: editForm.mail_type === 'followed_up'
        ? null
        : (editForm.use_hardcoded_personalized_intro ? (editForm.personalized_template_id || null) : null),
      use_hardcoded_personalized_intro: Boolean(editForm.use_hardcoded_personalized_intro),
      achievement: editAchievementIds[0] || null,
      achievement_ids_ordered: editAchievementIds,
      company_name: companyName,
      job_id: jobId,
      role,
      job_url: jobUrl,
      schedule_time: resolvedScheduleTime,
      mail_type: editForm.mail_type || 'fresh',
      template_subject: String(editForm.template_subject || '').trim(),
      interaction_time: String(editForm.interaction_time || '').trim(),
      interview_round: String(editForm.interview_round || '').trim(),
      resume: editForm.resume_id || null,
      tailored_resume: editForm.tailored_resume_id || null,
      is_freezed: Boolean(editForm.is_freezed),
      applied_date: editForm.applied_date || null,
      posting_date: editForm.posting_date || null,
      is_open: editForm.is_open,
      selected_hr_ids: editForm.mail_type === 'followed_up'
        ? ((Array.isArray(editForm.follow_thread_ids) && editForm.follow_thread_ids.length)
          ? editForm.follow_thread_ids.map((id) => String(id))
          : (editForm.follow_thread_id ? [String(editForm.follow_thread_id)] : selectedHrIds))
        : selectedHrIds,
    }
    try {
      setEditFormError('')
      const payload = {
        ...basePayload,
        mailed: false,
        mail_delivery_status: 'pending',
        resume: editForm.has_attachment ? (editForm.resume_id || null) : null,
        tailored_resume: editForm.has_attachment ? (editForm.tailored_resume_id || null) : null,
      }
      await updateTrackingRow(access, editForm.id, payload)
      const refreshed = await fetchTrackingRow(access, editForm.id).catch(() => null)
      const nextRow = refreshed || {
        ...rows.find((row) => row.id === editForm.id),
        ...payload,
        id: editForm.id,
      }
      setRows((prev) => prev.map((row) => (row.id === editForm.id ? nextRow : row)))
      setEditForm(null)
      await load()
    } catch (err) {
      setEditFormError(err.message || 'Could not save tracking row.')
    }
  }

  const removeRow = async (rowId) => {
    try {
      await deleteTrackingRow(access, rowId)
      await load()
    } catch (err) {
      console.error(err.message || 'Could not delete row.')
    }
  }

  const sendRowImmediately = async (row) => {
    if (!row || !row.id) return
    if (row.is_freezed) return
    try {
      setSendConfirmError('')
      const fullRow = await fetchTrackingRow(access, row.id).catch(() => row)
      setSendConfirmRow(fullRow || row)
    } catch (err) {
      setSendConfirmError(err.message || 'Could not load send details.')
      setSendConfirmRow(row)
    }
  }

  const confirmSendRowImmediately = async () => {
    const row = sendConfirmRow
    if (!row || !row.id) return
    try {
      setSendingRowId(row.id)
      const fullRow = await fetchTrackingRow(access, row.id)
      const templateIds = Array.isArray(fullRow?.template_ids_ordered) && fullRow.template_ids_ordered.length
        ? fullRow.template_ids_ordered.map((id) => String(id))
        : (Array.isArray(fullRow?.achievement_ids_ordered) && fullRow.achievement_ids_ordered.length
          ? fullRow.achievement_ids_ordered.map((id) => String(id))
          : (fullRow?.template_id ? [String(fullRow.template_id)] : []))
      const payload = {
        company: fullRow?.company || null,
        job: fullRow?.job || null,
        template: templateIds[0] || null,
        template_id: templateIds[0] || null,
        template_ids_ordered: templateIds,
        personalized_template: fullRow?.personalized_template_id || null,
        use_hardcoded_personalized_intro: Boolean(fullRow?.use_hardcoded_personalized_intro),
        achievement: templateIds[0] || null,
        achievement_ids_ordered: templateIds,
        company_name: fullRow?.company_name || '',
        job_id: fullRow?.job_id || '',
        role: fullRow?.role || '',
        job_url: fullRow?.job_url || '',
        schedule_time: null,
        mail_type: fullRow?.mail_type || 'fresh',
        template_subject: String(fullRow?.template_subject || '').trim(),
        interaction_time: String(fullRow?.interaction_time || '').trim(),
        interview_round: String(fullRow?.interview_round || '').trim(),
        resume: fullRow?.resume_preview?.id || null,
        tailored_resume: fullRow?.tailored_resume || null,
        is_freezed: Boolean(fullRow?.is_freezed),
        applied_date: fullRow?.applied_date || null,
        posting_date: fullRow?.posting_date || null,
        is_open: Boolean(fullRow?.is_open),
        selected_hr_ids: Array.isArray(fullRow?.selected_hr_ids) ? fullRow.selected_hr_ids.map((id) => String(id)) : [],
        send_now: true,
      }

      const updated = await updateTrackingRow(access, row.id, payload)
      setRows((prev) => prev.map((item) => (item.id === row.id ? updated : item)))
      setSendConfirmRow(null)
      setSendConfirmError('')
      await load()
    } catch (err) {
      setSendConfirmError(err.message || 'Could not send tracking mail immediately.')
    } finally {
      setSendingRowId(null)
    }
  }

  const bulkDeleteSelected = async () => {
    if (!selectedIds.length) return
    try {
      await Promise.allSettled(selectedIds.map((id) => deleteTrackingRow(access, id)))
      setSelectedIds([])
      await load()
    } catch (err) {
      console.error(err.message || 'Could not delete selected tracking rows.')
    }
  }

  const bulkFreezeSelected = async () => {
    if (!selectedIds.length) return
    try {
      const targetRows = filteredRows.filter((row) => selectedIds.includes(row.id))
      await Promise.allSettled(
        targetRows.map((row) => updateTrackingRow(access, row.id, { is_freezed: true })),
      )
      setSelectedIds([])
      await load()
    } catch (err) {
      console.error(err.message || 'Could not freeze selected tracking rows.')
    }
  }

  const filteredRows = useMemo(() => rows, [rows])
  const trackingStats = useMemo(() => {
    const visibleRows = filteredRows.length
    const mailedCount = filteredRows.filter((row) => row?.mailed).length
    const scheduledCount = filteredRows.filter((row) => String(rowLastSendMode(row)).toLowerCase() === 'scheduled').length
    const freezedCount = filteredRows.filter((row) => row?.is_freezed).length
    return [
      `${visibleRows} visible`,
      `${mailedCount} mailed`,
      `${scheduledCount} scheduled`,
      `${freezedCount} freezed`,
      `${selectedIds.length} selected`,
    ]
  }, [filteredRows, selectedIds])

  const createAssociatedResumeOptions = useMemo(
    () => (createForm?.job ? associatedResumeOptionsForJob(createForm.job) : []),
    [associatedResumeOptionsForJob, createForm?.job],
  )
  const editAssociatedResumeOptions = useMemo(
    () => (editForm?.job ? associatedResumeOptionsForJob(editForm.job) : []),
    [associatedResumeOptionsForJob, editForm?.job],
  )
  const baseResumeDropdownOptions = useMemo(
    () => (Array.isArray(resumeOptions) ? resumeOptions : []).map((item) => ({
      value: String(item.id),
      label: String(item.title || `Resume #${item.id}`),
    })),
    [resumeOptions],
  )
  const tailoredResumeDropdownOptions = useMemo(
    () => (Array.isArray(tailoredResumeOptions) ? tailoredResumeOptions : []).map((item) => ({
      value: String(item.id),
      label: String(item.name || item.title || `Tailored #${item.id}`),
    })),
    [tailoredResumeOptions],
  )
  const activeEmployeeOptions = useMemo(
    () => (Array.isArray(employeeOptions) ? employeeOptions.filter((emp) => emp?.working_mail !== false) : []),
    [employeeOptions],
  )
  const createSelectedJob = useMemo(
    () => (Array.isArray(jobOptions) ? jobOptions.find((job) => String(job.id) === String(createForm?.job || '')) : null),
    [jobOptions, createForm?.job],
  )
  const editSelectedJob = useMemo(
    () => (Array.isArray(jobOptions) ? jobOptions.find((job) => String(job.id) === String(editForm?.job || '')) : null),
    [jobOptions, editForm?.job],
  )
  const createSelectedJobLocation = useMemo(
    () => jobLocationValue(createSelectedJob),
    [createSelectedJob],
  )
  const editSelectedJobLocation = useMemo(
    () => jobLocationValue(editSelectedJob),
    [editSelectedJob],
  )
  const createCompanyDropdownOptions = useMemo(
    () => companyDropdownOptions(companyOptions, createForm?.company),
    [companyOptions, createForm?.company],
  )
  const editCompanyDropdownOptions = useMemo(
    () => companyDropdownOptions(companyOptions, editForm?.company, editForm?.company_name),
    [companyOptions, editForm?.company, editForm?.company_name],
  )
  const createEmployeeLocationOptions = useMemo(
    () => sortTextValues(activeEmployeeOptions.map((emp) => employeeLocationValue(emp))),
    [activeEmployeeOptions],
  )
  const editEmployeeLocationOptions = useMemo(
    () => sortTextValues(activeEmployeeOptions.map((emp) => employeeLocationValue(emp))),
    [activeEmployeeOptions],
  )
  const createScopedEmployeeOptions = useMemo(
    () => activeEmployeeOptions.filter((emp) => {
      if (!String(createForm?.employee_location || '').trim()) return true
      return employeeLocationValue(emp) === String(createForm?.employee_location || '').trim()
    }),
    [activeEmployeeOptions, createForm?.employee_location],
  )
  const editScopedEmployeeOptions = useMemo(
    () => activeEmployeeOptions.filter((emp) => {
      if (!String(editForm?.employee_location || '').trim()) return true
      return employeeLocationValue(emp) === String(editForm?.employee_location || '').trim()
    }),
    [activeEmployeeOptions, editForm?.employee_location],
  )
  const createSubjectOptions = useMemo(
    () => subjectOptionsForForm(createForm, companyOptions, jobOptions, profileYoe, subjectTemplateOptions, profileFullName),
    [createForm, companyOptions, jobOptions, profileYoe, subjectTemplateOptions, profileFullName],
  )
  const editSubjectOptions = useMemo(
    () => subjectOptionsForForm(editForm, companyOptions, jobOptions, profileYoe, subjectTemplateOptions, profileFullName),
    [editForm, companyOptions, jobOptions, profileYoe, subjectTemplateOptions, profileFullName],
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
  const editHasFreshMilestone = useMemo(
    () => (editForm ? Boolean(editForm.has_fresh_milestone) : false),
    [editForm],
  )
  const editMailTypeOptions = useMemo(
    () => mailTypeOptionsForRow(editHasFreshMilestone),
    [editHasFreshMilestone],
  )
  const editFollowUpCandidates = useMemo(
    () => buildFollowUpCandidates(editForm),
    [editForm],
  )
  const editFollowUpCandidateIds = useMemo(
    () => editFollowUpCandidates.map((item) => item.id),
    [editFollowUpCandidates],
  )
  const createDepartmentOptions = useMemo(
    () => sortTextValues(createScopedEmployeeOptions.map((emp) => String(emp.department || '').trim())),
    [createScopedEmployeeOptions],
  )
  const editDepartmentOptions = useMemo(
    () => sortTextValues(editScopedEmployeeOptions.map((emp) => String(emp.department || '').trim())),
    [editScopedEmployeeOptions],
  )
  const createRoleOptions = useMemo(
    () => sortTextValues(
      createScopedEmployeeOptions
        .filter((emp) => !createForm?.department || String(emp.department || '').trim() === String(createForm?.department || '').trim())
        .map((emp) => employeeRoleValue(emp))
    ),
    [createScopedEmployeeOptions, createForm?.department],
  )
  const editRoleOptions = useMemo(
    () => sortTextValues(
      editScopedEmployeeOptions
        .filter((emp) => !editForm?.department || String(emp.department || '').trim() === String(editForm?.department || '').trim())
        .map((emp) => employeeRoleValue(emp))
    ),
    [editScopedEmployeeOptions, editForm?.department],
  )
  const createEmployeeDropdownOptions = useMemo(
    () => createScopedEmployeeOptions
      .filter((emp) => !createForm?.department || String(emp.department || '').trim() === String(createForm?.department || '').trim())
      .filter((emp) => !createForm?.employee_role || employeeRoleValue(emp) === String(createForm?.employee_role || '').trim())
      .map((emp) => ({ value: String(emp.id), label: String(emp.name || '') })),
    [createScopedEmployeeOptions, createForm?.department, createForm?.employee_role],
  )
  const editEmployeeDropdownOptions = useMemo(
    () => {
      const source = String(editForm?.mail_type || '').trim() === 'followed_up'
        ? editFollowUpCandidates
        : editScopedEmployeeOptions
      return source
        .filter((emp) => !editForm?.employee_location || employeeLocationValue(emp) === String(editForm?.employee_location || '').trim())
        .filter((emp) => !editForm?.department || String(emp.department || '').trim() === String(editForm?.department || '').trim())
        .filter((emp) => !editForm?.employee_role || employeeRoleValue(emp) === String(editForm?.employee_role || '').trim())
        .map((emp) => ({ value: String(emp.id), label: String(emp.name || '') }))
    },
    [editScopedEmployeeOptions, editFollowUpCandidates, editForm?.employee_location, editForm?.department, editForm?.employee_role, editForm?.mail_type],
  )
  const editFollowThreadOptions = useMemo(
    () => editFollowUpCandidates.map((item) => ({
      value: String(item.id),
      label: [
        `Thread ID ${item.id}`,
        item.name,
        item.last_action_label || '',
        item.replied ? 'replied' : '',
      ].filter(Boolean).join(' | '),
    })),
    [editFollowUpCandidates],
  )
  const createAchievementDropdownOptions = useMemo(
    () => mergeAchievementOptions(achievementOptions, { id: createForm?.achievement_id }),
    [achievementOptions, createForm?.achievement_id],
  )
  const editAchievementDropdownOptions = useMemo(
    () => mergeAchievementOptions(achievementOptions, {
      id: editForm?.achievement_id,
      name: editForm?.achievement_name,
      text: editForm?.achievement_text,
    }),
    [achievementOptions, editForm?.achievement_id, editForm?.achievement_name, editForm?.achievement_text],
  )
  const createAchievementOptionsForMode = useMemo(
    () => filterAchievementOptionsForMode(createAchievementDropdownOptions),
    [createAchievementDropdownOptions],
  )
  const editAchievementOptionsForMode = useMemo(
    () => filterAchievementOptionsForMode(editAchievementDropdownOptions),
    [editAchievementDropdownOptions],
  )
  const personalizedTemplateOptions = useMemo(
    () => (Array.isArray(achievementOptions) ? achievementOptions : [])
      .filter((item) => String(item?.category || '').trim().toLowerCase() === 'personalized')
      .map((item) => ({
        ...item,
        value: String(item.id),
        label: formatTemplateLibraryLabel(item),
      })),
    [achievementOptions],
  )
  const followUpTemplateOptions = useMemo(
    () => (Array.isArray(achievementOptions) ? achievementOptions : [])
      .filter((item) => String(item?.category || '').trim().toLowerCase() === 'follow_up')
      .map((item) => ({
        ...item,
        value: String(item.id),
        label: formatTemplateLibraryLabel(item),
      })),
    [achievementOptions],
  )
  const createSelectedTemplatePreviews = useMemo(
    () => selectedTemplatePreviewRows(
      createForm?.achievement_ids_ordered,
      String(createForm?.mail_type || '').trim() === 'followed_up' ? followUpTemplateOptions : createAchievementOptionsForMode,
    ),
    [createForm?.achievement_ids_ordered, createForm?.mail_type, createAchievementOptionsForMode, followUpTemplateOptions],
  )
  const editSelectedTemplatePreviews = useMemo(
    () => selectedTemplatePreviewRows(
      editForm?.achievement_ids_ordered,
      String(editForm?.mail_type || '').trim() === 'followed_up' ? followUpTemplateOptions : editAchievementOptionsForMode,
    ),
    [editForm?.achievement_ids_ordered, editForm?.mail_type, editAchievementOptionsForMode, followUpTemplateOptions],
  )
  const createSelectedPersonalizedPreview = useMemo(
    () => selectedTemplatePreviewRows(
      createForm?.personalized_template_id ? [createForm.personalized_template_id] : [],
      personalizedTemplateOptions,
    ),
    [createForm?.personalized_template_id, personalizedTemplateOptions],
  )
  const editSelectedPersonalizedPreview = useMemo(
    () => selectedTemplatePreviewRows(
      editForm?.personalized_template_id ? [editForm.personalized_template_id] : [],
      personalizedTemplateOptions,
    ),
    [editForm?.personalized_template_id, personalizedTemplateOptions],
  )
  const createImmediateRuleWarning = useMemo(
    () => buildImmediateTrackingRuleWarning({
      form: createForm,
      rows,
      employees: activeEmployeeOptions,
      hasFreshMilestone: false,
      followUpCandidates: [],
    }),
    [createForm, rows, activeEmployeeOptions],
  )
  const editImmediateRuleWarning = useMemo(
    () => buildImmediateTrackingRuleWarning({
      form: editForm,
      rows,
      employees: activeEmployeeOptions,
      currentRowId: editForm?.id,
      hasFreshMilestone: editHasFreshMilestone,
      followUpCandidates: editFollowUpCandidates,
    }),
    [editForm, rows, activeEmployeeOptions, editHasFreshMilestone, editFollowUpCandidates],
  )
  const createEmployeeFilterLocked = !createForm?.company || !createForm?.department
  const editEmployeeFilterLocked = !editForm?.company || !editForm?.department
  const createBlockedMessage = createForm?.mail_type === 'followed_up'
    ? createImmediateRuleWarning
    : (createEmployeeFilterLocked ? 'Select company and department before choosing employees.' : createImmediateRuleWarning)
  const editBlockedMessage = editForm?.mail_type === 'followed_up'
    ? editImmediateRuleWarning
    : (editEmployeeFilterLocked ? 'Select company and department before choosing employees.' : editImmediateRuleWarning)
  const createSaveBlocked = Boolean(createBlockedMessage)
  const editSaveBlocked = Boolean(editBlockedMessage)
  const allSelected = filteredRows.length > 0 && filteredRows.every((row) => selectedIds.includes(row.id))
  useEffect(() => {
    if (!createForm) return
    setCreateFormError((prev) => {
      if (createBlockedMessage) return createBlockedMessage
      return isImmediateRuleMessage(prev) ? '' : prev
    })
  }, [createForm, createBlockedMessage])

  useEffect(() => {
    if (!editForm) return
    setEditFormError((prev) => {
      if (editBlockedMessage) return editBlockedMessage
      return isImmediateRuleMessage(prev) ? '' : prev
    })
  }, [editForm, editBlockedMessage])

  useEffect(() => {
    if (!createForm) return
    const currentChoice = String(createForm.template_choice || '').trim()
    if (!currentChoice) return
    if (isTemplateAllowed(currentChoice, createDepartmentBuckets, createForm.mail_type)) return
    setCreateForm((prev) => ({
      ...prev,
      template_choice: '',
      template_subject: '',
      template_name: '',
      schedule_time: '',
      compose_mode: 'hardcoded',
      hardcoded_follow_up: true,
    }))
  }, [createForm, createDepartmentBuckets])

  useEffect(() => {
    if (!editForm) return
    const currentChoice = String(editForm.template_choice || '').trim()
    if (!currentChoice) return
    if (isTemplateAllowed(currentChoice, editDepartmentBuckets, editForm.mail_type)) return
    setEditForm((prev) => ({
      ...prev,
      template_choice: '',
      template_subject: '',
      template_name: '',
      schedule_time: '',
      compose_mode: 'hardcoded',
      hardcoded_follow_up: true,
    }))
  }, [editForm, editDepartmentBuckets])

  useEffect(() => {
    if (!editForm) return
    if (String(editForm.mail_type || '').trim() !== 'followed_up') return
    const candidateSet = new Set(editFollowUpCandidateIds)
    const selectedIds = Array.isArray(editForm.selected_hr_ids) ? editForm.selected_hr_ids.map((id) => String(id)) : []
    const nextSelected = selectedIds.filter((id) => candidateSet.has(String(id)))
    if (nextSelected.length === selectedIds.length) return
    setEditForm((prev) => {
      if (!prev || String(prev.mail_type || '').trim() !== 'followed_up') return prev
      const currentIds = Array.isArray(prev.selected_hr_ids) ? prev.selected_hr_ids.map((id) => String(id)) : []
      const currentNext = currentIds.filter((id) => candidateSet.has(String(id)))
      return {
        ...prev,
        selected_hr_ids: currentNext.length ? currentNext : [...editFollowUpCandidateIds],
        follow_thread_id: currentNext[0] || editFollowUpCandidateIds[0] || '',
      }
    })
  }, [editForm, editFollowUpCandidateIds])

  useEffect(() => {
    if (!createForm) return
    const currentSubject = String(createForm.template_subject || '').trim()
    const firstOption = createSubjectOptions[0]?.value || ''
    if (!firstOption) return
    const previousOptions = Array.isArray(prevCreateSubjectOptionsRef.current) ? prevCreateSubjectOptionsRef.current : []
    const shouldRefresh = !currentSubject || (previousOptions.includes(currentSubject) && !createSubjectOptions.some((item) => item?.value === currentSubject))
    if (shouldRefresh) {
      setCreateForm((prev) => (prev ? { ...prev, template_subject: firstOption } : prev))
    }
    prevCreateSubjectOptionsRef.current = createSubjectOptions.map((item) => item?.value).filter(Boolean)
  }, [createForm, createSubjectOptions])

  useEffect(() => {
    if (!editForm) return
    const currentSubject = String(editForm.template_subject || '').trim()
    const firstOption = editSubjectOptions[0]?.value || ''
    if (!firstOption) return
    const previousOptions = Array.isArray(prevEditSubjectOptionsRef.current) ? prevEditSubjectOptionsRef.current : []
    const shouldRefresh = !currentSubject || (previousOptions.includes(currentSubject) && !editSubjectOptions.some((item) => item?.value === currentSubject))
    if (shouldRefresh) {
      setEditForm((prev) => (prev ? { ...prev, template_subject: firstOption } : prev))
    }
    prevEditSubjectOptionsRef.current = editSubjectOptions.map((item) => item?.value).filter(Boolean)
  }, [editForm, editSubjectOptions])

  useEffect(() => {
    if (!employeePreview) return
    const handlePointerDown = (event) => {
      if (employeePreviewRef.current && !employeePreviewRef.current.contains(event.target)) {
        setEmployeePreview(null)
      }
    }
    document.addEventListener('mousedown', handlePointerDown)
    return () => document.removeEventListener('mousedown', handlePointerDown)
  }, [employeePreview])

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
    <main className="page page-wide mx-auto w-full">
      <div className="tracking-head">
        <div>
          <h1>Tracking</h1>
          <p className="subtitle">Manage fresh mails, follow-ups, schedules, and milestones from one clean panel.</p>
          <p className="hint">Recommendation: always use the Test Mail panel before Manual Send or Schedule so you can verify the final subject and body first.</p>
        </div>
        <div className="actions">
          <button type="button" className="secondary" onClick={bulkFreezeSelected} disabled={!selectedIds.length || loading}>Mark Freezed</button>
          <button type="button" className="secondary" onClick={bulkDeleteSelected} disabled={!selectedIds.length || loading}>Delete Selected</button>
          <button type="button" className="secondary" onClick={openCreateForm}>Add Tracking</button>
        </div>
      </div>

      <div className="tracking-summary-bar">
        {trackingStats.map((item) => (
          <span key={item} className="tracking-summary-chip">{item}</span>
        ))}
      </div>

      <section className="tracking-filters filters-one-row">
        <label>Company Name<input value={filters.companyName} placeholder="Search company" onChange={(event) => setFilters((prev) => ({ ...prev, companyName: event.target.value }))} /></label>
        <label>Job ID<input value={filters.jobId} placeholder="Search job ID" onChange={(event) => setFilters((prev) => ({ ...prev, jobId: event.target.value }))} /></label>
        <label>Applied Date<input type="date" value={filters.appliedDate} onChange={(event) => setFilters((prev) => ({ ...prev, appliedDate: event.target.value }))} /></label>
        <label>Mailed<select value={filters.mailed} onChange={(event) => setFilters((prev) => ({ ...prev, mailed: event.target.value }))}><option value="all">All</option><option value="yes">Yes</option><option value="no">No</option></select></label>
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
              <th>Status</th>
              <th>Mailed</th>
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
              const visibleEmployeeNames = selectedHrValues.slice(0, 2)
              const hiddenEmployeeCount = Math.max(0, selectedHrValues.length - visibleEmployeeNames.length)
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
                    <td className="tracking-primary-cell">{capitalizeFirstDisplay(row.company_name) || '-'}</td>
                    <td className="tracking-mono-cell">{row.job_id || '-'}</td>
                    <td className="tracking-employee-cell">
                      <div className="tracking-employee-summary" ref={employeePreview?.rowId === row.id ? employeePreviewRef : null}>
                        <span className="tracking-employee-summary-text">
                          {selectedHrValues.length ? visibleEmployeeNames.join(', ') : '-'}
                        </span>
                        {hiddenEmployeeCount ? (
                          <button
                            type="button"
                            className="tracking-employee-more-btn"
                            onClick={() => setEmployeePreview((prev) => (
                              prev?.rowId === row.id
                                ? null
                                : {
                                  rowId: row.id,
                                  companyName: row.company_name || '',
                                  jobId: row.job_id || '',
                                  employees: selectedHrValues,
                                }
                            ))}
                          >
                            +{hiddenEmployeeCount}
                          </button>
                        ) : null}
                        {employeePreview?.rowId === row.id ? (
                          <div className="tracking-employee-popover">
                            <p className="tracking-employee-preview-text">
                              {(Array.isArray(employeePreview.employees) ? employeePreview.employees : []).join(', ') || 'No employees'}
                            </p>
                          </div>
                        ) : null}
                      </div>
                    </td>
                    <td><span className="tracking-badge tracking-badge-status">{formatStatusLabel(row.mail_delivery_status)}</span></td>
                    <td><span className={`tracking-badge ${row.mailed ? 'is-positive' : 'is-muted'}`}>{row.mailed ? 'Yes' : 'No'}</span></td>
                    <td><span className="tracking-badge tracking-badge-type">{formatMailTypeLabel(row.mail_type)}</span></td>
                    <td><span className="tracking-badge tracking-badge-send">{formatSendModeLabel(rowLastSendMode(row))}</span></td>
                    <td><span className={`tracking-badge ${row.is_freezed ? 'is-warning' : 'is-muted'}`}>{row.is_freezed ? 'Yes' : 'No'}</span></td>
                    <td><span className="tracking-badge tracking-badge-template">{humanizeLabel(row.template_choice)}</span></td>
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
                        {String(rowLastSendMode(row) || '').trim().toLowerCase() === 'on time' ? (
                          row.mailed ? null : (
                            <button
                              type="button"
                              className="tracking-send-now-btn"
                              title="Send Mail Now"
                              aria-label="Send Mail Now"
                            onClick={() => sendRowImmediately(row)}
                            disabled={row.is_freezed || sendingRowId === row.id}
                          >
                            <SendNowIcon />
                          </button>
                        )
                        ) : null}
                        <button type="button" className="secondary tracking-icon-btn" title="Detail" onClick={() => navigate(`/tracking/${row.id}`)}><DetailIcon /></button>
                        <button type="button" className="secondary tracking-icon-btn" title="Test Mail" onClick={() => navigate(`/tracking/${row.id}/test-mail`)}><MailTestIcon /></button>
                        <button type="button" className="secondary tracking-icon-btn" title="Edit" onClick={() => openEditForm(row)} disabled={row.is_freezed}><EditIcon /></button>
                        <button type="button" className="tracking-delete-btn tracking-icon-btn" title="Delete" onClick={() => removeRow(row.id)}><DeleteIcon /></button>
                      </div>
                    </td>
                  </tr>
                  <tr className="tracking-milestone-row">
                    <td colSpan={12}>
                      <div className="tracking-wave-scroll">
                        {(() => {
                          const totalPoints = Math.max(EMPTY_MILESTONE_DOTS, milestones.length || 0)
                          const waveStartX = WAVE_INSET_PX
                          const minimumTrackWidth = (WAVE_INSET_PX * 2) + (Math.max(totalPoints - 1, 0) * WAVE_POINT_SPACING_PX)

                          return (
                            <div
                              className="tracking-wave-wrap"
                              style={{
                                width: '100%',
                                minWidth: `${minimumTrackWidth}px`,
                                '--wave-inset': `${waveStartX}px`,
                                '--wave-svg-top': `${WAVE_SVG_TOP_PX}px`,
                              }}
                            >
                          <svg className="tracking-wave-svg" viewBox="0 0 1000 44" preserveAspectRatio="none" aria-hidden="true">
                            <path
                              d="M0 22 C20 2 40 2 60 22 S100 42 120 22 S160 2 180 22 S220 42 240 22 S280 2 300 22 S340 42 360 22 S400 2 420 22 S460 42 480 22 S520 2 540 22 S580 42 600 22 S640 2 660 22 S700 42 720 22 S760 2 780 22 S820 42 840 22 S880 2 900 22 S940 42 960 22 S980 2 1000 22"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.8"
                            />
                          </svg>
                          <div className="tracking-wave-points">
                            {Array.from({ length: totalPoints }).map((_, index) => {
                              const milestone = milestones[index]
                              const progress = totalPoints <= 1 ? 0 : (index / (totalPoints - 1))
                              const viewBoxX = progress * WAVE_VIEWBOX_WIDTH
                              const viewBoxY = 22 - (20 * Math.sin((Math.PI / 60) * viewBoxX))
                              const pointCenterY = WAVE_SVG_TOP_PX + ((viewBoxY / WAVE_VIEWBOX_HEIGHT) * WAVE_SVG_HEIGHT_PX)
                              const pointTop = pointCenterY - (WAVE_DOT_SIZE_PX / 2)
                              const pointLeft = totalPoints <= 1
                                ? `${waveStartX}px`
                                : `calc(${waveStartX}px + ${progress} * (100% - ${waveStartX * 2}px))`
                              return (
                                <div
                                  key={`${row.id}-wave-${index}`}
                                  className={`tracking-wave-point${index === 0 ? ' is-edge-start' : ''}${index === totalPoints - 1 ? ' is-edge-end' : ''}`}
                                  style={{ left: pointLeft, top: `${pointTop}px` }}
                                >
                                  <div
                                    className="tracking-wave-point-button"
                                    title={milestone ? formatMilestoneLabel(milestone) : `Step ${index + 1}`}
                                  >
                                    <span className={`tracking-wave-circle ${milestone ? 'is-on' : ''}`} />
                                    <span className="tracking-wave-label">{formatMilestoneCode(milestone)}</span>
                                  </div>
                                  {milestone ? (
                                    <div className="tracking-wave-popup">
                                      {formatMilestoneLabel(milestone)}
                                    </div>
                                  ) : null}
                                </div>
                              )
                            })}
                          </div>
                        </div>
                          )
                        })()}
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
        <div className="modal-overlay" onClick={() => { setCreateForm(null); setCreateFormError('') }}>
          <div className="modal-panel tracking-modal-panel" onClick={(event) => event.stopPropagation()}>
            <div className="tracking-modal-head">
              <h2>Add Tracking</h2>
              <p className="subtitle">Set the company, contacts, mail flow, and attachments in one pass.</p>
            </div>
            <div className="tracking-form-grid">
            <div className="tracking-form-section-title tracking-form-span-2">Core Details</div>
            <label>
              Company (dropdown)
              <SingleSelectDropdown
                value={createForm.company || ''}
                placeholder="Select company"
                options={createCompanyDropdownOptions.map((company) => ({ value: String(company.id), label: capitalizeFirstDisplay(company.name) }))}
                onChange={async (nextValue) => {
                  setCreateForm((prev) => ({
                    ...prev,
                    company: nextValue,
                    job: '',
                    employee_location: '',
                    department: '',
                    employee_role: '',
                    selected_hr_ids: [],
                    attachment_source: '',
                    resume_id: '',
                    tailored_resume_id: '',
                  }))
                  await hydrateCompanyDependent(nextValue)
                }}
              />
            </label>
            <label>
              Job (dropdown)
              <SingleSelectDropdown
                value={createForm.job || ''}
                placeholder="Select job"
                options={jobOptions.map((job) => ({ value: String(job.id), label: `${job.job_id || ''} - ${job.role || ''}` }))}
                onChange={(nextValue) => setCreateForm((prev) => ({
                  ...prev,
                  job: nextValue,
                  attachment_source: '',
                  resume_id: '',
                  tailored_resume_id: '',
                }))}
              />
            </label>
            <label>
              Job Location
              <span className="hint">
                {createSelectedJobLocation || (createForm.job ? 'Job location not available' : 'Select job first')}
              </span>
            </label>
            <label>
              Employee Location
              <SingleSelectDropdown
                value={createForm.employee_location || ''}
                placeholder="Select employee location"
                disabled={!createForm.company}
                options={createEmployeeLocationOptions.map((location) => ({ value: location, label: location }))}
                onChange={(nextValue) => setCreateForm((prev) => ({ ...prev, employee_location: nextValue, department: '', employee_role: '', selected_hr_ids: [] }))}
              />
            </label>
            <label>
              Department
              <SingleSelectDropdown
                value={createForm.department || ''}
                placeholder="Select department"
                options={createDepartmentOptions.map((dept) => ({ value: dept, label: dept }))}
                onChange={(nextValue) => setCreateForm((prev) => ({ ...prev, department: nextValue, employee_role: '', selected_hr_ids: [] }))}
              />
            </label>
            <label>
              Role
              <SingleSelectDropdown
                value={createForm.employee_role || ''}
                placeholder="Select role"
                disabled={!createForm.company || !createForm.department}
                options={createRoleOptions.map((role) => ({ value: role, label: role }))}
                onChange={(nextValue) => setCreateForm((prev) => ({ ...prev, employee_role: nextValue, selected_hr_ids: [] }))}
              />
            </label>
            <label className="tracking-form-span-2">
              Employee (multi-select)
              <MultiSelectDropdown
                values={Array.isArray(createForm.selected_hr_ids) ? createForm.selected_hr_ids : []}
                placeholder={createEmployeeFilterLocked ? 'Select company and department first' : 'Select employee(s)'}
                disabled={createEmployeeFilterLocked}
                options={createEmployeeDropdownOptions}
                onChange={(nextValues) => setCreateForm((prev) => ({ ...prev, selected_hr_ids: Array.isArray(nextValues) ? nextValues : [] }))}
              />
            </label>
            {createBlockedMessage ? <p className="error tracking-form-span-2">{createBlockedMessage}</p> : null}
            <div className="tracking-form-section-title tracking-form-span-2">Mail Setup</div>
            <label>
              Mail Type
              <input value="Fresh" readOnly disabled />
            </label>
            <p className="hint tracking-form-span-2">Follow Up is available only after a fresh tracking row exists. Add Tracking always starts with Fresh mail.</p>
            <label className="tracking-form-span-2">
              Subject Source
              <SingleSelectDropdown
                value={createForm.template_subject || ''}
                placeholder="Select subject source"
                searchPlaceholder="Search subject source"
                options={createSubjectOptions}
                onChange={(nextValue) => setCreateForm((prev) => ({ ...prev, template_subject: nextValue || '' }))}
              />
            </label>
            <label className="tracking-form-span-2">
              Subject
              <input
                value={createForm.template_subject || ''}
                onChange={(event) => setCreateForm((prev) => ({ ...prev, template_subject: event.target.value }))}
                placeholder="Example: Application for {role} at {company_name} | {job_id}"
              />
            </label>
            <label>
              Interaction Time
              <input
                type="datetime-local"
                value={createForm.interaction_time || ''}
                onChange={(event) => setCreateForm((prev) => ({ ...prev, interaction_time: event.target.value }))}
              />
            </label>
            <label>
              Interview Round
              <input
                value={createForm.interview_round || ''}
                onChange={(event) => setCreateForm((prev) => ({ ...prev, interview_round: event.target.value }))}
                placeholder="Example: Technical Round"
              />
            </label>
            <label>
              Send
              <SingleSelectDropdown
                value={createForm.send_mode || 'sent'}
                placeholder="Select send mode"
                options={SEND_MODE_OPTIONS}
                onChange={(nextValue) => setCreateForm((prev) => ({
                  ...prev,
                  send_mode: nextValue || 'sent',
                  schedule_time: (nextValue || 'sent') === 'scheduled' ? (prev.schedule_time || nowDateTimeLocalValue()) : '',
                }))}
              />
            </label>
            <p className="hint tracking-form-span-2">Recommendation: open the Test Mail panel before Manual Send or Schedule so you can review the exact final content first.</p>
            {createForm.send_mode === 'scheduled' ? (
              <label>
                Date & Time
                <input
                  type="datetime-local"
                  value={createForm.schedule_time || ''}
                  onChange={(event) => setCreateForm((prev) => ({ ...prev, schedule_time: event.target.value }))}
                />
              </label>
            ) : null}
            {createForm.mail_type === 'followed_up' && createForm.send_mode === 'sent' ? (
              <p className="hint tracking-form-span-2">Follow Up can be sent multiple times, but it is better not to send the same employee too frequently. Recommended: keep at least a day gap, or at most 2 same-day follow ups with time between them.</p>
            ) : null}
            {createForm.mail_type !== 'followed_up' ? (
              <div className="tracking-form-span-2 tracking-template-stack">
                <div className="tracking-form-section-title">Templates</div>
                <p className="hint">Fresh mail: select at least 1 template. Duplicate selection is blocked.</p>
                <div className="tracking-template-stack-list">
                  {Array.from({ length: TRACKING_TEMPLATE_SLOT_COUNT }, (_, index) => index).map((index) => (
                    <label key={`create-template-${index}`} className="tracking-template-stack-item">
                      {`Template ${index + 1}`}
                      <SingleSelectDropdown
                        value={Array.isArray(createForm.achievement_ids_ordered) ? (createForm.achievement_ids_ordered[index] || '') : ''}
                        placeholder="Search and select template"
                        searchPlaceholder="Type template name or category"
                        clearLabel="No template selected"
                        options={hardcodedAchievementOptionsForIndex(
                          createAchievementOptionsForMode,
                          createForm.achievement_ids_ordered,
                          index,
                        ).map((item) => ({
                          value: String(item.id),
                          label: formatTemplateLibraryLabel(item),
                        }))}
                        disabled={hardcodedAchievementSlotDisabled(createForm.achievement_ids_ordered, index)}
                        onChange={(nextValue) => {
                          setCreateForm((prev) => {
                            const nextIds = updateHardcodedAchievementIds(prev.achievement_ids_ordered, index, nextValue)
                            return syncLegacyAchievementFields({
                              ...prev,
                              achievement_ids_ordered: nextIds,
                              template_ids_ordered: nextIds,
                            }, createAchievementOptionsForMode)
                          })
                        }}
                      />
                    </label>
                  ))}
                </div>
                {createSelectedTemplatePreviews.length ? (
                  <div className="tracking-template-preview-list">
                    {createSelectedTemplatePreviews.map((item, index) => (
                      <article key={`create-template-preview-${item.id || index}`} className="tracking-template-preview-card">
                        <div className="tracking-template-preview-title">{item.label || `Template ${index + 1}`}</div>
                        <p className="tracking-template-preview-text">{item.text}</p>
                      </article>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
            {createForm.mail_type === 'followed_up' ? (
              <div className="tracking-form-span-2 tracking-template-stack">
                <div className="tracking-form-section-title">Follow Up Templates</div>
                <p className="hint">For follow up, select at least 1 and at most 2 Follow Up templates.</p>
                <div className="tracking-template-stack-list">
                  {Array.from({ length: TRACKING_TEMPLATE_SLOT_COUNT }, (_, index) => index).map((index) => (
                    <label key={`create-followup-template-${index}`} className="tracking-template-stack-item">
                      {`Follow Up Template ${index + 1}`}
                      <SingleSelectDropdown
                        value={Array.isArray(createForm.achievement_ids_ordered) ? (createForm.achievement_ids_ordered[index] || '') : ''}
                        placeholder="Search and select follow-up template"
                        searchPlaceholder="Type follow-up template name"
                        clearLabel="No follow-up template selected"
                        options={hardcodedAchievementOptionsForIndex(
                          followUpTemplateOptions,
                          createForm.achievement_ids_ordered,
                          index,
                        )}
                        onChange={(nextValue) => {
                          setCreateForm((prev) => {
                            const nextIds = updateHardcodedAchievementIds(prev.achievement_ids_ordered, index, nextValue).slice(0, 2)
                            return {
                              ...prev,
                              achievement_ids_ordered: nextIds,
                              template_ids_ordered: nextIds,
                            }
                          })
                        }}
                      />
                    </label>
                  ))}
                </div>
                {createSelectedTemplatePreviews.length ? (
                  <div className="tracking-template-preview-list">
                    {createSelectedTemplatePreviews.map((item, index) => (
                      <article key={`create-followup-template-preview-${item.id || index}`} className="tracking-template-preview-card">
                        <div className="tracking-template-preview-title">{item.label || `Follow Up Template ${index + 1}`}</div>
                        <p className="tracking-template-preview-text">{item.text}</p>
                      </article>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : (
              <>
                <label className="tracking-check-row tracking-form-span-2">
                  <input
                    type="checkbox"
                    checked={Boolean(createForm.use_hardcoded_personalized_intro)}
                    onChange={(event) => setCreateForm((prev) => ({
                      ...prev,
                      use_hardcoded_personalized_intro: event.target.checked,
                      personalized_template_id: event.target.checked ? prev.personalized_template_id : '',
                    }))}
                  />
                  {' '}
                  Use Personalized Template For Employee
                </label>
                {createForm.use_hardcoded_personalized_intro ? (
                  <div className="tracking-form-span-2 tracking-template-stack">
                    <label className="tracking-template-stack-item">
                      Personalized Template
                      <SingleSelectDropdown
                        value={createForm.personalized_template_id || ''}
                        placeholder="Search and select personalized template"
                        searchPlaceholder="Type personalized template name"
                        clearLabel="No personalized template selected"
                        options={personalizedTemplateOptions}
                        onChange={(nextValue) => setCreateForm((prev) => ({ ...prev, personalized_template_id: nextValue || '' }))}
                      />
                    </label>
                    {createSelectedPersonalizedPreview.length ? (
                      <div className="tracking-template-preview-list">
                        {createSelectedPersonalizedPreview.map((item, index) => (
                          <article key={`create-personalized-template-preview-${item.id || index}`} className="tracking-template-preview-card">
                            <div className="tracking-template-preview-title">{item.label || 'Personalized Template'}</div>
                            <p className="tracking-template-preview-text">{item.text}</p>
                          </article>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <p className="hint tracking-form-span-2">Mail content will come fully from your selected templates. Add a personalized template only if you want an employee-specific intro block.</p>
                )}
              </>
            )}
            <div className="tracking-form-section-title tracking-form-span-2">Attachments & Flags</div>
            <label className="tracking-check-row tracking-form-span-2">
              <input
                type="checkbox"
                checked={Boolean(createForm.has_attachment)}
                onChange={(event) => setCreateForm((prev) => {
                  const checked = event.target.checked
                  if (checked) return { ...prev, has_attachment: true }
                  return {
                    ...prev,
                    has_attachment: false,
                    attachment_source: '',
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
                  Base Resume
                  <SingleSelectDropdown
                    value={createForm.attachment_source === 'base' ? (createForm.resume_id || '') : ''}
                    placeholder="Select base resume"
                    options={baseResumeDropdownOptions}
                    onChange={(value) => {
                      setCreateForm((prev) => ({
                        ...prev,
                        attachment_source: value ? 'base' : '',
                        resume_id: value || '',
                        tailored_resume_id: '',
                      }))
                    }}
                  />
                </label>
                <label>
                  Tailored Resume
                  <SingleSelectDropdown
                    value={createForm.attachment_source === 'tailored' ? (createForm.tailored_resume_id || '') : ''}
                    placeholder="Select tailored resume"
                    options={tailoredResumeDropdownOptions}
                    onChange={(value) => {
                      setCreateForm((prev) => ({
                        ...prev,
                        attachment_source: value ? 'tailored' : '',
                        resume_id: '',
                        tailored_resume_id: value || '',
                      }))
                    }}
                  />
                </label>
                <label className="tracking-form-span-2">
                  Associated To Job
                  <SingleSelectDropdown
                    value={createForm.attachment_source === 'associated' ? (createForm.tailored_resume_id || createForm.resume_id || '') : ''}
                    placeholder="Select associated resume"
                    options={createAssociatedResumeOptions}
                    onChange={(value) => {
                      const selectedOption = createAssociatedResumeOptions.find((item) => String(item.value) === String(value || ''))
                      setCreateForm((prev) => ({
                        ...prev,
                        attachment_source: value ? 'associated' : '',
                        resume_id: selectedOption?.isTailored ? '' : (value || ''),
                        tailored_resume_id: selectedOption?.isTailored ? (value || '') : '',
                      }))
                    }}
                  />
                </label>
                <p className="hint tracking-form-span-2">Only one resume can be shared. Selecting Base, Tailored, or Associated To Job will override the other choices.</p>
                {!createAssociatedResumeOptions.length ? <p className="hint tracking-form-span-2">No resume is associated with this job yet.</p> : null}
              </>
            ) : null}
            <label className="tracking-check-row tracking-form-span-2">
              <input
                type="checkbox"
                checked={Boolean(createForm.is_freezed)}
                onChange={(event) => setCreateForm((prev) => ({ ...prev, is_freezed: event.target.checked }))}
              />
              {' '}
              Freeze
            </label>
            </div>
            {createFormError ? <p className="error">{createFormError}</p> : null}
            <div className="actions">
              <button type="button" onClick={createRow} disabled={createSaveBlocked}>Create</button>
              <button type="button" className="secondary" onClick={() => { setCreateForm(null); setCreateFormError('') }}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}

      {editForm ? (
        <div className="modal-overlay" onClick={() => { setEditForm(null); setEditFormError('') }}>
          <div className="modal-panel tracking-modal-panel" onClick={(event) => event.stopPropagation()}>
            <div className="tracking-modal-head">
              <h2>Edit Tracking Row</h2>
              <p className="subtitle">Update linked contacts, sending setup, templates, and freeze state.</p>
            </div>
            <div className="tracking-form-grid">
            <div className="tracking-form-section-title tracking-form-span-2">Core Details</div>
            <label>
              Company (dropdown)
              <SingleSelectDropdown
                value={editForm.company || ''}
                placeholder="Select company"
                options={editCompanyDropdownOptions.map((company) => ({ value: String(company.id), label: capitalizeFirstDisplay(company.name) }))}
                onChange={async (value) => {
                  setEditForm((prev) => ({
                    ...prev,
                    company: value,
                    job: '',
                    employee_location: '',
                    department: '',
                    employee_role: '',
                    selected_hr_ids: [],
                    attachment_source: '',
                    resume_id: '',
                    tailored_resume_id: '',
                  }))
                  await hydrateCompanyDependent(value)
                }}
              />
            </label>
            <label>
              Job (dropdown)
              <SingleSelectDropdown
                value={editForm.job || ''}
                placeholder="Select job"
                options={jobOptions.map((job) => ({ value: String(job.id), label: `${job.job_id || ''} - ${job.role || ''}` }))}
                disabled
                onChange={() => {}}
              />
            </label>
            <label>
              Job Location
              <span className="hint">
                {editSelectedJobLocation || (editForm.job ? 'Job location not available' : 'Select job first')}
              </span>
            </label>
            <label>
              Employee Location
              <SingleSelectDropdown
                value={editForm.employee_location || ''}
                placeholder="Select employee location"
                disabled={!editForm.company}
                options={editEmployeeLocationOptions.map((location) => ({ value: location, label: location }))}
                onChange={(value) => setEditForm((prev) => ({ ...prev, employee_location: value, department: '', employee_role: '', selected_hr_ids: [] }))}
              />
            </label>
            <label>
              Department
              <SingleSelectDropdown
                value={editForm.department || ''}
                placeholder="Select department"
                options={editDepartmentOptions.map((dept) => ({ value: dept, label: dept }))}
                onChange={(value) => setEditForm((prev) => ({ ...prev, department: value, employee_role: '', selected_hr_ids: [] }))}
              />
            </label>
            <label>
              Role
              <SingleSelectDropdown
                value={editForm.employee_role || ''}
                placeholder="Select role"
                disabled={!editForm.company || !editForm.department}
                options={editRoleOptions.map((role) => ({ value: role, label: role }))}
                onChange={(value) => setEditForm((prev) => ({ ...prev, employee_role: value, selected_hr_ids: [] }))}
              />
            </label>
            <label className="tracking-form-span-2">
              Employee (multi-select)
              <MultiSelectDropdown
                values={Array.isArray(editForm.selected_hr_ids) ? editForm.selected_hr_ids : []}
                placeholder={editForm.mail_type === 'followed_up'
                  ? 'Employee is locked for follow up mode'
                  : (editEmployeeFilterLocked ? 'Select company and department first' : 'Select employee(s)')}
                options={editEmployeeDropdownOptions}
                disabled={editForm.mail_type === 'followed_up' || editEmployeeFilterLocked}
                onChange={(nextValues) => {
                  setEditForm((prev) => ({ ...prev, selected_hr_ids: Array.isArray(nextValues) ? nextValues : [] }))
                }}
              />
            </label>
            {editBlockedMessage ? <p className="error tracking-form-span-2">{editBlockedMessage}</p> : null}
            <div className="tracking-form-section-title tracking-form-span-2">Mail Setup</div>
            <label>
              Mail Type
              <SingleSelectDropdown
                value={editForm.mail_type || 'fresh'}
                placeholder="Select mail type"
                options={editMailTypeOptions}
                onChange={(value) => setEditForm((prev) => {
                  const nextMailType = value || 'fresh'
                  if (nextMailType !== 'followed_up') {
                    return {
                      ...prev,
                      mail_type: nextMailType,
                      achievement_ids_ordered: prev.achievement_ids_ordered,
                      template_ids_ordered: prev.template_ids_ordered,
                      follow_thread_id: '',
                      follow_thread_ids: [],
                    }
                  }
                  const currentIds = Array.isArray(prev.selected_hr_ids) ? prev.selected_hr_ids.map((id) => String(id)) : []
                  const candidateSet = new Set(editFollowUpCandidateIds.map((id) => String(id)))
                  const matchingIds = currentIds.filter((id) => candidateSet.has(String(id)))
                  return {
                    ...prev,
                    mail_type: nextMailType,
                    achievement_ids_ordered: [],
                    template_ids_ordered: [],
                    use_hardcoded_personalized_intro: false,
                    selected_hr_ids: matchingIds.length ? matchingIds : [...editFollowUpCandidateIds],
                    follow_thread_id: matchingIds[0] || editFollowUpCandidateIds[0] || '',
                    follow_thread_ids: matchingIds.length ? matchingIds : [...editFollowUpCandidateIds],
                  }
                })}
              />
            </label>
            <p className="hint tracking-form-span-2">Edit Tracking can send Fresh again. Follow Up remains available when this row already has a fresh thread.</p>
            <label className="tracking-form-span-2">
              Subject Source
              <SingleSelectDropdown
                value={editForm.template_subject || ''}
                placeholder="Select subject source"
                searchPlaceholder="Search subject source"
                options={editSubjectOptions}
                onChange={(nextValue) => setEditForm((prev) => ({ ...prev, template_subject: nextValue || '' }))}
              />
            </label>
            <label className="tracking-form-span-2">
              Subject
              <input
                value={editForm.template_subject || ''}
                onChange={(event) => setEditForm((prev) => ({ ...prev, template_subject: event.target.value }))}
                placeholder="Example: Application for {role} at {company_name} | {job_id}"
              />
            </label>
            <label>
              Interaction Time
              <input
                type="datetime-local"
                value={editForm.interaction_time || ''}
                onChange={(event) => setEditForm((prev) => ({ ...prev, interaction_time: event.target.value }))}
              />
            </label>
            <label>
              Interview Round
              <input
                value={editForm.interview_round || ''}
                onChange={(event) => setEditForm((prev) => ({ ...prev, interview_round: event.target.value }))}
                placeholder="Example: Final Round"
              />
            </label>
            <label>
              Send
              <SingleSelectDropdown
                value={editForm.send_mode || 'sent'}
                placeholder="Select send mode"
                options={SEND_MODE_OPTIONS}
                onChange={(value) => setEditForm((prev) => ({
                  ...prev,
                  send_mode: value || 'sent',
                  schedule_time: (value || 'sent') === 'scheduled' ? (prev.schedule_time || nowDateTimeLocalValue()) : '',
                }))}
              />
            </label>
            <p className="hint tracking-form-span-2">Recommendation: open the Test Mail panel before Manual Send or Schedule so you can review the exact final content first.</p>
            {editForm.send_mode === 'scheduled' ? (
              <label>
                Date & Time
                <input
                  type="datetime-local"
                  value={editForm.schedule_time || ''}
                  onChange={(event) => setEditForm((prev) => ({ ...prev, schedule_time: event.target.value }))}
                />
              </label>
            ) : null}
            {editForm.mail_type === 'followed_up' && editForm.send_mode === 'sent' ? (
              <p className="hint tracking-form-span-2">Follow Up can be sent multiple times, but it is better not to send the same employee too frequently. Recommended: keep at least a day gap, or at most 2 same-day follow ups with time between them.</p>
            ) : null}
            {editForm.mail_type === 'followed_up' ? (
              <>
                <label className="tracking-form-span-2">
                  Follow Thread ID
                  <MultiSelectDropdown
                    values={Array.isArray(editForm.follow_thread_ids) ? editForm.follow_thread_ids : []}
                    placeholder="Select follow thread(s)"
                    options={editFollowThreadOptions}
                    onChange={(values) => setEditForm((prev) => ({
                      ...prev,
                      follow_thread_ids: Array.isArray(values) ? values.map((value) => String(value)) : [],
                      follow_thread_id: Array.isArray(values) && values.length ? String(values[0]) : '',
                      selected_hr_ids: Array.isArray(values) ? values.map((value) => String(value)) : prev.selected_hr_ids,
                    }))}
                  />
                </label>
                <p className="hint tracking-form-span-2">
                  {editFollowUpCandidates.length
                    ? 'Employee selection is frozen in Follow Up mode. Choose the thread by ID, name, email, and fresh-mail time.'
                    : 'No employee is eligible for follow-up yet. Send a fresh mail first.'}
                </p>
              </>
            ) : null}
            {editForm.mail_type !== 'followed_up' ? (
              <div className="tracking-form-span-2 tracking-template-stack">
                <div className="tracking-form-section-title">Templates</div>
                <p className="hint">Fresh mail: select at least 1 template. Duplicate selection is blocked.</p>
                <div className="tracking-template-stack-list">
                  {Array.from({ length: TRACKING_TEMPLATE_SLOT_COUNT }, (_, index) => index).map((index) => (
                    <label key={`edit-template-${index}`} className="tracking-template-stack-item">
                      {`Template ${index + 1}`}
                      <SingleSelectDropdown
                        value={Array.isArray(editForm.achievement_ids_ordered) ? (editForm.achievement_ids_ordered[index] || '') : ''}
                        placeholder="Search and select template"
                        searchPlaceholder="Type template name or category"
                        clearLabel="No template selected"
                        options={hardcodedAchievementOptionsForIndex(
                          editAchievementOptionsForMode,
                          editForm.achievement_ids_ordered,
                          index,
                        ).map((item) => ({
                          value: String(item.id),
                          label: formatTemplateLibraryLabel(item),
                        }))}
                        disabled={hardcodedAchievementSlotDisabled(editForm.achievement_ids_ordered, index)}
                        onChange={(nextValue) => {
                          setEditForm((prev) => {
                            const nextIds = updateHardcodedAchievementIds(prev.achievement_ids_ordered, index, nextValue)
                            return syncLegacyAchievementFields({
                              ...prev,
                              achievement_ids_ordered: nextIds,
                              template_ids_ordered: nextIds,
                            }, editAchievementOptionsForMode)
                          })
                        }}
                      />
                    </label>
                  ))}
                </div>
                {editSelectedTemplatePreviews.length ? (
                  <div className="tracking-template-preview-list">
                    {editSelectedTemplatePreviews.map((item, index) => (
                      <article key={`edit-template-preview-${item.id || index}`} className="tracking-template-preview-card">
                        <div className="tracking-template-preview-title">{item.label || `Template ${index + 1}`}</div>
                        <p className="tracking-template-preview-text">{item.text}</p>
                      </article>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
            {editForm.mail_type === 'followed_up' ? (
              <div className="tracking-form-span-2 tracking-template-stack">
                <div className="tracking-form-section-title">Follow Up Templates</div>
                <p className="hint">For follow up, select at least 1 and at most 2 Follow Up templates.</p>
                <div className="tracking-template-stack-list">
                  {Array.from({ length: TRACKING_TEMPLATE_SLOT_COUNT }, (_, index) => index).map((index) => (
                    <label key={`edit-followup-template-${index}`} className="tracking-template-stack-item">
                      {`Follow Up Template ${index + 1}`}
                      <SingleSelectDropdown
                        value={Array.isArray(editForm.achievement_ids_ordered) ? (editForm.achievement_ids_ordered[index] || '') : ''}
                        placeholder="Search and select follow-up template"
                        searchPlaceholder="Type follow-up template name"
                        clearLabel="No follow-up template selected"
                        options={hardcodedAchievementOptionsForIndex(
                          followUpTemplateOptions,
                          editForm.achievement_ids_ordered,
                          index,
                        )}
                        onChange={(nextValue) => {
                          setEditForm((prev) => {
                            const nextIds = updateHardcodedAchievementIds(prev.achievement_ids_ordered, index, nextValue).slice(0, 2)
                            return {
                              ...prev,
                              achievement_ids_ordered: nextIds,
                              template_ids_ordered: nextIds,
                            }
                          })
                        }}
                      />
                    </label>
                  ))}
                </div>
                {editSelectedTemplatePreviews.length ? (
                  <div className="tracking-template-preview-list">
                    {editSelectedTemplatePreviews.map((item, index) => (
                      <article key={`edit-followup-template-preview-${item.id || index}`} className="tracking-template-preview-card">
                        <div className="tracking-template-preview-title">{item.label || `Follow Up Template ${index + 1}`}</div>
                        <p className="tracking-template-preview-text">{item.text}</p>
                      </article>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : (
              <>
                <label className="tracking-check-row tracking-form-span-2">
                  <input
                    type="checkbox"
                    checked={Boolean(editForm.use_hardcoded_personalized_intro)}
                    onChange={(event) => setEditForm((prev) => ({
                      ...prev,
                      use_hardcoded_personalized_intro: event.target.checked,
                      personalized_template_id: event.target.checked ? prev.personalized_template_id : '',
                    }))}
                  />
                  {' '}
                  Use Personalized Template For Employee
                </label>
                {editForm.use_hardcoded_personalized_intro ? (
                  <div className="tracking-form-span-2 tracking-template-stack">
                    <label className="tracking-template-stack-item">
                      Personalized Template
                      <SingleSelectDropdown
                        value={editForm.personalized_template_id || ''}
                        placeholder="Search and select personalized template"
                        searchPlaceholder="Type personalized template name"
                        clearLabel="No personalized template selected"
                        options={personalizedTemplateOptions}
                        onChange={(nextValue) => setEditForm((prev) => ({ ...prev, personalized_template_id: nextValue || '' }))}
                      />
                    </label>
                    {editSelectedPersonalizedPreview.length ? (
                      <div className="tracking-template-preview-list">
                        {editSelectedPersonalizedPreview.map((item, index) => (
                          <article key={`edit-personalized-template-preview-${item.id || index}`} className="tracking-template-preview-card">
                            <div className="tracking-template-preview-title">{item.label || 'Personalized Template'}</div>
                            <p className="tracking-template-preview-text">{item.text}</p>
                          </article>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <p className="hint tracking-form-span-2">Mail content will come fully from your selected templates. Add a personalized template only if you want an employee-specific intro block.</p>
                )}
              </>
            )}
            <div className="tracking-form-section-title tracking-form-span-2">Attachments & Flags</div>
            <label className="tracking-check-row tracking-form-span-2">
              <input
                type="checkbox"
                checked={Boolean(editForm.has_attachment)}
                onChange={(event) => setEditForm((prev) => {
                  const checked = event.target.checked
                  if (checked) return { ...prev, has_attachment: true }
                  return {
                    ...prev,
                    has_attachment: false,
                    attachment_source: '',
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
                  Base Resume
                  <SingleSelectDropdown
                    value={editForm.attachment_source === 'base' ? (editForm.resume_id || '') : ''}
                    placeholder="Select base resume"
                    options={baseResumeDropdownOptions}
                    onChange={(value) => {
                      setEditForm((prev) => ({
                        ...prev,
                        attachment_source: value ? 'base' : '',
                        resume_id: value || '',
                        tailored_resume_id: '',
                      }))
                    }}
                  />
                </label>
                <label>
                  Tailored Resume
                  <SingleSelectDropdown
                    value={editForm.attachment_source === 'tailored' ? (editForm.tailored_resume_id || '') : ''}
                    placeholder="Select tailored resume"
                    options={tailoredResumeDropdownOptions}
                    onChange={(value) => {
                      setEditForm((prev) => ({
                        ...prev,
                        attachment_source: value ? 'tailored' : '',
                        resume_id: '',
                        tailored_resume_id: value || '',
                      }))
                    }}
                  />
                </label>
                <label className="tracking-form-span-2">
                  Associated To Job
                  <SingleSelectDropdown
                    value={editForm.attachment_source === 'associated' ? (editForm.tailored_resume_id || editForm.resume_id || '') : ''}
                    placeholder="Select associated resume"
                    options={editAssociatedResumeOptions}
                    onChange={(value) => {
                      const selectedOption = editAssociatedResumeOptions.find((item) => String(item.value) === String(value || ''))
                      setEditForm((prev) => ({
                        ...prev,
                        attachment_source: value ? 'associated' : '',
                        resume_id: selectedOption?.isTailored ? '' : (value || ''),
                        tailored_resume_id: selectedOption?.isTailored ? (value || '') : '',
                      }))
                    }}
                  />
                </label>
                <p className="hint tracking-form-span-2">Only one resume can be shared. Selecting Base, Tailored, or Associated To Job will override the other choices.</p>
                {!editAssociatedResumeOptions.length ? <p className="hint tracking-form-span-2">No resume is associated with this job yet.</p> : null}
              </>
            ) : null}
            <label className="tracking-check-row tracking-form-span-2">
              <input
                type="checkbox"
                checked={Boolean(editForm.is_freezed)}
                onChange={(event) => setEditForm((prev) => ({ ...prev, is_freezed: event.target.checked }))}
              />
              {' '}
              Freeze
            </label>
            </div>
            {editFormError ? <p className="error">{editFormError}</p> : null}
            <div className="actions">
              <button type="button" onClick={saveEditForm} disabled={editSaveBlocked}>Save</button>
              <button type="button" className="secondary" onClick={() => { setEditForm(null); setEditFormError('') }}>Cancel</button>
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

      {sendConfirmRow ? (
        <div className="modal-overlay" onClick={() => { if (!sendingRowId) { setSendConfirmRow(null); setSendConfirmError('') } }}>
          <div className="modal-panel tracking-send-confirm-modal" onClick={(event) => event.stopPropagation()}>
            <h2>Send Mail Now</h2>
            <p className="subtitle">Re-check everything before sending this mail immediately.</p>
            <div className="tracking-send-confirm-grid">
              <div className="tracking-send-confirm-item">
                <span>Company</span>
                <strong>{capitalizeFirstDisplay(sendConfirmRow.company_name) || '-'}</strong>
              </div>
              <div className="tracking-send-confirm-item">
                <span>Job Name</span>
                <strong>{sendConfirmRow.role || '-'}</strong>
              </div>
              <div className="tracking-send-confirm-item">
                <span>Job ID</span>
                <strong>{sendConfirmRow.job_id || '-'}</strong>
              </div>
              <div className="tracking-send-confirm-item">
                <span>Mail Type</span>
                <strong>{formatMailTypeLabel(sendConfirmRow.mail_type)}</strong>
              </div>
            </div>
            <div className="tracking-send-confirm-list">
              <div className="tracking-send-confirm-list-title">Employees</div>
              {(Array.isArray(sendConfirmRow.selected_employees) && sendConfirmRow.selected_employees.length
                ? sendConfirmRow.selected_employees
                : []
              ).map((employee, index) => (
                <div key={`send-confirm-employee-${employee.id || index}`} className="tracking-send-confirm-person">
                  <strong>{employee.name || '-'}</strong>
                  <span>{employee.email || 'No email'}</span>
                </div>
              ))}
            </div>
            {sendConfirmError ? <p className="error">{sendConfirmError}</p> : null}
            <div className="actions">
              <button type="button" onClick={confirmSendRowImmediately} disabled={sendingRowId === sendConfirmRow.id}>
                {sendingRowId === sendConfirmRow.id ? 'Sending...' : 'Confirm Send'}
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  if (sendingRowId) return
                  setSendConfirmRow(null)
                  setSendConfirmError('')
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  )
}

export default TrackingPage
