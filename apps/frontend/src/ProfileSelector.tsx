import React, { useEffect, useMemo, useState } from 'react'

type Goals = {
  families: Record<string, { profiles?: Record<string, unknown> }>
}

type Props = {
  family: string
  profile: string
  lang: 'de' | 'en'
  warning: string | null
  onFamilyChange: (family: string) => void
  onProfileChange: (profile: string) => void
  onLangChange: (lang: 'de' | 'en') => void
  onWarningChange: (warning: string | null) => void
}

export default function ProfileSelector({
  family,
  profile,
  lang,
  warning,
  onFamilyChange,
  onProfileChange,
  onLangChange,
  onWarningChange,
}: Props) {
  const [goals, setGoals] = useState<Goals | null>(null)

  useEffect(() => {
    fetch('/api/compression/goals')
      .then((r) => r.json())
      .then(setGoals)
      .catch(() => setGoals(null))
  }, [])

  const families = useMemo(() => Object.keys(goals?.families || {}), [goals])
  const profiles = useMemo(
    () => Object.keys(goals?.families?.[family]?.profiles || {}),
    [goals, family],
  )

  useEffect(() => {
    if (families.length > 0 && !families.includes(family)) {
      onFamilyChange(families[0])
    }
  }, [families, family, onFamilyChange])

  useEffect(() => {
    if (profiles.length > 0 && !profiles.includes(profile)) {
      onProfileChange(profiles[0])
    }
  }, [profiles, profile, onProfileChange])

  useEffect(() => {
    if (!family || !profile) {
      onWarningChange(null)
      return
    }

    fetch(`/api/compression/profile?family=${encodeURIComponent(family)}&profile=${encodeURIComponent(profile)}&lang=${encodeURIComponent(lang)}`)
      .then((r) => r.json())
      .then((data) => onWarningChange(data.warning || null))
      .catch(() => onWarningChange(null))
  }, [family, profile, lang, onWarningChange])

  if (!goals) return <div className="message">Lade Komprimierungsziele...</div>

  return (
    <div className="profile-selector">
      <div className="profile-control">
        <label>Family</label>
        <select value={family} onChange={(e) => onFamilyChange(e.target.value)} data-testid="compression-family">
          {families.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
      </div>

      <div className="profile-control">
        <label>Profile</label>
        <select value={profile} onChange={(e) => onProfileChange(e.target.value)} data-testid="compression-profile">
          {profiles.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>

      <div className="profile-control">
        <label>Sprache</label>
        <select value={lang} onChange={(e) => onLangChange(e.target.value as 'de' | 'en')} data-testid="compression-lang">
          <option value="de">Deutsch</option>
          <option value="en">English</option>
        </select>
      </div>

      {warning ? (
        <div className="warning">
          <strong>{lang === 'de' ? 'Warnung:' : 'Warning:'}</strong> {warning}
        </div>
      ) : (
        <div className="ok">{lang === 'de' ? 'Profil scheint unkritisch.' : 'Profile looks OK.'}</div>
      )}
    </div>
  )
}
