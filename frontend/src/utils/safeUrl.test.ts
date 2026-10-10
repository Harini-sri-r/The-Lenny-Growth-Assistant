import { describe, expect, it } from 'vitest'
import { safeExternalUrl } from './safeUrl'

describe('safeExternalUrl', () => {
  it('allows HTTP and HTTPS source links', () => {
    expect(safeExternalUrl('https://example.test/source')).toBe('https://example.test/source')
    expect(safeExternalUrl('http://example.test/source')).toBe('http://example.test/source')
  })

  it('rejects executable, data, and malformed URLs', () => {
    expect(safeExternalUrl('javascript:alert(1)')).toBeUndefined()
    expect(safeExternalUrl('data:text/html,<script>alert(1)</script>')).toBeUndefined()
    expect(safeExternalUrl('not a URL')).toBeUndefined()
    expect(safeExternalUrl(undefined)).toBeUndefined()
  })
})
