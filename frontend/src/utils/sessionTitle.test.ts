import { describe, expect, it } from 'vitest'
import { generateSessionTitle, isDefaultSessionTitle } from './sessionTitle'

describe('session title generation', () => {
  it.each([
    ['How to Find Product-Market Fit', 'Finding Product-Market Fit'],
    ['What are the best ways to improve user onboarding?', 'Improving User Onboarding'],
    ['Explain startup growth loops with examples', 'Understanding Startup Growth Loops'],
    ['Help me write a Ship 30 essay about product growth', 'Writing an Essay on Product Growth'],
    ['What did Lenny say about retention?', 'Lenny’s Lessons on Retention'],
    ['How can I validate my startup idea?', 'Validating a Startup Idea'],
  ])('summarizes “%s”', (message, expected) => {
    const title = generateSessionTitle(message)
    expect(title).toBe(expected)
    expect(title!.split(/\s+/).length).toBeLessThanOrEqual(7)
    expect(title!.length).toBeLessThanOrEqual(50)
  })

  it.each(['', 'Hi', 'Hello there!', 'Thanks', 'Okay.'])('keeps the placeholder for a greeting: %s', message => {
    expect(generateSessionTitle(message)).toBeNull()
  })

  it('omits credentials and contact details', () => {
    const title = generateSessionTitle('Ask about retention; email jane@example.com, password=Secret123, phone +1 555-555-0182')
    expect(title).toBe('Retention')
    expect(title).not.toMatch(/jane|secret|555/i)
  })

  it('recognizes only default placeholders as eligible for automatic updates', () => {
    expect(isDefaultSessionTitle(' New CHAT ')).toBe(true)
    expect(isDefaultSessionTitle('Improving User Onboarding')).toBe(false)
  })
})
