import { useEffect, useState } from "react"
import { Toaster as Sonner, toast } from "sonner"

/**
 * Theme-aware toaster. App uses html.light-mode / html.dark-mode (not next-themes),
 * so we sync from document class and force high-contrast toast colors.
 */
const Toaster = ({ ...props }) => {
  const [theme, setTheme] = useState("dark")

  useEffect(() => {
    const sync = () => {
      const light = document.documentElement.classList.contains("light-mode")
      setTheme(light ? "light" : "dark")
    }
    sync()
    const obs = new MutationObserver(sync)
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] })
    return () => obs.disconnect()
  }, [])

  const isLight = theme === "light"

  return (
    <Sonner
      theme={theme}
      className="toaster group"
      position="top-right"
      closeButton
      toastOptions={{
        duration: 5000,
        classNames: {
          toast:
            "group toast !border !shadow-lg !rounded-xl !px-4 !py-3 !gap-2 " +
            (isLight
              ? "!bg-white !text-gray-900 !border-gray-200"
              : "!bg-crm-elevated !text-[#F4F4F5] !border-white/15"),
          title: isLight ? "!text-gray-900 !font-semibold" : "!text-[#FAFAFA] !font-semibold",
          description: isLight ? "!text-gray-600" : "!text-crm-fg-secondary",
          actionButton: isLight
            ? "!bg-gray-900 !text-white"
            : "!bg-[#C5A059] !text-[#0A0A0A]",
          cancelButton: isLight
            ? "!bg-gray-100 !text-gray-700"
            : "!bg-white/10 !text-crm-fg-secondary",
          closeButton: isLight
            ? "!bg-white !border-gray-200 !text-gray-500"
            : "!bg-crm-elevated !border-white/15 !text-crm-fg-secondary",
          success: isLight ? "!border-emerald-200" : "!border-emerald-500/30",
          error: isLight ? "!border-red-200" : "!border-red-500/40",
          warning: isLight ? "!border-amber-200" : "!border-amber-500/30",
          info: isLight ? "!border-sky-200" : "!border-sky-500/30",
        },
      }}
      {...props}
    />
  )
}

export { Toaster, toast }
