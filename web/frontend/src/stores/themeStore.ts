import { create } from 'zustand'

export type Theme = 'dark' | 'light'

const STORAGE_KEY = 'theme'

function applyTheme(theme: Theme) {
  const root = document.documentElement
  root.classList.remove('dark', 'light')
  root.classList.add(theme)
}

function systemPrefersDark(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
  )
}

function systemTheme(): Theme {
  return systemPrefersDark() ? 'dark' : 'light'
}

function loadInitialTheme(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY) as Theme | null
  if (stored === 'dark' || stored === 'light') {
    return stored
  }
  return systemTheme()
}

interface ThemeState {
  theme: Theme
  followsSystem: boolean
  toggle: () => void
  setTheme: (theme: Theme) => void
  followSystem: () => void
  initialize: () => () => void
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: loadInitialTheme(),
  followsSystem: localStorage.getItem(STORAGE_KEY) === null,

  toggle: () => {
    const next: Theme = get().theme === 'dark' ? 'light' : 'dark'
    localStorage.setItem(STORAGE_KEY, next)
    applyTheme(next)
    set({ theme: next, followsSystem: false })
  },

  setTheme: (theme) => {
    localStorage.setItem(STORAGE_KEY, theme)
    applyTheme(theme)
    set({ theme, followsSystem: false })
  },

  followSystem: () => {
    localStorage.removeItem(STORAGE_KEY)
    const next = systemTheme()
    applyTheme(next)
    set({ theme: next, followsSystem: true })
  },

  initialize: () => {
    applyTheme(get().theme)

    if (typeof window === 'undefined' || !window.matchMedia) return () => {}

    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = (e: MediaQueryListEvent) => {
      if (localStorage.getItem(STORAGE_KEY) !== null) return
      const next: Theme = e.matches ? 'dark' : 'light'
      applyTheme(next)
      set({ theme: next, followsSystem: true })
    }
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  },
}))
