import { useEffect, useRef, useState } from 'react'

export function useFadeIn<T extends HTMLElement = HTMLDivElement>(
  options: { threshold?: number; rootMargin?: string; once?: boolean } = {}
) {
  const { threshold = 0.1, rootMargin = '0px 0px -50px 0px', once = true } = options
  const ref = useRef<T>(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setVisible(true)
            if (once) observer.unobserve(entry.target)
          } else if (!once) {
            setVisible(false)
          }
        })
      },
      { threshold, rootMargin }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [threshold, rootMargin, once])

  return { ref, visible }
}

export function useCountUp(target: number, run: boolean, duration = 1500) {
  const [value, setValue] = useState(0)

  useEffect(() => {
    if (!run) return
    let raf = 0
    const start = performance.now()
    const step = (now: number) => {
      const progress = Math.min((now - start) / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setValue(Math.floor(eased * target))
      if (progress < 1) raf = requestAnimationFrame(step)
      else setValue(target)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [target, run, duration])

  return value
}
