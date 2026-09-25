import { $textDirection, forcedTextDirection } from '@/store/text-direction'

export type TextDirection = 'ltr' | 'rtl'

const RTL_STRONG_RE =
  /[\p{Script=Adlam}\p{Script=Arabic}\p{Script=Hebrew}\p{Script=Nko}\p{Script=Syriac}\p{Script=Thaana}]/u

const LETTER_RE = /\p{Letter}/u

const LEADING_DIRECTIVE_RE = /^@[\w-]{1,64}:(?:`[^`]*`|"[^"]*"|'[^']*'|[^\s]+)/u
const LEADING_INLINE_CODE_RE = /^(`+)[\s\S]*?\1/u

const LEADING_LATIN_LABEL_TOKEN_RE =
  /^(?:[\p{Script=Latin}\p{Number}][\p{Script=Latin}\p{Number}\p{Punctuation}+]*|\([\p{Script=Latin}\p{Number}\p{Punctuation}\s+]+\))(?:\s+|$)/u
const LOWERCASE_LETTER_RE = /^\p{Lowercase_Letter}/u

const LEADING_PATH_TOKEN_RE = /^(?:\.{1,2}\/|\/|~\/|[A-Za-z]:[\\/])[^\s]+/u
const LEADING_SLASH_COMMAND_RE = /^\/[A-Za-z][\w-]*(?=\s|$)/u

function firstStrongDirection(text: string): TextDirection | null {
  for (const ch of text) {
    if (RTL_STRONG_RE.test(ch)) {
      return 'rtl'
    }

    if (LETTER_RE.test(ch)) {
      return 'ltr'
    }
  }

  return null
}

function dominantStrongDirection(text: string): TextDirection | null {
  let ltr = 0
  let rtl = 0

  for (const ch of text) {
    if (RTL_STRONG_RE.test(ch)) {
      rtl += 1
    } else if (LETTER_RE.test(ch)) {
      ltr += 1
    }
  }

  if (rtl > ltr) {
    return 'rtl'
  }

  if (ltr > 0) {
    return 'ltr'
  }

  return rtl > 0 ? 'rtl' : null
}

function stripLeadingNonStrong(text: string) {
  let index = 0

  for (const ch of text) {
    if (RTL_STRONG_RE.test(ch) || LETTER_RE.test(ch)) {
      break
    }

    index += ch.length
  }

  return text.slice(index)
}

function stripOneLeadingToken(text: string) {
  const trimmed = text.trimStart()

  const token =
    trimmed.match(LEADING_INLINE_CODE_RE)?.[0] ??
    trimmed.match(LEADING_DIRECTIVE_RE)?.[0] ??
    trimmed.match(LEADING_SLASH_COMMAND_RE)?.[0] ??
    trimmed.match(LEADING_PATH_TOKEN_RE)?.[0]

  return token ? trimmed.slice(token.length) : stripLeadingNonStrong(trimmed)
}

function stripLeadingDirectionalTokens(text: string) {
  let next = text

  for (let i = 0; i < 8; i += 1) {
    const stripped = stripOneLeadingToken(next)

    if (stripped === next) {
      return stripped
    }

    next = stripped
  }

  return next
}

function isLabelShapedToken(token: string) {
  const word = token.trim()

  // Technical tokens ("existing:", "Task16", "GPT-5.6") and acronyms ("NOOP")
  // read as labels; a plain capitalized word does not, because every English
  // sentence starts with one.
  return (
    /[\d\p{Punctuation}]/u.test(word) ||
    (word.length > 1 && /\p{Letter}/u.test(word) && word === word.toUpperCase())
  )
}

function lowercaseLatinContinuesAfterRtl(text: string) {
  const tokens = text.split(/\s+/u)
  const firstRtl = tokens.findIndex(token => RTL_STRONG_RE.test(token))

  for (const token of tokens.slice(firstRtl + 1)) {
    const first = token.charAt(0)

    if (LETTER_RE.test(first)) {
      return LOWERCASE_LETTER_RE.test(first)
    }
  }

  return false
}

function startsWithLatinLabelThenRtl(text: string) {
  let remainder = text.trimStart()

  for (let i = 0; i < 8; i += 1) {
    const token = remainder.match(LEADING_LATIN_LABEL_TOKEN_RE)?.[0]

    if (!token) {
      return false
    }

    remainder = remainder.slice(token.length)

    if (firstStrongDirection(remainder) === 'rtl') {
      const rtlWordCount = remainder.split(/\s+/u).filter(token => RTL_STRONG_RE.test(token)).length

      if (rtlWordCount > 1) {
        return true
      }

      // A single RTL word only flips the line when it is a label tail
      // ("Learning terminal existing: NOOP مايتحولش.") or sits in brand
      // position ("Google عندها Gemini 3.5"). Lowercase English continuing
      // past the word marks a quotation inside an English sentence
      // ("explain what مرحبا means?"); casing alone decides nothing, because
      // every English sentence starts with a capital letter.
      if (lowercaseLatinContinuesAfterRtl(remainder)) {
        return false
      }

      return isLabelShapedToken(token) || i === 0
    }
  }

  return false
}

export function resolveTextDirection(text: string, fallback: TextDirection = 'ltr'): TextDirection {
  const afterSpecialStart = stripLeadingDirectionalTokens(text)
  const afterSpecialDirection = firstStrongDirection(afterSpecialStart)

  if (afterSpecialDirection === 'rtl' || startsWithLatinLabelThenRtl(afterSpecialStart)) {
    return 'rtl'
  }

  return dominantStrongDirection(text) ?? afterSpecialDirection ?? firstStrongDirection(text) ?? fallback
}

export function syncElementTextDirection(element: HTMLElement, text: string) {
  // Appearance → Text direction (forced RTL/LTR) outranks the resolver. Under
  // Auto, resolve from the draft so an Arabic sentence that opens with a Latin
  // brand does not stay LTR.
  const forced = forcedTextDirection($textDirection.get())

  element.dir = forced ?? (text.trim() ? resolveTextDirection(text) : 'auto')
}
