import { useEffect, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'

interface SelectOption<T extends string | number> {
  value: T
  label: string
}

interface SelectProps<T extends string | number> {
  value: T
  options: SelectOption<T>[]
  onChange: (value: T) => void
  className?: string
}

export default function Select<T extends string | number>({
  value,
  options,
  onChange,
  className = '',
}: SelectProps<T>) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  const selected = options.find((o) => o.value === value)

  return (
    <div ref={ref} className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 flex items-center justify-between"
      >
        <span className="text-sm font-medium">{selected?.label}</span>
        <ChevronDown
          className={`w-5 h-5 text-gray-500 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div className="absolute z-10 w-full mt-1 bg-gray-800 border border-gray-700 rounded-lg shadow-xl overflow-hidden">
          {options.map((option) => {
            const isSelected = option.value === value
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => {
                  onChange(option.value)
                  setOpen(false)
                }}
                className={`w-full px-4 py-3 text-left text-sm transition-colors ${
                  isSelected
                    ? 'text-emerald-400 bg-emerald-500/10'
                    : 'text-gray-400 hover:bg-gray-700 hover:text-gray-200'
                }`}
              >
                {option.label}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
