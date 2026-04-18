import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { fetchResume } from '../api'
import ResumeSheet from '../components/ResumeSheet'
import { printAtsPdf } from '../utils/resumeExport'

function ResumePreviewPage() {
  const [resume, setResume] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const { resumeId = '' } = useParams()

  useEffect(() => {
    const load = async () => {
      const access = localStorage.getItem('access')
      if (!access) {
        navigate('/login')
        return
      }
      if (!resumeId) {
        navigate('/')
        return
      }
      setError('')
      try {
        setLoading(true)
        const data = await fetchResume(access, resumeId)
        setResume(data)
      } catch (err) {
        setError(err.message || 'Failed to load resume')
      } finally {
        setLoading(false)
      }
    }

    load()
  }, [navigate, resumeId])

  const handleEdit = async () => {
    const access = localStorage.getItem('access')
    if (!access) {
      navigate('/login')
      return
    }
    try {
      setLoading(true)
      const full = await fetchResume(access, resumeId)
      sessionStorage.setItem('builderImport', JSON.stringify(full.builder_data || {}))
      sessionStorage.setItem('builderSaveMode', 'edit')
      sessionStorage.setItem('builderResumeId', String(resumeId))
      navigate('/builder')
    } catch (err) {
      setError(err.message || 'Failed to open resume in builder')
    } finally {
      setLoading(false)
    }
  }

  const handlePdf = () => {
    if (!resume?.builder_data) return
    printAtsPdf(resume.builder_data)
  }

  return (
    <main className="page page-wide page-plain">
      <div className="preview-only-header">
        <div>
          <h1 className="preview-only-title">Preview</h1>
          <p className="subtitle preview-only-subtitle">
            {resume?.title ? resume.title : 'Resume'}
          </p>
        </div>
        <div className="actions">
          <button type="button" className="secondary" onClick={() => navigate('/')}>
            Back
          </button>
          <button type="button" onClick={handleEdit} disabled={loading || !resumeId}>
            Edit
          </button>
          <button type="button" className="secondary" onClick={handlePdf}>
            ATS PDF
          </button>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {loading && !resume && <p className="hint">Loading...</p>}

      {resume && (
        <section className="preview-only">
          <ResumeSheet form={resume.builder_data || {}} />
        </section>
      )}
    </main>
  )
}

export default ResumePreviewPage
