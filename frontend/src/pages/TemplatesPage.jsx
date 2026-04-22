import { useEffect, useMemo, useState } from 'react'

import {
  createTemplate,
  deleteTemplate,
  fetchProfile,
  fetchTemplates,
  updateTemplate,
} from '../api'
import { SingleSelectDropdown } from '../components/SearchableDropdown'
import { useAuth } from '../contexts/useAuth'

const TEMPLATE_CATEGORY_OPTIONS = [
  { value: 'personalized', label: 'Personalized' },
  { value: 'follow_up', label: 'Follow Up' },
  { value: 'experience', label: 'Experience' },
  { value: 'general', label: 'General' },
]
const EMPTY_TEMPLATE = {
  name: '',
  category: 'general',
  paragraph: '',
}
const PAGE_SIZE = 10

function normalizeTemplateCategory(value) {
  const normalized = String(value || 'general').trim().toLowerCase()
  if (normalized === 'opening' || normalized === 'closing') return 'general'
  return normalized || 'general'
}

function buildPageNumberWindow(currentPage, totalPages, maxVisible = 5) {
  const safeTotal = Math.max(1, Number(totalPages || 1))
  const safeCurrent = Math.min(Math.max(1, Number(currentPage || 1)), safeTotal)
  const visibleCount = Math.max(1, Math.min(maxVisible, safeTotal))
  let start = Math.max(1, safeCurrent - Math.floor(visibleCount / 2))
  let end = start + visibleCount - 1
  if (end > safeTotal) {
    end = safeTotal
    start = Math.max(1, end - visibleCount + 1)
  }
  return Array.from({ length: end - start + 1 }, (_, index) => start + index)
}

function templateSortValue(row) {
  const category = normalizeTemplateCategory(row?.category)
  const name = String(row?.name || '').trim().toLowerCase()
  return `${category}|${name}`
}

function sortTemplates(rows) {
  const nextRows = Array.isArray(rows) ? [...rows] : []
  nextRows.sort((left, right) => templateSortValue(left).localeCompare(templateSortValue(right)))
  return nextRows
}

function humanizeCategory(value) {
  return normalizeTemplateCategory(value).replaceAll('_', ' ') || 'general'
}

function formatTemplateDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleDateString([], {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
  })
}

function templateWordCount(text) {
  return String(text || '').trim().split(/\s+/).filter(Boolean).length
}

function TemplatesPage() {
  const { accessToken } = useAuth()
  const [rows, setRows] = useState([])
  const [permissions, setPermissions] = useState({
    can_add: false,
    can_edit: false,
    can_delete: false,
  })
  const [category, setCategory] = useState('')
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(() => Boolean(accessToken))
  const [error, setError] = useState('')
  const [ok, setOk] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [editingTemplateId, setEditingTemplateId] = useState(null)
  const [templateForm, setTemplateForm] = useState(EMPTY_TEMPLATE)
  const [showTemplateHints, setShowTemplateHints] = useState(false)
  const [templateError, setTemplateError] = useState('')
  const [templateOk, setTemplateOk] = useState('')

  useEffect(() => {
    if (!accessToken) return undefined
    let cancelled = false

    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const [profileData, templateData] = await Promise.all([
          fetchProfile(accessToken),
          fetchTemplates(accessToken),
        ])
        if (cancelled) return
        setPermissions({
          can_add: Boolean(profileData?.permissions?.templates?.can_add),
          can_edit: Boolean(profileData?.permissions?.templates?.can_edit),
          can_delete: Boolean(profileData?.permissions?.templates?.can_delete),
        })
        setRows(sortTemplates(templateData))
      } catch (err) {
        if (!cancelled) {
          setRows([])
          setError(err.message || 'Could not load templates.')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [accessToken])

  const filteredRows = useMemo(() => {
    const selectedCategory = normalizeTemplateCategory(category)
    const nextRows = Array.isArray(rows) ? rows : []
    if (!String(category || '').trim()) return nextRows
    return nextRows.filter((row) => normalizeTemplateCategory(row?.category) === selectedCategory)
  }, [rows, category])

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE)),
    [filteredRows.length],
  )
  const currentPage = Math.min(page, totalPages)

  const pagedRows = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE
    return filteredRows.slice(start, start + PAGE_SIZE)
  }, [currentPage, filteredRows])

  const visiblePageNumbers = useMemo(
    () => buildPageNumberWindow(currentPage, totalPages),
    [currentPage, totalPages],
  )

  const openCreateTemplate = () => {
    if (!permissions.can_add) return
    setError('')
    setOk('')
    setTemplateError('')
    setTemplateOk('')
    setEditingTemplateId(null)
    setTemplateForm(EMPTY_TEMPLATE)
    setShowTemplateHints(false)
    setShowForm(true)
  }

  const closeTemplateForm = () => {
    setShowForm(false)
    setEditingTemplateId(null)
    setTemplateForm(EMPTY_TEMPLATE)
    setShowTemplateHints(false)
    setTemplateError('')
  }

  const editTemplate = (row) => {
    if (!row?.can_edit) return
    setError('')
    setOk('')
    setTemplateError('')
    setTemplateOk('')
    setEditingTemplateId(row.id)
    setTemplateForm({
      name: row.name || '',
      category: normalizeTemplateCategory(row.category),
      paragraph: row.paragraph || '',
    })
    setShowTemplateHints(false)
    setShowForm(true)
  }

  const saveTemplate = async () => {
    try {
      setTemplateError('')
      setTemplateOk('')
      const payload = {
        name: String(templateForm.name || '').trim(),
        category: normalizeTemplateCategory(templateForm.category),
        paragraph: String(templateForm.paragraph || '').trim(),
      }
      if (!payload.name || !payload.paragraph) {
        setTemplateError('Template needs name and paragraph text.')
        return
      }
      if (editingTemplateId) {
        const updated = await updateTemplate(accessToken, editingTemplateId, payload)
        setRows((prev) => sortTemplates(prev.map((row) => (row.id === editingTemplateId ? updated : row))))
        setTemplateOk('Template updated.')
      } else {
        const created = await createTemplate(accessToken, payload)
        setRows((prev) => sortTemplates([created, ...prev]))
        setTemplateOk('Template added.')
      }
      closeTemplateForm()
    } catch (err) {
      setTemplateError(err.message || 'Could not save template.')
    }
  }

  const removeTemplate = async (row) => {
    if (!row?.can_delete) return
    try {
      setError('')
      setOk('')
      setTemplateError('')
      setTemplateOk('')
      await deleteTemplate(accessToken, row.id)
      setRows((prev) => prev.filter((item) => item.id !== row.id))
      setTemplateOk('Template deleted.')
    } catch (err) {
      setTemplateError(err.message || 'Could not delete template.')
    }
  }

  return (
    <main className="page page-wide">
      <section className="dash-card">
        <div className="tracking-head profile-section-head">
          <div>
            <h1>Templates</h1>
            <p className="subtitle">Manage your reusable templates in one place.</p>
          </div>
          <div className="actions profile-template-head-actions">
            <div className="profile-template-filter">
              <SingleSelectDropdown
                value={category}
                placeholder="Category"
                searchPlaceholder="Search category"
                clearLabel="All Categories"
                options={TEMPLATE_CATEGORY_OPTIONS}
                onChange={(nextValue) => {
                  setCategory(nextValue || '')
                  setPage(1)
                }}
              />
            </div>
            {permissions.can_add ? (
              <button type="button" className="secondary" onClick={openCreateTemplate}>Add Template</button>
            ) : null}
          </div>
        </div>

        {loading ? <p className="hint">Loading templates...</p> : null}
        {!loading && error ? <p className="error">{error}</p> : null}
        {!loading && !error && ok ? <p className="success">{ok}</p> : null}
        {!loading && !error && templateError ? <p className="error">{templateError}</p> : null}
        {!loading && !error && templateOk ? <p className="success">{templateOk}</p> : null}
        {!loading && !error && !permissions.can_add && !permissions.can_edit && !permissions.can_delete ? (
          <p className="hint">You have read-only access to templates.</p>
        ) : null}

        {!loading && !error ? (
          <>
            <div className="template-library-grid">
              {pagedRows.map((row) => (
                <article key={row.id} className="profile-template-row">
                  <div className="profile-template-main">
                    <p className="profile-template-title"><strong>{row.name || 'Template'}</strong></p>
                    <div className="profile-template-meta-list">
                      <span className="profile-template-meta-chip">{humanizeCategory(row?.category)}</span>
                      <span className="profile-template-meta-chip">Words: {templateWordCount(row?.paragraph)}</span>
                      <span className="profile-template-meta-chip">Updated: {formatTemplateDate(row?.updated_at || row?.created_at)}</span>
                    </div>
                    <p className="profile-template-snippet">{row.paragraph || '-'}</p>
                  </div>
                  {row.can_edit || row.can_delete ? (
                    <div className="profile-template-actions">
                      {row.can_edit ? (
                        <button type="button" className="secondary" onClick={() => editTemplate(row)}>Edit</button>
                      ) : null}
                      {row.can_delete ? (
                        <button type="button" className="secondary" onClick={() => removeTemplate(row)}>Delete</button>
                      ) : null}
                    </div>
                  ) : null}
                </article>
              ))}
              {!rows.length ? <p className="hint">No templates yet.</p> : null}
              {rows.length && !filteredRows.length ? <p className="hint">No templates in this category.</p> : null}
            </div>

            {filteredRows.length > PAGE_SIZE ? (
              <div className="table-pagination">
                <button type="button" className="secondary" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={currentPage <= 1}>Previous</button>
                <div className="table-pagination-numbers" aria-label="Template pages">
                  {visiblePageNumbers[0] > 1 ? (
                    <>
                      <button type="button" className={`secondary${currentPage === 1 ? ' is-active' : ''}`} onClick={() => setPage(1)} aria-current={currentPage === 1 ? 'page' : undefined}>1</button>
                      {visiblePageNumbers[0] > 2 ? <span className="table-pagination-ellipsis">…</span> : null}
                    </>
                  ) : null}
                  {visiblePageNumbers.map((pageNumber) => (
                    <button
                      key={pageNumber}
                      type="button"
                      className={`secondary${pageNumber === currentPage ? ' is-active' : ''}`}
                      onClick={() => setPage(pageNumber)}
                      aria-current={pageNumber === currentPage ? 'page' : undefined}
                    >
                      {pageNumber}
                    </button>
                  ))}
                  {visiblePageNumbers[visiblePageNumbers.length - 1] < totalPages ? (
                    <>
                      {visiblePageNumbers[visiblePageNumbers.length - 1] < totalPages - 1 ? (
                        <span className="table-pagination-ellipsis">…</span>
                      ) : null}
                      <button
                        type="button"
                        className={`secondary${currentPage === totalPages ? ' is-active' : ''}`}
                        onClick={() => setPage(totalPages)}
                        aria-current={currentPage === totalPages ? 'page' : undefined}
                      >
                        {totalPages}
                      </button>
                    </>
                  ) : null}
                </div>
                <span>Page {currentPage} of {totalPages}</span>
                <button type="button" className="secondary" onClick={() => setPage((current) => Math.min(totalPages, current + 1))} disabled={currentPage >= totalPages}>Next</button>
              </div>
            ) : null}
          </>
        ) : null}
      </section>

      {showForm ? (
        <div className="modal-overlay" onClick={closeTemplateForm}>
          <div className="modal-panel profile-modal-panel" onClick={(e) => e.stopPropagation()}>
            <h2>{editingTemplateId ? 'Edit Template' : 'Add Template'}</h2>
            <div className="profile-form-grid">
              <label>
                Name
                <input
                  value={templateForm.name}
                  onChange={(e) => setTemplateForm((current) => ({ ...current, name: e.target.value }))}
                  placeholder="Example: Follow Up Interview"
                />
              </label>
              <label>
                Category
                <SingleSelectDropdown
                  value={templateForm.category || 'general'}
                  placeholder="Select category"
                  searchPlaceholder="Search category"
                  options={TEMPLATE_CATEGORY_OPTIONS}
                  onChange={(nextValue) => setTemplateForm((current) => ({ ...current, category: nextValue || 'general' }))}
                />
              </label>
              <label className="tracking-form-span-2">
                Template Paragraph
                <textarea
                  rows={6}
                  value={templateForm.paragraph}
                  onChange={(e) => setTemplateForm((current) => ({ ...current, paragraph: e.target.value }))}
                  placeholder="Example: Hi {name}, I’m reaching out about the {role} role at {company_name}. My experience at {current_employer} and {years_of_experience} years in the field feel closely aligned."
                />
              </label>
              {templateError ? <p className="error tracking-form-span-2">{templateError}</p> : null}
              <div className="profile-template-hint-panel tracking-form-span-2">
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setShowTemplateHints((current) => !current)}
                >
                  {showTemplateHints ? 'Hide Hints' : 'Show Hints'}
                </button>
                {showTemplateHints ? (
                  <div className="profile-template-hint-box">
                    <p className="hint profile-form-note">Pick the category first, then write one reusable paragraph with placeholders.</p>
                    <p className="hint profile-form-note">Available placeholders: <code>{'{name}'}</code>, <code>{'{employee_name}'}</code>, <code>{'{first_name}'}</code>, <code>{'{employee_role}'}</code>, <code>{'{department}'}</code>, <code>{'{employee_department}'}</code>, <code>{'{company_name}'}</code>, <code>{'{current_employer}'}</code>, <code>{'{role}'}</code>, <code>{'{job_id}'}</code>, <code>{'{job_link}'}</code>, <code>{'{resume_link}'}</code>, <code>{'{years_of_experience}'}</code>, <code>{'{yoe}'}</code>, <code>{'{interaction_time}'}</code>, <code>{'{interview_round}'}</code>.</p>
                  </div>
                ) : null}
              </div>
            </div>
            <div className="actions">
              <button type="button" onClick={saveTemplate}>{editingTemplateId ? 'Update' : 'Create'}</button>
              <button type="button" className="secondary" onClick={closeTemplateForm}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  )
}

export default TemplatesPage
