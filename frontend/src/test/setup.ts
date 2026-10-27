import '@testing-library/jest-dom/vitest'

// jsdom no implementa los diálogos modales nativos: alcanza con abrir y cerrar.
const dialogo = HTMLDialogElement.prototype as Partial<HTMLDialogElement>
dialogo.showModal ??= function showModal(this: HTMLDialogElement) {
  this.open = true
}
dialogo.close ??= function close(this: HTMLDialogElement) {
  this.open = false
  this.dispatchEvent(new Event('close'))
}
