import { formatDecimal } from '../../lib/decimal'

/** Suma 1 a un entero escrito en texto ("1999" → "2000"), sin pasar por `number`. */
function sumarUno(entero: string): string {
  const digitos = entero.split('')
  let i = digitos.length - 1
  while (i >= 0 && digitos[i] === '9') {
    digitos[i] = '0'
    i -= 1
  }
  if (i < 0) return `1${digitos.join('')}`
  digitos[i] = String(Number(digitos[i]) + 1)
  return digitos.join('')
}

/** Puntos enteros, redondeados desde la mitad (Caja, 24/11/2026): "10.5" → "11", "10.4" → "10",
 * "1234.5" → "1.235". Se guardan con 6 decimales; solo se muestran enteros. */
export function formatPuntos(value: string): string {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value.trim())
  if (!match) return value
  const [, signo = '', entero = '0', fraccion = ''] = match
  const redondeado = (fraccion[0] ?? '0') >= '5' ? sumarUno(entero) : entero
  const sinCeros = redondeado.replace(/^0+(?=\d)/, '')
  return formatDecimal(`${sinCeros === '0' ? '' : signo}${sinCeros}`, 0)
}
