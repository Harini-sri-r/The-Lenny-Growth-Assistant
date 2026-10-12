import type { Artifact, AuthUser, ChatResponse, ChatSession, Message, ProviderStatus } from '../types/chat'

const API_BASE = import.meta.env.VITE_API_BASE_URL
  ?? '/api/v1'
let csrfToken = ''
let currentUserRequest: Promise<AuthUser> | null = null

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

function cookie(name: string): string {
  const prefix = `${name}=`
  return document.cookie.split('; ').find(item => item.startsWith(prefix))?.slice(prefix.length) ?? ''
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  const headers = new Headers(init?.headers)
  if (init?.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (init?.method && !['GET', 'HEAD', 'OPTIONS'].includes(init.method.toUpperCase())) {
    const csrf = csrfToken || cookie('lenny_csrf')
    if (csrf) headers.set('X-CSRF-Token', decodeURIComponent(csrf))
  }
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: 'include' })
  } catch {
    throw new ApiError('Cannot reach the assistant service. Check your connection and try again.', 0)
  }
  const responseCsrf = response.headers?.get?.('X-CSRF-Token')
  if (responseCsrf) csrfToken = responseCsrf
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = body?.detail
    const validation = Array.isArray(detail)
        ? detail.map(item => {
          const location = Array.isArray(item?.loc) ? item.loc : []
          const field = location.length ? String(location[location.length - 1]) : ''
          const description = typeof item?.msg === 'string' ? item.msg : ''
          return description ? `${field ? `${field}: ` : ''}${description}` : ''
        }).filter(Boolean).join('. ')
        : ''
    const knownSafeMessages = new Set([
      'Sign in to continue', 'Your session expired. Sign in again',
      'Email or password is incorrect', 'Request verification failed. Refresh and try again',
      'Request origin is not allowed',
    ])
    const safeMessage = typeof detail === 'string' && knownSafeMessages.has(detail) ? detail
      : response.status === 409 ? 'An account with this email already exists. Try signing in instead.'
        : response.status === 401 && path === '/auth/me' ? 'Sign in to continue'
          : response.status === 401 && path === '/auth/login' ? 'Email or password is incorrect'
            : response.status === 401 ? 'Sign in to continue'
            : response.status === 403 ? 'This request could not be verified. Refresh the page and try again.'
              : response.status === 422 && validation ? validation
                : response.status >= 500 ? 'The service is temporarily unavailable. Please try again.'
                  : 'This request could not be completed. Please check the details and try again.'
    throw new ApiError(safeMessage, response.status)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const register = (email: string, password: string, displayName: string) =>
  request<AuthUser>('/auth/register', { method: 'POST', body: JSON.stringify({ email, password, display_name: displayName }) })
export const login = (email: string, password: string) =>
  request<AuthUser>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
export const getMe = () => {
  if (!currentUserRequest) {
    currentUserRequest = request<AuthUser>('/auth/me').then(profile => {
      currentUserRequest = null
      return profile
    }, error => {
      currentUserRequest = null
      throw error
    })
  }
  return currentUserRequest
}
export const updateProfile = (displayName: string) =>
  request<AuthUser>('/auth/me', { method: 'PATCH', body: JSON.stringify({ display_name: displayName }) })
export const updateAppearance = (mode: AuthUser['appearance_mode'], palette: AuthUser['pastel_palette']) =>
  request<AuthUser>('/auth/preferences', { method: 'PATCH', body: JSON.stringify({ appearance_mode: mode, pastel_palette: palette }) })
export const logout = () => request<void>('/auth/logout', { method: 'POST' })
export const deleteAccount = (confirmation: string, password: string) =>
  request<void>('/auth/account', { method: 'DELETE', body: JSON.stringify({ confirmation, password }) })

export const listSessions = () => request<ChatSession[]>('/chat/sessions')
export const createSession = () => request<ChatSession>('/chat/sessions', { method: 'POST', body: JSON.stringify({}) })
export const listMessages = (sessionId: string) => request<Message[]>(`/chat/sessions/${encodeURIComponent(sessionId)}/messages`)
export const sendMessage = (sessionId: string, message: string, clientMessageId: string) => request<ChatResponse>(`/chat/sessions/${encodeURIComponent(sessionId)}/messages`, { method: 'POST', body: JSON.stringify({ message, client_message_id: clientMessageId }) })
export const renameSession = (sessionId: string, title: string) => request<ChatSession>(`/chat/sessions/${encodeURIComponent(sessionId)}`, { method: 'PATCH', body: JSON.stringify({ title }) })
export const deleteSession = (sessionId: string) => request<void>(`/chat/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
export const listArtifacts = () => request<Artifact[]>('/artifacts')
export const getProviderStatus = () => request<ProviderStatus>('/providers')
export const createShip30Artifact = (sessionId: string, topic: string, audience: string, artifactFormat: 'markdown' | 'html') =>
  request<Artifact>('/artifacts/ship30', { method: 'POST', body: JSON.stringify({ session_id: sessionId, topic, audience, artifact_format: artifactFormat }) })
export const createConversationArtifact = (sessionId: string, artifactRequest: string, artifactFormat: 'markdown' | 'html') =>
  request<Artifact>('/artifacts/from-chat', { method: 'POST', body: JSON.stringify({ session_id: sessionId, request: artifactRequest, artifact_format: artifactFormat }) })
