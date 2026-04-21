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
  { value: 'opening', label: 'Opening' },
  { value: 'experience', label: 'Experience' },
  { value: 'closing', label: 'Closing' },
  { value: 'general', label: 'General' },
]
const EMPTY_TEMPLATE = {
  name: '',
  category: 'general',
  paragraph: '',
}
const PAGE_SIZE = 10

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
  const category = String(row?.category || 'general').trim().toLowerCase()
  const name = String(row?.name || '').trim().toLowerCase()
  return `${category}|${name}`
}

function sortTemplates(rows) {
  const nextRows = Array.isArray(rows) ? [...rows] : []
  nextRows.sort((left, right) => templateSortValue(left).localeCompare(templateSortValue(right)))
  return nextRows
}

function humanizeCategory(value) {
  return String(value || 'general').trim().replaceAll('_', ' ') || 'general'
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
    const selectedCategory = String(category || '').trim().toLowerCase()
    const nextRows = Array.isArray(rows) ? rows : []
    if (!selectedCategory) return nextRows
    return nextRows.filter((row) => String(row?.category || '').trim().toLowerCase() === selectedCategory)
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
  }

  const editTemplate = (row) => {
    if (!row?.can_edit) return
    setError('')
    setOk('')
    setEditingTemplateId(row.id)
    setTemplateForm({
      name: row.name || '',
      category: row.category || 'general',
      paragraph: row.paragraph || '',
    })
    setShowTemplateHints(false)
    setShowForm(true)
  }

  const saveTemplate = async () => {
    try {
      setError('')
      setOk('')
      const payload = {
        name: String(templateForm.name || '').trim(),
        category: String(templateForm.category || 'general').trim() || 'general',
        paragraph: String(templateForm.paragraph || '').trim(),
      }
      if (!payload.name || !payload.paragraph) {
        setError('Template needs name and paragraph text.')
        return
      }
      if (editingTemplateId) {
        const updated = await updateTemplate(accessToken, editingTemplateId, payload)
        setRows((prev) => sortTemplates(prev.map((row) => (row.id === editingTemplateId ? updated : row))))
        setOk('Template updated.')
      } else {
        const created = await createTemplate(accessToken, payload)
        setRows((prev) => sortTemplates([created, ...prev]))
        setOk('Template added.')
      }
      closeTemplateForm()
    } catch (err) {
      setError(err.message || 'Could not save template.')
    }
  }

  const removeTemplate = async (row) => {
    if (!row?.can_delete) return
    try {
      setError('')
      setOk('')
      await deleteTemplate(accessToken, row.id)
      setRows((prev) => prev.filter((item) => item.id !== row.id))
      setOk('Template deleted.')
    } catch (err) {
      setError(err.message || 'Could not delete template.')
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
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <h2>{editingTemplateId ? 'Edit Template' : 'Add Template'}</h2>
            <div className="grid">
              <label>Name<input value={templateForm.name} onChange={(e) => setTemplateForm((current) => ({ ...current, name: e.target.value }))} /></label>
              <label>Category<select value={templateForm.category || 'general'} onChange={(e) => setTemplateForm((current) => ({ ...current, category: e.target.value }))}><option value="personalized">Personalized</option><option value="follow_up">Follow Up</option><option value="opening">Opening</option><option value="experience">Experience</option><option value="closing">Closing</option><option value="general">General</option></select></label>
              <label>Paragraph</label>
              <div className="rich-editor-shell">
                <textarea rows={4} value={templateForm.paragraph} onChange={(e) => setTemplateForm((current) => ({ ...current, paragraph: e.target.value }))} placeholder="Example: Hi {name}, I’m reaching out about the {role} role at {company_name}. My experience at {current_employer} and {years_of_experience} years in the field feel closely aligned." />
              </div>
              <div className="actions" style={{ justifyContent: 'space-between' }}>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setShowTemplateHints((current) => !current)}
                >
                  {showTemplateHints ? 'Hide Hints' : 'Show Hints'}
                </button>
                {showTemplateHints ? (
                  <div className="hint" style={{ flex: 1, marginLeft: 12 }}>
                    Available placeholders: {'{name}'}, {'{employee_name}'}, {'{first_name}'}, {'{employee_role}'}, {'{department}'}, {'{employee_department}'}, {'{company_name}'}, {'{current_employer}'}, {'{role}'}, {'{job_id}'}, {'{job_link}'}, {'{resume_link}'}, {'{years_of_experience}'}, {'{yoe}'}, {'{interaction_time}'}, {'{interview_round}'}.
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
