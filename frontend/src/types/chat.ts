export type Source = {
  source_id: string
  title: string
  document_type: string
  source_path: string
  url: string | null
  chunk_id: string
  excerpt?: string
}

export type Message = {
  id: string
  session_id: string
  role: 'user' | 'assistant'
  content: string
  sources: Source[]
  grounded: boolean | null
  created_at: string
}

export type ChatSession = {
  id: string
  user_id: string
  title: string
  created_at: string
  updated_at: string
}

export type ChatResponse = {
  session: ChatSession
  user_message: Message
  assistant_message: Message
}

export type Artifact = {
  id: string
  user_id: string
  session_id: string
  title: string
  artifact_format: 'markdown' | 'html'
  content: string
  sources: Source[]
  word_count: number
  created_at: string
}

export type ProviderStatus = {
  configured_route: string
  route_label: string
  note: string
  providers: Array<{
    id: 'gemini' | 'ollama' | 'anthropic' | 'openai'
    label: string
    supported: boolean
    state: 'selected' | 'fallback' | 'optional' | 'credentials_missing' | 'unavailable'
    model: string | null
  }>
}

export type AuthUser = { id: string; email: string; display_name: string | null; created_at: string; appearance_mode: 'light' | 'dark'; pastel_palette: 'blue' | 'lavender' | 'mint' | 'pink' | 'peach' | 'cream' }
