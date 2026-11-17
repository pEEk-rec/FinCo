/** Banks shout (RAMESH K, GUPTA JUICE CENTRE). People read Ramesh K and Gupta Juice Centre. */
export function displayName(name: string): string {
  const letters = name.replace(/[^A-Za-z]/g, '');
  if (letters.length < 2 || letters !== letters.toUpperCase()) return name;
  return name
    .toLowerCase()
    .replace(/(^|[\s\-/&.])([a-z])/g, (_m, sep: string, ch: string) => sep + ch.toUpperCase());
}
