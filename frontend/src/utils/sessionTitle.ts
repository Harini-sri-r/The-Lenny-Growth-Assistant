const DEFAULT_TITLES = new Set(['new chat', 'new conversation', 'untitled', 'session 1'])
const GREETINGS = new Set(['hi', 'hello', 'hey', 'hiya', 'good morning', 'good afternoon', 'good evening', 'hi there', 'hello there', 'hey there', 'thanks', 'thank you', 'ok', 'okay', 'got it'])
const STOP_WORDS = new Set(['a', 'an', 'and', 'are', 'can', 'could', 'for', 'how', 'i', 'in', 'is', 'it', 'me', 'my', 'of', 'on', 'please', 'should', 'the', 'to', 'we', 'what', 'with', 'would', 'you', 'your'])
const GERUNDS: Record<string, string> = {
  build: 'Building', create: 'Creating', design: 'Designing', find: 'Finding', grow: 'Growing',
  improve: 'Improving', increase: 'Increasing', launch: 'Launching', measure: 'Measuring',
  reduce: 'Reducing', start: 'Starting', understand: 'Understanding', validate: 'Validating',
  write: 'Writing', draft: 'Drafting',
}

export function isDefaultSessionTitle(title: string): boolean {
  return DEFAULT_TITLES.has(title.trim().toLocaleLowerCase())
}

function safeMessage(message: string): string {
  return message
    .replace(/```[\s\S]*?```|`[^`]*`/g, ' ')
    .replace(/\[[^\]]*\]\([^)]+\)/g, ' ')
    .replace(/\bemail\s*[:=]?\s*[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|https?:\/\/\S+|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b/gi, ' ')
    .replace(/\b(?:phone|mobile)\s*[:=]?\s*\+?\d[\d ()-]{7,}\d|(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)/gi, ' ')
    .replace(/\b(?:password|passcode|api[_ -]?key|access[_ -]?token|secret|ssn|credit card)\s*(?:is|:|=)?\s*[^\s,;]+/gi, ' ')
    .replace(/["“”‘’]/g, ' ')
    .replace(/[#*_>`]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim().replace(/^[ .?!,:;-]+|[ .?!,:;-]+$/g, '')
}

function titleCase(value: string): string {
  const small = new Set(['a', 'an', 'and', 'for', 'in', 'of', 'on', 'the', 'to', 'with'])
  return value.split(/\s+/).map((word, index) => word.split('-').map(part => index > 0 && small.has(part.toLocaleLowerCase())
    ? part.toLocaleLowerCase()
    : part.charAt(0).toLocaleUpperCase() + part.slice(1)).join('-')).join(' ')
}

function fitTitle(value: string): string {
  let title = value.trim().split(/\s+/).slice(0, 7).join(' ')
  if (title.length > 50) title = title.slice(0, 50).replace(/\s+\S*$/, '')
  return title.replace(/[ .,:;\-?!]+$/, '')
}

function actionTitle(action: string, target: string): string {
  let topic = target.replace(/^(?:my|our|the)\s+/i, '').replace(/\b(?:please|for me|with examples?)\b/gi, ' ').replace(/\s+/g, ' ').trim().replace(/[ .?!,:;-]+$/, '')
  if (action.toLocaleLowerCase() === 'validate' && /^startup idea\b/i.test(topic)) topic = `a ${topic}`
  return fitTitle(titleCase(`${GERUNDS[action.toLocaleLowerCase()] ?? 'Understanding'} ${topic}`))
}

/** Local, immediate title fallback. It avoids another model call on the slow chat path. */
export function generateSessionTitle(message: string): string | null {
  let source = safeMessage(message)
  if (!source || GREETINGS.has(source.toLocaleLowerCase())) return null
  source = source.replace(/^(?:hi|hello|hey|hiya|thanks|thank you|okay|ok)(?: there)?[,.! ]+/i, '').trim()
  if (!source) return null

  let match = source.match(/^what did lenny say about\s+(.+)/i)
  if (match) return fitTitle(titleCase(`Lenny’s Lessons on ${match[1]}`))

  match = source.match(/^help me (?:write|draft|create)\s+(.+)/i)
  if (match) {
    const target = match[1].replace(/^(?:an?\s+)?ship\s*30\s+/i, '').trim()
    const essay = target.match(/^(?:an?\s+)?essay\s+(?:about|on)\s+(.+)/i)
    if (essay) return fitTitle(titleCase(`Writing an Essay on ${essay[1]}`))
    return actionTitle('write', target)
  }

  match = source.match(/^(?:what are )?(?:the )?(?:best ways|ways) to\s+([a-z]+)\s+(.+)/i)
  if (match) return actionTitle(match[1], match[2])

  match = source.match(/^how (?:can|do|should) (?:i|we|you)\s+([a-z]+)\s+(.+)/i)
  if (match) return actionTitle(match[1], match[2])

  match = source.match(/^how to\s+([a-z]+)\s+(.+)/i)
  if (match) return actionTitle(match[1], match[2])

  match = source.match(/^explain\s+(.+)/i)
  if (match) {
    const topic = match[1].replace(/\s+with examples?\b/i, '').replace(/\s+and\s+(?:many|several|lots of|more|additional)\b.*$/i, '').trim()
    return fitTitle(titleCase(`Understanding ${topic}`))
  }

  source = source.replace(/^(?:what are |what is |why do |why does |tell me about |ask about |discuss )/i, '')
  const words = (source.match(/[\w'-]+/g) ?? []).filter(word => !STOP_WORDS.has(word.toLocaleLowerCase())).slice(0, 5)
  const topic = words.join(' ').replace(/\b\w*\d\w*\b/g, '').trim()
  return topic ? fitTitle(titleCase(topic)) : null
}
