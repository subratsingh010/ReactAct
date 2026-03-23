import { useEffect, useMemo, useState } from 'react'

import AuthContext from './auth-context'

function dispatchAuthChanged() {
  window.dispatchEvent(new Event('auth-changed'))
}

export function AuthProvider({ children }) {
  const [tokens, setTokens] = useState(() => ({
    access: localStorage.getItem('access') || '',
    refresh: localStorage.getItem('refresh') || '',
  }))

  useEffect(() => {
    const syncAuth = () => {
      setTokens({
        access: localStorage.getItem('access') || '',
        refresh: localStorage.getItem('refresh') || '',
      })
    }

    window.addEventListener('storage', syncAuth)
    window.addEventListener('auth-changed', syncAuth)
    return () => {
      window.removeEventListener('storage', syncAuth)
      window.removeEventListener('auth-changed', syncAuth)
    }
  }, [])

  const value = useMemo(
    () => ({
      accessToken: tokens.access,
      refreshToken: tokens.refresh,
      isLoggedIn: Boolean(tokens.access),
      login: (access, refresh) => {
        localStorage.setItem('access', access)
        localStorage.setItem('refresh', refresh)
        setTokens({ access, refresh })
        dispatchAuthChanged()
      },
      logout: () => {
        localStorage.removeItem('access')
        localStorage.removeItem('refresh')
        setTokens({ access: '', refresh: '' })
        dispatchAuthChanged()
      },
    }),
    [tokens],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
