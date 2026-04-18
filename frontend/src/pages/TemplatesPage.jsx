import { useEffect, useMemo, useState } from 'react'

import { fetchTemplates } from '../api'
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

function formatTemplateHeading(row) {
  const category = String(row?.category || 'general').trim().replaceAll('_', ' ')
  const rawName = String(row?.name || 'Template').trim() || 'Template'
  const name = rawName.replace(/^\[system seed\]\s*/i, '').trim() || rawName
  const owner = String(row?.owner_label || '').trim() || 'system'
  return `${category} - ${name} | ${owner}`
}

function formatTemplateMetaLabel(value, fallback = '-') {
  const text = String(value || '').trim()
  if (!text) return fallback
  return text.replaceAll('_', ' ')
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

function templateSortValue(row) {
  const category = String(row?.category || 'general').trim().toLowerCase()
  const name = String(row?.name || '').trim().toLowerCase()
  const owner = String(row?.owner_label || 'system').trim().toLowerCase()
  return `${category}|${name}|${owner}`
}

function TemplatesPage() {
  const { accessToken } = useAuth()
  const [rows, setRows] = useState([])
  const [category, setCategory] = useState('')
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(() => Boolean(accessToken))
  const [error, setError] = useState('')

  useEffect(() => {
    if (!accessToken) return undefined
    let cancelled = false
    fetchTemplates(accessToken)
      .then((data) => {
        if (cancelled) return
        const nextRows = Array.isArray(data) ? [...data] : []
        nextRows.sort((left, right) => templateSortValue(left).localeCompare(templateSortValue(right)))
        setRows(nextRows)
        setError('')
      })
      .catch((err) => {
        if (!cancelled) {
          setRows([])
          setError(err.message || 'Could not load templates.')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [accessToken])

  const filteredRows = useMemo(() => {
    const systemRows = (Array.isArray(rows) ? rows : []).filter(
      (row) => String(row?.template_scope || '').trim().toLowerCase() === 'system',
    )
    const selectedCategory = String(category || '').trim().toLowerCase()
    if (!selectedCategory) return systemRows
    return systemRows.filter((row) => String(row?.category || '').trim().toLowerCase() === selectedCategory)
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

  return (
    <main className="page page-wide">
      <section className="dash-card">
        <div className="tracking-head profile-section-head">
          <div>
            <h1>Template Library</h1>
            <p className="subtitle">View shared system templates here. Personal templates stay in Profile.</p>
          </div>
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
        </div>

        {loading ? <p className="hint">Loading templates...</p> : null}
        {!loading && error ? <p className="error">{error}</p> : null}

        {!loading && !error ? (
          <>
            <div className="template-library-grid">
            {pagedRows.map((row) => (
              <article key={row.id} className="profile-template-row">
                <div className="profile-template-main">
                  <p className="profile-template-title"><strong>{formatTemplateHeading(row)}</strong></p>
                  <div className="profile-template-meta-list">
                    <span className="profile-template-meta-chip">{formatTemplateMetaLabel(row?.template_scope, 'system')}</span>
                    <span className="profile-template-meta-chip">{formatTemplateMetaLabel(row?.category, 'general')}</span>
                    <span className="profile-template-meta-chip">Owner: {String(row?.owner_label || 'system').trim() || 'system'}</span>
                    <span className="profile-template-meta-chip">Words: {templateWordCount(row?.paragraph)}</span>
                    <span className="profile-template-meta-chip">Updated: {formatTemplateDate(row?.updated_at || row?.created_at)}</span>
                  </div>
                  <p className="profile-template-snippet">{row.paragraph || '-'}</p>
                </div>
              </article>
            ))}
            {!rows.some((row) => String(row?.template_scope || '').trim().toLowerCase() === 'system') ? <p className="hint">No system templates available yet.</p> : null}
            {rows.some((row) => String(row?.template_scope || '').trim().toLowerCase() === 'system') && !filteredRows.length ? <p className="hint">No system templates in this category.</p> : null}
            </div>
            {filteredRows.length > PAGE_SIZE ? (
              <div className="table-pagination">
                <button type="button" className="secondary" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={currentPage <= 1}>Previous</button>
                <div className="table-pagination-numbers" aria-label="Template Library pages">
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
    </main>
  )
}

export default TemplatesPage
