import type { Artifact, ChatResponse, ChatSession, Message } from '../types/chat'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    throw new Error('Cannot reach the assistant API. Check that the backend is running.')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail ?? `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export function getUserId(): string {
  const key = 'lenny-assistant-user-id'
  let id = localStorage.getItem(key)
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem(key, id)
  }
  return id
}

export const listSessions = (userId: string) =>
  request<ChatSession[]>(`/chat/sessions?user_id=${encodeURIComponent(userId)}`)

export const createSession = (userId: string) =>
  request<ChatSession>('/chat/sessions', {
    method: 'POST', body: JSON.stringify({ user_id: userId, display_name: 'Local workspace' }),
  })

export const listMessages = (sessionId: string, userId: string) =>
  request<Message[]>(`/chat/sessions/${sessionId}/messages?user_id=${encodeURIComponent(userId)}`)

export const sendMessage = (sessionId: string, userId: string, message: string) =>
  request<ChatResponse>(`/chat/sessions/${sessionId}/messages`, {
    method: 'POST', body: JSON.stringify({ user_id: userId, message }),
  })

export const listArtifacts = (userId: string) =>
  request<Artifact[]>(`/artifacts?user_id=${encodeURIComponent(userId)}`)

export const createShip30Artifact = (userId: string, sessionId: string, topic: string, audience: string, artifactFormat: 'markdown' | 'html') =>
  request<Artifact>('/artifacts/ship30', {
    method: 'POST', body: JSON.stringify({ user_id: userId, session_id: sessionId, topic, audience, artifact_format: artifactFormat }),
  })
