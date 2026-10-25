/** Zona horaria institucional: todas las fechas se muestran en hora de San Juan. */
export const LOCAL_TIME_ZONE = 'America/Argentina/San_Juan'

const localDateTime = new Intl.DateTimeFormat('es-AR', {
  timeZone: LOCAL_TIME_ZONE,
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
})

const utcTime = new Intl.DateTimeFormat('es-AR', {
  timeZone: 'UTC',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
})

const localTime = new Intl.DateTimeFormat('es-AR', {
  timeZone: LOCAL_TIME_ZONE,
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
})

export function formatLocalDateTime(date: Date): string {
  return localDateTime.format(date).replace(',', '')
}

export function formatUtcTime(date: Date): string {
  return utcTime.format(date)
}

export function formatLocalTime(date: Date): string {
  return localTime.format(date)
}
