import { useEffect, useRef, useState } from 'react'

export function SingleSelectDropdown({
  value,
  onChange,
  options,
  placeholder,
  disabled = false,
  clearLabel = 'Please select',
  searchPlaceholder = '',
}) {
  const wrapRef = useRef(null)
  const inputRef = useRef(null)
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')

  useEffect(() => {
    const found = (options || []).find((opt) => String(opt.value) === String(value || ''))
    setText(found ? String(found.label || '') : '')
    setSearchQuery('')
  }, [options, value])

  useEffect(() => {
    const onDocMouseDown = (event) => {
      if (!wrapRef.current) return
      if (!wrapRef.current.contains(event.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDocMouseDown)
    return () => document.removeEventListener('mousedown', onDocMouseDown)
  }, [])

  const filtered = (options || []).filter((opt) => {
    const label = String(opt.label || '').toLowerCase()
    const query = String(searchQuery || '').toLowerCase().trim()
    return !query || label.includes(query)
  })

  return (
    <div ref={wrapRef} className={`search-dd ${disabled ? 'is-disabled' : ''}`}>
      <div className="search-dd-input-wrap">
        <input
          ref={inputRef}
          className="search-dd-input"
          value={text}
          disabled={disabled}
          placeholder={open && searchPlaceholder ? searchPlaceholder : placeholder}
          onClick={() => {
            if (!disabled) {
              setOpen(true)
            }
          }}
          onFocus={() => {
            if (!disabled) {
              setOpen(true)
              setSearchQuery('')
            }
          }}
          onChange={(event) => {
            const nextText = event.target.value
            setText(nextText)
            setSearchQuery(nextText)
            setOpen(true)
          }}
        />
        <button
          type="button"
          className="search-dd-toggle"
          disabled={disabled}
          onMouseDown={(event) => event.preventDefault()}
          onTouchStart={(event) => event.preventDefault()}
          onClick={() => {
            if (disabled) return
            setOpen((prev) => {
              const next = !prev
              if (next) {
                window.requestAnimationFrame(() => inputRef.current?.focus())
              }
              return next
            })
          }}
          aria-label="Toggle options"
        >
          {open ? '▴' : '▾'}
        </button>
      </div>
      {open && !disabled ? (
        <div className="search-dd-menu" role="listbox">
          <button
            type="button"
            className={`search-dd-item ${String(value || '') ? '' : 'is-active'}`}
            onClick={() => {
              setText('')
              setSearchQuery('')
              setOpen(false)
              onChange('')
            }}
          >
            {clearLabel}
          </button>
          {filtered.length ? (
            filtered.map((opt) => (
              <button
                key={String(opt.value)}
                type="button"
                className={`search-dd-item ${String(value || '') === String(opt.value) ? 'is-active' : ''}`}
                onClick={() => {
                  setText(String(opt.label || ''))
                  setSearchQuery('')
                  setOpen(false)
                  onChange(String(opt.value))
                }}
              >
                {String(opt.label || '')}
              </button>
            ))
          ) : (
            <div className="search-dd-empty">No results</div>
          )}
        </div>
      ) : null}
    </div>
  )
}

export function MultiSelectDropdown({
  values,
  onChange,
  options,
  placeholder,
  disabled = false,
  searchPlaceholder = 'Search',
  className = '',
}) {
  const wrapRef = useRef(null)
  const inputRef = useRef(null)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')

  const safeValues = Array.isArray(values) ? values.map((v) => String(v)) : []
  const selectedSet = new Set(safeValues)
  const selectedLabels = (options || [])
    .filter((opt) => selectedSet.has(String(opt.value)))
    .map((opt) => String(opt.label || ''))
    .filter(Boolean)

  useEffect(() => {
    const onDocMouseDown = (event) => {
      if (!wrapRef.current) return
      if (!wrapRef.current.contains(event.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDocMouseDown)
    return () => document.removeEventListener('mousedown', onDocMouseDown)
  }, [])

  const filtered = (options || []).filter((opt) => {
    const label = String(opt.label || '').toLowerCase()
    const text = String(query || '').trim().toLowerCase()
    return !text || label.includes(text)
  })
  const filteredIds = filtered.map((opt) => String(opt.value))

  const summary = selectedLabels.length
    ? `${selectedLabels.slice(0, 2).join(', ')}${selectedLabels.length > 2 ? ` +${selectedLabels.length - 2}` : ''}`
    : ''
  const inputValue = open ? query : summary

  return (
    <div ref={wrapRef} className={`search-dd ${disabled ? 'is-disabled' : ''} ${className}`.trim()}>
      <div className="search-dd-input-wrap">
        <input
          ref={inputRef}
          className={`search-dd-input ${summary && !open ? '' : 'search-dd-placeholder'}`}
          value={inputValue}
          disabled={disabled}
          readOnly={!open}
          placeholder={open ? searchPlaceholder : placeholder}
          onClick={() => {
            if (!disabled) {
              setOpen(true)
            }
          }}
          onFocus={() => {
            if (!disabled) {
              setOpen(true)
              setQuery('')
            }
          }}
          onChange={(event) => {
            setQuery(event.target.value)
            setOpen(true)
          }}
        />
        <button
          type="button"
          className="search-dd-toggle"
          disabled={disabled}
          onMouseDown={(event) => event.preventDefault()}
          onTouchStart={(event) => event.preventDefault()}
          onClick={() => {
            if (disabled) return
            setOpen((prev) => {
              const next = !prev
              if (next) {
                setQuery('')
                window.requestAnimationFrame(() => inputRef.current?.focus())
              }
              return next
            })
          }}
          aria-label="Toggle options"
        >
          {open ? '▴' : '▾'}
        </button>
      </div>
      {open && !disabled ? (
        <div className="search-dd-menu" role="listbox">
          <div className="search-dd-multi-list">
            {filtered.length ? (
              filtered.map((opt) => {
                const id = String(opt.value)
                const checked = selectedSet.has(id)
                return (
                  <label
                    key={id}
                    className={`search-dd-item search-dd-multi-option ${checked ? 'is-active' : ''}`}
                    onMouseDown={(event) => event.preventDefault()}
                    onTouchStart={(event) => event.preventDefault()}
                  >
                    <input
                      type="checkbox"
                      className="search-dd-multi-checkbox"
                      checked={checked}
                      onChange={(event) => {
                        const next = new Set(safeValues)
                        if (event.target.checked) next.add(id)
                        else next.delete(id)
                        onChange(Array.from(next))
                      }}
                    />
                    <span className="search-dd-multi-option-label">{String(opt.label || '')}</span>
                    <span className="search-dd-multi-option-mark" aria-hidden="true">{checked ? '✓' : ''}</span>
                  </label>
                )
              })
            ) : (
              <div className="search-dd-empty">No results</div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  )
}
