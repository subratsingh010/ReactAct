import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { fetchProfile } from '../api'
import { useAuth } from '../contexts/useAuth'
import { useTheme } from '../contexts/useTheme'

function MenuIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="currentColor" d="M4 7h16v2H4V7Zm0 8h16v2H4v-2Zm0-4h16v2H4v-2Z" />
    </svg>
  )
}

function NavBar() {
  const [openForPath, setOpenForPath] = useState('')
  const [username, setUsername] = useState('')
  const { accessToken, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const { theme, toggleTheme } = useTheme()
  const currentPath = location.pathname
  const currentLocationKey = `${location.pathname}${location.search}${location.hash}`
  const open = openForPath === currentLocationKey

  const items = useMemo(
    () => [
      { label: 'Home', path: '/' },
      { label: 'Profile', path: '/profile' },
      { label: 'Templates', path: '/templates' },
      { label: 'Companies', path: '/companies' },
      { label: 'Tracking', path: '/tracking' },
      { label: 'Schedule', path: '/tracking-schedule' },
      { label: 'Jobs', path: '/jobs' },
      { label: 'Bulk', path: '/bulk-upload' },
    ],
    [],
  )

  const go = (path) => {
    setOpenForPath('')
    navigate(path)
  }

  useEffect(() => {
    if (!accessToken) return
    let cancelled = false
    fetchProfile(accessToken)
      .then((p) => {
        if (!cancelled) setUsername(String(p?.username || ''))
      })
      .catch(() => {
        if (!cancelled) setUsername('')
      })
    return () => {
      cancelled = true
    }
  }, [accessToken])

  const displayUsername = accessToken ? username : ''

  return (
    <header className="nav sticky top-0">
      <div className="nav-inner mx-auto flex w-full items-center justify-between">
        <button type="button" className="nav-brand" onClick={() => go('/')}>
          <span className="nav-brand-mark">AP</span>
          <span className="nav-brand-copy">
            <strong>ApplyPilot</strong>
            <small>Jobs, Tracking, Resumes</small>
          </span>
        </button>

        <button
          type="button"
          className="nav-toggle secondary"
          onClick={() => setOpenForPath((value) => (value === currentLocationKey ? '' : currentLocationKey))}
          aria-expanded={open ? 'true' : 'false'}
          aria-controls="nav-links"
        >
          <MenuIcon />
          <span>Menu</span>
        </button>

        <nav id="nav-links" className={`nav-links${open ? ' is-open' : ''}`}>
          <div className="nav-left nav-link-cluster">
            {items.map((item) => (
              <button
                key={item.path}
                type="button"
                className={`nav-link${currentPath === item.path ? ' is-active' : ''}`}
                onClick={() => go(item.path)}
              >
                {item.label}
              </button>
            ))}
          </div>

          <div className="nav-right">
            {displayUsername ? (
              <div className="nav-user-block">
                <div className="nav-user">{displayUsername}</div>
              </div>
            ) : null}

            <button
              type="button"
              className="nav-icon-btn"
              onClick={() => {
                setOpenForPath('')
                toggleTheme()
              }}
              aria-label="Toggle dark mode"
              title="Toggle dark mode"
            >
              {theme === 'dark' ? (
                <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    fill="currentColor"
                    d="M12 18a6 6 0 1 1 0-12a6 6 0 0 1 0 12ZM12 2h1v3h-1V2Zm0 19h1v3h-1v-3ZM4.22 5.64l.7-.7l2.12 2.12l-.7.7L4.22 5.64Zm12.62 12.62l.7-.7l2.12 2.12l-.7.7l-2.12-2.12ZM2 12h3v1H2v-1Zm19 0h3v1h-3v-1ZM4.22 18.36l2.12-2.12l.7.7l-2.12 2.12l-.7-.7ZM16.96 7.06l2.12-2.12l.7.7l-2.12 2.12l-.7-.7Z"
                  />
                </svg>
              ) : (
                <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    fill="currentColor"
                    d="M12.74 2a9 9 0 0 0 0 18A9 9 0 0 1 12.74 2Zm0 20C7.37 22 3 17.63 3 12.26S7.37 2.52 12.74 2.52c.78 0 1.55.1 2.29.29a1 1 0 0 1 .29 1.82A7 7 0 0 0 12.74 22Z"
                  />
                </svg>
              )}
            </button>

            <button
              type="button"
              className="nav-link nav-link-logout danger"
              onClick={() => {
                setOpenForPath('')
                logout()
                navigate('/login')
              }}
            >
              Logout
            </button>
          </div>
        </nav>
      </div>
    </header>
  )
}

export default NavBar
