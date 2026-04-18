import { useEffect, useMemo, useRef, useState } from 'react'

import Link from '@tiptap/extension-link'
import Placeholder from '@tiptap/extension-placeholder'
import TextAlign from '@tiptap/extension-text-align'
import { FontFamily, TextStyle } from '@tiptap/extension-text-style'
import Underline from '@tiptap/extension-underline'
import { EditorContent, useEditor, useEditorState } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'

import { useTheme } from '../contexts/useTheme'

const ALLOWED_TAGS = new Set([
  'B',
  'STRONG',
  'I',
  'EM',
  'S',
  'DEL',
  'STRIKE',
  'U',
  'P',
  'BR',
  'UL',
  'OL',
  'LI',
  'A',
  'SPAN',
  'H1',
  'H2',
  'H3',
  'H4',
])
const ALLOWED_TEXT_ALIGN = new Set(['left', 'center', 'right', 'justify'])
const FONT_OPTIONS = [
  { key: 'default', label: 'Default', value: '' },
  { key: 'arial', label: 'Arial', value: 'Arial, Helvetica, sans-serif' },
  { key: 'calibri', label: 'Calibri', value: 'Calibri, Arial, sans-serif' },
  { key: 'cambria', label: 'Cambria', value: 'Cambria, Georgia, serif' },
  { key: 'georgia', label: 'Georgia', value: 'Georgia, serif' },
  { key: 'garamond', label: 'Garamond', value: 'Garamond, Georgia, serif' },
  { key: 'times', label: 'Times New Roman', value: '"Times New Roman", Times, serif' },
  { key: 'verdana', label: 'Verdana', value: 'Verdana, Geneva, sans-serif' },
  { key: 'tahoma', label: 'Tahoma', value: 'Tahoma, Geneva, sans-serif' },
  { key: 'trebuchet', label: 'Trebuchet MS', value: '"Trebuchet MS", Helvetica, sans-serif' },
  { key: 'palatino', label: 'Palatino', value: '"Palatino Linotype", Palatino, serif' },
]
const DEFAULT_EDITOR_STATE = {
  bold: false,
  italic: false,
  underline: false,
  bulletList: false,
  orderedList: false,
  link: false,
  alignLeft: true,
  alignCenter: false,
  alignRight: false,
  alignJustify: false,
  fontFamily: 'default',
}

function sanitizeHtml(inputHtml) {
  const parser = new DOMParser()
  const doc = parser.parseFromString(String(inputHtml || ''), 'text/html')

  const sanitizeNode = (node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      return document.createTextNode(node.nodeValue || '')
    }

    if (node.nodeType !== Node.ELEMENT_NODE) {
      return document.createTextNode('')
    }

    const tag = node.tagName

    if (tag === 'DIV') {
      const p = document.createElement('p')
      node.childNodes.forEach((child) => p.appendChild(sanitizeNode(child)))
      return p
    }

    if (!ALLOWED_TAGS.has(tag)) {
      const frag = document.createDocumentFragment()
      node.childNodes.forEach((child) => frag.appendChild(sanitizeNode(child)))
      return frag
    }

    const el = document.createElement(tag.toLowerCase())
    if (tag === 'A') {
      const href = String(node.getAttribute('href') || '').trim()
      if (href && /^(https?:\/\/|mailto:)/i.test(href)) {
        el.setAttribute('href', href)
      }
      el.setAttribute('target', '_blank')
      el.setAttribute('rel', 'noreferrer')
    }

    if (tag === 'P' || tag === 'UL' || tag === 'OL' || tag === 'LI' || tag === 'H1' || tag === 'H2' || tag === 'H3' || tag === 'H4') {
      const styleAttr = String(node.getAttribute('style') || '')
      const match = styleAttr.match(/text-align\s*:\s*(left|center|right|justify)/i)
      const align = match ? String(match[1] || '').toLowerCase() : ''
      if (ALLOWED_TEXT_ALIGN.has(align)) {
        el.setAttribute('style', `text-align:${align}`)
      }
    }

    if (tag === 'SPAN') {
      const styleAttr = String(node.getAttribute('style') || '')
      const styles = []
      const fontMatch = styleAttr.match(/font-family\s*:\s*([^;]+)/i)
      const fontFamily = fontMatch ? String(fontMatch[1] || '').trim() : ''
      if (fontFamily) styles.push(`font-family:${fontFamily}`)
      if (styles.length) el.setAttribute('style', styles.join(';'))
    }

    node.childNodes.forEach((child) => el.appendChild(sanitizeNode(child)))
    return el
  }

  const container = document.createElement('div')
  doc.body.childNodes.forEach((child) => container.appendChild(sanitizeNode(child)))
  const text = (container.textContent || '').trim()
  if (!text) return ''
  return container.innerHTML
}

function normalizeLink(value) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  if (/^mailto:/i.test(raw)) return raw
  if (/^https?:\/\//i.test(raw)) return raw
  return `https://${raw}`
}

function findFontKey(value) {
  const normalizeFontString = (input) =>
    String(input || '')
      .trim()
      .toLowerCase()
      .replace(/['"]/g, '')
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean)

  const targetParts = normalizeFontString(value)
  if (!targetParts.length) return 'default'

  const match = FONT_OPTIONS.find((option) => {
    const optionParts = normalizeFontString(option.value)
    if (!optionParts.length) return false
    return optionParts[0] === targetParts[0]
  })
  return match ? match.key : 'default'
}

function Icon({ name }) {
  const common = {
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: '1.8',
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    viewBox: '0 0 24 24',
    className: 'toolbar-icon-svg',
    'aria-hidden': 'true',
  }

  const icons = {
    minus: (
      <svg {...common}>
        <path d="M5 12h14" />
      </svg>
    ),
    plus: (
      <svg {...common}>
        <path d="M12 5v14" />
        <path d="M5 12h14" />
      </svg>
    ),
    chevron: (
      <svg {...common}>
        <path d="m7 10 5 5 5-5" />
      </svg>
    ),
    bulletList: (
      <svg {...common}>
        <circle cx="5" cy="7" r="1.1" fill="currentColor" stroke="none" />
        <circle cx="5" cy="12" r="1.1" fill="currentColor" stroke="none" />
        <circle cx="5" cy="17" r="1.1" fill="currentColor" stroke="none" />
        <path d="M9 7h11" />
        <path d="M9 12h11" />
        <path d="M9 17h11" />
      </svg>
    ),
    orderedList: (
      <svg {...common}>
        <path d="M3.8 6.5h1.7v2.7" />
        <path d="M3.3 9.2h2.8" />
        <path d="M3.5 12c.3-.5.8-.8 1.5-.8.9 0 1.5.5 1.5 1.2 0 .5-.3.9-.8 1.2l-1.1.8H6.7" />
        <path d="M3.5 16.2c.3-.4.8-.7 1.5-.7.9 0 1.5.5 1.5 1.2 0 .5-.4.9-.9 1.1.6.1 1 .5 1 1.1 0 .8-.6 1.3-1.7 1.3-.7 0-1.2-.3-1.6-.8" />
        <path d="M10 7h10" />
        <path d="M10 12h10" />
        <path d="M10 17h10" />
      </svg>
    ),
    bold: (
      <svg {...common}>
        <path d="M8 6h5.5a3 3 0 0 1 0 6H8z" />
        <path d="M8 12h6.5a3 3 0 0 1 0 6H8z" />
      </svg>
    ),
    italic: (
      <svg {...common}>
        <path d="M13 4h4" />
        <path d="M7 20h4" />
        <path d="M14 4 10 20" />
      </svg>
    ),
    underline: (
      <svg {...common}>
        <path d="M8 4v6a4 4 0 1 0 8 0V4" />
        <path d="M6 20h12" />
      </svg>
    ),
    link: (
      <svg {...common}>
        <path d="M10 13a5 5 0 0 1 0-7l1-1a5 5 0 0 1 7 7l-1 1" />
        <path d="M14 11a5 5 0 0 1 0 7l-1 1a5 5 0 0 1-7-7l1-1" />
      </svg>
    ),
    alignLeft: (
      <svg {...common}>
        <path d="M4 6h16" />
        <path d="M4 10h11" />
        <path d="M4 14h16" />
        <path d="M4 18h11" />
      </svg>
    ),
    alignCenter: (
      <svg {...common}>
        <path d="M4 6h16" />
        <path d="M7 10h10" />
        <path d="M4 14h16" />
        <path d="M7 18h10" />
      </svg>
    ),
    alignRight: (
      <svg {...common}>
        <path d="M4 6h16" />
        <path d="M9 10h11" />
        <path d="M4 14h16" />
        <path d="M9 18h11" />
      </svg>
    ),
    alignJustify: (
      <svg {...common}>
        <path d="M4 6h16" />
        <path d="M4 10h16" />
        <path d="M4 14h16" />
        <path d="M4 18h16" />
      </svg>
    ),
  }

  return icons[name] || null
}

function ToolbarButton({ active, disabled, title, onClick, variant = 'icon', className = '', children }) {
  return (
    <button
      type="button"
      aria-label={title}
      onMouseDown={(event) => {
        event.preventDefault()
        if (disabled) return
        onClick()
      }}
      disabled={disabled}
      className={`toolbar-btn toolbar-btn-${variant}${active ? ' is-active' : ''}${disabled ? ' is-disabled' : ''}${className ? ` ${className}` : ''}`}
    >
      {children}
    </button>
  )
}

function RichTextarea({ id, label, value, onChange, placeholder }) {
  const { theme } = useTheme()
  const [showLinkEditor, setShowLinkEditor] = useState(false)
  const [linkDraft, setLinkDraft] = useState('')
  const [zoomLevel, setZoomLevel] = useState(100)
  const valueRef = useRef('')
  const onChangeRef = useRef(onChange)
  const sanitizedValue = useMemo(() => sanitizeHtml(value), [value])

  useEffect(() => {
    valueRef.current = sanitizedValue
    onChangeRef.current = onChange
  }, [sanitizedValue, onChange])

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: {
          levels: [1, 2, 3, 4],
        },
        blockquote: false,
        code: false,
        codeBlock: false,
        horizontalRule: false,
      }),
      Underline,
      TextStyle,
      FontFamily.configure({
        types: ['textStyle'],
      }),
      TextAlign.configure({
        types: ['paragraph', 'heading', 'listItem'],
      }),
      Link.configure({
        openOnClick: false,
        autolink: true,
        defaultProtocol: 'https',
        HTMLAttributes: {
          target: '_blank',
          rel: 'noreferrer',
        },
      }),
      Placeholder.configure({
        placeholder: placeholder || '',
      }),
    ],
    content: sanitizedValue,
    immediatelyRender: false,
    onUpdate: ({ editor: currentEditor }) => {
      const next = sanitizeHtml(currentEditor.getHTML())
      if (next !== valueRef.current) {
        valueRef.current = next
        onChangeRef.current(next)
      }
    },
    editorProps: {
      attributes: {
        id,
        class: 'rich-editor-surface',
      },
    },
  })

  const editorState = useEditorState({
    editor,
    selector: ({ editor: currentEditor }) =>
      currentEditor
        ? {
            bold: currentEditor.isActive('bold'),
            italic: currentEditor.isActive('italic'),
            underline: currentEditor.isActive('underline'),
            bulletList: currentEditor.isActive('bulletList'),
            orderedList: currentEditor.isActive('orderedList'),
            link: currentEditor.isActive('link'),
            alignLeft: currentEditor.isActive({ textAlign: 'left' }),
            alignCenter: currentEditor.isActive({ textAlign: 'center' }),
            alignRight: currentEditor.isActive({ textAlign: 'right' }),
            alignJustify: currentEditor.isActive({ textAlign: 'justify' }),
            fontFamily: findFontKey(currentEditor.getAttributes('textStyle').fontFamily),
          }
        : DEFAULT_EDITOR_STATE,
  })

  useEffect(() => {
    if (!editor) return
    editor.setOptions({
      editorProps: {
        attributes: {
          id,
          class: 'rich-editor-surface',
          'data-theme': theme,
        },
      },
    })
  }, [editor, id, theme])

  useEffect(() => {
    if (!editor) return
    const current = sanitizeHtml(editor.getHTML())
    if (current !== sanitizedValue) {
      editor.commands.setContent(sanitizedValue || '', { emitUpdate: false })
      valueRef.current = sanitizedValue
    }
  }, [editor, sanitizedValue])

  useEffect(() => {
    if (!editor) return undefined

    const syncLinkState = () => {
      if (!showLinkEditor) return
      setLinkDraft(editor.getAttributes('link').href || '')
    }

    editor.on('selectionUpdate', syncLinkState)
    return () => {
      editor.off('selectionUpdate', syncLinkState)
    }
  }, [editor, showLinkEditor])

  if (!editor) {
    return (
      <div className="rich-field">
        {label && <label htmlFor={id}>{label}</label>}
        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900/60 dark:text-slate-400">
          Loading editor...
        </div>
      </div>
    )
  }

  const openLinkEditor = () => {
    setLinkDraft(editor.getAttributes('link').href || '')
    setShowLinkEditor(true)
  }

  const applyLink = () => {
    const normalized = normalizeLink(linkDraft)
    if (!normalized) {
      editor.chain().focus().unsetLink().run()
      setShowLinkEditor(false)
      return
    }
    editor.chain().focus().extendMarkRange('link').setLink({ href: normalized }).run()
    setShowLinkEditor(false)
  }

  const adjustZoom = (delta) => {
    setZoomLevel((current) => Math.max(50, Math.min(175, current + delta)))
  }

  const applyFontFamily = (key) => {
    const selected = FONT_OPTIONS.find((option) => option.key === key)
    if (!selected || !selected.value) {
      editor.chain().focus().unsetFontFamily().run()
      return
    }
    editor.chain().focus().setFontFamily(selected.value).run()
  }

  return (
    <div className="rich-field">
      {label && <label htmlFor={id}>{label}</label>}
      <div className="grid gap-2">
        <div className="rich-toolbar">
            <ToolbarButton title="Zoom out" variant="icon" onClick={() => adjustZoom(-25)}>
              <Icon name="minus" />
            </ToolbarButton>
            <div className="toolbar-zoom" aria-label="Zoom level">
              {zoomLevel}%
            </div>
            <ToolbarButton title="Zoom in" variant="icon" onClick={() => adjustZoom(25)}>
              <Icon name="plus" />
            </ToolbarButton>
            <span className="toolbar-divider" aria-hidden="true" />
            <select
              aria-label="Font family"
              className="toolbar-native-select toolbar-native-select-font"
              value={editorState.fontFamily}
              onChange={(event) => applyFontFamily(event.target.value)}
            >
              {FONT_OPTIONS.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label}
                </option>
              ))}
            </select>
            <ToolbarButton
              title="Bullet list"
              active={editorState.bulletList}
              disabled={!editor.can().chain().focus().toggleBulletList().run()}
              onClick={() => editor.chain().focus().toggleBulletList().run()}
            >
              <Icon name="bulletList" />
            </ToolbarButton>
            <ToolbarButton
              title="Ordered list"
              active={editorState.orderedList}
              disabled={!editor.can().chain().focus().toggleOrderedList().run()}
              onClick={() => editor.chain().focus().toggleOrderedList().run()}
            >
              <Icon name="orderedList" />
            </ToolbarButton>
            <ToolbarButton
              title="Bold"
              active={editorState.bold}
              disabled={!editor.can().chain().focus().toggleBold().run()}
              onClick={() => editor.chain().focus().toggleBold().run()}
            >
              <Icon name="bold" />
            </ToolbarButton>
            <ToolbarButton
              title="Italic"
              active={editorState.italic}
              disabled={!editor.can().chain().focus().toggleItalic().run()}
              onClick={() => editor.chain().focus().toggleItalic().run()}
            >
              <Icon name="italic" />
            </ToolbarButton>
            <ToolbarButton
              title="Add link"
              active={editorState.link || showLinkEditor}
              onClick={openLinkEditor}
            >
              <Icon name="link" />
            </ToolbarButton>
            <ToolbarButton
              title="Underline"
              active={editorState.underline}
              disabled={!editor.can().chain().focus().toggleUnderline().run()}
              onClick={() => editor.chain().focus().toggleUnderline().run()}
            >
              <Icon name="underline" />
            </ToolbarButton>
            <span className="toolbar-divider" aria-hidden="true" />
            <ToolbarButton
              title="Align left"
              active={editorState.alignLeft}
              onClick={() => editor.chain().focus().setTextAlign('left').run()}
            >
              <Icon name="alignLeft" />
            </ToolbarButton>
            <ToolbarButton
              title="Align center"
              active={editorState.alignCenter}
              onClick={() => editor.chain().focus().setTextAlign('center').run()}
            >
              <Icon name="alignCenter" />
            </ToolbarButton>
            <ToolbarButton
              title="Align right"
              active={editorState.alignRight}
              onClick={() => editor.chain().focus().setTextAlign('right').run()}
            >
              <Icon name="alignRight" />
            </ToolbarButton>
            <ToolbarButton
              title="Justify"
              active={editorState.alignJustify}
              onClick={() => editor.chain().focus().setTextAlign('justify').run()}
            >
              <Icon name="alignJustify" />
            </ToolbarButton>
        </div>
        {showLinkEditor && (
          <div className="rich-link-panel">
            <input
              type="text"
              value={linkDraft}
              onChange={(event) => setLinkDraft(event.target.value)}
              placeholder="https://example.com"
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  applyLink()
                }
                if (event.key === 'Escape') {
                  event.preventDefault()
                  setShowLinkEditor(false)
                }
              }}
            />
            <div className="rich-link-actions">
              <button type="button" onClick={applyLink}>
                Apply
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  setShowLinkEditor(false)
                  setLinkDraft('')
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
        <div className="rich-editor-frame" style={{ zoom: zoomLevel / 100 }}>
          <EditorContent editor={editor} />
        </div>
      </div>
    </div>
  )
}

export default RichTextarea
