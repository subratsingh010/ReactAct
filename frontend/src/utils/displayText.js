export function capitalizeFirstDisplay(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  return text
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}
