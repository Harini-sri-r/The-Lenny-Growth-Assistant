import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import * as chatApi from '../services/chat'
import type { Artifact, ChatResponse, ChatSession, Message } from '../types/chat'

vi.mock('../services/chat', () => ({
  createSession: vi.fn(),
  createShip30Artifact: vi.fn(),
  getProviderStatus: vi.fn(),
  getUserId: vi.fn(() => 'test-user-123'),
  listArtifacts: vi.fn(),
  listMessages: vi.fn(),
  listSessions: vi.fn(),
  sendMessage: vi.fn(),
}))

const session: ChatSession = {
  id: 'session-1', user_id: 'test-user-123', title: 'New conversation',
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}

const artifact: Artifact = {
  id: 'artifact-1', user_id: 'test-user-123', session_id: session.id,
  title: 'Retention essay', artifact_format: 'html', content: '<!doctype html><html><head></head><body><h1>Retention</h1></body></html>',
  sources: [], word_count: 1250, created_at: '2026-01-01T00:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(chatApi.listSessions).mockResolvedValue([session])
  vi.mocked(chatApi.listMessages).mockResolvedValue([])
  vi.mocked(chatApi.listArtifacts).mockResolvedValue([])
  vi.mocked(chatApi.getProviderStatus).mockResolvedValue({
    configured_route: 'ollama', route_label: 'Ollama local provider',
    note: 'Configuration only; provider connectivity and per-response routing are not verified here.',
    providers: [
      { id: 'ollama', label: 'Ollama', supported: true, state: 'selected', model: 'llama3:latest' },
      { id: 'anthropic', label: 'Anthropic', supported: true, state: 'credentials_missing', model: 'sonnet' },
      { id: 'gemini', label: 'Gemini', supported: true, state: 'credentials_missing', model: 'gemini-3.5-flash' },
    ],
  })
})

afterEach(() => cleanup())

describe('App', () => {
  it('keeps the composer outside the message scroller and offers accessible panel controls', async () => {
    const { container } = render(<App />)
    await screen.findByRole('heading', { name: /good ideas start/i })

    expect(container.querySelector('.composer-wrap')?.parentElement).toHaveClass('main')
    expect(container.querySelector('.conversation')?.contains(container.querySelector('.composer-wrap'))).toBe(false)
    expect(screen.getByRole('button', { name: 'Conversations' })).toHaveAttribute('aria-controls', 'conversation-sidebar')
    expect(screen.getByRole('button', { name: 'Artifacts' })).toHaveAttribute('aria-controls', 'artifact-panel')
    fireEvent.click(screen.getByRole('button', { name: 'Artifacts' }))
    expect(container.querySelector('.main')).toHaveClass('mobile-chat-hidden')
    fireEvent.click(screen.getByRole('button', { name: 'Close artifacts' }))
    expect(container.querySelector('.main')).not.toHaveClass('mobile-chat-hidden')
    expect(screen.getByRole('heading', { name: /good ideas start/i })).toBeInTheDocument()
  })

  it('shows truthful, separate provider configuration without attributing responses to a model', async () => {
    render(<App />)
    await screen.findByRole('heading', { name: /good ideas start/i })
    fireEvent.click(screen.getByText('Provider configuration'))

    expect(screen.getByText('Configured · Ollama local provider')).toBeInTheDocument()
    expect(screen.getByText('Selected in backend')).toBeInTheDocument()
    expect(screen.getAllByText('Credentials not set')).toHaveLength(2)
    expect(screen.getByText('gemini-3.5-flash')).toBeInTheDocument()
    expect(screen.getByText('llama3:latest')).toBeInTheDocument()
    expect(screen.queryByText(/Connected|Claude generated|Gemini generated/i)).toBeNull()
  })

  it('generates through the session artifact action and shows the sandboxed HTML result', async () => {
    vi.mocked(chatApi.createShip30Artifact).mockResolvedValue(artifact)
    render(<App />)
    await screen.findByRole('heading', { name: /good ideas start/i })
    fireEvent.click(screen.getByRole('button', { name: /create ship 30 for 30 essay/i }))
    fireEvent.change(screen.getByLabelText('Essay topic'), { target: { value: 'User retention' } })
    fireEvent.change(screen.getByLabelText('Format'), { target: { value: 'html' } })
    fireEvent.click(screen.getByRole('button', { name: 'Generate grounded essay' }))

    const preview = await screen.findByTitle('Artifact preview: Retention essay')
    expect(preview.tagName).toBe('IFRAME')
    expect(preview).toHaveAttribute('sandbox', '')
    expect(preview.getAttribute('srcdoc')).toContain('Content-Security-Policy')
    expect(chatApi.createShip30Artifact).toHaveBeenCalledWith('test-user-123', session.id, 'User retention', 'product managers and startup operators', 'html')
    expect(screen.getAllByRole('status').some(node => node.textContent?.includes('Essay generated and saved to this conversation.'))).toBe(true)
  })

  it('renders saved Markdown artifacts in the Artifact Viewer', async () => {
    vi.mocked(chatApi.listArtifacts).mockResolvedValue([{
      ...artifact, artifact_format: 'markdown',
      content: '# Retention that lasts\n\nHelp users **reach value** early. [S1]',
    }])
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: /Retention essay/ }))
    expect(await screen.findByRole('heading', { name: 'Retention that lasts' })).toBeInTheDocument()
    expect(screen.getByText('reach value')).toHaveProperty('tagName', 'STRONG')
    expect(screen.getByText(/\[S1\]/)).toBeInTheDocument()
  })

  it('shows generation errors and keeps the topic available for retry without a fake preview', async () => {
    vi.mocked(chatApi.createShip30Artifact).mockRejectedValueOnce(new Error('The transcript library did not return sufficient evidence.'))
    render(<App />)
    await screen.findByRole('heading', { name: /good ideas start/i })
    fireEvent.click(screen.getByRole('button', { name: /create ship 30 for 30 essay/i }))
    fireEvent.change(screen.getByLabelText('Essay topic'), { target: { value: 'User retention' } })
    fireEvent.click(screen.getByRole('button', { name: 'Generate grounded essay' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('transcript library did not return sufficient evidence')
    expect(screen.getByLabelText('Essay topic')).toHaveValue('User retention')
    expect(screen.getByRole('button', { name: 'Retry essay generation' })).toBeInTheDocument()
    expect(screen.queryByTitle(/Artifact preview/)).toBeNull()
    expect(screen.getByText('Artifact viewer')).toBeInTheDocument()
  })

  it('removes a failed pending message and retries without duplicating history', async () => {
    const userMessage: Message = {
      id: 'user-message', session_id: session.id, role: 'user', content: 'How do I improve retention?',
      sources: [], grounded: null, created_at: '2026-01-01T00:00:00Z',
    }
    const assistantMessage: Message = {
      id: 'assistant-message', session_id: session.id, role: 'assistant', content: 'Measure D7 retention. [S1]',
      sources: [], grounded: true, created_at: '2026-01-01T00:00:01Z',
    }
    const response: ChatResponse = { session, user_message: userMessage, assistant_message: assistantMessage }
    vi.mocked(chatApi.sendMessage).mockRejectedValueOnce(new Error('Connection failed')).mockResolvedValueOnce(response)
    render(<App />)
    await screen.findByRole('heading', { name: /good ideas start/i })
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask a question' }), { target: { value: userMessage.content } })
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Retry message' }))

    await waitFor(() => expect(screen.getAllByText(userMessage.content)).toHaveLength(1))
    expect(screen.getByText('Measure D7 retention. [S1]')).toBeInTheDocument()
    expect(chatApi.sendMessage).toHaveBeenCalledTimes(2)
  })
})
