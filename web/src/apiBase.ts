const API_BASE = normalizeApiBase(import.meta.env.VITE_API_BASE)

function normalizeApiBase(value: unknown) {
  return String(value ?? '').trim().replace(/\/+$/, '')
}

export function apiUrl(path: string) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${API_BASE}${normalizedPath}`
}

export function apiWebSocketUrl(path: string) {
  const url = new URL(apiUrl(path), window.location.origin)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}
