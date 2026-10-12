import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import * as chatApi from '../services/chat'
import type { Artifact, ChatResponse, ChatSession, Message } from '../types/chat'

vi.mock('../services/chat', () => ({
  createConversationArtifact: vi.fn(),
  createSession: vi.fn(),
  createShip30Artifact: vi.fn(),
  deleteAccount: vi.fn(),
  deleteSession: vi.fn(),
  getMe: vi.fn(),
  getProviderStatus: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  register: vi.fn(),
  renameSession: vi.fn(),
  listArtifacts: vi.fn(),
  listMessages: vi.fn(),
  listSessions: vi.fn(),
  sendMessage: vi.fn(),
  updateProfile: vi.fn(),
  updateAppearance: vi.fn(),
}))

const session: ChatSession = {
  id: 'session-1', user_id: 'test-user-123', title: 'New chat',
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}

const artifact: Artifact = {
  id: 'artifact-1', user_id: 'test-user-123', session_id: session.id,
  title: 'Retention essay', artifact_format: 'html', content: '<!doctype html><html><head></head><body><h1>Retention</h1></body></html>',
  sources: [], word_count: 1250, created_at: '2026-01-01T00:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
  window.history.replaceState({}, '', '/')
  document.documentElement.dataset.theme = 'light'
  document.documentElement.dataset.palette = 'pink'
  localStorage.removeItem('lenny-theme')
  localStorage.removeItem('lenny-palette')
  vi.mocked(chatApi.getMe).mockResolvedValue({ id: 'test-user-123', email: 'person@example.test', display_name: 'Person', created_at: '2026-01-01T00:00:00Z', appearance_mode: 'light', pastel_palette: 'pink' })
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
  it('filters real conversation history and starts an independent persisted chat', async () => {
    vi.mocked(chatApi.createSession).mockResolvedValue({ ...session, id: 'session-2', title: 'New chat' })
    render(<App />)
    await screen.findByRole('heading', { name: /better product decisions/i })
    expect(await screen.findByText('Earlier')).toBeInTheDocument()
    fireEvent.change(screen.getByRole('textbox', { name: 'Search conversations' }), { target: { value: 'does-not-match' } })
    expect(screen.getByText('No matching conversations')).toBeInTheDocument()
    fireEvent.change(screen.getByRole('textbox', { name: 'Search conversations' }), { target: { value: '' } })
    fireEvent.click(document.querySelector<HTMLButtonElement>('button.new-chat')!)
    await waitFor(() => expect(chatApi.createSession).toHaveBeenCalledTimes(1))
  })

  it('offers signup and shows validation errors when authentication is needed', async () => {
    vi.mocked(chatApi.getMe).mockRejectedValueOnce(new Error('Sign in to continue'))
    vi.mocked(chatApi.register).mockRejectedValueOnce(new Error('Unable to create an account with these details. Try signing in or use another email.'))
    render(<App />)
    fireEvent.click(await screen.findByRole('tab', { name: 'Create account' }))
    expect(screen.getByRole('heading', { name: 'Create your account' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Your name'), { target: { value: 'A Person' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'person@example.test' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'long enough password' } })
    fireEvent.change(screen.getByLabelText(/Confirm password/), { target: { value: 'different password' } })
    expect(document.querySelector<HTMLButtonElement>('.auth-submit')).toBeEnabled()
    fireEvent.click(document.querySelector<HTMLButtonElement>('.auth-submit')!)
    expect(screen.getByText('Passwords do not match.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/Confirm password/), { target: { value: 'long enough password' } })
    fireEvent.click(document.querySelector<HTMLButtonElement>('.auth-submit')!)
    expect(await screen.findByRole('alert')).toHaveTextContent('Try signing in')
  })

  it('uses a generic login error and preserves the email when switching to signup', async () => {
    vi.mocked(chatApi.getMe).mockRejectedValueOnce(new Error('Sign in to continue'))
    vi.mocked(chatApi.login).mockRejectedValueOnce(new Error('Email or password is incorrect'))
    render(<App />)
    await screen.findByRole('heading', { name: 'Welcome back' })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'person@example.test' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'not-the-right-password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Create account' }))
    expect(screen.getByRole('heading', { name: 'Create your account' })).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toHaveValue('person@example.test')
  })

  it('verifies the cookie session after a successful login before showing private data', async () => {
    const profile = { id: 'test-user-123', email: 'person@example.test', display_name: 'Person', created_at: '2026-01-01T00:00:00Z', appearance_mode: 'light' as const, pastel_palette: 'blue' as const }
    vi.mocked(chatApi.getMe)
      .mockRejectedValueOnce(new Error('Sign in to continue'))
      .mockResolvedValueOnce(profile)
    vi.mocked(chatApi.login).mockResolvedValueOnce(profile)
    render(<App />)
    await screen.findByRole('heading', { name: 'Welcome back' })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'person@example.test' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => expect(chatApi.login).toHaveBeenCalledTimes(1))
    expect(await screen.findByRole('heading', { name: /start with better questions/i })).toBeInTheDocument()
    expect(chatApi.getMe).toHaveBeenCalledTimes(2)
  })

  it('silently clears an expired session cookie and shows a clean sign-in form', async () => {
    vi.mocked(chatApi.getMe).mockRejectedValueOnce(new Error('Your session expired. Sign in again'))
    render(<App />)
    await screen.findByRole('heading', { name: 'Welcome back' })
    await waitFor(() => expect(chatApi.logout).toHaveBeenCalledTimes(1))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('does not request private chats or artifacts before authentication', async () => {
    vi.mocked(chatApi.getMe).mockRejectedValueOnce(new Error('Sign in to continue'))
    render(<App />)
    await screen.findByRole('heading', { name: 'Welcome back' })
    expect(chatApi.listSessions).not.toHaveBeenCalled()
    expect(chatApi.listArtifacts).not.toHaveBeenCalled()
  })

  it('returns to sign-in with a success message after registration without loading a session', async () => {
    vi.mocked(chatApi.getMe).mockRejectedValueOnce(new Error('Sign in to continue'))
    vi.mocked(chatApi.register).mockResolvedValueOnce({ id: 'new-user', email: 'person@example.test', display_name: 'A Person', created_at: '2026-01-01T00:00:00Z', appearance_mode: 'light', pastel_palette: 'blue' })
    render(<App />)

    fireEvent.click(await screen.findByRole('tab', { name: 'Create account' }))
    expect(screen.queryByText(/session expired/i)).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Your name'), { target: { value: 'A Person' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'person@example.test' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'a secure password' } })
    fireEvent.change(screen.getByLabelText(/Confirm password/), { target: { value: 'a secure password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))

    await waitFor(() => expect(chatApi.register).toHaveBeenCalledTimes(1))
    expect(chatApi.register).toHaveBeenCalledWith('person@example.test', 'a secure password', 'A Person')
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Account created successfully. Please sign in.')
    expect(screen.getByLabelText('Email')).toHaveValue('person@example.test')
    expect(screen.getByLabelText('Password')).toHaveValue('')
    expect(chatApi.getMe).toHaveBeenCalledTimes(1)
    expect(chatApi.login).not.toHaveBeenCalled()
    expect(chatApi.listSessions).not.toHaveBeenCalled()
    expect(chatApi.listArtifacts).not.toHaveBeenCalled()
    expect(screen.queryByText(/session expired/i)).not.toBeInTheDocument()
  })

  it('registers first, then authenticates only through a successful sign-in', async () => {
    const profile = { id: 'new-user', email: 'person@example.test', display_name: 'A Person', created_at: '2026-01-01T00:00:00Z', appearance_mode: 'light' as const, pastel_palette: 'pink' as const }
    vi.mocked(chatApi.getMe).mockRejectedValueOnce(new Error('Sign in to continue')).mockResolvedValue(profile)
    vi.mocked(chatApi.register).mockResolvedValueOnce(profile)
    vi.mocked(chatApi.login).mockResolvedValueOnce(profile)
    render(<App />)
    await screen.findByRole('heading', { name: 'Welcome back' })
    fireEvent.click(screen.getByRole('tab', { name: 'Create account' }))
    fireEvent.change(screen.getByLabelText('Your name'), { target: { value: 'A Person' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: profile.email } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'a secure password' } })
    fireEvent.change(screen.getByLabelText(/Confirm password/), { target: { value: 'a secure password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Account created successfully. Please sign in.')
    expect(chatApi.getMe).toHaveBeenCalledTimes(1)
    expect(chatApi.listSessions).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'a secure password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(chatApi.login).toHaveBeenCalledTimes(1))
    expect(await screen.findByRole('heading', { name: /start with better questions/i })).toBeInTheDocument()
    expect(chatApi.login).toHaveBeenCalledWith(profile.email, 'a secure password')
    expect(chatApi.getMe).toHaveBeenCalledTimes(2)
    expect(chatApi.listSessions).toHaveBeenCalledTimes(1)
    expect(chatApi.listArtifacts).toHaveBeenCalledTimes(1)
  })

  it('shows actual deduplicated source references in Research Results', async () => {
    const source = { source_id: 'S1', title: 'Sample episode', document_type: 'podcast', source_path: 'podcasts/sample.md', url: 'https://example.test/episode', chunk_id: 'chunk-1' }
    const assistant: Message = { id: 'answer-1', session_id: session.id, role: 'assistant', content: 'A grounded answer [S1]', sources: [source, source], grounded: true, created_at: '2026-01-01T00:00:00Z' }
    vi.mocked(chatApi.listMessages).mockResolvedValueOnce([assistant])
    render(<App />)
    expect(await screen.findByRole('link', { name: /Sample episode/ })).toHaveAttribute('href', source.url)
    expect(screen.getByRole('heading', { name: 'Research Results' })).toBeInTheDocument()
    expect(screen.getByText('podcast · podcasts/sample.md')).toBeInTheDocument()
    expect(screen.getAllByText('Sample episode')).toHaveLength(1)
  })

  it('does not display raw unauthenticated 401 errors during refresh', async () => {
    vi.mocked(chatApi.getMe).mockRejectedValueOnce(Object.assign(new Error('Sign in to continue'), { status: 401 }))
    render(<App />)
    await screen.findByRole('heading', { name: 'Welcome back' })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByText(/401|unauthorized/i)).not.toBeInTheDocument()
    expect(chatApi.listSessions).not.toHaveBeenCalled()
    expect(chatApi.listArtifacts).not.toHaveBeenCalled()
  })

  it('shows registration validation beside fields without native browser prompts', async () => {
    vi.mocked(chatApi.getMe).mockRejectedValueOnce(new Error('Sign in to continue'))
    render(<App />)
    fireEvent.click(await screen.findByRole('tab', { name: 'Create account' }))
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))

    expect(await screen.findByText('Enter your name.')).toBeInTheDocument()
    expect(screen.getByText('Enter a valid email address.')).toBeInTheDocument()
    expect(screen.getAllByText('Use at least 12 characters.')).toHaveLength(2)
    expect(chatApi.register).not.toHaveBeenCalled()
  })

  it('restores an authenticated workspace under React StrictMode', async () => {
    render(<StrictMode><App /></StrictMode>)
    expect(await screen.findByRole('heading', { name: /start with better questions/i })).toBeInTheDocument()
    expect(chatApi.listSessions).toHaveBeenCalled()
    expect(chatApi.listArtifacts).toHaveBeenCalled()
  })

  it('clears private workspace state immediately on logout', async () => {
    vi.mocked(chatApi.logout).mockResolvedValueOnce(undefined)
    render(<App />)
    await screen.findByRole('heading', { name: /start with better questions/i })
    fireEvent.click(screen.getByText('Person'))
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }))
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
    expect(chatApi.logout).toHaveBeenCalledTimes(1)
  })

  it('keeps the authenticated workspace and explains when logout cannot reach the server', async () => {
    vi.mocked(chatApi.logout).mockRejectedValueOnce(new Error('network failure'))
    render(<App />)
    await screen.findByRole('heading', { name: /start with better questions/i })
    fireEvent.click(screen.getByText('Person'))
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }))
    expect(await screen.findByText(/could not confirm sign out/i)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /start with better questions/i })).toBeInTheDocument()
  })

  it('revalidates authentication before restoring a back-forward cached workspace', async () => {
    const profile = { id: 'test-user-123', email: 'person@example.test', display_name: 'Person', created_at: '2026-01-01T00:00:00Z', appearance_mode: 'light' as const, pastel_palette: 'blue' as const }
    vi.mocked(chatApi.getMe).mockReset().mockResolvedValueOnce(profile).mockRejectedValueOnce(new Error('Your session expired. Sign in again'))
    render(<App />)
    await screen.findByRole('heading', { name: /start with better questions/i })
    const restore = new Event('pageshow') as PageTransitionEvent
    Object.defineProperty(restore, 'persisted', { value: true })
    window.dispatchEvent(restore)
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
    expect(screen.queryByText('Person')).not.toBeInTheDocument()
  })

  it('provides explicit sign-in and registration tabs and a password visibility control', async () => {
    vi.mocked(chatApi.getMe).mockRejectedValueOnce(new Error('Sign in to continue'))
    render(<App />)
    await screen.findByRole('heading', { name: 'Welcome back' })
    expect(screen.getByRole('tab', { name: 'Sign in' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'Show password' }))
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'text')
    fireEvent.click(screen.getByRole('tab', { name: 'Create account' }))
    expect(screen.getByRole('heading', { name: 'Create your account' })).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toHaveAttribute('autocomplete', 'new-password')
  })

  it('supports browser back and forward between sign-in and registration', async () => {
    vi.mocked(chatApi.getMe).mockRejectedValueOnce(new Error('Sign in to continue'))
    render(<App />)
    await screen.findByRole('heading', { name: 'Welcome back' })
    fireEvent.click(screen.getByRole('tab', { name: 'Create account' }))
    expect(window.location.search).toBe('?auth=register')
    window.history.back()
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Sign in' })).toHaveAttribute('aria-selected', 'true'))
    window.history.forward()
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Create account' })).toHaveAttribute('aria-selected', 'true'))
  })

  it('toggles and persists the selected theme without resetting auth state', async () => {
    vi.mocked(chatApi.getMe).mockRejectedValueOnce(new Error('Sign in to continue'))
    render(<App />)
    await screen.findByRole('heading', { name: 'Welcome back' })
    fireEvent.click(screen.getByRole('button', { name: 'Switch to Black mode' }))
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem('lenny-theme')).toBe('dark')
    expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Switch to White mode' })).toBeInTheDocument()
  })

  it('exposes the workspace theme control after authentication', async () => {
    render(<App />)
    await screen.findByRole('heading', { name: /better product decisions/i })
    fireEvent.click(screen.getByRole('button', { name: 'Switch to Black mode' }))
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('opens settings, persists pastel choice and saves the display name', async () => {
    vi.mocked(chatApi.updateProfile).mockImplementation(async displayName => ({
      id: 'test-user-123', email: 'person@example.test', display_name: displayName, created_at: '2026-01-01T00:00:00Z', appearance_mode: 'light', pastel_palette: 'blue',
    }))
    render(<App />)
    await screen.findByRole('heading', { name: /better product decisions/i })
    fireEvent.click(screen.getByText('Person', { selector: 'strong' }))
    fireEvent.click(screen.getByRole('button', { name: 'Account settings' }))
    await screen.findByRole('heading', { name: 'Personal information' })
    fireEvent.change(screen.getByRole('textbox', { name: 'Display name' }), { target: { value: 'New Name' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    expect(await screen.findByText('Your profile was saved.')).toBeInTheDocument()
    expect(chatApi.updateProfile).toHaveBeenCalledWith('New Name')
    fireEvent.click(screen.getByRole('button', { name: 'Appearance' }))
    fireEvent.click(screen.getByRole('button', { name: 'Pastel Lavender' }))
    expect(document.documentElement.dataset.palette).toBe('lavender')
    expect(localStorage.getItem('lenny-palette')).toBe('lavender')
  })

  it('requires typed confirmation and a password before account deletion', async () => {
    vi.mocked(chatApi.deleteAccount).mockResolvedValueOnce(undefined)
    render(<App />)
    await screen.findByRole('heading', { name: /better product decisions/i })
    fireEvent.click(screen.getByText('Person', { selector: 'strong' }))
    fireEvent.click(screen.getByRole('button', { name: 'Account settings' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Security' }))
    fireEvent.click(screen.getByRole('button', { name: /delete account/i }))
    const confirmButton = screen.getByRole('button', { name: /^Delete account$/ })
    expect(confirmButton).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Type DELETE to confirm'), { target: { value: 'DELETE' } })
    expect(confirmButton).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Current password'), { target: { value: 'current password' } })
    expect(confirmButton).toBeEnabled()
    fireEvent.click(confirmButton)
    await waitFor(() => expect(chatApi.deleteAccount).toHaveBeenCalledWith('DELETE', 'current password'))
  })

  it('keeps the composer outside the message scroller and offers accessible panel controls', async () => {
    const { container } = render(<App />)
    await screen.findByRole('heading', { name: /better product decisions/i })

    expect(container.querySelector('.composer-wrap')?.parentElement).toHaveClass('main')
    expect(container.querySelector('.conversation')?.contains(container.querySelector('.composer-wrap'))).toBe(false)
    expect(screen.getByRole('button', { name: 'Conversations' })).toHaveAttribute('aria-controls', 'conversation-sidebar')
    expect(screen.getByRole('button', { name: 'Artifacts' })).toHaveAttribute('aria-controls', 'artifact-panel')
    fireEvent.click(screen.getByRole('button', { name: 'Artifacts' }))
    expect(container.querySelector('.main')).toHaveClass('mobile-chat-hidden')
    fireEvent.click(screen.getByRole('button', { name: 'Close artifacts' }))
    expect(container.querySelector('.main')).not.toHaveClass('mobile-chat-hidden')
    expect(screen.getByRole('heading', { name: /better product decisions/i })).toBeInTheDocument()
  })

  it('removes the Model configuration panel and lets the desktop sidebar collapse', async () => {
    render(<App />)
    await screen.findByRole('heading', { name: /better product decisions/i })
    expect(screen.queryByText('Model configuration')).not.toBeInTheDocument()
    const sidebar = screen.getByRole('complementary', { name: 'Conversation sidebar' })
    fireEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    expect(sidebar).toHaveClass('sidebar-is-collapsed')
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(screen.getByRole('button', { name: 'Expand sidebar' }))
    expect(sidebar).not.toHaveClass('sidebar-is-collapsed')
  })

  it('updates a default conversation title immediately while the chat request is pending', async () => {
    const userMessage: Message = {
      id: 'title-user-message', session_id: session.id, role: 'user', content: 'How to Find Product-Market Fit',
      sources: [], grounded: null, created_at: '2026-01-01T00:00:00Z',
    }
    const assistantMessage: Message = {
      id: 'title-assistant-message', session_id: session.id, role: 'assistant', content: 'Start by talking to customers.',
      sources: [], grounded: true, created_at: '2026-01-01T00:00:01Z',
    }
    let completeRequest!: (response: ChatResponse) => void
    vi.mocked(chatApi.sendMessage).mockReturnValueOnce(new Promise(resolve => { completeRequest = resolve }))
    render(<App />)
    await screen.findByRole('heading', { name: /better product decisions/i })
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask a question' }), { target: { value: userMessage.content } })
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    const titleButton = screen.getByRole('button', { name: 'Finding Product-Market Fit' })
    expect(titleButton).toHaveAttribute('title', 'Finding Product-Market Fit')
    expect(titleButton).toBeInTheDocument()

    completeRequest({ session: { ...session, title: 'Finding Product-Market Fit' }, user_message: userMessage, assistant_message: assistantMessage })
    expect(await screen.findByText('Start by talking to customers.')).toBeInTheDocument()
  })

  it('generates through the session artifact action and shows the sandboxed HTML result', async () => {
    vi.mocked(chatApi.createShip30Artifact).mockResolvedValue(artifact)
    render(<App />)
    await screen.findByRole('heading', { name: /better product decisions/i })
    fireEvent.click(screen.getAllByRole('button', { name: /create essay/i })[0])
    fireEvent.change(screen.getByLabelText('Essay topic'), { target: { value: 'User retention' } })
    fireEvent.change(screen.getByLabelText('Format'), { target: { value: 'html' } })
    fireEvent.click(screen.getByRole('button', { name: 'Generate grounded essay' }))

    const preview = await screen.findByTitle('Artifact preview: Retention essay')
    expect(preview.tagName).toBe('IFRAME')
    expect(preview).toHaveAttribute('sandbox', '')
    expect(preview.getAttribute('srcdoc')).toContain('Content-Security-Policy')
    expect(chatApi.createShip30Artifact).toHaveBeenCalledWith(session.id, 'User retention', 'product managers and startup operators', 'html')
    expect(screen.getAllByRole('status').some(node => node.textContent?.includes('Essay generated and saved to this conversation.'))).toBe(true)
  })

  it('keeps essay questions in the center when launched from the center toolbar', async () => {
    render(<App />)
    await screen.findByRole('heading', { name: /better product decisions/i })
    fireEvent.click(screen.getByRole('button', { name: 'Collapse research panel' }))

    fireEvent.click(screen.getByRole('button', { name: 'Open Create Essay form' }))

    expect(screen.getByLabelText('Essay topic')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Expand research panel' })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('textbox', { name: 'Ask a question' })).toBeInTheDocument()
    expect(screen.getByLabelText('Essay topic').closest('.conversation')).not.toBeNull()
  })

  it('creates and previews a grounded artifact from the active conversation', async () => {
    vi.mocked(chatApi.createConversationArtifact).mockResolvedValue({
      ...artifact, title: 'Retention strategy', artifact_format: 'html',
      content: '<!doctype html><html><head></head><body><h1>Retention strategy</h1></body></html>',
    })
    render(<App />)
    await screen.findByRole('heading', { name: /better product decisions/i })
    fireEvent.click(screen.getAllByRole('button', { name: /create artifact/i })[0])
    fireEvent.change(screen.getByRole('textbox', { name: 'Artifact request' }), { target: { value: 'Summarize our retention discussion' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Artifact format' }), { target: { value: 'html' } })
    fireEvent.click(screen.getByRole('button', { name: 'Generate grounded artifact' }))

    const preview = await screen.findByTitle('Artifact preview: Retention strategy')
    expect(preview).toHaveAttribute('sandbox', '')
    expect(preview.getAttribute('srcdoc')).toContain("script-src 'none'")
    expect(chatApi.createConversationArtifact).toHaveBeenCalledWith(session.id, 'Summarize our retention discussion', 'html')
    expect(screen.getByRole('button', { name: /Retention strategy/ })).toBeInTheDocument()
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

  it('shows neutral retry guidance and keeps the topic available without a fake preview', async () => {
    vi.mocked(chatApi.createShip30Artifact).mockRejectedValueOnce(new Error('The transcript library did not return sufficient evidence.'))
    render(<App />)
    await screen.findByRole('heading', { name: /better product decisions/i })
    fireEvent.click(screen.getAllByRole('button', { name: /create essay/i })[0])
    fireEvent.change(screen.getByLabelText('Essay topic'), { target: { value: 'User retention' } })
    fireEvent.click(screen.getByRole('button', { name: 'Generate grounded essay' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Please retry in a moment')
    expect(screen.queryByText(/transcript library did not return sufficient evidence/i)).toBeNull()
    expect(screen.getByLabelText('Essay topic')).toHaveValue('User retention')
    expect(screen.getByRole('button', { name: 'Retry essay generation' })).toBeInTheDocument()
    expect(screen.queryByTitle(/Artifact preview/)).toBeNull()
    expect(screen.getByRole('heading', { name: 'Generated Outputs' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: /artifact viewer/i })).toBeNull()
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
    await screen.findByRole('heading', { name: /better product decisions/i })
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask a question' }), { target: { value: userMessage.content } })
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Retry message' }))

    await waitFor(() => expect(screen.getAllByText(userMessage.content)).toHaveLength(1))
    expect(screen.getByText('Measure D7 retention. [S1]')).toBeInTheDocument()
    expect(chatApi.sendMessage).toHaveBeenCalledTimes(2)
    expect(vi.mocked(chatApi.sendMessage).mock.calls[0][2]).toBe(vi.mocked(chatApi.sendMessage).mock.calls[1][2])
  })
})
