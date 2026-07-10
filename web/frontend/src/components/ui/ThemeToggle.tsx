import { Moon, Sun } from 'lucide-react'
import { useThemeStore } from '../../stores/themeStore'

interface ThemeToggleProps {
  className?: string
}

export default function ThemeToggle({ className = '' }: ThemeToggleProps) {
  const theme = useThemeStore((s) => s.theme)
  const toggle = useThemeStore((s) => s.toggle)

  return (
    <button
      onClick={toggle}
      className={`p-2 rounded-lg text-text-secondary hover:text-accent hover:bg-surface-2 transition-colors ${className}`}
      title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      aria-label="Toggle theme"
    >
      {theme === 'dark' ? (
        <Sun className="w-4 h-4" />
      ) : (
        <Moon className="w-4 h-4" />
      )}
    </button>
  )
}
