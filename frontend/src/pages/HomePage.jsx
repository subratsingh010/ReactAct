import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { fetchProfile } from '../api'
import { useAuth } from '../contexts/useAuth'

function HomePage() {
  const [username, setUsername] = useState('')
  const navigate = useNavigate()
  const { isLoggedIn } = useAuth()

  useEffect(() => {
    const access = localStorage.getItem('access')
    if (!access) return
    fetchProfile(access)
      .then((p) => setUsername(String(p?.username || '')))
      .catch(() => {})
  }, [])

  return (
    <main className="home-shell w-full">
      {username && (
        <div className="home-top">
          <div className="home-top-inner mx-auto flex justify-center">
            <p className="home-welcome">Welcome {username} 🖐🏻!</p>
          </div>
        </div>
      )}

      <div className="page page-wide home mx-auto w-full">
        <div className="home-hero grid items-start gap-5">
        <div className="home-left flex flex-col gap-4">
          <h1>Resume Builder + ATS Score</h1>
          <p className="subtitle">
            Build an A4 resume, preview it live, export to PDF, and score it against role keywords.
          </p>
            <div className="actions flex flex-wrap gap-3">
              {!isLoggedIn && (
                <>
                  <button type="button" onClick={() => navigate('/login')}>
                    Login
                  </button>
                  <button type="button" className="secondary" onClick={() => navigate('/register')}>
                    Register
                  </button>
                </>
              )}
              <button type="button" onClick={() => navigate('/dashboard')}>
                Dashboard
              </button>
              <button type="button" className="secondary" onClick={() => navigate('/builder')}>
                Resume Builder
              </button>
            </div>
          </div>

          <div className="home-right grid gap-3">
            <div className="home-card">
              <h2 className="home-card-title">What you get</h2>
              <ul className="home-list">
                <li>A4 resume preview that matches print</li>
                <li>Section ordering + custom sections</li>
                <li>ATS score (0–100) using keyword profiles</li>
                <li>Experience/project bullets quality checks</li>
              </ul>
            </div>
            <div className="home-card home-card-accent">
              <h2 className="home-card-title">Tip</h2>
              <p className="home-tip">
                Write 3+ bullets per experience/project, keep each bullet 50–100 characters, and add numbers.
              </p>
            </div>
          </div>
        </div>
      </div>
    </main>
  )
}

export default HomePage
