/** A price's currency as a reader here writes it: crowns are «Kč», never «CZK». */
export function currencyLabel(currency: string = 'CZK'): string {
  return currency === 'CZK' ? 'Kč' : currency;
}
